"""Shared utility functions for aw-export-timewarrior."""

from datetime import datetime

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
            'RETURN_AS_TIMEZONE_AWARE': True,
            'TIMEZONE': 'local',
        }
    )

    if dt is None:
        raise ValueError(f"Unable to parse datetime string: {dt_string}")

    return dt
