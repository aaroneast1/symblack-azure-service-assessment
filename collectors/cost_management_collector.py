#!/usr/bin/env python3
"""
Cost Management Collector
Collects Azure Cost Management data in 30-day chunks.
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from tempfile import NamedTemporaryFile

from utils.azure_client import AzureClient
from utils.date_utils import (
    calculate_query_periods,
    format_date_for_filename,
    get_period_filename,
    parse_azure_date
)


class CostManagementCollector:
    """Collects Azure Cost Management data in manageable chunks."""

    def __init__(self, azure_client: AzureClient):
        """
        Initialize the cost management collector.

        Args:
            azure_client: Azure CLI client instance
        """
        self.client = azure_client

    def collect_cost_data(
        self,
        subscription_id: str,
        output_dir: Path,
        subscription_created_date: Optional[datetime] = None,
        force_refresh: bool = False
    ) -> Dict:
        """
        Collect cost management data for a subscription in 30-day chunks.

        Args:
            subscription_id: Azure subscription ID
            output_dir: Directory to save cost data files
            subscription_created_date: When subscription was created (for age calculation)
            force_refresh: If True, re-download existing files

        Returns:
            Summary dict with collection statistics
        """
        print(f"\n💰 Collecting Cost Management data for subscription {subscription_id}")

        # Set active subscription
        self.client.set_subscription(subscription_id)

        # Create output directory
        cost_dir = output_dir / "cost-management"
        cost_dir.mkdir(parents=True, exist_ok=True)

        # Calculate query periods (30-day chunks)
        # Note: Cost Management API requires ranges < 1 year
        periods = calculate_query_periods(
            subscription_created_date,
            max_days=365,
            chunk_days=30
        )

        print(f"  ℹ️  Will query {len(periods)} periods (30-day chunks)")
        print(f"  ℹ️  Date range: {periods[0][0].strftime('%Y-%m-%d')} to {periods[-1][1].strftime('%Y-%m-%d')}")
        print(f"  ℹ️  5-second delay between requests + automatic retry on rate limits")

        # Collect each period
        collected_files = []
        skipped_files = []
        failed_periods = []
        total_services = set()

        for i, (start_date, end_date) in enumerate(periods, 1):
            period_result = self._collect_period(
                subscription_id=subscription_id,
                start_date=start_date,
                end_date=end_date,
                period_num=i,
                total_periods=len(periods),
                output_dir=cost_dir,
                force_refresh=force_refresh
            )

            if period_result["status"] == "collected":
                collected_files.append(period_result["file"])
                total_services.update(period_result.get("services", []))
            elif period_result["status"] == "skipped":
                skipped_files.append(period_result["file"])
                total_services.update(period_result.get("services", []))
            elif period_result["status"] == "failed":
                failed_periods.append({
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "error": period_result.get("error")
                })

            # Delay to avoid rate limiting (Azure Cost Management has strict limits)
            if i < len(periods):
                time.sleep(5)

        # Summary
        print(f"\n  ✅ Cost Management Collection Summary:")
        print(f"     • Files collected: {len(collected_files)}")
        print(f"     • Files skipped (existing): {len(skipped_files)}")
        print(f"     • Periods failed: {len(failed_periods)}")
        print(f"     • Unique services found: {len(total_services)}")

        if failed_periods:
            print(f"\n  ⚠️  Failed periods (this is normal for subscriptions without cost data):")
            for fp in failed_periods[:5]:  # Show only first 5
                print(f"     • {fp['start']} to {fp['end']}")
            if len(failed_periods) > 5:
                print(f"     ... and {len(failed_periods) - 5} more")

        return {
            "subscription_id": subscription_id,
            "collected_files": collected_files,
            "skipped_files": skipped_files,
            "failed_periods": failed_periods,
            "total_services": len(total_services),
            "total_periods": len(periods)
        }

    def _collect_period(
        self,
        subscription_id: str,
        start_date: datetime,
        end_date: datetime,
        period_num: int,
        total_periods: int,
        output_dir: Path,
        force_refresh: bool
    ) -> Dict:
        """
        Collect cost data for a single period.

        Args:
            subscription_id: Azure subscription ID
            start_date: Period start date
            end_date: Period end date
            period_num: Period number (for display)
            total_periods: Total number of periods (for display)
            output_dir: Directory to save files
            force_refresh: If True, re-download existing files

        Returns:
            Result dict with status and file path
        """
        # Generate filename
        filename = get_period_filename("cost-management", start_date, end_date)
        output_file = output_dir / filename

        # Check if file already exists
        if output_file.exists() and not force_refresh:
            print(f"  [{period_num:02d}/{total_periods:02d}] {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} → ⏭️  Skipped (exists)")
            # Count services in existing file
            try:
                with open(output_file, 'r') as f:
                    data = json.load(f)
                    services = self._extract_services_from_result(data)
            except:
                services = []

            return {
                "status": "skipped",
                "file": str(output_file),
                "services": services
            }

        # Format dates for API (YYYY-MM-DD)
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        print(f"  [{period_num:02d}/{total_periods:02d}] {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} → ", end="", flush=True)

        # Create query payload
        query_payload = {
            "type": "Usage",
            "timeframe": "Custom",
            "timePeriod": {
                "from": start_str,
                "to": end_str
            },
            "dataset": {
                "granularity": "Monthly",
                "aggregation": {
                    "totalCost": {
                        "name": "PreTaxCost",
                        "function": "Sum"
                    }
                },
                "grouping": [
                    {
                        "type": "Dimension",
                        "name": "ServiceName"
                    }
                ]
            }
        }

        # Save to temp file
        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
            json.dump(query_payload, temp_file)
            temp_path = temp_file.name

        try:
            # Execute cost query via REST API with retry logic
            uri = f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query?api-version=2023-03-01"

            # Retry with exponential backoff for rate limiting
            max_retries = 3
            retry_delay = 10  # Start with 10 seconds

            for attempt in range(max_retries + 1):
                result = self.client.rest_api_call(
                    method="POST",
                    uri=uri,
                    body=f"@{temp_path}",
                    timeout=60
                )

                # Check if we hit rate limit
                if result.get("failed"):
                    error_msg = result.get("error", "Unknown error")

                    # Check if it's a rate limit error (429)
                    if "429" in error_msg or "Too Many Requests" in error_msg:
                        if attempt < max_retries:
                            print(f"⏳ Rate limited, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})...", end="", flush=True)
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                            continue
                        else:
                            print(f"❌ Failed: Rate limit exceeded after {max_retries} retries")
                            Path(temp_path).unlink(missing_ok=True)
                            return {
                                "status": "failed",
                                "error": "Rate limit exceeded"
                            }

                # If we get here, either success or non-retryable error
                break

            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

            # Check for errors
            if result.get("failed"):
                error_msg = result.get("error", "Unknown error")
                # Check if it's a "no data" error
                if "NotFound" in error_msg or "GtmDimensionDataProvider" in error_msg or "no data" in error_msg.lower():
                    print(f"⚠️  No cost data")
                    # Save empty result
                    with open(output_file, 'w') as f:
                        json.dump({"error": "No cost data available", "rows": []}, f, indent=2)
                    return {
                        "status": "failed",
                        "error": "No cost data available",
                        "services": []
                    }
                else:
                    print(f"❌ Failed: {error_msg[:50]}")
                    return {
                        "status": "failed",
                        "error": error_msg
                    }

            # Extract services
            services = self._extract_services_from_result(result)

            # Save to file
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2)

            print(f"✓ {len(services)} services")

            return {
                "status": "collected",
                "file": str(output_file),
                "services": services
            }

        except Exception as e:
            Path(temp_path).unlink(missing_ok=True)
            print(f"❌ Exception: {str(e)[:50]}")
            return {
                "status": "failed",
                "error": str(e)
            }

    def _extract_services_from_result(self, result: Dict) -> List[str]:
        """
        Extract service names from Cost Management API result.

        Args:
            result: Cost Management API response

        Returns:
            List of service names
        """
        services = []

        if "properties" in result and "rows" in result["properties"]:
            for row in result["properties"]["rows"]:
                if row and row[0]:  # Service name is first element
                    service_name = row[0]

                    # Skip if service_name is not a string (sometimes it's a float/number)
                    if not isinstance(service_name, str):
                        continue

                    # Filter out non-service items
                    if service_name.lower() not in ["tax", "support", "bandwidth", "unassigned"]:
                        services.append(service_name)

        return services
