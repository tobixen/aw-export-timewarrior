"""Test that batch mode prepares the event pipeline once, not once per call.

Regression test for the efficiency finding (docs/CODE_REVIEW_2026-07.md,
"Efficiency", main.py:1478): find_next_activity() re-ran the full
EventPipeline (fetch, AFK gap workaround, heartbeat merge, lid merge,
window-split, sort) on every call.  Each AFK transition makes
find_next_activity() return early, so tick(process_all=True) re-called the
pipeline O(number of AFK transitions) times over the same immutable batch
data.

In batch mode (end_time set) the underlying data cannot change, so the
pipeline should run the expensive preparation once and serve subsequent
calls by filtering the memoized result on the advanced last_tick.
"""

from datetime import UTC, datetime, timedelta

from aw_export_timewarrior.utils import strip_timew_hints

from .conftest import FixtureDataBuilder

CONFIG = {
    "rules": {
        "app": {
            "mplayer": {
                "app_names": ["MPlayer"],
                "tags": ["entertainment", "video"],
            }
        }
    },
    "exclusive": {},
    "tags": {},
    "terminal_apps": [],
}


def _build_exporter_with_afk_transitions():
    """Batch scenario with two AFK periods → several early pipeline returns.

    Timeline (seconds relative to start):
      0–300     not-afk + MPlayer window
      300–700   afk (400s, passes the 240s max_mixed_interval filter)
      700–1000  not-afk + MPlayer window
      1000–1400 afk (400s)
      1400–1700 not-afk + MPlayer window
    """
    start_time = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
    builder = FixtureDataBuilder(start_time=start_time)

    for offset in (0, 700, 1400):
        ts = start_time + timedelta(seconds=offset)
        builder.add_afk_event("not-afk", duration=300, timestamp=ts)
        builder.add_window_event("MPlayer", "MPlayer", duration=300, timestamp=ts)
    for offset in (300, 1000):
        builder.add_afk_event("afk", duration=400, timestamp=start_time + timedelta(seconds=offset))

    from aw_export_timewarrior.main import Exporter

    return Exporter(
        dry_run=True,
        test_data=builder.build(),
        start_time=start_time,
        end_time=start_time + timedelta(seconds=1800),
        config=CONFIG,
        enable_assert=True,
    )


def test_batch_mode_prepares_pipeline_once() -> None:
    """The expensive per-bucket fetch must happen once for the whole batch run."""
    exporter = _build_exporter_with_afk_transitions()

    window_fetches = []
    original_get_events = exporter.event_fetcher.get_events

    def counting_get_events(bucket_id, *args, **kwargs):
        if "window" in bucket_id:
            window_fetches.append(bucket_id)
        return original_get_events(bucket_id, *args, **kwargs)

    exporter.event_fetcher.get_events = counting_get_events

    exporter.tick(process_all=True)

    # Without memoization each AFK transition re-runs the pipeline, giving one
    # window-bucket fetch per find_next_activity() call (4+ in this scenario).
    assert len(window_fetches) == 1, (
        f"window bucket fetched {len(window_fetches)} times in batch mode; "
        "the pipeline should prepare events once and serve later calls from memory"
    )


def test_batch_mode_memoized_pipeline_still_exports_all_intervals() -> None:
    """The memoized pipeline must still yield every activity/afk interval."""
    exporter = _build_exporter_with_afk_transitions()
    commands: list = []
    exporter.tracker.capture_commands = commands

    exporter.tick(process_all=True)

    start_cmds = [cmd for cmd in commands if len(cmd) >= 2 and cmd[1] == "start"]
    afk_starts = [cmd for cmd in start_cmds if "afk" in cmd and "not-afk" not in cmd]
    video_starts = [cmd for cmd in start_cmds if "video" in cmd]

    # Both AFK periods and all three activity periods must be exported.
    assert len(afk_starts) >= 2, f"expected 2+ afk exports, got: {start_cmds}"
    assert len(video_starts) >= 3, f"expected 3+ video exports, got: {start_cmds}"

    # Export start timestamps must never go backwards.
    start_times = [datetime.fromisoformat(strip_timew_hints(cmd)[-1]) for cmd in start_cmds]
    assert start_times == sorted(start_times), f"exports out of order: {start_times}"
