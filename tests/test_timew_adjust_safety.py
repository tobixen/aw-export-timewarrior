"""Safety tests for the `timew ... :adjust` paths in TimewTracker.start_tracking.

`:adjust` lets timew resolve an overlap instead of erroring out, but the two
command forms have very different blast radii, and the whole guard in
`_first_protected_interval` only makes sense against the real
semantics.  `TestAdjustSemantics` pins those down against the real binary in a
sandbox database; everything below it tests the guard against mocks.
"""

import json
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.main import Exporter
from aw_export_timewarrior.state import AfkState
from aw_export_timewarrior.time_tracker import ProtectedIntervalError
from aw_export_timewarrior.timew_tracker import TimewTracker


def _as_current_tracking(interval: dict) -> dict:
    """The get_current_tracking() view of an open interval.

    start_tracking() asks that, not `timew export`, whenever the open interval
    began at or before the new start -- so a test about an *ongoing* interval
    has to present it the way production sees it, or it pins a state
    TimeWarrior cannot be in (an open interval in the export with nothing
    currently tracked).
    """
    return {
        "id": interval["id"],
        "start": interval["start"].strftime("%Y%m%dT%H%M%SZ"),
        "start_dt": interval["start"],
        "tags": interval["tags"],
    }


@pytest.fixture
def mock_aw_client():
    """Mocked ActivityWatch client, so Exporter() needs no running server."""
    with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
        mock_client = Mock()
        current_time = datetime.now(UTC).isoformat()
        mock_client.get_buckets.return_value = {
            "aw-watcher-window_test": {
                "id": "aw-watcher-window_test",
                "client": "aw-watcher-window",
                "last_updated": current_time,
            },
            "aw-watcher-afk_test": {
                "id": "aw-watcher-afk_test",
                "client": "aw-watcher-afk",
                "last_updated": current_time,
            },
        }
        mock_aw_class.return_value = mock_client
        yield mock_client


def _timew(*args: str) -> subprocess.CompletedProcess:
    """Run a timew command in the sandbox database, non-interactively."""
    return subprocess.run(["timew", *args, ":yes"], capture_output=True, text=True, check=False)


def _intervals() -> list[tuple[str, str, list[str]]]:
    """Export the sandbox database as (start, end, tags) triples."""
    result = _timew("export", "2026-09-10T00:00:00", "-", "2026-09-11T00:00:00")
    return [
        (i["start"], i.get("end", "OPEN"), sorted(i["tags"]))
        for i in json.loads(result.stdout or "[]")
    ]


class TestAdjustSemantics:
    """What `:adjust` actually does, pinned against the real timew binary."""

    def test_open_ended_start_adjust_deletes_everything_after_it(self, timew_sandbox: str) -> None:
        """`timew start <past> :adjust` wipes ALL later intervals, '~aw' included.

        This is why start_tracking cannot use the open-ended form to backfill
        into a region that already has history: the exporter's own previously
        exported intervals are destroyed and never re-created.
        """
        _timew("track", "2026-09-10T08:00:00", "-", "2026-09-10T09:00:00", "aone", "~aw")
        _timew("track", "2026-09-10T09:00:00", "-", "2026-09-10T10:00:00", "btwo", "~aw")

        _timew("start", "dnew", "~aw", "2026-09-10T08:30:00", ":adjust")

        intervals = _intervals()
        tags = [t for _, _, t in intervals]
        assert ["btwo", "~aw"] not in tags, (
            f"open-ended start :adjust was expected to delete 'btwo', got {intervals}"
        )
        # 'aone' survives, clipped back to the new start.
        assert intervals[0][2] == ["aone", "~aw"]
        assert intervals[0][1] == "20260910T063000Z"

    def test_bounded_track_adjust_preserves_later_intervals(self, timew_sandbox: str) -> None:
        """`timew track <start> - <end> :adjust` only touches [start, end]."""
        _timew("track", "2026-09-10T08:00:00", "-", "2026-09-10T09:00:00", "aone", "~aw")
        _timew("track", "2026-09-10T09:00:00", "-", "2026-09-10T10:00:00", "btwo", "~aw")

        _timew(
            "track",
            "2026-09-10T08:30:00",
            "-",
            "2026-09-10T09:00:00",
            "dnew",
            "~aw",
            ":adjust",
        )

        tags = [t for _, _, t in _intervals()]
        assert ["btwo", "~aw"] in tags, "bounded track :adjust must not touch later intervals"
        assert ["dnew", "~aw"] in tags

    def test_closed_interval_cannot_follow_the_open_one(self, timew_sandbox: str) -> None:
        """TimeWarrior refuses to record closed history after the open interval.

        start_tracking() leans on this: when the open interval began at or
        before the new start, it is the only interval `:adjust` can touch, so
        the 7-day overlap probe can be skipped in favour of the (cached)
        current-tracking state.  If a future timew ever allows this, that
        shortcut would start deleting the interval this test tries to create.
        """
        _timew("track", "2026-09-10T08:00:00", "-", "2026-09-10T09:00:00", "closedone")
        _timew("start", "2026-09-10T10:00:00", "openone")

        # Three shapes, because what the shortcut needs is that no closed
        # interval *ends* after the open one's start -- not merely that none
        # *starts* after it.  A straddling interval is the one that would
        # defeat the guard: it would be foreign data `:adjust` never sees.
        for start, end, tag in (
            ("2026-09-10T12:00:00", "2026-09-10T13:00:00", "afterone"),
            ("2026-09-10T09:30:00", "2026-09-10T10:30:00", "straddleone"),
            ("2026-09-10T10:30:00", "2026-09-10T11:00:00", "insideone"),
        ):
            result = _timew("track", start, "-", end, tag)
            assert result.returncode != 0, (
                f"timew accepted {tag} ({start} - {end}) alongside the open "
                f"interval: {_intervals()}"
            )
            assert [istart for istart, _, _ in _intervals()] == [
                "20260910T060000Z",
                "20260910T080000Z",
            ], _intervals()

    def test_start_adjust_clips_an_open_foreign_interval(self, timew_sandbox: str) -> None:
        """Starting inside an ongoing manual interval stops it, keeping the entry.

        This is the deliberate exception the guard allows: taking over from a
        manual `timew start`.
        """
        _timew("start", "2026-09-10T10:00:00", "manualopen")

        _timew("start", "2026-09-10T10:15:00", "taken", "~aw", ":adjust")

        intervals = _intervals()
        assert intervals[0][2] == ["manualopen"]
        assert intervals[0][1] == "20260910T081500Z", (
            "manual interval should be clipped, not deleted"
        )
        assert intervals[1][2] == ["taken", "~aw"]


