"""Convert report timestamps to the configured human-facing timezone."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

REPORT_TIMEZONE_NAME = "America/Los_Angeles"
REPORT_TIMEZONE = ZoneInfo(REPORT_TIMEZONE_NAME)


def to_report_timezone(value: datetime) -> datetime:
    """Return an aware datetime expressed in Los Angeles local time."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(REPORT_TIMEZONE)


def format_report_time(value: datetime) -> str:
    """Format a timestamp with the correct PST/PDT abbreviation."""

    return to_report_timezone(value).strftime("%Y-%m-%d %H:%M:%S %Z")


def report_isoformat(value: datetime) -> str:
    """Serialize a timestamp with the Los Angeles UTC offset."""

    return to_report_timezone(value).isoformat()


__all__ = [
    "REPORT_TIMEZONE_NAME",
    "format_report_time",
    "report_isoformat",
    "to_report_timezone",
]
