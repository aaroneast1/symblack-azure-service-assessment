#!/usr/bin/env python3
"""
Subscription Collector
Discovers all Azure subscriptions and collects metadata.
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from utils.azure_client import AzureClient
from utils.date_utils import parse_azure_date, estimate_subscription_age_days


class SubscriptionCollector:
    """Collects information about Azure subscriptions."""

    def __init__(self, azure_client: AzureClient):
        """
        Initialize the subscription collector.

        Args:
            azure_client: Azure CLI client instance
        """
        self.client = azure_client

    def discover_subscriptions(
        self,
        filter_subscription_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Discover all Azure subscriptions the user has access to.

        Args:
            filter_subscription_ids: Optional list of subscription IDs to filter to

        Returns:
            List of subscription metadata dicts
        """
        print("🔍 Discovering Azure subscriptions...")

        subscriptions = self.client.list_subscriptions()

        if not subscriptions:
            print("  ❌ No subscriptions found or access denied")
            return []

        # Filter to only enabled subscriptions
        enabled_subs = [
            sub for sub in subscriptions
            if sub.get("state") == "Enabled"
        ]

        print(f"  ✓ Found {len(enabled_subs)} enabled subscriptions (out of {len(subscriptions)} total)")

        # Apply user filter if provided
        if filter_subscription_ids:
            enabled_subs = [
                sub for sub in enabled_subs
                if sub.get("id") in filter_subscription_ids
            ]
            print(f"  ℹ️  Filtered to {len(enabled_subs)} specified subscriptions")

        # Enrich with metadata
        enriched_subs = []
        for sub in enabled_subs:
            metadata = self._get_subscription_metadata(sub)
            enriched_subs.append(metadata)

        return enriched_subs

    def _get_subscription_metadata(self, subscription: Dict) -> Dict:
        """
        Get detailed metadata for a subscription.

        Args:
            subscription: Basic subscription info from az account list

        Returns:
            Enriched subscription metadata
        """
        sub_id = subscription.get("id")
        sub_name = subscription.get("name")
        tenant_id = subscription.get("tenantId")

        print(f"\n  📋 {sub_name} ({sub_id})")

        # Try to get creation date from subscription details
        # Note: Azure doesn't always expose creation date easily
        # We'll try to get it from the subscription properties
        self.client.set_subscription(sub_id)

        # Try to get subscription details via REST API
        creation_date = None
        try:
            result = self.client.rest_api_call(
                method="GET",
                uri=f"https://management.azure.com/subscriptions/{sub_id}?api-version=2022-12-01",
                timeout=30
            )
            if not result.get("failed"):
                # Some subscriptions may have createdTime property
                creation_date_str = result.get("subscriptionPolicies", {}).get("quotaId")
                # Alternative: look at the subscription state change date
                # This is a best-effort attempt
        except:
            pass

        # Calculate age
        created_datetime = parse_azure_date(creation_date) if creation_date else None
        age_days = estimate_subscription_age_days(created_datetime)

        metadata = {
            "subscription_id": sub_id,
            "subscription_name": sub_name,
            "tenant_id": tenant_id,
            "state": subscription.get("state"),
            "created_date": creation_date,
            "estimated_age_days": age_days if age_days > 0 else None,
            "is_default": subscription.get("isDefault", False),
            "environment_name": subscription.get("environmentName"),
            "collected_at": datetime.now().isoformat()
        }

        if age_days > 0:
            print(f"     • Age: ~{age_days} days")
        else:
            print(f"     • Age: Unknown (will query last 365 days)")

        return metadata

    def save_subscription_metadata(
        self,
        subscription: Dict,
        output_dir: Path
    ) -> Path:
        """
        Save subscription metadata to file.

        Args:
            subscription: Subscription metadata dict
            output_dir: Output directory for this subscription

        Returns:
            Path to saved file
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / "subscription-info.json"
        with open(output_file, 'w') as f:
            json.dump(subscription, f, indent=2)

        return output_file

    def get_subscription_output_dir(
        self,
        base_output_dir: Path,
        subscription_id: str
    ) -> Path:
        """
        Get the output directory for a specific subscription.

        Args:
            base_output_dir: Base output directory
            subscription_id: Subscription ID

        Returns:
            Path to subscription-specific output directory
        """
        # Use short form of subscription ID (last 8 chars) for readability
        # but include full ID in the folder name for uniqueness
        return base_output_dir / subscription_id