class TestGuardBoundaries:
    """The exact comparisons in _first_protected_interval."""

    def test_refuses_straddling_closed_foreign_interval(self) -> None:
        """A closed foreign interval the new start falls *inside* is protected.

        The docstring argues a closed foreign interval must be protected "even
        a partial clip, since that rewrites data with a user-set end" -- but
        the only existing test covered the wholesale-delete case (interval
        entirely after start_time).  This covers the clip case.
        """
        tracker = TimewTracker(grace_time=0, capture_commands=[], hide_output=True)
        start_time = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
        straddling = {
            "id": 1,
            "start": datetime(2026, 7, 14, 11, 0, 0, tzinfo=UTC),
            "end": datetime(2026, 7, 14, 13, 0, 0, tzinfo=UTC),
            "tags": {"manual-coding"},  # no '~aw' -> foreign
        }

        with (
            patch.object(tracker, "get_intervals", return_value=[straddling]),
            # Nothing tracked, so start_tracking uses the full overlap probe
            patch.object(tracker, "get_current_tracking", return_value=None),
            patch("subprocess.run", return_value=Mock(returncode=0)) as mock_run,
            pytest.raises(ProtectedIntervalError, match="manually-curated"),
        ):
            tracker.start_tracking({"work", "~aw"}, start_time)

        mock_run.assert_not_called()

    def test_allows_closed_foreign_ending_exactly_at_start(self) -> None:
        """end == start_time is untouched by :adjust, so it must not block."""
        captured: list[list[str]] = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        start_time = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
        abutting = {
            "id": 1,
            "start": datetime(2026, 7, 14, 11, 0, 0, tzinfo=UTC),
            "end": start_time,  # exactly at the boundary
            "tags": {"manual-meeting"},
        }

        with (
            patch.object(tracker, "get_intervals", return_value=[abutting]),
            # Nothing tracked, so start_tracking uses the full overlap probe
            patch.object(tracker, "get_current_tracking", return_value=None),
            patch("subprocess.run", return_value=Mock(returncode=0)),
        ):
            tracker.start_tracking({"work", "~aw"}, start_time)

        assert captured[0][-1] == ":adjust"

    def test_refuses_ongoing_foreign_starting_exactly_at_start(self) -> None:
        """start == start_time would delete the manual entry, not clip it."""
        tracker = TimewTracker(grace_time=0, capture_commands=[], hide_output=True)
        start_time = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
        ongoing = {
            "id": 1,
            "start": start_time,  # exactly at the boundary
            "end": None,
            "tags": {"sometag"},
        }

        with (
            patch.object(tracker, "get_intervals") as probe,
            patch.object(
                tracker, "get_current_tracking", return_value=_as_current_tracking(ongoing)
            ),
            patch("subprocess.run", return_value=Mock(returncode=0)) as mock_run,
            pytest.raises(ProtectedIntervalError),
        ):
            tracker.start_tracking({"work", "~aw"}, start_time)

        mock_run.assert_not_called()
        probe.assert_not_called()


