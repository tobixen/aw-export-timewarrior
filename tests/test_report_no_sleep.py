"""Tests to ensure report command doesn't block with time.sleep.

The report command should complete quickly even for recent events.
It should not call time.sleep() when generating reports.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def test_data_path() -> Path:
    """Path to the anonymized test data file."""
    return Path(__file__).parent / "fixtures" / "report_test_data.json"


@pytest.fixture
def exporter_with_test_data(test_data_path: Path):
    """Create an Exporter instance with test data loaded."""
    from src.aw_export_timewarrior.export import load_test_data
    from src.aw_export_timewarrior.main import Exporter

    test_data = load_test_data(test_data_path)
    exporter = Exporter(dry_run=True, test_data=test_data)
    return exporter


def test_collect_report_data_does_not_sleep(exporter_with_test_data):
    """Test that collect_report_data doesn't call time.sleep."""
    from src.aw_export_timewarrior.report import collect_report_data

    start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
    end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

    # Mock time.sleep to track if it's called
    with patch("time.sleep") as mock_sleep:
        data = collect_report_data(exporter_with_test_data, start_time, end_time)

        # Assert sleep was never called
        mock_sleep.assert_not_called()

    # Sanity check: we got some data
    assert len(data) > 0


def test_extract_specialized_data_does_not_sleep(exporter_with_test_data):
    """Test that extract_specialized_data doesn't call time.sleep for browser events."""
    from src.aw_export_timewarrior.report import extract_specialized_data

    # Create a browser window event that should trigger get_corresponding_event
    browser_event = {
        "timestamp": datetime(2025, 12, 11, 9, 4, 43, tzinfo=UTC),
        "duration": timedelta(seconds=10),
        "data": {"app": "chromium", "title": "Test Page - Chromium"},
    }

    with patch("time.sleep") as mock_sleep:
        extract_specialized_data(exporter_with_test_data, browser_event)

        # Assert sleep was never called
        mock_sleep.assert_not_called()


def test_get_corresponding_event_does_not_sleep_for_report(exporter_with_test_data):
    """Test that get_corresponding_event doesn't sleep when retry=0."""
    # Create a window event
    window_event = {
        "timestamp": datetime(2025, 12, 11, 9, 4, 43, tzinfo=UTC),
        "duration": timedelta(seconds=10),
        "data": {"app": "chromium", "title": "Test Page - Chromium"},
    }

    # Get a browser bucket ID
    bucket_key = "aw-watcher-web-chrome"
    if bucket_key not in exporter_with_test_data.event_fetcher.bucket_short:
        pytest.skip("No browser bucket in test data")

    bucket_id = exporter_with_test_data.event_fetcher.bucket_short[bucket_key]["id"]

    with patch("time.sleep") as mock_sleep:
        # get_corresponding_event with retry=0 should never sleep
        exporter_with_test_data.event_fetcher.get_corresponding_event(
            window_event, bucket_id, retry=0
        )

        # Assert sleep was never called
        mock_sleep.assert_not_called()


def test_generate_activity_report_does_not_sleep(exporter_with_test_data, capsys):
    """Test that generate_activity_report doesn't call time.sleep."""
    from src.aw_export_timewarrior.report import generate_activity_report

    # Set the exporter's time range to match our test data
    exporter_with_test_data.start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
    exporter_with_test_data.end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

    with patch("time.sleep") as mock_sleep:
        generate_activity_report(
            exporter=exporter_with_test_data,
            all_columns=False,
            format="table",
            truncate=True,
        )

        # Assert sleep was never called
        mock_sleep.assert_not_called()


def test_generate_activity_report_with_show_exports_does_not_sleep(exporter_with_test_data, capsys):
    """Test that generate_activity_report with show_exports doesn't sleep."""
    from src.aw_export_timewarrior.report import generate_activity_report

    # Set the exporter's time range to match our test data
    exporter_with_test_data.start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
    exporter_with_test_data.end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

    with patch("time.sleep") as mock_sleep:
        generate_activity_report(
            exporter=exporter_with_test_data,
            all_columns=True,
            format="table",
            truncate=True,
            show_exports=True,  # This is what the user was using
        )

        # Assert sleep was never called
        mock_sleep.assert_not_called()


