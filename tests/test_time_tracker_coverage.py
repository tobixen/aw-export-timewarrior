"""Tests to improve coverage of time_tracker.py.

Covers:
- DryRunTracker with capture_commands enabled
- get_intervals edge case: interval spans entire query range
"""

from datetime import UTC, datetime

from aw_export_timewarrior.time_tracker import DryRunTracker


class TestDryRunTrackerCaptureCommands:
    """Tests for DryRunTracker with capture_commands enabled."""

    def test_stop_tracking_captures_command(self) -> None:
        """Test that stop_tracking captures command when capture_commands is set."""
        captured: list = []
        tracker = DryRunTracker(capture_commands=captured, hide_output=True)

        # Start tracking first
        start_time = datetime(2025, 1, 11, 10, 0, 0, tzinfo=UTC)
        tracker.start_tracking({"work", "coding"}, start_time)

        # Clear the start command
        captured.clear()

        # Stop tracking
        tracker.stop_tracking()

        assert len(captured) == 1
        assert captured[0] == ["timew", "stop"]

    def test_retag_captures_command(self) -> None:
        """Test that retag captures command when capture_commands is set."""
        captured: list = []
        tracker = DryRunTracker(capture_commands=captured, hide_output=True)

        # Start tracking first
        start_time = datetime(2025, 1, 11, 10, 0, 0, tzinfo=UTC)
        tracker.start_tracking({"work"}, start_time)

        # Clear the start command
        captured.clear()

        # Retag
        tracker.retag({"work", "meeting"})

        assert len(captured) == 1
        cmd = captured[0]
        assert cmd[0] == "timew"
        assert cmd[1] == "tag"
        assert cmd[2] == "@1"
        assert "meeting" in cmd
        assert "work" in cmd

    def test_track_interval_captures_command(self) -> None:
        """Test that track_interval captures command when capture_commands is set."""
        captured: list = []
        tracker = DryRunTracker(capture_commands=captured, hide_output=True)

        start = datetime(2025, 1, 11, 9, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 11, 10, 0, 0, tzinfo=UTC)
        tags = {"work", "coding"}

        tracker.track_interval(start, end, tags)

        assert len(captured) == 1
        cmd = captured[0]
        assert cmd[0] == "timew"
        assert cmd[1] == "track"
        assert "-" in cmd  # Separator between start and end
        assert "coding" in cmd
        assert "work" in cmd


class TestDryRunTrackerGetIntervalsEdgeCases:
    """Tests for get_intervals edge cases."""

    def test_interval_spans_entire_query_range(self) -> None:
        """Test that an interval spanning the entire query range is included."""
        tracker = DryRunTracker(hide_output=True)

        # Add an interval that spans a large range
        interval_start = datetime(2025, 1, 11, 8, 0, 0, tzinfo=UTC)
        interval_end = datetime(2025, 1, 11, 18, 0, 0, tzinfo=UTC)
        tracker.intervals.append(
            {
                "start": interval_start,
                "end": interval_end,
                "tags": {"work", "all-day"},
            }
        )

        # Query a smaller range that's entirely within the interval
        query_start = datetime(2025, 1, 11, 10, 0, 0, tzinfo=UTC)
        query_end = datetime(2025, 1, 11, 12, 0, 0, tzinfo=UTC)

        result = tracker.get_intervals(query_start, query_end)

        # The interval should be included because it spans the entire query range
        assert len(result) == 1
        assert result[0]["tags"] == {"work", "all-day"}

    def test_interval_before_query_range_excluded(self) -> None:
        """Test that an interval entirely before the query range is excluded."""
        tracker = DryRunTracker(hide_output=True)

        # Add an interval before the query range
        tracker.intervals.append(
            {
                "start": datetime(2025, 1, 11, 6, 0, 0, tzinfo=UTC),
                "end": datetime(2025, 1, 11, 7, 0, 0, tzinfo=UTC),
                "tags": {"early-work"},
            }
        )

        # Query a later range
        query_start = datetime(2025, 1, 11, 10, 0, 0, tzinfo=UTC)
        query_end = datetime(2025, 1, 11, 12, 0, 0, tzinfo=UTC)

        result = tracker.get_intervals(query_start, query_end)

        assert len(result) == 0

    def test_interval_after_query_range_excluded(self) -> None:
        """Test that an interval entirely after the query range is excluded."""
        tracker = DryRunTracker(hide_output=True)

        # Add an interval after the query range
        tracker.intervals.append(
            {
                "start": datetime(2025, 1, 11, 14, 0, 0, tzinfo=UTC),
                "end": datetime(2025, 1, 11, 15, 0, 0, tzinfo=UTC),
                "tags": {"late-work"},
            }
        )

        # Query an earlier range
        query_start = datetime(2025, 1, 11, 10, 0, 0, tzinfo=UTC)
        query_end = datetime(2025, 1, 11, 12, 0, 0, tzinfo=UTC)

        result = tracker.get_intervals(query_start, query_end)

        assert len(result) == 0

    def test_interval_overlapping_start_included(self) -> None:
        """Test that an interval overlapping the start of query range is included."""
        tracker = DryRunTracker(hide_output=True)

        # Add an interval that starts before and ends within the query range
        tracker.intervals.append(
            {
                "start": datetime(2025, 1, 11, 9, 0, 0, tzinfo=UTC),
                "end": datetime(2025, 1, 11, 11, 0, 0, tzinfo=UTC),
                "tags": {"overlap-start"},
            }
        )

        query_start = datetime(2025, 1, 11, 10, 0, 0, tzinfo=UTC)
        query_end = datetime(2025, 1, 11, 12, 0, 0, tzinfo=UTC)

        result = tracker.get_intervals(query_start, query_end)

        assert len(result) == 1
        assert result[0]["tags"] == {"overlap-start"}

    def test_interval_overlapping_end_included(self) -> None:
        """Test that an interval overlapping the end of query range is included."""
        tracker = DryRunTracker(hide_output=True)

        # Add an interval that starts within and ends after the query range
        tracker.intervals.append(
            {
                "start": datetime(2025, 1, 11, 11, 0, 0, tzinfo=UTC),
                "end": datetime(2025, 1, 11, 13, 0, 0, tzinfo=UTC),
                "tags": {"overlap-end"},
            }
        )

        query_start = datetime(2025, 1, 11, 10, 0, 0, tzinfo=UTC)
        query_end = datetime(2025, 1, 11, 12, 0, 0, tzinfo=UTC)

        result = tracker.get_intervals(query_start, query_end)

        assert len(result) == 1
        assert result[0]["tags"] == {"overlap-end"}


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