class TestOwnHistoryPreserved:
    """start_tracking must not delete the exporter's own later intervals."""

    def test_backfill_uses_bounded_track_when_own_intervals_follow(self) -> None:
        """A '~aw' interval starting after start_time bounds the command.

        Open-ended `start ... :adjust` would delete it (see
        TestAdjustSemantics).  When history exists after the new start, the
        exporter fills only the hole, up to the next interval's start.
        """
        captured: list[list[str]] = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        start_time = datetime(2026, 7, 14, 8, 30, 0, tzinfo=UTC)
        later_own = {
            "id": 1,
            "start": datetime(2026, 7, 14, 9, 0, 0, tzinfo=UTC),
            "end": datetime(2026, 7, 14, 10, 0, 0, tzinfo=UTC),
            "tags": {"btwo", "~aw"},
        }

        with (
            patch.object(tracker, "get_intervals", return_value=[later_own]),
            # Nothing tracked, so start_tracking uses the full overlap probe
            patch.object(tracker, "get_current_tracking", return_value=None),
            patch("subprocess.run", return_value=Mock(returncode=0)),
        ):
            tracker.start_tracking({"work", "~aw"}, start_time)

        cmd = captured[0]
        assert cmd[1] == "track", f"expected the bounded track form, got: {cmd}"
        assert "-" in cmd, f"expected a start - end range, got: {cmd}"
        assert cmd[-1] == ":adjust"
        # The range must end where the existing interval begins.
        assert cmd[cmd.index("-") + 1].startswith("2026-07-14T"), cmd

    def test_open_ended_start_when_nothing_follows(self) -> None:
        """The ordinary live case is unchanged: open-ended `start ... :adjust`."""
        captured: list[list[str]] = []
        tracker = TimewTracker(grace_time=0, capture_commands=captured, hide_output=True)
        start_time = datetime(2026, 7, 14, 8, 30, 0, tzinfo=UTC)
        own_open = {
            "id": 1,
            "start": datetime(2026, 7, 14, 8, 0, 0, tzinfo=UTC),
            "end": None,
            "tags": {"aone", "~aw"},
        }

        with (
            patch.object(tracker, "get_intervals") as probe,
            patch.object(
                tracker, "get_current_tracking", return_value=_as_current_tracking(own_open)
            ),
            patch("subprocess.run", return_value=Mock(returncode=0)),
        ):
            tracker.start_tracking({"work", "~aw"}, start_time)

        assert captured[0][1] == "start"
        assert captured[0][-1] == ":adjust"
        probe.assert_not_called()


class TestRefusalIsRecoverable:
    """Protecting foreign data must not kill the sync daemon."""

    def test_refusal_is_a_distinct_exception_type(self) -> None:
        """The refusal is catchable on its own, and still a RuntimeError."""
        assert issubclass(ProtectedIntervalError, RuntimeError)

    @patch("aw_export_timewarrior.main.config", {"exclusive": {}, "tags": {}})
    def test_ensure_tag_exported_survives_a_protected_interval(self, mock_aw_client: Mock) -> None:
        """A refusal is logged and skipped, not propagated out of the export.

        Regression test for the crash loop: start_tracking's refusal reached
        main()'s `except Exception`, which exits 1; systemd restarts, timew
        state is identical, and the daemon refuses again -- for ever.
        """
        exporter = Exporter(enable_assert=False)
        exporter.state.last_known_tick = datetime(2025, 5, 28, 14, 0, 0, tzinfo=UTC)
        exporter.state.last_start_time = datetime(2025, 5, 28, 14, 0, 0, tzinfo=UTC)
        exporter.state.set_afk_state(AfkState.ACTIVE)
        exporter.state.manual_tracking = False

        exporter.tracker.get_current_tracking = Mock(
            return_value={
                "id": 1,
                "start": "20250528T140000Z",
                "start_dt": datetime(2025, 5, 28, 14, 0, 0, tzinfo=UTC),
                "tags": {"old", "tags"},
            }
        )
        exporter.tracker.start_tracking = Mock(
            side_effect=ProtectedIntervalError("would overwrite manually-curated data")
        )
        exporter.tracker.retag = Mock()

        event = {
            "timestamp": datetime(2025, 5, 28, 14, 0, 0, tzinfo=UTC),
            "duration": timedelta(seconds=120),
        }

        # Must not raise -- the daemon keeps running and skips this block.
        exporter.ensure_tag_exported({"4work", "programming"}, event)

        exporter.tracker.start_tracking.assert_called_once()
