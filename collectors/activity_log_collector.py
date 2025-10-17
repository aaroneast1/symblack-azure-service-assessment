#!/usr/bin/env python3
"""
Activity Log Collector
Collects Azure Activity Logs in 30-day chunks.
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from utils.azure_client import AzureClient
from utils.date_utils import (
    calculate_query_periods,
    format_date_for_azure,
    get_period_filename,
    parse_azure_date
)


class ActivityLogCollector:
    """Collects Azure Activity Logs in manageable chunks."""

    def __init__(self, azure_client: AzureClient):
        """
        Initialize the activity log collector.

        Args:
            azure_client: Azure CLI client instance
        """
        self.client = azure_client

    def collect_activity_logs(
        self,
        subscription_id: str,
        output_dir: Path,
        subscription_created_date: Optional[datetime] = None,
        force_refresh: bool = False
    ) -> Dict:
        """
        Collect activity logs for a subscription in 30-day chunks.

        Args:
            subscription_id: Azure subscription ID
            output_dir: Directory to save activity log files
            subscription_created_date: When subscription was created (for age calculation)
            force_refresh: If True, re-download existing files

        Returns:
            Summary dict with collection statistics
        """
        print(f"\n📋 Collecting Activity Logs for subscription {subscription_id}")

        # Set active subscription
        self.client.set_subscription(subscription_id)

        # Create output directory
        activity_log_dir = output_dir / "activity-log"
        activity_log_dir.mkdir(parents=True, exist_ok=True)

        # Calculate query periods (30-day chunks)
        # Note: Activity log retention is 90 days (Azure limitation)
        periods = calculate_query_periods(
            subscription_created_date,
            max_days=90,
            chunk_days=30
        )

        print(f"  ℹ️  Will query {len(periods)} periods (30-day chunks)")
        print(f"  ℹ️  Date range: {periods[0][0].strftime('%Y-%m-%d')} to {periods[-1][1].strftime('%Y-%m-%d')}")
        print(f"  ℹ️  5-second delay between requests")

        # Collect each period
        collected_files = []
        skipped_files = []
        failed_periods = []
        total_entries = 0

        for i, (start_date, end_date) in enumerate(periods, 1):
            period_result = self._collect_period(
                start_date=start_date,
                end_date=end_date,
                period_num=i,
                total_periods=len(periods),
                output_dir=activity_log_dir,
                force_refresh=force_refresh
            )

            if period_result["status"] == "collected":
                collected_files.append(period_result["file"])
                total_entries += period_result["entries"]
            elif period_result["status"] == "skipped":
                skipped_files.append(period_result["file"])
                total_entries += period_result["entries"]
            elif period_result["status"] == "failed":
                failed_periods.append({
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "error": period_result.get("error")
                })

            # Delay to avoid rate limiting
            if i < len(periods):
                time.sleep(5)

        # Summary
        print(f"\n  ✅ Activity Log Collection Summary:")
        print(f"     • Files collected: {len(collected_files)}")
        print(f"     • Files skipped (existing): {len(skipped_files)}")
        print(f"     • Periods failed: {len(failed_periods)}")
        print(f"     • Total entries: {total_entries:,}")

        if failed_periods:
            print(f"\n  ⚠️  Failed periods:")
            for fp in failed_periods:
                print(f"     • {fp['start']} to {fp['end']}: {fp['error']}")

        return {
            "subscription_id": subscription_id,
            "collected_files": collected_files,
            "skipped_files": skipped_files,
            "failed_periods": failed_periods,
            "total_entries": total_entries,
            "total_periods": len(periods)
        }

    def _collect_period(
        self,
        start_date: datetime,
        end_date: datetime,
        period_num: int,
        total_periods: int,
        output_dir: Path,
        force_refresh: bool
    ) -> Dict:
        """
        Collect activity logs for a single period.

        Args:
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
        filename = get_period_filename("activity-log", start_date, end_date)
        output_file = output_dir / filename

        # Check if file already exists
        if output_file.exists() and not force_refresh:
            print(f"  [{period_num:02d}/{total_periods:02d}] {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} → ⏭️  Skipped (exists)")
            # Count entries in existing file
            try:
                with open(output_file, 'r') as f:
                    data = json.load(f)
                    entries = len(data) if isinstance(data, list) else 0
            except:
                entries = 0

            return {
                "status": "skipped",
                "file": str(output_file),
                "entries": entries
            }

        # Format dates for Azure CLI
        start_str = format_date_for_azure(start_date)
        end_str = format_date_for_azure(end_date)

        print(f"  [{period_num:02d}/{total_periods:02d}] {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} → ", end="", flush=True)

        # Query activity logs
        result = self.client.run_command(
            [
                "monitor", "activity-log", "list",
                "--start-time", start_str,
                "--end-time", end_str
            ],
            allow_failure=True,
            timeout=300  # 5 minutes
        )

        # Check for errors (result will be a dict if failed, list if succeeded)
        if isinstance(result, dict) and result.get("failed"):
            error_msg = result.get("error", "Unknown error")[:100]
            print(f"❌ Failed: {error_msg}")
            return {
                "status": "failed",
                "error": error_msg
            }

        # Check if we got data
        if not isinstance(result, list):
            print(f"❌ No data")
            return {
                "status": "failed",
                "error": "No data returned"
            }

        # Save to file
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)

        print(f"✓ {len(result):,} entries")

        return {
            "status": "collected",
            "file": str(output_file),
            "entries": len(result)
        }