def test_get_corresponding_event_with_retry_sleeps_for_recent_events():
    """Test that get_corresponding_event with retry > 0 will sleep for recent events.

    This test documents the expected behavior: when retry > 0 and events are
    recent (within 90s of current time), get_corresponding_event will sleep
    if no matching event found. This is by design for the sync command where
    we want to wait for events to propagate.

    The report code should always pass retry=0 to avoid this sleep.
    """
    import contextlib

    from src.aw_export_timewarrior.aw_client import EventFetcher

    # Create a minimal event fetcher
    fetcher = EventFetcher(test_data={"buckets": {}})

    # Create a very recent event (within 90 seconds of "now")
    now = datetime.now(UTC)
    recent_event = {
        "timestamp": now - timedelta(seconds=30),
        "duration": timedelta(seconds=10),
        "data": {"app": "chromium", "title": "Test Page"},
    }

    # Track sleep calls
    sleep_calls = []

    def mock_sleep(seconds):
        sleep_calls.append(seconds)
        # Don't actually wait, just track the call
        raise InterruptedError("Sleep interrupted for test")

    # Using retry=6 should trigger sleep for recent events
    # We expect InterruptedError since we interrupt the sleep
    with (
        patch("time.sleep", side_effect=mock_sleep),
        contextlib.suppress(InterruptedError),
    ):
        fetcher.get_corresponding_event(
            recent_event,
            "nonexistent_bucket",
            retry=6,
        )

    # Verify that sleep was attempted (this is expected behavior for retry > 0)
    assert len(sleep_calls) > 0, "Expected sleep to be called for recent events with retry > 0"


def test_get_corresponding_event_with_retry_zero_does_not_sleep():
    """Test that get_corresponding_event with retry=0 never sleeps.

    This is the behavior we need for the report command.
    """
    from src.aw_export_timewarrior.aw_client import EventFetcher

    # Create a minimal event fetcher
    fetcher = EventFetcher(test_data={"buckets": {}})

    # Create a very recent event (within 90 seconds of "now")
    now = datetime.now(UTC)
    recent_event = {
        "timestamp": now - timedelta(seconds=30),
        "duration": timedelta(seconds=10),
        "data": {"app": "chromium", "title": "Test Page"},
    }

    with patch("time.sleep") as mock_sleep:
        fetcher.get_corresponding_event(
            recent_event,
            "nonexistent_bucket",
            retry=0,  # Critical: no retries means no sleep
        )

        # Verify sleep was never called
        mock_sleep.assert_not_called()


def test_extract_specialized_data_with_recent_browser_event_does_not_sleep():
    """Test that extract_specialized_data does NOT sleep for recent browser events.

    This test verifies the fix: extract_specialized_data now calls
    get_corresponding_event with retry=0, so it never sleeps even for
    recent events without matching sub-events.
    """
    from src.aw_export_timewarrior.export import load_test_data
    from src.aw_export_timewarrior.main import Exporter
    from src.aw_export_timewarrior.report import extract_specialized_data

    # Create an exporter with test data
    test_data_path = Path(__file__).parent / "fixtures" / "report_test_data.json"
    test_data = load_test_data(test_data_path)
    exporter = Exporter(dry_run=True, test_data=test_data)

    # Create a recent browser event that WON'T have a matching web event
    # (because it's at a timestamp our test data doesn't cover)
    now = datetime.now(UTC)
    recent_browser_event = {
        "timestamp": now - timedelta(seconds=60),  # 1 minute ago
        "duration": timedelta(seconds=10),
        "data": {"app": "chromium", "title": "Recent Browser Page - Chromium"},
    }

    with patch("time.sleep") as mock_sleep:
        result = extract_specialized_data(exporter, recent_browser_event)

        # Verify sleep was never called - this is the key assertion
        mock_sleep.assert_not_called()

        # Result should still be valid, just without specialized data
        assert result["app"] == "chromium"
        assert result["specialized_type"] == "browser"
        # specialized_data may or may not be None depending on whether there's
        # a matching browser event in our test data
