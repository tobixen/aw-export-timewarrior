"""Test tmux fallback to most recent event when no overlap exists.

This test uses real-world data from Dec 30, 2025 where:
- Window event at 11:39:16 (124.3s duration) falls in a gap in tmux events
- Tmux events: 11:39:03-11:39:09, then gap until 11:41:39
- Without fallback: no tmux match found
- With fallback: uses the 11:39:03 event (most recent before window event)
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from aw_export_timewarrior.aw_client import EventFetcher


class TestTmuxFallback:
    """Test the fallback_to_recent parameter for tmux events."""

    @pytest.fixture
    def mock_event_fetcher(self):
        """Create a mock EventFetcher with real-world tmux data."""
        fetcher = MagicMock(spec=EventFetcher)
        fetcher.log_callback = lambda *args, **kwargs: None

        # Tmux events from Dec 30, 2025 - note the gap from 11:39:09 to 11:41:39
        self.tmux_events = [
            {
                "id": 487014,
                "timestamp": datetime(2025, 12, 30, 11, 41, 39, tzinfo=UTC),
                "duration": timedelta(seconds=10.0),
                "data": {
                    "pane_current_command": "claude",
                    "pane_current_path": "/home/tobias/mobilizon",
                    "pane_title": "✳ Erlang Installation Issues",
                },
            },
            {
                "id": 487003,
                "timestamp": datetime(2025, 12, 30, 11, 39, 3, tzinfo=UTC),
                "duration": timedelta(seconds=6.0),
                "data": {
                    "pane_current_command": "claude",
                    "pane_current_path": "/home/tobias/mobilizon",
                    "pane_title": "✳ Erlang Installation Issues",
                },
            },
            {
                "id": 487002,
                "timestamp": datetime(2025, 12, 30, 11, 38, 59, tzinfo=UTC),
                "duration": timedelta(seconds=0.0),
                "data": {
                    "pane_current_command": "claude",
                    "pane_current_path": "/home/tobias/caldav",
                    "pane_title": "✳ Push commits",
                },
            },
        ]

        # Window event that falls in the gap (11:39:16, between 11:39:09 and 11:41:39)
        self.window_event_in_gap = {
            "id": 487010,
            "timestamp": datetime(2025, 12, 30, 11, 39, 16, tzinfo=UTC),
            "duration": timedelta(seconds=124.3),
            "data": {"app": "foot", "title": "✳ Container Tracking & Hook Errors"},
        }

        # Window event that overlaps with tmux event at 11:39:03
        self.window_event_overlapping = {
            "id": 487005,
            "timestamp": datetime(2025, 12, 30, 11, 39, 5, tzinfo=UTC),
            "duration": timedelta(seconds=3.0),
            "data": {"app": "foot", "title": "some terminal"},
        }

        return fetcher

    def test_no_fallback_returns_none_for_gap(self, mock_event_fetcher):
        """Without fallback, window events in tmux gaps return None."""

        # Configure mock to return events based on time range
        def get_events_side_effect(bucket_id, start=None, end=None):
            # Filter tmux events to those overlapping the query range
            result = []
            for e in self.tmux_events:
                event_end = e["timestamp"] + e["duration"]
                # Check if event overlaps with query range
                if start and end and e["timestamp"] < end and event_end > start:
                    result.append(e)
            return result

        mock_event_fetcher.get_events = MagicMock(side_effect=get_events_side_effect)

        # Create real EventFetcher and patch its get_events
        real_fetcher = EventFetcher.__new__(EventFetcher)
        real_fetcher.get_events = mock_event_fetcher.get_events
        real_fetcher.log_callback = lambda *args, **kwargs: None

        # Call without fallback
        result = real_fetcher.get_corresponding_event(
            self.window_event_in_gap,
            "aw-watcher-tmux",
            ignorable=True,
            fallback_to_recent=False,
        )

        # Should return None - no overlapping tmux event
        assert result is None

    def test_fallback_returns_most_recent_for_gap(self, mock_event_fetcher):
        """With fallback, window events in tmux gaps use most recent prior event."""
        call_count = [0]

        def get_events_side_effect(bucket_id, start=None, end=None):
            call_count[0] += 1
            result = []
            for e in self.tmux_events:
                event_end = e["timestamp"] + e["duration"]
                if not (start and end):
                    continue
                # Include overlapping events OR events that started within the range
                overlaps = e["timestamp"] < end and event_end > start
                in_range = e["timestamp"] < end and e["timestamp"] >= start
                if overlaps or in_range:
                    result.append(e)
            return result

        mock_event_fetcher.get_events = MagicMock(side_effect=get_events_side_effect)

        real_fetcher = EventFetcher.__new__(EventFetcher)
        real_fetcher.get_events = mock_event_fetcher.get_events
        real_fetcher.log_callback = lambda *args, **kwargs: None

        # Call with fallback enabled
        result = real_fetcher.get_corresponding_event(
            self.window_event_in_gap,
            "aw-watcher-tmux",
            ignorable=True,
            fallback_to_recent=True,
        )

        # Should return the most recent tmux event before the window event
        assert result is not None
        assert result["data"]["pane_current_command"] == "claude"
        # Should be the 11:39:03 event (most recent before 11:39:16)
        assert result["timestamp"] == datetime(2025, 12, 30, 11, 39, 3, tzinfo=UTC)

    def test_overlapping_event_returned_without_fallback(self, mock_event_fetcher):
        """When there's an overlapping event, it's returned without needing fallback."""

        def get_events_side_effect(bucket_id, start=None, end=None):
            result = []
            for e in self.tmux_events:
                event_end = e["timestamp"] + e["duration"]
                if start and end and e["timestamp"] < end and event_end > start:
                    result.append(e)
            return result

        mock_event_fetcher.get_events = MagicMock(side_effect=get_events_side_effect)

        real_fetcher = EventFetcher.__new__(EventFetcher)
        real_fetcher.get_events = mock_event_fetcher.get_events
        real_fetcher.log_callback = lambda *args, **kwargs: None

        # Call without fallback - should still work for overlapping event
        result = real_fetcher.get_corresponding_event(
            self.window_event_overlapping,
            "aw-watcher-tmux",
            ignorable=True,
            fallback_to_recent=False,
        )

        # Should return the overlapping event (11:39:03, 6s duration overlaps 11:39:05)
        assert result is not None
        assert result["timestamp"] == datetime(2025, 12, 30, 11, 39, 3, tzinfo=UTC)

    def test_fallback_finds_event_slightly_after_window(self, mock_event_fetcher):
        """Fallback should find tmux events that start slightly after the window event.

        Real-world scenario: 0-second window events at 19:04:08 just before
        tmux activity starts at 19:04:10. The fallback should look forward
        (within EVENT_MATCHING_BUFFER_SECONDS) as well as backward.
        """
        # A 0-second window event just before tmux activity starts
        window_event_before_tmux = {
            "id": 500001,
            "timestamp": datetime(2025, 12, 30, 19, 4, 8, tzinfo=UTC),
            "duration": timedelta(seconds=0),
            "data": {"app": "foot", "title": "aw-export-timewarrior"},
        }

        # Tmux event starts 2 seconds after the window event
        tmux_event_after = {
            "id": 500010,
            "timestamp": datetime(2025, 12, 30, 19, 4, 10, tzinfo=UTC),
            "duration": timedelta(seconds=23.0),
            "data": {
                "pane_current_command": "claude",
                "pane_current_path": "/home/tobias/puppet-atop",
                "pane_title": "Forge Publishing",
            },
        }

        def get_events_side_effect(bucket_id, start=None, end=None):
            events = [tmux_event_after]
            result = []
            for e in events:
                event_end = e["timestamp"] + e["duration"]
                if not (start and end):
                    continue
                overlaps = e["timestamp"] < end and event_end > start
                in_range = e["timestamp"] < end and e["timestamp"] >= start
                if overlaps or in_range:
                    result.append(e)
            return result

        mock_event_fetcher.get_events = MagicMock(side_effect=get_events_side_effect)

        real_fetcher = EventFetcher.__new__(EventFetcher)
        real_fetcher.get_events = mock_event_fetcher.get_events
        real_fetcher.log_callback = lambda *args, **kwargs: None

        # With fallback, should find the tmux event that starts 2s later
        result = real_fetcher.get_corresponding_event(
            window_event_before_tmux,
            "aw-watcher-tmux",
            ignorable=True,
            fallback_to_recent=True,
        )

        assert result is not None
        assert result["data"]["pane_current_path"] == "/home/tobias/puppet-atop"
        assert result["timestamp"] == datetime(2025, 12, 30, 19, 4, 10, tzinfo=UTC)
