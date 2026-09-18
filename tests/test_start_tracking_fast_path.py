"""start_tracking() skips its 7-day `timew export` probe when it can.

The probe exists to decide whether `timew start ... :adjust` would destroy
foreign data.  It cost one extra subprocess (and one full parse of a 7-day
window, or of the whole database on an install without ranged export) per
activity block, which in a batch run -- `tick(process_all=True)`, `sync`
catching up after a suspend -- is once per block on a path whose fetch cost
was deliberately optimised.

TimeWarrior never places a closed interval after the open one (pinned against
the real binary by
tests/test_timew_adjust_safety.py::TestAdjustSemantics::test_closed_interval_cannot_follow_the_open_one),
so when the open interval started at or before the new start, it is the *only*
interval `:adjust` can touch -- and `get_current_tracking()` already knows it,
behind a cache.  See TODO.md, "Cache the overlap probe in `start_tracking`".
"""

import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.time_tracker import ProtectedIntervalError
from aw_export_timewarrior.timew_tracker import TimewTracker

START = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


def _tracker() -> tuple[TimewTracker, list]:
    captured: list = []
    return TimewTracker(grace_time=0, capture_commands=captured, hide_output=True), captured


def _current(start: datetime, tags: set[str]) -> dict:
    return {"id": 1, "start": start.strftime("%Y%m%dT%H%M%SZ"), "start_dt": start, "tags": tags}


def test_own_open_interval_needs_no_probe() -> None:
    """The ordinary case: the exporter appends to its own open interval."""
    tracker, captured = _tracker()
    probe = Mock(name="get_intervals")

    with (
        patch.object(tracker, "get_intervals", probe),
        patch.object(
            tracker,
            "get_current_tracking",
            return_value=_current(START - timedelta(minutes=30), {"work", "~aw"}),
        ),
        patch("subprocess.run", return_value=Mock(returncode=0)),
    ):
        tracker.start_tracking({"reading", "~aw"}, START)

    probe.assert_not_called()
    assert captured[0][1] == "start"
    assert captured[0][-1] == ":adjust"


def test_ongoing_foreign_interval_is_still_clipped_without_a_probe() -> None:
    """Taking over from a manual `timew start` stays allowed."""
    tracker, captured = _tracker()
    probe = Mock(name="get_intervals")

    with (
        patch.object(tracker, "get_intervals", probe),
        patch.object(
            tracker,
            "get_current_tracking",
            return_value=_current(START - timedelta(minutes=30), {"manual"}),
        ),
        patch("subprocess.run", return_value=Mock(returncode=0)),
    ):
        tracker.start_tracking({"work", "~aw"}, START)

    probe.assert_not_called()
    assert captured[0][1] == "start"


def test_foreign_interval_starting_at_the_new_start_is_refused_without_a_probe() -> None:
    """`:adjust` would delete it wholesale rather than clip it."""
    tracker, captured = _tracker()
    probe = Mock(name="get_intervals")

    with (
        patch.object(tracker, "get_intervals", probe),
        patch.object(tracker, "get_current_tracking", return_value=_current(START, {"manual"})),
        patch("subprocess.run", return_value=Mock(returncode=0)),
        pytest.raises(ProtectedIntervalError, match="manual"),
    ):
        tracker.start_tracking({"work", "~aw"}, START)

    probe.assert_not_called()
    assert captured == []


def test_no_open_interval_falls_back_to_the_probe() -> None:
    """With nothing tracked, closed history may follow the new start."""
    tracker, captured = _tracker()
    later_own = {
        "id": 1,
        "start": START + timedelta(hours=1),
        "end": START + timedelta(hours=2),
        "tags": {"work", "~aw"},
    }
    probe = Mock(name="get_intervals", return_value=[later_own])

    with (
        patch.object(tracker, "get_intervals", probe),
        patch.object(tracker, "get_current_tracking", return_value=None),
        patch("subprocess.run", return_value=Mock(returncode=0)),
    ):
        tracker.start_tracking({"reading", "~aw"}, START)

    probe.assert_called_once()
    # Bounded form, so the exporter's own later interval survives
    assert captured[0][1] == "track"


def test_open_interval_starting_after_the_new_start_falls_back_to_the_probe() -> None:
    """Backfilling before the open interval: the probe must see the rest."""
    tracker, _captured = _tracker()
    manual = {
        "id": 2,
        "start": START + timedelta(minutes=10),
        "end": START + timedelta(minutes=20),
        "tags": {"manual"},
    }
    probe = Mock(name="get_intervals", return_value=[manual])

    with (
        patch.object(tracker, "get_intervals", probe),
        patch.object(
            tracker,
            "get_current_tracking",
            return_value=_current(START + timedelta(minutes=30), {"work", "~aw"}),
        ),
        patch("subprocess.run", return_value=Mock(returncode=0)),
        pytest.raises(ProtectedIntervalError),
    ):
        tracker.start_tracking({"reading", "~aw"}, START)

    probe.assert_called_once()


def test_probe_does_not_trust_the_cached_current_tracking() -> None:
    """A manual `timew start` seconds ago must still be seen.

    get_current_tracking() serves a cache_ttl-old answer, which is fine for
    reporting but not for this guard: within that window the exporter would
    take the cached view of its own open interval as proof that nothing else
    is in the way, and `:adjust` would silently swallow the manual interval
    the full export would have caught.
    """
    tracker, captured = _tracker()
    tracker._current_cache = _current(START - timedelta(minutes=30), {"work", "~aw"})
    tracker._cache_time = time.monotonic()
    fresh = json.dumps({"id": 1, "start": START.strftime("%Y%m%dT%H%M%SZ"), "tags": ["manual"]})

    with (
        patch("subprocess.check_output", return_value=fresh.encode()),
        patch("subprocess.run", return_value=Mock(returncode=0)),
        pytest.raises(ProtectedIntervalError, match="manual"),
    ):
        tracker.start_tracking({"work", "~aw"}, START)

    assert captured == []
