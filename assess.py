#!/usr/bin/env python3
"""
Azure Multi-Subscription Security Assessment Tool

Analyzes Azure subscriptions to:
1. Discover all services used across multiple subscriptions
2. Collect activity logs and cost data in 30-day chunks
3. Generate custom RBAC role definitions with read-only permissions
4. Create Service Principal with access to all subscriptions
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

from utils.azure_client import AzureClient
from utils.date_utils import parse_azure_date
from collectors.subscription_collector import SubscriptionCollector
from collectors.activity_log_collector import ActivityLogCollector
from collectors.cost_management_collector import CostManagementCollector
from analyzers.service_analyzer import ServiceAnalyzer
from generators.terraform_generator import TerraformGenerator


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Azure Multi-Subscription Security Assessment Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Assess all subscriptions
  python3 assess.py

  # Assess specific subscriptions
  python3 assess.py --subscriptions "sub-1,sub-2,sub-3"

  # Force refresh all data
  python3 assess.py --force-refresh

  # Custom output directory
  python3 assess.py --output-dir ./my-output
        """
    )
    parser.add_argument(
        "--subscriptions",
        help="Comma-separated list of subscription IDs to assess (default: all)"
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Output directory for generated files (default: ./output)"
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Force re-download of all data even if files exist"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("Azure Multi-Subscription Security Assessment Tool")
    print("=" * 70)

    # Initialize Azure client
    azure_client = AzureClient()

    # Check prerequisites
    print("\n🔍 Checking prerequisites...")
    if not azure_client.check_cli_installed():
        print("❌ Azure CLI is not installed")
        print("   Visit: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli")
        sys.exit(1)
    print("  ✓ Azure CLI is installed")

    if not azure_client.check_logged_in():
        print("❌ Not logged in to Azure")
        print("   Please run: az login")
        sys.exit(1)

    current_sub = azure_client.get_current_subscription()
    if current_sub:
        print(f"  ✓ Logged in as: {current_sub.get('user', {}).get('name', 'Unknown')}")

    # Parse subscription filter
    filter_subscription_ids = None
    if args.subscriptions:
        filter_subscription_ids = [s.strip() for s in args.subscriptions.split(",")]
        print(f"  ℹ️  Will filter to {len(filter_subscription_ids)} specified subscriptions")

    # Initialize collectors and analyzers
    subscription_collector = SubscriptionCollector(azure_client)
    activity_log_collector = ActivityLogCollector(azure_client)
    cost_collector = CostManagementCollector(azure_client)
    analyzer = ServiceAnalyzer()
    terraform_gen = TerraformGenerator()

    # Step 1: Discover subscriptions
    print("\n" + "=" * 70)
    print("STEP 1: DISCOVER SUBSCRIPTIONS")
    print("=" * 70)

    subscriptions = subscription_collector.discover_subscriptions(
        filter_subscription_ids=filter_subscription_ids
    )

    if not subscriptions:
        print("\n❌ No subscriptions found or accessible")
        sys.exit(1)

    print(f"\n✅ Will assess {len(subscriptions)} subscriptions:")
    for sub in subscriptions:
        print(f"   • {sub['subscription_name']} ({sub['subscription_id']})")

    # Step 2: Collect data for each subscription
    print("\n" + "=" * 70)
    print("STEP 2: COLLECT DATA FROM ALL SUBSCRIPTIONS")
    print("=" * 70)

    base_output_dir = Path(args.output_dir)
    subscription_ids = []

    for i, subscription in enumerate(subscriptions, 1):
        sub_id = subscription["subscription_id"]
        sub_name = subscription["subscription_name"]
        subscription_ids.append(sub_id)

        print(f"\n[{i}/{len(subscriptions)}] Processing: {sub_name}")
        print("=" * 70)

        # Create subscription output directory
        sub_output_dir = subscription_collector.get_subscription_output_dir(
            base_output_dir, sub_id
        )

        # Save subscription metadata
        subscription_collector.save_subscription_metadata(subscription, sub_output_dir)

        # Parse creation date for age calculation
        created_date = parse_azure_date(subscription.get("created_date"))

        # Collect activity logs
        activity_result = activity_log_collector.collect_activity_logs(
            subscription_id=sub_id,
            output_dir=sub_output_dir,
            subscription_created_date=created_date,
            force_refresh=args.force_refresh
        )

        # Collect cost management data
        cost_result = cost_collector.collect_cost_data(
            subscription_id=sub_id,
            output_dir=sub_output_dir,
            subscription_created_date=created_date,
            force_refresh=args.force_refresh
        )

    # Step 3: Analyze and consolidate
    print("\n" + "=" * 70)
    print("STEP 3: ANALYZE AND CONSOLIDATE DATA")
    print("=" * 70)

    analysis_result = analyzer.analyze_all_subscriptions(
        base_output_dir=base_output_dir,
        subscription_ids=subscription_ids
    )

    # Save consolidated report
    today = datetime.now().strftime("%Y-%m-%d")
    report_file = base_output_dir / f"azure-service-consumption.{today}.json"
    analyzer.save_consolidated_report(analysis_result, report_file)

    # Step 4: Generate Terraform
    print("\n" + "=" * 70)
    print("STEP 4: GENERATE TERRAFORM CONFIGURATION")
    print("=" * 70)

    terraform_gen.generate(
        analysis_result=analysis_result,
        output_dir=base_output_dir,
        subscriptions=subscriptions
    )

    # Final summary
    print("\n" + "=" * 70)
    print("✅ ASSESSMENT COMPLETE")
    print("=" * 70)

    print(f"\n📊 Summary:")
    print(f"   • Subscriptions assessed: {len(subscriptions)}")
    print(f"   • Unique providers found: {analysis_result['consolidated']['total_providers']}")
    print(f"   • Unique services found: {analysis_result['consolidated']['total_services']}")

    print(f"\n📁 Output Files:")
    print(f"   • Consolidated report: {report_file}")
    print(f"   • Terraform config: {base_output_dir}/terraform/")
    print(f"   • Per-subscription data: {base_output_dir}/{{subscription-id}}/")

    print(f"\n📖 Next Steps:")
    print(f"\n  1. Review the consolidated report:")
    print(f"     cat {report_file}")
    print(f"\n  2. Deploy service principal with Terraform:")
    print(f"     cd {base_output_dir}/terraform")
    print(f"     terraform init")
    print(f"     terraform plan")
    print(f"     terraform apply")
    print(f"\n  3. Retrieve credentials:")
    print(f"     terraform output")
    print(f"     terraform output -raw client_secret")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
