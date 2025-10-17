#!/usr/bin/env python3
"""
Date Utilities
Handles date range calculations and subscription age logic.
"""

from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from dateutil import parser


def parse_azure_date(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse Azure date string to datetime object.

    Args:
        date_str: Azure date string (ISO format or various formats)

    Returns:
        datetime object or None if parsing fails
    """
    if not date_str:
        return None

    try:
        return parser.parse(date_str)
    except:
        return None


def calculate_query_periods(
    subscription_created_date: Optional[datetime],
    max_days: int = 365,
    chunk_days: int = 30
) -> List[Tuple[datetime, datetime]]:
    """
    Calculate appropriate query periods based on subscription age.

    Handles subscriptions of any age:
    - Sub created 400 days ago → 12 chunks (360 days, stay under 365)
    - Sub created 60 days ago → 2 chunks (60 days)
    - Sub created 15 days ago → 1 chunk (15 days)
    - Sub created 2 days ago → 1 chunk (2 days)
    - Sub created today → 1 chunk (partial day)

    Args:
        subscription_created_date: When the subscription was created
        max_days: Maximum days to look back (default 365 for activity logs)
        chunk_days: Size of each chunk in days (default 30)

    Returns:
        List of (start_date, end_date) tuples representing query periods
    """
    end_date = datetime.now()

    # If no creation date provided, use max_days
    if subscription_created_date is None:
        start_date = end_date - timedelta(days=max_days)
    else:
        # Use the later of: creation date or max_days ago
        start_date = max(subscription_created_date, end_date - timedelta(days=max_days))

    days_available = (end_date - start_date).days

    # Handle brand new subscription (created today or within hours)
    if days_available < 1:
        return [(start_date, end_date)]

    # If less than chunk_days, return single period
    if days_available <= chunk_days:
        return [(start_date, end_date)]

    # Split into chunks
    periods = []
    current_start = start_date

    while current_start < end_date:
        current_end = min(current_start + timedelta(days=chunk_days), end_date)
        periods.append((current_start, current_end))
        current_start = current_end

    return periods


def format_date_for_azure(dt: datetime) -> str:
    """
    Format datetime for Azure CLI commands.

    Args:
        dt: datetime object

    Returns:
        ISO 8601 formatted string (e.g., "2025-01-15T10:30:00Z")
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_date_for_filename(dt: datetime) -> str:
    """
    Format datetime for use in filenames.

    Args:
        dt: datetime object

    Returns:
        Filename-safe date string (e.g., "2025-01-15")
    """
    return dt.strftime("%Y-%m-%d")


def get_period_filename(
    period_type: str,
    start_date: datetime,
    end_date: datetime
) -> str:
    """
    Generate filename for a specific time period.

    Args:
        period_type: Type of data ("activity-log" or "cost-management")
        start_date: Start of period
        end_date: End of period

    Returns:
        Filename like "activity-log.2025-01-01_to_2025-01-30.json"
    """
    start_str = format_date_for_filename(start_date)
    end_str = format_date_for_filename(end_date)
    return f"{period_type}.{start_str}_to_{end_str}.json"


def estimate_subscription_age_days(subscription_created_date: Optional[datetime]) -> int:
    """
    Estimate how many days old a subscription is.

    Args:
        subscription_created_date: When the subscription was created

    Returns:
        Number of days (0 if unknown)
    """
    if not subscription_created_date:
        return 0

    age = datetime.now() - subscription_created_date
    return max(0, age.days)


def is_subscription_young(subscription_created_date: Optional[datetime], threshold_days: int = 30) -> bool:
    """
    Check if a subscription is younger than threshold.

    Args:
        subscription_created_date: When the subscription was created
        threshold_days: Age threshold in days (default 30)

    Returns:
        True if subscription is younger than threshold
    """
    age_days = estimate_subscription_age_days(subscription_created_date)
    return age_days < threshold_days if age_days > 0 else False
