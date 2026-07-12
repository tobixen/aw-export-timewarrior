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

    def test_get_current_tracking_cache_expires_after_ttl(self) -> None:
        """Regression test for CODE_REVIEW_2026-07.md #3.

        The cache was previously only invalidated by the tracker's own
        `_run_timew` calls, with no TTL - so a manual `timew start` run by the
        user in another terminal was invisible until the exporter itself next
        ran a timew command. A TTL bounds how stale the cache can get.
        """
        tracker = TimewTracker(grace_time=0, cache_ttl=1.0)

        first_data = {"id": 1, "start": "20250101T120000Z", "tags": ["auto"]}
        second_data = {"id": 2, "start": "20250101T130000Z", "tags": ["manual", "override"]}

        with patch("time.monotonic", side_effect=[100.0, 100.5, 102.0]):
            with patch("subprocess.check_output", return_value=json.dumps(first_data).encode()):
                result1 = tracker.get_current_tracking()
                result2 = tracker.get_current_tracking()

            assert result1["tags"] == {"auto"}
            assert result2 is result1  # still within TTL

            # Simulate a manual `timew start` happening externally, then TTL expiring
            with patch(
                "subprocess.check_output", return_value=json.dumps(second_data).encode()
            ) as mock_check:
                result3 = tracker.get_current_tracking()

            assert mock_check.call_count == 1
            assert result3["tags"] == {"manual", "override"}


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

    def test_retag_adds_new_tags_when_nothing_currently_tracked(self) -> None:
        """Test retagging when get_current_tracking finds no active interval."""
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        tags = {"work", "meeting", "client"}

        with (
            patch(
                "subprocess.check_output",
                side_effect=subprocess.CalledProcessError(1, "timew"),
            ),
            patch("subprocess.run", return_value=Mock(returncode=0)),
        ):
            tracker.retag(tags)

        assert len(captured) == 1
        cmd = captured[0]
        assert cmd[0] == "timew"
        assert cmd[1] == "retag"
        assert cmd[2] == "@1"
        assert "client" in cmd
        assert "meeting" in cmd
        assert "work" in cmd

    def test_retag_removes_tags_no_longer_present(self) -> None:
        """Regression test for CODE_REVIEW_2026-07.md #2: retag() only added tags.

        `timew tag @1 <tags>` only ADDS tags - it never removes anything. retag()
        must converge the interval's tag set to what the caller asked for,
        including removals (now via a single atomic `timew retag` call).
        """
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        current_data = {
            "id": 1,
            "start": "20250101T120000Z",
            "tags": ["work", "personal"],
        }
        new_tags = {"work", "meeting"}

        with (
            patch("subprocess.check_output", return_value=json.dumps(current_data).encode()),
            patch("subprocess.run", return_value=Mock(returncode=0)),
        ):
            tracker.retag(new_tags)

        assert len(captured) == 1
        cmd = captured[0]
        assert cmd[:3] == ["timew", "retag", "@1"]
        assert set(cmd[3:]) == new_tags, (
            f"Expected the retag command to carry exactly {new_tags}, got: {cmd}"
        )

    def test_retag_is_atomic_single_command(self) -> None:
        """Regression test for CODE_REVIEW_2026-07-12.md #1: retag() issued
        `timew untag` then `timew tag` as two separate commands. If the untag
        succeeded but the following tag command failed (db lock, hook
        rejection), the interval was left with tags stripped and never
        replaced - silent data loss with no rollback. A single atomic
        `timew retag @1 <tags>` replaces the whole tag set in one command, so
        a failure leaves the original tags intact instead of half-applied.
        """
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        current_data = {
            "id": 1,
            "start": "20250101T120000Z",
            "tags": ["work", "personal"],
        }

        with (
            patch("subprocess.check_output", return_value=json.dumps(current_data).encode()),
            patch("subprocess.run", return_value=Mock(returncode=0)),
        ):
            tracker.retag({"work", "meeting"})

        assert len(captured) == 1, f"Expected a single atomic retag command, got: {captured}"
        cmd = captured[0]
        assert cmd[:3] == ["timew", "retag", "@1"]
        assert set(cmd[3:]) == {"work", "meeting"}

    def test_retag_noop_when_tags_unchanged(self) -> None:
        """No timew command should be issued if the tag set is already correct."""
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        current_data = {
            "id": 1,
            "start": "20250101T120000Z",
            "tags": ["work", "meeting"],
        }

        with (
            patch("subprocess.check_output", return_value=json.dumps(current_data).encode()),
            patch("subprocess.run", return_value=Mock(returncode=0)),
        ):
            tracker.retag({"work", "meeting"})

        assert captured == []


