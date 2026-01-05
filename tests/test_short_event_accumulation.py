"""Tests for short event accumulation logic.

When rapidly switching within the same app (e.g., flipping through photos in feh),
individual events may be very short (<3s), but the cumulative wall-clock time
represents significant activity that should not be ignored.

This module tests the smart ignore logic that tracks consecutive short events
and prevents ignoring them when the total time span is significant.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aw_export_timewarrior.main import Exporter


class TestShortEventAccumulation:
    """Test that consecutive short events in the same app are not ignored."""

    @pytest.fixture
    def config_path(self):
        return Path(__file__).parent / "fixtures" / "test_config.toml"

    def create_test_data_with_short_events(
        self,
        app: str,
        num_events: int,
        event_duration_seconds: float,
        event_gap_seconds: float,
        start_time: datetime | None = None,
    ) -> dict:
        """Create test data with multiple short events from the same app.

        Args:
            app: Application name
            num_events: Number of events to create
            event_duration_seconds: Duration of each event
            event_gap_seconds: Gap between events (simulates rapid title changes)
            start_time: Starting timestamp
        """
        start_time = start_time or datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
        current_time = start_time

        window_events = []
        afk_events = []

        # Create the short window events
        for i in range(num_events):
            event = {
                "id": i,
                "timestamp": current_time,
                "duration": timedelta(seconds=event_duration_seconds),
                "data": {"app": app, "title": f"{app} [image {i + 1} of {num_events}]"},
            }
            window_events.append(event)
            current_time += timedelta(seconds=event_duration_seconds + event_gap_seconds)

        end_time = current_time

        # Create a single not-afk event covering the whole period
        afk_events.append(
            {
                "id": 0,
                "timestamp": start_time,
                "duration": end_time - start_time,
                "data": {"status": "not-afk"},
            }
        )

        return {
            "buckets": {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "type": "currentwindow",
                    "client": "aw-watcher-window",
                    "hostname": "test",
                    "created": start_time.isoformat(),
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "type": "afkstatus",
                    "client": "aw-watcher-afk",
                    "hostname": "test",
                    "created": start_time.isoformat(),
                },
            },
            "events": {
                "aw-watcher-window_test": window_events,
                "aw-watcher-afk_test": afk_events,
            },
            "metadata": {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        }

    def test_single_short_event_is_ignored(self, config_path):
        """Test that a single short event (<3s) is still ignored."""
        test_data = self.create_test_data_with_short_events(
            app="feh",
            num_events=1,
            event_duration_seconds=0.5,  # Very short
            event_gap_seconds=0,
        )

        exporter = Exporter(
            dry_run=True,
            config_path=config_path,
            test_data=test_data,
            show_unmatched=True,
        )

        # Process all events
        exporter.tick(process_all=True)

        # Single short event should be ignored
        assert len(exporter.unmatched_events) == 0

    def test_many_short_events_same_app_not_ignored(self, config_path):
        """Test that many short events from the same app are NOT ignored
        when total wall-clock time exceeds ignore_interval (3s).
        """
        # Create 10 events of 0.5s each, with 0.5s gaps
        # Total wall-clock time: 10 * (0.5 + 0.5) = 10s > 3s
        test_data = self.create_test_data_with_short_events(
            app="feh",
            num_events=10,
            event_duration_seconds=0.5,
            event_gap_seconds=0.5,
        )

        exporter = Exporter(
            dry_run=True,
            config_path=config_path,
            test_data=test_data,
            show_unmatched=True,
        )

        # Process all events
        exporter.tick(process_all=True)

        # The events should NOT be ignored - feh doesn't match any rules,
        # so they should appear as unmatched
        assert len(exporter.unmatched_events) > 0, (
            "Short events from the same app should not be ignored "
            "when wall-clock time exceeds threshold"
        )

        # All feh events should be tracked as unmatched
        feh_events = [e for e in exporter.unmatched_events if e["data"]["app"] == "feh"]
        assert len(feh_events) > 0

    def test_short_events_different_apps_still_ignored(self, config_path):
        """Test that short events from different apps ARE still ignored
        (window-switching noise).
        """
        start_time = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
        current_time = start_time

        window_events = []
        apps = ["app1", "app2", "app3", "app4", "app5"]

        # Create 5 events of 0.5s each, from different apps
        for i, app in enumerate(apps):
            event = {
                "id": i,
                "timestamp": current_time,
                "duration": timedelta(seconds=0.5),
                "data": {"app": app, "title": f"Window {i + 1}"},
            }
            window_events.append(event)
            current_time += timedelta(seconds=1)

        end_time = current_time

        afk_events = [
            {
                "id": 0,
                "timestamp": start_time,
                "duration": end_time - start_time,
                "data": {"status": "not-afk"},
            }
        ]

        test_data = {
            "buckets": {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "type": "currentwindow",
                    "client": "aw-watcher-window",
                    "hostname": "test",
                    "created": start_time.isoformat(),
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "type": "afkstatus",
                    "client": "aw-watcher-afk",
                    "hostname": "test",
                    "created": start_time.isoformat(),
                },
            },
            "events": {
                "aw-watcher-window_test": window_events,
                "aw-watcher-afk_test": afk_events,
            },
            "metadata": {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        }

        exporter = Exporter(
            dry_run=True,
            config_path=config_path,
            test_data=test_data,
            show_unmatched=True,
        )

        # Process all events
        exporter.tick(process_all=True)

        # Events from different apps should be ignored (window-switching noise)
        assert len(exporter.unmatched_events) == 0, (
            "Short events from different apps should be ignored as window-switching noise"
        )

    def test_zero_duration_events_accumulated(self, config_path):
        """Test that even zero-duration events are tracked when
        wall-clock time is significant.

        This simulates feh where each photo switch creates a 0-duration event
        but you're actively viewing photos for a significant time.
        """
        start_time = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
        current_time = start_time

        window_events = []

        # Create 20 events with 0 duration, spaced 0.5s apart
        # Total wall-clock time: 20 * 0.5 = 10s > 3s
        for i in range(20):
            event = {
                "id": i,
                "timestamp": current_time,
                "duration": timedelta(seconds=0),  # Zero duration!
                "data": {"app": "feh", "title": f"feh [{i + 1} of 20] - photo.jpg"},
            }
            window_events.append(event)
            current_time += timedelta(seconds=0.5)

        end_time = current_time

        afk_events = [
            {
                "id": 0,
                "timestamp": start_time,
                "duration": end_time - start_time,
                "data": {"status": "not-afk"},
            }
        ]

        test_data = {
            "buckets": {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "type": "currentwindow",
                    "client": "aw-watcher-window",
                    "hostname": "test",
                    "created": start_time.isoformat(),
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "type": "afkstatus",
                    "client": "aw-watcher-afk",
                    "hostname": "test",
                    "created": start_time.isoformat(),
                },
            },
            "events": {
                "aw-watcher-window_test": window_events,
                "aw-watcher-afk_test": afk_events,
            },
            "metadata": {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        }

        exporter = Exporter(
            dry_run=True,
            config_path=config_path,
            test_data=test_data,
            show_unmatched=True,
        )

        # Process all events
        exporter.tick(process_all=True)

        # Even zero-duration events should be tracked when wall-clock time is significant
        assert len(exporter.unmatched_events) > 0, (
            "Zero-duration events should not be ignored "
            "when wall-clock time in same app exceeds threshold"
        )


class TestShortEventAccumulationReset:
    """Test that short event accumulation resets correctly."""

    @pytest.fixture
    def config_path(self):
        return Path(__file__).parent / "fixtures" / "test_config.toml"

    def test_long_event_resets_accumulation(self, config_path):
        """Test that a long event resets the short event accumulation."""
        start_time = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
        current_time = start_time

        window_events = []

        # 2 short events from app1 (not enough to exceed threshold)
        for i in range(2):
            window_events.append(
                {
                    "id": len(window_events),
                    "timestamp": current_time,
                    "duration": timedelta(seconds=0.5),
                    "data": {"app": "app1", "title": f"Window {i + 1}"},
                }
            )
            current_time += timedelta(seconds=1)

        # 1 long event (resets accumulation)
        window_events.append(
            {
                "id": len(window_events),
                "timestamp": current_time,
                "duration": timedelta(seconds=5),  # > 3s
                "data": {"app": "app2", "title": "Long event"},
            }
        )
        current_time += timedelta(seconds=5)

        # 2 more short events from app1 (starts fresh, not enough)
        for i in range(2):
            window_events.append(
                {
                    "id": len(window_events),
                    "timestamp": current_time,
                    "duration": timedelta(seconds=0.5),
                    "data": {"app": "app1", "title": f"Window {i + 3}"},
                }
            )
            current_time += timedelta(seconds=1)

        end_time = current_time

        afk_events = [
            {
                "id": 0,
                "timestamp": start_time,
                "duration": end_time - start_time,
                "data": {"status": "not-afk"},
            }
        ]

        test_data = {
            "buckets": {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "type": "currentwindow",
                    "client": "aw-watcher-window",
                    "hostname": "test",
                    "created": start_time.isoformat(),
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "type": "afkstatus",
                    "client": "aw-watcher-afk",
                    "hostname": "test",
                    "created": start_time.isoformat(),
                },
            },
            "events": {
                "aw-watcher-window_test": window_events,
                "aw-watcher-afk_test": afk_events,
            },
            "metadata": {
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        }

        exporter = Exporter(
            dry_run=True,
            config_path=config_path,
            test_data=test_data,
            show_unmatched=True,
        )

        # Process all events
        exporter.tick(process_all=True)

        # The long event (app2) should be tracked as unmatched
        # The short events from app1 should be ignored (not enough time before/after reset)
        app2_events = [e for e in exporter.unmatched_events if e["data"]["app"] == "app2"]
        assert len(app2_events) == 1, "Long event should be tracked"

        app1_events = [e for e in exporter.unmatched_events if e["data"]["app"] == "app1"]
        assert len(app1_events) == 0, (
            "Short events before/after long event should be ignored "
            "(accumulation reset by long event)"
        )
