"""Tests for TimewTracker implementation."""

import json
import subprocess
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.timew_tracker import TimewTracker


class TestTimewTrackerInit:
    """Test TimewTracker initialization."""

    def test_default_init(self) -> None:
        """Test initialization with defaults."""
        with patch.dict("os.environ", {}, clear=False):
            tracker = TimewTracker()

            assert tracker.grace_time == 10.0
            assert tracker.capture_commands is None
            assert tracker.hide_output is False
            assert tracker._current_cache is None

    def test_custom_grace_time(self) -> None:
        """Test initialization with custom grace time."""
        tracker = TimewTracker(grace_time=5.0)

        assert tracker.grace_time == 5.0

    def test_grace_time_from_env(self) -> None:
        """Test grace time from environment variable."""
        with patch.dict("os.environ", {"AW2TW_GRACE_TIME": "3.5"}):
            tracker = TimewTracker()

            assert tracker.grace_time == 3.5

    def test_capture_commands(self) -> None:
        """Test command capture for testing."""
        captured = []
        tracker = TimewTracker(capture_commands=captured)

        assert tracker.capture_commands is captured

    def test_hide_output(self) -> None:
        """Test output hiding."""
        tracker = TimewTracker(hide_output=True)

        assert tracker.hide_output is True


class TestGetCurrentTracking:
    """Test get_current_tracking method."""

    def test_get_current_tracking_active(self) -> None:
        """Test getting active tracking."""
        tracker = TimewTracker(grace_time=0)

        mock_data = {"id": 123, "start": "20250101T120000Z", "tags": ["work", "coding", "python"]}

        with patch("subprocess.check_output", return_value=json.dumps(mock_data).encode()):
            result = tracker.get_current_tracking()

        assert result is not None
        assert result["id"] == 123
        assert result["start"] == "20250101T120000Z"
        assert result["start_dt"] == datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert result["tags"] == {"work", "coding", "python"}

    def test_get_current_tracking_none(self) -> None:
        """Test getting tracking when nothing is active."""
        tracker = TimewTracker(grace_time=0)

        with patch(
            "subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "timew")
        ):
            result = tracker.get_current_tracking()

        assert result is None

    def test_get_current_tracking_caches_result(self) -> None:
        """Test that result is cached."""
        tracker = TimewTracker(grace_time=0)

        mock_data = {"id": 123, "start": "20250101T120000Z", "tags": []}

        with patch(
            "subprocess.check_output", return_value=json.dumps(mock_data).encode()
        ) as mock_check:
            result1 = tracker.get_current_tracking()
            result2 = tracker.get_current_tracking()

            # Should only call subprocess once (cached)
            assert mock_check.call_count == 1
            assert result1 is result2

    def test_get_current_tracking_cache_invalidated_after_command(self) -> None:
        """Test that cache is invalidated after running a command."""
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)

        mock_data = {"id": 123, "start": "20250101T120000Z", "tags": []}

        with (
            patch(
                "subprocess.check_output", return_value=json.dumps(mock_data).encode()
            ) as mock_check,
            patch("subprocess.run", return_value=Mock(returncode=0)),
        ):
            # Get current tracking (caches it)
            tracker.get_current_tracking()
            assert mock_check.call_count == 1

            # Run a command (should invalidate cache)
            tracker.stop_tracking()

            # Get current tracking again (should call subprocess again)
            tracker.get_current_tracking()
            assert mock_check.call_count == 2


class TestStartTracking:
    """Test start_tracking method."""

    def test_start_tracking(self) -> None:
        """Test starting tracking."""
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        start_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        tags = {"work", "coding", "python"}

        with patch("subprocess.run", return_value=Mock(returncode=0)):
            tracker.start_tracking(tags, start_time)

        assert len(captured) == 1
        cmd = captured[0]
        assert cmd[0] == "timew"
        assert cmd[1] == "start"
        assert "coding" in cmd
        assert "python" in cmd
        assert "work" in cmd
        # Check time format (will be in local time)
        assert any("2025-01-01" in arg for arg in cmd)


class TestStopTracking:
    """Test stop_tracking method."""

    def test_stop_tracking(self) -> None:
        """Test stopping tracking."""
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)

        with patch("subprocess.run", return_value=Mock(returncode=0)):
            tracker.stop_tracking()

        assert captured == [["timew", "stop"]]


class TestRetag:
    """Test retag method."""

    def test_retag(self) -> None:
        """Test retagging current interval."""
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        tags = {"work", "meeting", "client"}

        with patch("subprocess.run", return_value=Mock(returncode=0)):
            tracker.retag(tags)

        assert len(captured) == 1
        cmd = captured[0]
        assert cmd[0] == "timew"
        assert cmd[1] == "tag"
        assert cmd[2] == "@1"
        assert "client" in cmd
        assert "meeting" in cmd
        assert "work" in cmd


