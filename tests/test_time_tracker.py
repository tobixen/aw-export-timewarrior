"""Tests for TimeTracker interface and DryRunTracker implementation."""

from datetime import UTC, datetime, timedelta

import pytest

from aw_export_timewarrior.time_tracker import DryRunTracker, TimeTracker


class TestTimeTrackerInterface:
    """Test that TimeTracker is a proper abstract base class."""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """Test that TimeTracker cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            TimeTracker()  # type: ignore

    def test_must_implement_all_abstract_methods(self) -> None:
        """Test that subclasses must implement all abstract methods."""

        class IncompleteTracker(TimeTracker):
            """Incomplete implementation missing methods."""

            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteTracker()  # type: ignore


class TestDryRunTracker:
    """Test the DryRunTracker no-op implementation."""

    def test_initialization(self) -> None:
        """Test DryRunTracker initializes with no active tracking."""
        tracker = DryRunTracker()

        assert tracker.get_current_tracking() is None
        assert tracker.intervals == []

    def test_start_tracking(self, capsys) -> None:
        """Test starting tracking creates current entry."""
        tracker = DryRunTracker()
        tags = {"work", "coding", "python"}
        start_time = datetime.now(UTC)

        tracker.start_tracking(tags, start_time)

        current = tracker.get_current_tracking()
        assert current is not None
        assert current["id"] == 1
        assert current["start"] == start_time
        assert current["tags"] == tags

        # Check dry-run output
        captured = capsys.readouterr()
        assert "DRY RUN: Would start tracking" in captured.out
        assert "work" in captured.out or str(tags) in captured.out

    def test_stop_tracking(self, capsys) -> None:
        """Test stopping tracking clears current entry."""
        tracker = DryRunTracker()
        tags = {"work", "meeting"}

        tracker.start_tracking(tags, datetime.now(UTC))
        assert tracker.get_current_tracking() is not None

        tracker.stop_tracking()
        assert tracker.get_current_tracking() is None

        # Check dry-run output
        captured = capsys.readouterr()
        assert "DRY RUN: Would stop tracking" in captured.out

    def test_stop_tracking_when_nothing_active(self, capsys) -> None:
        """Test stopping tracking when nothing is active."""
        tracker = DryRunTracker()

        tracker.stop_tracking()

        # Should not print anything
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_retag(self, capsys) -> None:
        """Test retagging changes tags on current entry."""
        tracker = DryRunTracker()
        initial_tags = {"work", "coding"}
        new_tags = {"work", "meeting"}

        tracker.start_tracking(initial_tags, datetime.now(UTC))
        tracker.retag(new_tags)

        current = tracker.get_current_tracking()
        assert current is not None
        assert current["tags"] == new_tags

        # Check dry-run output
        captured = capsys.readouterr()
        assert "DRY RUN: Would retag to" in captured.out

    def test_retag_when_nothing_active(self, capsys) -> None:
        """Test retagging when nothing is active."""
        tracker = DryRunTracker()

        tracker.retag({"work", "coding"})

        # Should not print anything
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_track_interval(self, capsys) -> None:
        """Test tracking a past interval."""
        tracker = DryRunTracker()
        start = datetime.now(UTC) - timedelta(hours=2)
        end = datetime.now(UTC) - timedelta(hours=1)
        tags = {"work", "coding", "python"}

        tracker.track_interval(start, end, tags)

        assert len(tracker.intervals) == 1
        interval = tracker.intervals[0]
        assert interval["start"] == start
        assert interval["end"] == end
        assert interval["tags"] == tags

        # Check dry-run output
        captured = capsys.readouterr()
        assert "DRY RUN: Would track" in captured.out

    def test_get_intervals_empty(self) -> None:
        """Test getting intervals when none exist."""
        tracker = DryRunTracker()
        start = datetime.now(UTC) - timedelta(days=1)
        end = datetime.now(UTC)

        intervals = tracker.get_intervals(start, end)

        assert intervals == []

    def test_get_intervals_filters_by_time_range(self) -> None:
        """Test getting intervals filters by time range correctly."""
        tracker = DryRunTracker()
        now = datetime.now(UTC)

        # Add intervals at different times
        tracker.track_interval(
            now - timedelta(hours=5), now - timedelta(hours=4), {"work", "coding"}
        )
        tracker.track_interval(
            now - timedelta(hours=2), now - timedelta(hours=1), {"work", "meeting"}
        )
        tracker.track_interval(
            now + timedelta(hours=1), now + timedelta(hours=2), {"personal", "reading"}
        )

        # Query for intervals in specific range
        intervals = tracker.get_intervals(now - timedelta(hours=3), now)

        # Should only get the middle interval
        assert len(intervals) == 1
        assert intervals[0]["tags"] == {"work", "meeting"}

    def test_multiple_track_intervals(self) -> None:
        """Test tracking multiple intervals."""
        tracker = DryRunTracker()
        now = datetime.now(UTC)

        tracker.track_interval(
            now - timedelta(hours=3), now - timedelta(hours=2), {"work", "coding"}
        )
        tracker.track_interval(now - timedelta(hours=1), now, {"work", "meeting"})

        assert len(tracker.intervals) == 2

    def test_start_tracking_increments_id(self) -> None:
        """Test that starting tracking multiple times increments ID."""
        tracker = DryRunTracker()

        # Add an interval first
        tracker.track_interval(datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC), {"work"})

        # Start tracking - ID should be based on number of intervals
        tracker.start_tracking({"work", "coding"}, datetime.now(UTC))

        current = tracker.get_current_tracking()
        assert current is not None
        assert current["id"] == 2  # 1 interval + 1 = 2

    def test_workflow_start_stop_track(self, capsys) -> None:
        """Test a complete workflow: start, stop, track past interval."""
        tracker = DryRunTracker()
        now = datetime.now(UTC)

        # Start tracking
        tracker.start_tracking({"work", "coding"}, now)
        assert tracker.get_current_tracking() is not None

        # Retag while tracking
        tracker.retag({"work", "meeting"})
        current = tracker.get_current_tracking()
        assert current is not None
        assert current["tags"] == {"work", "meeting"}

        # Stop tracking
        tracker.stop_tracking()
        assert tracker.get_current_tracking() is None

        # Track a past interval
        tracker.track_interval(
            now - timedelta(hours=2), now - timedelta(hours=1), {"personal", "reading"}
        )

        assert len(tracker.intervals) == 1

        # Verify all dry-run messages were printed
        captured = capsys.readouterr()
        assert "Would start tracking" in captured.out
        assert "Would retag" in captured.out
        assert "Would stop tracking" in captured.out
        assert "Would track" in captured.out


class TestTimeTrackerCompleteImplementation:
    """Test that DryRunTracker implements all TimeTracker methods."""

    def test_implements_all_abstract_methods(self) -> None:
        """Test that DryRunTracker can be instantiated (all methods implemented)."""
        tracker = DryRunTracker()

        # Should not raise TypeError
        assert isinstance(tracker, TimeTracker)
        assert isinstance(tracker, DryRunTracker)

    def test_has_all_required_methods(self) -> None:
        """Test that DryRunTracker has all required methods."""
        tracker = DryRunTracker()

        assert hasattr(tracker, "get_current_tracking")
        assert hasattr(tracker, "start_tracking")
        assert hasattr(tracker, "stop_tracking")
        assert hasattr(tracker, "retag")
        assert hasattr(tracker, "get_intervals")
        assert hasattr(tracker, "track_interval")

        # Verify they're callable
        assert callable(tracker.get_current_tracking)
        assert callable(tracker.start_tracking)
        assert callable(tracker.stop_tracking)
        assert callable(tracker.retag)
        assert callable(tracker.get_intervals)
        assert callable(tracker.track_interval)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