class TestRetagIntervalById:
    """Test retag_interval_by_id method."""

    def test_retag_interval_by_id_issues_retag_command(self) -> None:
        """Test that retag_interval_by_id addresses the given interval by @N.

        Unlike retag() (which always targets @1, the current interval),
        retag_interval_by_id is used by retag.py to bulk-retag arbitrary
        historical intervals.
        """
        captured = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)

        with patch("subprocess.run", return_value=Mock(returncode=0)):
            tracker.retag_interval_by_id(42, {"work", "meeting"})

        assert len(captured) == 1
        cmd = captured[0]
        assert cmd[0] == "timew"
        assert cmd[1] == "retag"
        assert cmd[2] == "@42"
        assert "work" in cmd
        assert "meeting" in cmd

    def test_retag_interval_by_id_raises_on_command_failure(self) -> None:
        """A failed retag command must propagate, not fail silently."""
        tracker = TimewTracker(grace_time=0, hide_output=True)

        with (
            patch("subprocess.run", return_value=Mock(returncode=1, stderr="error")),
            pytest.raises(RuntimeError),
        ):
            tracker.retag_interval_by_id(42, {"work"})


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

    def test_get_intervals_ongoing_interval_started_before_range(self) -> None:
        """Regression test for CODE_REVIEW_2026-07.md #8.

        An ongoing interval (no 'end') that started BEFORE the query range was
        previously invisible: all three in-range branches required
        `interval_end` truthy, so `start <= interval_start <= end` failed (it
        started earlier) and the two `interval_end and ...` branches short
        circuited on the missing end. The interval is still overlapping the
        query range (it's still running), so it must be included.
        """
        tracker = TimewTracker(grace_time=0)
        query_start = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        query_end = datetime(2025, 1, 1, 18, 0, 0, tzinfo=UTC)

        mock_data = [
            {
                "id": 1,
                "start": "20250101T100000Z",  # started 2 hours before query_start
                # No 'end' field - still ongoing
                "tags": ["work", "coding"],
            }
        ]

        mock_result = Mock()
        mock_result.stdout = json.dumps(mock_data)

        with patch("subprocess.run", return_value=mock_result):
            intervals = tracker.get_intervals(query_start, query_end)

        assert len(intervals) == 1, f"Expected ongoing interval to be included, got: {intervals}"
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

    def test_get_intervals_passes_date_range_to_export(self) -> None:
        """get_intervals should pass the range to `timew export`, not export everything.

        Regression test for the efficiency finding in CODE_REVIEW_2026-07.md:
        a bare `timew export` re-parses the entire (potentially huge)
        database on every call. The date range must be passed as CLI args so
        timew itself narrows the result.
        """
        tracker = TimewTracker(grace_time=0)
        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        mock_result = Mock()
        mock_result.stdout = "[]"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            tracker.get_intervals(start, end)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "timew"
        assert cmd[1] == "export"
        assert "-" in cmd
        assert len(cmd) == 5  # ["timew", "export", start_str, "-", end_str]

    def test_get_intervals_falls_back_to_bare_export_on_range_failure(self) -> None:
        """If ranged export fails (older timew, unsupported range syntax),
        fall back to a bare `timew export` and filter client-side."""
        tracker = TimewTracker(grace_time=0)
        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC)

        mock_data = [
            {
                "id": 1,
                "start": "20250101T100000Z",
                "end": "20250101T110000Z",
                "tags": ["work"],
            }
        ]
        bare_result = Mock()
        bare_result.stdout = json.dumps(mock_data)

        with patch(
            "subprocess.run",
            side_effect=[subprocess.CalledProcessError(1, "timew"), bare_result],
        ) as mock_run:
            intervals = tracker.get_intervals(start, end)

        assert mock_run.call_count == 2
        first_cmd = mock_run.call_args_list[0][0][0]
        second_cmd = mock_run.call_args_list[1][0][0]
        assert first_cmd == ["timew", "export", *first_cmd[2:]]  # ranged attempt first
        assert second_cmd == ["timew", "export"]  # bare fallback
        assert len(intervals) == 1
        assert intervals[0]["tags"] == {"work"}

    def test_get_intervals_remembers_ranged_export_unsupported(self) -> None:
        """Regression test for CODE_REVIEW_2026-07-12.md cleanup list: once
        ranged export has failed once, subsequent calls should go straight to
        the bare export instead of paying a failed subprocess call every time.
        """
        tracker = TimewTracker(grace_time=0)
        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC)

        bare_result = Mock()
        bare_result.stdout = "[]"

        with patch(
            "subprocess.run",
            side_effect=[subprocess.CalledProcessError(1, "timew"), bare_result],
        ):
            tracker.get_intervals(start, end)

        assert tracker._ranged_export_supported is False

        # Second call: only the bare export should be attempted.
        with patch("subprocess.run", return_value=bare_result) as mock_run:
            tracker.get_intervals(start, end)

        mock_run.assert_called_once_with(
            ["timew", "export"], capture_output=True, text=True, check=True
        )

    def test_get_intervals_transient_failure_does_not_latch_off_ranged(self) -> None:
        """A transient failure (db lock, hook) that also fails the bare-export
        fallback must NOT permanently disable ranged export: both attempts
        raise, so the next call should still try the efficient ranged export
        rather than degrading to a full-DB scan forever after one blip."""
        tracker = TimewTracker(grace_time=0)
        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC)

        # Ranged attempt fails, and the bare fallback fails too -> propagate.
        with (
            patch(
                "subprocess.run",
                side_effect=[
                    subprocess.CalledProcessError(1, "timew"),
                    subprocess.CalledProcessError(1, "timew"),
                ],
            ),
            pytest.raises(RuntimeError),
        ):
            tracker.get_intervals(start, end)

        # Flag stays optimistic: the failure wasn't proven to be the range syntax.
        assert tracker._ranged_export_supported is True

        # Next call still leads with the ranged export.
        ok_result = Mock()
        ok_result.stdout = "[]"
        with patch("subprocess.run", return_value=ok_result) as mock_run:
            tracker.get_intervals(start, end)

        first_cmd = mock_run.call_args_list[0][0][0]
        assert first_cmd[:2] == ["timew", "export"]
        assert "-" in first_cmd  # ranged syntax attempted again


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
        """Test that command waits for grace period when output (and the undo
        message) is visible."""
        tracker = TimewTracker(grace_time=0.01, hide_output=False)  # Very short for testing

        with (
            patch("subprocess.run", return_value=Mock(returncode=0)),
            patch("time.sleep") as mock_sleep,
        ):
            tracker._run_timew(["test"])

            mock_sleep.assert_called_once_with(0.01)

    def test_run_timew_skips_grace_period_when_output_hidden(self) -> None:
        """The grace-period sleep exists to give the user a window to react to
        the printed undo message; with hide_output=True that message is never
        shown, so sleeping serves no purpose and only slows down batches of
        commands (e.g. retag.py's bulk retag loop).
        """
        tracker = TimewTracker(grace_time=10, hide_output=True)

        with (
            patch("subprocess.run", return_value=Mock(returncode=0)),
            patch("time.sleep") as mock_sleep,
        ):
            tracker._run_timew(["test"])

            mock_sleep.assert_not_called()

    def test_run_timew_raises_on_nonzero_returncode(self) -> None:
        """Test that a failed timew command raises instead of failing silently.

        Regression test: _run_timew used check=False and no caller inspected
        the returncode, so a failed timew command (db lock, hook failure)
        was silently swallowed even though callers like ensure_tag_exported
        had already advanced internal state (last_known_tick, accumulator)
        assuming the command succeeded.
        """
        tracker = TimewTracker(grace_time=0, hide_output=True)

        with (
            patch(
                "subprocess.run",
                return_value=Mock(returncode=1, stderr="There is already an active time tracking."),
            ),
            pytest.raises(RuntimeError, match="timew"),
        ):
            tracker._run_timew(["start", "work"])

    def test_start_tracking_raises_on_command_failure(self) -> None:
        """Test that start_tracking propagates a failed timew command."""
        tracker = TimewTracker(grace_time=0, hide_output=True)
        start_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        with (
            patch("subprocess.run", return_value=Mock(returncode=1, stderr="error")),
            pytest.raises(RuntimeError),
        ):
            tracker.start_tracking({"work"}, start_time)


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
            assert call_kwargs["capture_output"] is False, (
                "Output should not be captured in normal mode (capture_commands=None)"
            )

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
            assert call_kwargs["capture_output"] is True, (
                "Output should be captured when capture_commands is a list (test mode)"
            )
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
