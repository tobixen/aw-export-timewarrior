"""Shared utility functions for aw-export-timewarrior."""

from datetime import datetime, timedelta

import dateparser


def parse_datetime(dt_string: str) -> datetime:
    """
    Parse a datetime string in various formats.

    Supports:
    - ISO format: "2025-01-01T09:00:00Z"
    - Relative dates: "yesterday", "today", "tomorrow", "2 hours ago"
    - Simple format: "2025-01-01 09:00" (interpreted as local time)

    Args:
        dt_string: DateTime string to parse

    Returns:
        Timezone-aware datetime object (local timezone)
    """
    # Use dateparser which handles many formats including relative dates
    dt = dateparser.parse(
        dt_string,
        settings={
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": "local",
        },
    )

    if dt is None:
        raise ValueError(f"Unable to parse datetime string: {dt_string}")

    return dt


def normalize_timestamp(ts: str | datetime) -> datetime:
    """
    Normalize a timestamp to a timezone-aware datetime object.

    Args:
        ts: Timestamp as ISO string or datetime object

    Returns:
        Timezone-aware datetime object
    """
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def normalize_duration(dur: float | timedelta) -> timedelta:
    """
    Normalize a duration to a timedelta object.

    Args:
        dur: Duration as float (seconds) or timedelta

    Returns:
        timedelta object
    """
    if isinstance(dur, timedelta):
        return dur
    return timedelta(seconds=dur)


def get_event_range(event: dict) -> tuple[datetime, datetime]:
    """
    Get the start and end time of an event.

    Args:
        event: Event dictionary with 'timestamp' and 'duration' keys

    Returns:
        Tuple of (start, end) datetime objects
    """
    start = normalize_timestamp(event["timestamp"])
    duration = normalize_duration(event["duration"])
    end = start + duration
    return start, end


def ts2str(ts: datetime, format: str = "%FT%H:%M:%S") -> str:
    """Format a datetime as a string in the local timezone."""
    return ts.astimezone().strftime(format)


def ts2strtime(ts: datetime | None) -> str:
    """Format a datetime as time-only string (HH:MM:SS)."""
    if not ts:
        return "XX:XX:XX"
    return ts2str(ts, "%H:%M:%S")
