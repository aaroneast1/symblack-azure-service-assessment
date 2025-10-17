#!/usr/bin/env python3
"""
Service Analyzer
Analyzes collected data and extracts Azure resource providers and services.
"""

import json
import re
from pathlib import Path
from typing import Set, Dict, List
from datetime import datetime


class ServiceAnalyzer:
    """Analyzes collected data to identify Azure services and providers."""

    def __init__(self):
        """Initialize the service analyzer."""
        self.providers = set()
        self.services = set()
        self.provider_to_subscriptions = {}

    def analyze_all_subscriptions(
        self,
        base_output_dir: Path,
        subscription_ids: List[str]
    ) -> Dict:
        """
        Analyze all collected data across multiple subscriptions.

        Args:
            base_output_dir: Base output directory containing subscription folders
            subscription_ids: List of subscription IDs to analyze

        Returns:
            Consolidated analysis results
        """
        print("\n" + "=" * 70)
        print("ANALYZING COLLECTED DATA")
        print("=" * 70)

        all_providers = set()
        all_services = set()
        subscription_results = []

        for sub_id in subscription_ids:
            sub_dir = base_output_dir / sub_id
            if not sub_dir.exists():
                print(f"\n⚠️  Skipping {sub_id}: directory not found")
                continue

            print(f"\n📊 Analyzing subscription: {sub_id}")

            result = self.analyze_subscription(sub_dir, sub_id)
            subscription_results.append(result)

            all_providers.update(result["providers"])
            all_services.update(result["services"])

        # Add essential security assessment providers
        essential_providers = self._get_essential_providers()
        all_providers.update(essential_providers)

        print("\n" + "=" * 70)
        print(f"CONSOLIDATED RESULTS: {len(all_providers)} Providers, {len(all_services)} Services")
        print("=" * 70)

        return {
            "generated_at": datetime.now().isoformat(),
            "query_parameters": {
                "total_subscriptions": len(subscription_ids),
                "analyzed_subscriptions": len(subscription_results)
            },
            "subscriptions": subscription_results,
            "consolidated": {
                "unique_providers": sorted(list(all_providers)),
                "unique_services": sorted(list(all_services)),
                "total_providers": len(all_providers),
                "total_services": len(all_services)
            }
        }

    def analyze_subscription(
        self,
        subscription_dir: Path,
        subscription_id: str
    ) -> Dict:
        """
        Analyze data for a single subscription.

        Args:
            subscription_dir: Path to subscription directory
            subscription_id: Subscription ID

        Returns:
            Analysis results for this subscription
        """
        providers = set()
        services = set()

        # Analyze activity logs
        activity_log_dir = subscription_dir / "activity-log"
        if activity_log_dir.exists():
            activity_providers, activity_services = self._analyze_activity_logs(activity_log_dir)
            providers.update(activity_providers)
            services.update(activity_services)
            print(f"  ✓ Activity logs: {len(activity_providers)} providers, {len(activity_services)} services")
        else:
            print(f"  ⚠️  No activity logs found")

        # Analyze cost management data
        cost_dir = subscription_dir / "cost-management"
        if cost_dir.exists():
            cost_services = self._analyze_cost_management(cost_dir)
            services.update(cost_services)
            print(f"  ✓ Cost data: {len(cost_services)} services")
        else:
            print(f"  ⚠️  No cost data found")

        print(f"  📊 Total: {len(providers)} providers, {len(services)} services")

        return {
            "subscription_id": subscription_id,
            "providers": sorted(list(providers)),
            "services": sorted(list(services)),
            "total_providers": len(providers),
            "total_services": len(services)
        }

    def _analyze_activity_logs(self, activity_log_dir: Path) -> tuple[Set[str], Set[str]]:
        """
        Extract providers and services from activity log files.

        Args:
            activity_log_dir: Directory containing activity log JSON files

        Returns:
            Tuple of (providers, services)
        """
        providers = set()
        services = set()

        log_files = list(activity_log_dir.glob("activity-log.*.json"))

        for log_file in log_files:
            try:
                with open(log_file, 'r') as f:
                    data = json.load(f)

                if not isinstance(data, list):
                    continue

                for entry in data:
                    # Extract providers using multiple methods
                    extracted = self._extract_providers_from_log_entry(entry)
                    providers.update(extracted)

                    # Extract service names
                    service_names = self._extract_services_from_log_entry(entry)
                    services.update(service_names)

            except Exception as e:
                print(f"  ⚠️  Error reading {log_file.name}: {e}")

        return providers, services

    def _extract_providers_from_log_entry(self, entry: Dict) -> Set[str]:
        """
        Extract Microsoft.* providers from a single activity log entry.

        Args:
            entry: Activity log entry dict

        Returns:
            Set of provider namespaces
        """
        providers = set()

        # Method 1: Extract from operationName
        operation = entry.get("operationName", {})
        if isinstance(operation, dict):
            operation_str = operation.get("value", "")
        else:
            operation_str = str(operation)

        if "/" in operation_str:
            provider = operation_str.split("/")[0]
            if provider.startswith("Microsoft.") or provider.startswith("microsoft."):
                # Normalize to proper case
                providers.add(self._normalize_provider_name(provider))

        # Method 2: Extract from resourceType
        resource_type = entry.get("resourceType", {})
        if isinstance(resource_type, dict):
            rt_str = resource_type.get("value", "")
        else:
            rt_str = str(resource_type)

        if "/" in rt_str:
            provider = rt_str.split("/")[0]
            if provider.startswith("Microsoft.") or provider.startswith("microsoft."):
                providers.add(self._normalize_provider_name(provider))

        # Method 3: Extract from resourceProvider field
        resource_provider = entry.get("resourceProvider", {})
        if isinstance(resource_provider, dict):
            rp_str = resource_provider.get("value", "")
        else:
            rp_str = str(resource_provider)

        if rp_str.startswith("Microsoft.") or rp_str.startswith("microsoft."):
            providers.add(self._normalize_provider_name(rp_str))

        # Method 4: Extract from resourceId using regex
        resource_id = entry.get("resourceId", "")
        if resource_id and "/providers/" in resource_id:
            match = re.search(r'/providers/(Microsoft\.[^/]+)/', resource_id, re.IGNORECASE)
            if match:
                providers.add(self._normalize_provider_name(match.group(1)))

        # Method 5: Infer from infrastructure patterns (Private DNS, etc.)
        inferred = self._infer_provider_from_resource_id(resource_id)
        if inferred:
            providers.add(inferred)

        return providers

    def _extract_services_from_log_entry(self, entry: Dict) -> Set[str]:
        """
        Extract human-readable service names from activity log entry.

        Args:
            entry: Activity log entry dict

        Returns:
            Set of service names
        """
        services = set()

        # Extract from operation name
        operation = entry.get("operationName", {})
        if isinstance(operation, dict):
            operation_str = operation.get("value", "")
        else:
            operation_str = str(operation)

        if "/" in operation_str:
            parts = operation_str.split("/")
            if len(parts) >= 2:
                provider = parts[0]
                resource_type = parts[1]
                service_name = self._format_service_name(provider, resource_type)
                if service_name:
                    services.add(service_name)

        return services

    def _analyze_cost_management(self, cost_dir: Path) -> Set[str]:
        """
        Extract service names from cost management files.

        Args:
            cost_dir: Directory containing cost management JSON files

        Returns:
            Set of service names
        """
        services = set()

        cost_files = list(cost_dir.glob("cost-management.*.json"))

        for cost_file in cost_files:
            try:
                with open(cost_file, 'r') as f:
                    data = json.load(f)

                if "properties" in data and "rows" in data["properties"]:
                    for row in data["properties"]["rows"]:
                        if row and row[0]:
                            service_name = row[0]
                            # Filter out non-service items
                            if service_name.lower() not in ["tax", "support", "bandwidth", "unassigned"]:
                                services.add(service_name)

            except Exception as e:
                print(f"  ⚠️  Error reading {cost_file.name}: {e}")

        return services

    def _normalize_provider_name(self, provider: str) -> str:
        """
        Normalize provider name to proper case.

        Args:
            provider: Provider namespace (any case)

        Returns:
            Normalized provider name (e.g., "Microsoft.Compute")
        """
        # Convert to lowercase, then capitalize properly
        parts = provider.lower().split(".")
        if parts[0] == "microsoft":
            parts[0] = "Microsoft"
            # Capitalize each part after Microsoft
            for i in range(1, len(parts)):
                parts[i] = parts[i].capitalize()
        return ".".join(parts)

    def _format_service_name(self, provider: str, resource_type: str) -> str:
        """
        Format a human-readable service name.

        Args:
            provider: Provider namespace (e.g., "Microsoft.Compute")
            resource_type: Resource type (e.g., "virtualMachines")

        Returns:
            Formatted service name (e.g., "Compute - Virtual Machines")
        """
        provider_name = provider.replace("Microsoft.", "").replace("microsoft.", "")

        # Convert camelCase to Title Case
        resource_name = re.sub(r'([a-z])([A-Z])', r'\1 \2', resource_type)
        resource_name = resource_name.title()

        return f"{provider_name} - {resource_name}"

    def _infer_provider_from_resource_id(self, resource_id: str) -> str:
        """
        Infer provider from infrastructure patterns in resource ID.

        Args:
            resource_id: Azure resource ID

        Returns:
            Provider namespace or empty string
        """
        service_indicators = {
            "postgres.database.azure.com": "Microsoft.DBforPostgreSQL",
            "mysql.database.azure.com": "Microsoft.DBforMySQL",
            "redis.cache.windows.net": "Microsoft.Cache",
            "azurecr.io": "Microsoft.ContainerRegistry",
            "vault.azure.net": "Microsoft.KeyVault",
            "blob.core.windows.net": "Microsoft.Storage",
            "queue.core.windows.net": "Microsoft.Storage",
            "table.core.windows.net": "Microsoft.Storage",
            "file.core.windows.net": "Microsoft.Storage",
            "servicebus.windows.net": "Microsoft.ServiceBus",
            "azurewebsites.net": "Microsoft.Web",
            "documents.azure.com": "Microsoft.DocumentDB",
            "sql.azuresynapse.net": "Microsoft.Synapse",
        }

        resource_id_lower = resource_id.lower()
        for indicator, provider in service_indicators.items():
            if indicator in resource_id_lower:
                return provider

        return ""

    def _get_essential_providers(self) -> Set[str]:
        """
        Get essential providers that should always be included.

        Returns:
            Set of essential provider namespaces
        """
        return {
            "Microsoft.Authorization",
            "Microsoft.Resources",
            "Microsoft.Subscription",
            "Microsoft.CostManagement",
            "Microsoft.Advisor",
            "Microsoft.Security",
            "Microsoft.PolicyInsights",
            "Microsoft.Insights",
            "Microsoft.ResourceGraph",
        }

    def save_consolidated_report(
        self,
        analysis_result: Dict,
        output_file: Path
    ) -> Path:
        """
        Save consolidated analysis report to file.

        Args:
            analysis_result: Analysis result dict
            output_file: Path to output file

        Returns:
            Path to saved file
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w') as f:
            json.dump(analysis_result, f, indent=2)

        print(f"\n✅ Consolidated report saved to: {output_file}")
        return output_file