class TestGetIntervals:
    """Test get_intervals method."""

    def test_get_intervals_empty(self) -> None:
        """Test getting intervals when none exist."""
        tracker = TimewTracker(grace_time=0)
        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC)

        mock_result = Mock()
        mock_result.stdout = "[]"

        with patch("subprocess.run", return_value=mock_result):
            intervals = tracker.get_intervals(start, end)

        assert intervals == []

    def test_get_intervals_with_data(self) -> None:
        """Test getting intervals with data."""
        tracker = TimewTracker(grace_time=0)
        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC)

        mock_data = [
            {
                "id": 1,
                "start": "20250101T100000Z",
                "end": "20250101T110000Z",
                "tags": ["work", "coding"],
            },
            {
                "id": 2,
                "start": "20250101T140000Z",
                "end": "20250101T150000Z",
                "tags": ["work", "meeting"],
            },
        ]

        mock_result = Mock()
        mock_result.stdout = json.dumps(mock_data)

        with patch("subprocess.run", return_value=mock_result):
            intervals = tracker.get_intervals(start, end)

        assert len(intervals) == 2
        assert intervals[0]["id"] == 1
        assert intervals[0]["start"] == datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        assert intervals[0]["end"] == datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC)
        assert intervals[0]["tags"] == {"work", "coding"}

        assert intervals[1]["id"] == 2
        assert intervals[1]["tags"] == {"work", "meeting"}

    def test_get_intervals_ongoing(self) -> None:
        """Test getting intervals with ongoing interval (no end time)."""
        tracker = TimewTracker(grace_time=0)
        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC)

        mock_data = [
            {
                "id": 1,
                "start": "20250101T100000Z",
                # No 'end' field - ongoing interval
                "tags": ["work", "coding"],
            }
        ]

        mock_result = Mock()
        mock_result.stdout = json.dumps(mock_data)

        with patch("subprocess.run", return_value=mock_result):
            intervals = tracker.get_intervals(start, end)

        assert len(intervals) == 1
        assert intervals[0]["end"] is None

    def test_get_intervals_command_failure(self) -> None:
        """Test handling of timew export failure."""
        tracker = TimewTracker(grace_time=0)
        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC)

        with (
            patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "timew")),
            pytest.raises(RuntimeError, match="Failed to fetch TimeWarrior intervals"),
        ):
            tracker.get_intervals(start, end)


class TestTrackInterval:
    """Test track_interval method."""

    def test_track_interval(self) -> None:
        """Test tracking a past interval."""
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC)
        tags = {"work", "coding", "python"}

        with patch("subprocess.run", return_value=Mock(returncode=0)):
            tracker.track_interval(start, end, tags)

        assert len(captured) == 1
        cmd = captured[0]
        assert cmd[0] == "timew"
        assert cmd[1] == "track"
        assert "-" in cmd  # The separator between start and end
        assert "coding" in cmd
        assert "python" in cmd
        assert "work" in cmd


class TestRunTimew:
    """Test _run_timew internal method."""

    def test_run_timew_captures_commands(self) -> None:
        """Test that commands are captured when capture_commands is set."""
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)

        with patch("subprocess.run", return_value=Mock(returncode=0)):
            tracker._run_timew(["test", "command"])

        assert captured == [["timew", "test", "command"]]

    def test_run_timew_invalidates_cache(self) -> None:
        """Test that running a command invalidates the cache."""
        tracker = TimewTracker(grace_time=0, hide_output=True)

        # Set up a cache
        tracker._current_cache = {"test": "data"}

        with patch("subprocess.run", return_value=Mock(returncode=0)):
            tracker._run_timew(["test"])

        # Cache should be cleared
        assert tracker._current_cache is None

    def test_run_timew_waits_grace_period(self) -> None:
        """Test that command waits for grace period."""
        tracker = TimewTracker(grace_time=0.01, hide_output=True)  # Very short for testing

        with (
            patch("subprocess.run", return_value=Mock(returncode=0)),
            patch("time.sleep") as mock_sleep,
        ):
            tracker._run_timew(["test"])

            mock_sleep.assert_called_once_with(0.01)


class TestOutputVisibility:
    """Test that timew output is visible in normal mode."""

    def test_output_not_captured_when_capture_commands_is_none(self) -> None:
        """Test that timew output goes to terminal when capture_commands is None."""
        tracker = TimewTracker(grace_time=0, capture_commands=None, hide_output=True)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)
            tracker._run_timew(["test"])

            # Verify subprocess.run was called with capture_output=False
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert (
                call_kwargs["capture_output"] is False
            ), "Output should not be captured in normal mode (capture_commands=None)"

    def test_output_captured_when_capture_commands_is_list(self) -> None:
        """Test that timew output is captured when capture_commands is a list."""
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
            tracker._run_timew(["test", "arg"])

            # Verify subprocess.run was called with capture_output=True
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert (
                call_kwargs["capture_output"] is True
            ), "Output should be captured when capture_commands is a list (test mode)"
            # Verify command was captured
            assert captured == [["timew", "test", "arg"]]


class TestTimewTrackerInterface:
    """Test that TimewTracker properly implements TimeTracker interface."""

    def test_is_time_tracker_instance(self) -> None:
        """Test that TimewTracker is a TimeTracker instance."""
        from aw_export_timewarrior.time_tracker import TimeTracker

        tracker = TimewTracker(grace_time=0)

        assert isinstance(tracker, TimeTracker)
        assert isinstance(tracker, TimewTracker)

    def test_has_all_required_methods(self) -> None:
        """Test that TimewTracker has all required TimeTracker methods."""
        tracker = TimewTracker(grace_time=0)

        assert hasattr(tracker, "get_current_tracking")
        assert hasattr(tracker, "start_tracking")
        assert hasattr(tracker, "stop_tracking")
        assert hasattr(tracker, "retag")
        assert hasattr(tracker, "get_intervals")
        assert hasattr(tracker, "track_interval")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
