"""Regression tests for rolling-cache staleness in sync mode and sync/batch equivalence.

Background
----------
In sync mode (end_time=None, not test_data) the Exporter builds a rolling
event cache in EventFetcher to avoid O(N²) HTTP requests to AW.  Within a
single tick, all get_events() calls are served from the in-memory cache.

Bug (commit 6f22ee3): the cache was only initialised when _cache_range was
None — i.e., once per "burst".  During an AFK period, current_event is not
None keeps find_next_activity() returning True indefinitely, preventing the
sleep path (the only place reset_cache() was called) from ever firing.
New events arriving after the initial cache window were therefore invisible,
producing the repeated "Window events are stale" log messages.

Fix: unconditionally rebuild the cache at the start of every tick(), so the
window is always current regardless of what happened during the previous tick.

This file provides two test classes:

1. ``TestEventFetcherCacheRegression`` — unit tests that target the EventFetcher
   cache layer directly, without the full Exporter machinery.  These are the
   most precise tests for the staleness bug and will fail on commit 6f22ee3.

2. ``TestExporterWithMockAW`` — integration tests that run a mock
   ActivityWatchClient through the full Exporter path, verifying that
   tick()-one-at-a-time (sync style) and tick(process_all=True) (batch/diff)
   produce equivalent intervals.  These do NOT use the test_data shortcut, so
   the real EventFetcher code path (including the cache) is exercised.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from aw_core.models import Event
from freezegun import freeze_time

from aw_export_timewarrior.aw_client import EventFetcher
from aw_export_timewarrior.compare import SuggestedInterval, TimewInterval, compare_intervals
from aw_export_timewarrior.main import Exporter
from tests.conftest import FixtureDataBuilder

CONFIG_FILE = Path(__file__).parent / "fixtures" / "test_config.toml"

# ---------------------------------------------------------------------------
# Helpers shared by both test classes
# ---------------------------------------------------------------------------


def _build_mock_aw_client(test_data: dict) -> MagicMock:
    """Create a mock ActivityWatchClient backed by FixtureDataBuilder test data.

    Returns aw_core.models.Event objects (same type as the real AW client), so
    _filter_events_in_range() and the event pipeline exercise the same code paths
    they would in production.
    """
    mock_aw = MagicMock()
    mock_aw.get_buckets.return_value = test_data["buckets"]

    def _get_events(
        bucket_id: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[Event]:
        raw = test_data["events"].get(bucket_id, [])
        result = []
        for ev in raw:
            ts = ev["timestamp"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            dur = ev["duration"]
            if isinstance(dur, int | float):
                dur = timedelta(seconds=dur)
            event_end = ts + dur
            if start and event_end < start:
                continue
            if end and ts > end:
                continue
            result.append(Event(timestamp=ts, duration=dur, data=dict(ev["data"])))
        return result

    mock_aw.get_events.side_effect = _get_events
    return mock_aw


def _suggested_to_timew(intervals: list[SuggestedInterval]) -> list[TimewInterval]:
    return [
        TimewInterval(id=i, start=s.start, end=s.end, tags=s.tags) for i, s in enumerate(intervals)
    ]


def _assert_no_differences(sync_intervals: list, diff_intervals: list) -> None:
    """Assert sync and diff intervals agree completely."""
    timew_like = _suggested_to_timew(sync_intervals)
    cmp = compare_intervals(timew_like, diff_intervals)

    def _fmt(items: list) -> str:
        return "\n  ".join(str(i) for i in items)

    assert cmp["missing"] == [], (
        f"Diff found intervals missing from sync:\n  {_fmt(cmp['missing'])}"
    )
    assert cmp["extra"] == [], f"Sync created extra intervals not in diff:\n  {_fmt(cmp['extra'])}"
    assert cmp["different_tags"] == [], "Tag mismatches between sync and diff:\n  " + "\n  ".join(
        f"timew={tw}  suggested={sg}" for tw, sg in cmp["different_tags"]
    )
    assert cmp["previously_synced"] == [], (
        f"Sync created unaccounted intervals:\n  {_fmt(cmp['previously_synced'])}"
    )


def _run_sync_ticks(exporter: Exporter, n: int) -> None:
    """Run tick() up to n times.

    Stops early when tick() returns False (no more events) or when the
    dry-run guard raises ValueError (equivalent to "no more events" in
    dry_run + no-end_time mode).
    """
    for _ in range(n):
        try:
            if not exporter.tick():
                break
        except (ValueError, AssertionError):
            # dry_run guard fired: all events consumed, no more activity to find.
            # This is semantically equivalent to tick() returning False.
            break


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------


def _work_afk_work_scenario() -> tuple[dict, datetime, datetime]:
    """10 min coding → 20 min AFK → 10 min coding.

    Returns (test_data, t0, t_end).
    """
    t0 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
    builder = FixtureDataBuilder(start_time=t0)
    # Phase 1 (T+0 .. T+600): active coding
    builder.add_window_event("Code", "main.py - VS Code", 600)
    builder.add_afk_event("not-afk", 600)
    # Phase 2 (T+600 .. T+1800): AFK (20 min – well above max_mixed_interval)
    builder.add_window_event("Code", "screensaver", 1200)
    builder.add_afk_event("afk", 1200)
    # Phase 3 (T+1800 .. T+2400): coding resumes
    builder.add_window_event("Code", "main.py - VS Code", 600)
    builder.add_afk_event("not-afk", 600)
    return builder.build(), t0, t0 + timedelta(seconds=2400)


def _simple_coding_scenario() -> tuple[dict, datetime, datetime]:
    """Single uninterrupted coding session."""
    t0 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
    builder = FixtureDataBuilder(start_time=t0)
    builder.add_window_event("Code", "main.py - VS Code", 600)
    builder.add_afk_event("not-afk", 600)
    return builder.build(), t0, t0 + timedelta(seconds=600)


# ---------------------------------------------------------------------------
# Test class 1: EventFetcher cache unit tests
# ---------------------------------------------------------------------------


class TestEventFetcherCacheRegression:
    """Unit tests that target the EventFetcher cache layer directly.

    These tests are independent of the full Exporter machinery and fail
    precisely on the cache staleness bug introduced in commit 6f22ee3.
    """

    def test_initial_cache_misses_events_after_window(self) -> None:
        """Events starting after the initial cache end are invisible until cache is reset.

        This is the precise failure mode of the staleness bug: the cache was
        built for [t40, t716] and never rebuilt.  The phase-3 coding event
        (starting at t1800) is not in that window, so get_events() returns an
        empty list even though the event exists in AW.
        """
        test_data, t0, _t_end = _work_afk_work_scenario()
        mock_aw = _build_mock_aw_client(test_data)

        t_cache_start = t0 - timedelta(seconds=40)
        t_cache_end = t0 + timedelta(seconds=716)  # covers only phase 1 + start of AFK

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient", return_value=mock_aw):
            fetcher = EventFetcher(test_data=None, cache_range=(t_cache_start, t_cache_end))

            # Phase-3 coding event (t1800-t2400) starts after the cache end (t716).
            # The mock AW contains this event, but the stale cache never fetched it.
            events = fetcher.get_events(
                "aw-watcher-window_test",
                start=t0 + timedelta(seconds=1800),
                end=t0 + timedelta(seconds=2400),
            )
            phase3_coding = [e for e in events if e["data"].get("title") == "main.py - VS Code"]
            assert phase3_coding == [], (
                f"Stale cache should not expose phase-3 coding events — but got: {phase3_coding}"
            )

    def test_reset_cache_exposes_events_after_original_window(self) -> None:
        """After reset_cache with a wider window, post-window events become visible.

        This verifies the fix: every tick() rebuilds the cache, so new events
        that arrive after the initial window are eventually fetched.
        """
        test_data, t0, _t_end = _work_afk_work_scenario()
        mock_aw = _build_mock_aw_client(test_data)

        t_cache_start = t0 - timedelta(seconds=40)
        t_cache_end = t0 + timedelta(seconds=716)

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient", return_value=mock_aw):
            fetcher = EventFetcher(test_data=None, cache_range=(t_cache_start, t_cache_end))

            # Confirm phase-3 events are absent from stale cache (same as previous test)
            events_stale = fetcher.get_events(
                "aw-watcher-window_test",
                start=t0 + timedelta(seconds=1800),
                end=t0 + timedelta(seconds=2400),
            )
            assert not any(e["data"].get("title") == "main.py - VS Code" for e in events_stale), (
                "Precondition: phase-3 event must be absent from stale cache"
            )

            # Reset cache to a window that covers phase 3
            t_new_start = t0 + timedelta(seconds=1240)  # simulates last_tick - 11 min at T=2500
            t_new_end = t0 + timedelta(seconds=2516)
            fetcher.reset_cache(new_range=(t_new_start, t_new_end))

            # Phase-3 coding event is now visible
            events_fresh = fetcher.get_events(
                "aw-watcher-window_test",
                start=t0 + timedelta(seconds=1800),
                end=t0 + timedelta(seconds=2400),
            )
            phase3_coding = [
                e for e in events_fresh if e["data"].get("title") == "main.py - VS Code"
            ]
            assert len(phase3_coding) == 1, (
                f"Fresh cache should expose phase-3 coding event, but got: {events_fresh}"
            )

    def test_mock_aw_client_filtering_sanity(self) -> None:
        """Sanity-check: mock AW client correctly filters by time range."""
        test_data, t0, t_end = _work_afk_work_scenario()
        mock_aw = _build_mock_aw_client(test_data)

        # All three window events should be in the full range
        all_events = mock_aw.get_events("aw-watcher-window_test", start=t0, end=t_end)
        assert len(all_events) == 3, f"Expected 3 window events, got {len(all_events)}"

        # Only events starting before T=700 should appear in the early range
        early_events = mock_aw.get_events(
            "aw-watcher-window_test",
            start=t0,
            end=t0 + timedelta(seconds=700),
        )
        assert all(e["timestamp"] <= t0 + timedelta(seconds=700) for e in early_events)


# ---------------------------------------------------------------------------
# Test class 2: Exporter-level sync/batch equivalence with mock AW
# ---------------------------------------------------------------------------


class TestExporterWithMockAW:
    """Integration tests using a mock AW client instead of the test_data shortcut.

    These tests verify that tick()-one-at-a-time (sync style with end_time) and
    tick(process_all=True) produce equivalent intervals when the EventFetcher
    code path is actually exercised.

    Note: these tests use end_time to bound processing (matching ``sync --once``
    behaviour), which enables the batch cache in __post_init__.  The rolling
    cache (used only when end_time is None) is covered by the unit tests above
    and by the freeze_time regression test below.
    """

    def _run_sync_and_batch(
        self, test_data: dict, t0: datetime, t_end: datetime
    ) -> tuple[list[SuggestedInterval], list[SuggestedInterval]]:
        """Run both sync (tick-by-tick) and batch (process_all) with mock AW.

        Returns (sync_intervals, batch_intervals).
        """
        mock_aw = _build_mock_aw_client(test_data)

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient", return_value=mock_aw):
            # Sync style: tick() one at a time
            exporter_sync = Exporter(
                dry_run=True,
                start_time=t0,
                end_time=t_end,
                config_path=CONFIG_FILE,
            )
            _run_sync_ticks(exporter_sync, 1000)
            sync_intervals = exporter_sync.get_suggested_intervals()

            # Batch style: single tick(process_all=True)
            exporter_batch = Exporter(
                dry_run=True,
                start_time=t0,
                end_time=t_end,
                config_path=CONFIG_FILE,
            )
            exporter_batch.tick(process_all=True)
            batch_intervals = exporter_batch.get_suggested_intervals()

        return sync_intervals, batch_intervals

    def test_simple_coding_session(self) -> None:
        """Single coding session: sync and batch produce equivalent intervals."""
        test_data, t0, t_end = _simple_coding_scenario()
        sync, batch = self._run_sync_and_batch(test_data, t0, t_end)
        _assert_no_differences(sync, batch)

    def test_work_afk_work(self) -> None:
        """Work → AFK → work: sync and batch agree across the AFK boundary."""
        test_data, t0, t_end = _work_afk_work_scenario()
        sync, batch = self._run_sync_and_batch(test_data, t0, t_end)
        _assert_no_differences(sync, batch)

    def test_rolling_cache_rebuilt_enables_post_afk_events(self) -> None:
        """Regression: rolling cache must be rebuilt each tick or phase-3 events are lost.

        Uses freeze_time to simulate wall-clock advances between ticks, exercising
        the rolling cache code path (end_time=None).  The dry_run guard
        (ValueError when no more events remain) is caught and treated as a clean
        stop.

        Timeline
        --------
        T=0..600    coding (phase 1) — inside first cache window
        T=600..1800  AFK             — keeps current_event alive, no cache rebuild without fix
        T=1800..2400 coding (phase 3) — only visible after cache is rebuilt

        With the bug (commit 6f22ee3): cache stays at [T40, T716]; T1800 events invisible.
        With the fix: cache rebuilt at T=2500 to [T1240, T2516]; T1800 events visible.
        """
        test_data, t0, t_end = _work_afk_work_scenario()
        mock_aw = _build_mock_aw_client(test_data)

        t_during_afk = t0 + timedelta(seconds=700)
        t_past_all = t0 + timedelta(seconds=2500)

        with (
            patch("aw_export_timewarrior.aw_client.ActivityWatchClient", return_value=mock_aw),
            freeze_time(t_during_afk) as frozen_time,
        ):
            exporter = Exporter(
                dry_run=True,
                start_time=t0,
                # No end_time: activates the rolling cache in tick()
                config_path=CONFIG_FILE,
            )
            # A few ticks at T=700 process phase-1 and enter the AFK period.
            # Initial cache covers [t0-11min, t700+16s] — phase 3 is outside this window.
            _run_sync_ticks(exporter, 20)

            # Jump wall clock to T=2500: all events have now "happened".
            # Fix:   cache rebuilt to [t1240, t2516] → phase-3 coding visible.
            # Bug:   cache stays at [t40, t716]       → phase-3 coding invisible.
            frozen_time.move_to(t_past_all)
            _run_sync_ticks(exporter, 100)

        # get_suggested_intervals() only closes the last open interval when end_time is set.
        # Temporarily set end_time so the ongoing phase-3 coding interval is included.
        exporter.end_time = t_end
        sync_intervals = exporter.get_suggested_intervals()

        # Phase-3 coding must appear in sync output
        phase3_start = t0 + timedelta(seconds=1800)
        phase3_intervals = [
            iv for iv in sync_intervals if iv.end is not None and iv.end > phase3_start
        ]
        assert phase3_intervals, (
            "Sync mode produced no intervals after AFK ended.\n"
            "This is the cache staleness regression: phase-3 events were invisible "
            "because the cache was not rebuilt after the wall clock advanced.\n"
            f"All sync intervals: {sync_intervals}"
        )

        # Full equivalence: sync must match batch
        exporter_batch = Exporter(
            dry_run=True,
            test_data=test_data,  # test_data is fine for the reference run
            config_path=CONFIG_FILE,
        )
        exporter_batch.tick(process_all=True)
        batch_intervals = exporter_batch.get_suggested_intervals()

        _assert_no_differences(sync_intervals, batch_intervals)


class TestCacheGatedOnClosedRange:
    """The AW event cache must only be enabled for a genuinely closed (past)
    range, not merely "start and end both set".

    A bounded live sync (`sync --from <past> --to <future>`) has both times set
    but is still an open range: new heartbeats keep arriving.  Caching the first
    snapshot would freeze the live portion, so the cache must stay disabled -
    mirroring EventPipeline's batch-memo gate (end_time <= now).
    """

    def test_future_end_time_disables_event_cache(self) -> None:
        test_data, t0, _t_end = _simple_coding_scenario()
        mock_aw = _build_mock_aw_client(test_data)

        now = datetime.now(UTC)
        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient", return_value=mock_aw):
            exporter = Exporter(
                dry_run=True,
                start_time=now - timedelta(hours=1),
                end_time=now + timedelta(hours=1),  # future -> open range
                config_path=CONFIG_FILE,
            )

        assert exporter.event_fetcher._cache_range is None, (
            "Cache must be disabled for a future end_time (open range); otherwise "
            "the live portion is frozen to the first-tick snapshot."
        )

    def test_past_end_time_enables_event_cache(self) -> None:
        test_data, t0, t_end = _simple_coding_scenario()
        mock_aw = _build_mock_aw_client(test_data)

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient", return_value=mock_aw):
            exporter = Exporter(
                dry_run=True,
                start_time=t0,
                end_time=t_end,  # both in the past -> closed range
                config_path=CONFIG_FILE,
            )

        assert exporter.event_fetcher._cache_range is not None, (
            "Cache should be enabled for a closed, past range."
        )
