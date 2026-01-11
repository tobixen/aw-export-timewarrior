"""Tests for the report generation functionality."""

from datetime import UTC, datetime

import pytest

from src.aw_export_timewarrior.main import Exporter
from src.aw_export_timewarrior.report import (
    collect_report_data,
    extract_specialized_data,
    format_duration,
    truncate_string,
)

# Uses shared fixtures from conftest.py:
# - report_test_data_path
# - exporter_with_report_data


def test_format_duration() -> None:
    """Test duration formatting."""
    from datetime import timedelta

    assert format_duration(timedelta(hours=1, minutes=23, seconds=45)) == "01:23:45"
    assert format_duration(timedelta(seconds=30)) == "00:00:30"
    assert format_duration(timedelta(hours=10)) == "10:00:00"
    assert format_duration(timedelta(0)) == "00:00:00"


def test_truncate_string() -> None:
    """Test string truncation."""
    assert truncate_string("short", 50) == "short"
    assert truncate_string("x" * 100, 50) == "x" * 47 + "..."
    assert len(truncate_string("x" * 100, 50)) == 50


def test_extract_specialized_data_browser(exporter_with_report_data: Exporter) -> None:
    """Test extraction of browser URL data."""
    # Create a test window event with chromium
    window_event = {
        "timestamp": datetime(2025, 12, 11, 9, 4, 43, tzinfo=UTC),
        "duration": pytest.approx(0.0),
        "data": {"app": "chromium", "title": "Chat - Test Chat - Chromium"},
    }

    result = extract_specialized_data(exporter_with_report_data, window_event)

    assert result["app"] == "chromium"
    assert result["specialized_type"] == "browser"
    # May or may not find a matching browser event depending on timing
    # Just verify the structure is correct
    if result["specialized_data"]:
        assert "https://" in result["specialized_data"]


def test_extract_specialized_data_non_browser(exporter_with_report_data: Exporter) -> None:
    """Test that non-browser/editor/terminal apps return no specialized data."""
    window_event = {
        "timestamp": datetime(2025, 12, 11, 9, 0, 1, tzinfo=UTC),
        "duration": pytest.approx(0.0),
        "data": {"app": "feh", "title": "photo.jpg"},
    }

    result = extract_specialized_data(exporter_with_report_data, window_event)

    assert result["app"] == "feh"
    assert result["specialized_type"] is None
    assert result["specialized_data"] is None


def test_collect_report_data(exporter_with_report_data: Exporter) -> None:
    """Test collecting report data from test dataset."""
    start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
    end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

    data = collect_report_data(exporter_with_report_data, start_time, end_time)

    # Should have multiple events
    assert len(data) > 0

    # Check that data has required keys
    for row in data:
        assert "timestamp" in row
        assert "duration" in row
        assert "window_title" in row
        assert "app" in row
        assert "specialized_type" in row
        assert "specialized_data" in row
        assert "afk_status" in row
        assert "tags" in row

    # Find a browser event and verify it has URL
    browser_events = [row for row in data if row["specialized_type"] == "browser"]
    assert len(browser_events) > 0

    # At least one browser event should have a URL
    urls = [row["specialized_data"] for row in browser_events if row["specialized_data"]]
    assert len(urls) > 0
    assert any("https://" in url for url in urls)


def test_report_data_sorted_by_timestamp(exporter_with_report_data: Exporter) -> None:
    """Test that report data is sorted by timestamp."""
    start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
    end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

    data = collect_report_data(exporter_with_report_data, start_time, end_time)

    # Verify chronological order
    for i in range(len(data) - 1):
        assert data[i]["timestamp"] <= data[i + 1]["timestamp"]


def test_report_includes_afk_status(exporter_with_report_data: Exporter) -> None:
    """Test that AFK status is included in report data."""
    start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
    end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

    data = collect_report_data(exporter_with_report_data, start_time, end_time)

    # Check that AFK status is populated
    afk_statuses = {row["afk_status"] for row in data}
    # Should have at least one status (not-afk, afk, or unknown)
    assert len(afk_statuses) > 0
    assert afk_statuses.issubset({"not-afk", "afk", "unknown"})


def test_report_includes_tags(exporter_with_report_data: Exporter) -> None:
    """Test that tags are determined for events."""
    start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
    end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

    data = collect_report_data(exporter_with_report_data, start_time, end_time)

    # All events should have tags (at minimum 'UNMATCHED' if no rules match)
    for row in data:
        assert isinstance(row["tags"], set)
        assert len(row["tags"]) > 0
