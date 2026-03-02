"""Test that known_events_time is clipped for events spanning an export boundary.

Regression test for the bug where an event starting before last_known_tick had
its full duration added to known_events_time, causing the assertion:
  tracked_gap < known_events_time
to fire in batch/diff mode.

Root cause:
  In real AW data the AFK period is composed of many short heartbeat events.
  The pipeline merges consecutive heartbeats with the same status, so on the
  FIRST call all heartbeats merge into one long event (> max_mixed_interval)
  which is used to split the overlapping window event.  After the AFK is
  exported, last_tick advances to afk_end.  On the SECOND call only the LAST
  heartbeat is returned (because earlier ones have event_end < last_tick).  Its
  short duration is filtered (< max_mixed_interval), leaving merged_afk_events
  empty, so _split_window_events_by_afk() does NOT split the window event.
  The full (unsplit) window event — which started before last_known_tick — is
  then processed with its entire duration added to known_events_time, violating
  the invariant  known_events_time <= tracked_gap.

Scenario:
  - T+0:    not-afk + MPlayer window event start (window lasts 12 min = 720s)
  - T+300s: AFK heartbeat 1 starts (lasts 250s → ends at T+550s)
  - T+550s: AFK heartbeat 2 starts (lasts  50s → ends at T+600s)
            (heartbeats merge to 300s on 1st fetch, but only h2 survives on 2nd)
  - T+600s: not-afk resumes

  After AFK export last_tick = T+600s.  2nd pipeline call fetches only h2 (50s).
  50s < max_mixed_interval (240s) → filtered → no split → full MPlayer returned.
  known_events_time gets 720s, tracked_gap = T+720s - T+600s = 120s → assertion.
"""

from datetime import UTC, datetime, timedelta

from .conftest import FixtureDataBuilder


def test_known_events_time_not_overcounted_after_afk() -> None:
    """known_events_time must not exceed tracked_gap after an AFK export boundary."""
    start_time = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
    builder = FixtureDataBuilder(start_time=start_time)

    # not-afk for 5 min (T+0 to T+300s)
    builder.add_afk_event("not-afk", duration=300, timestamp=start_time)

    # MPlayer window for 12 min (T+0 to T+720s) - spans the AFK period
    builder.add_window_event("MPlayer", "MPlayer", duration=720, timestamp=start_time)

    # Two consecutive AFK heartbeats (total 300s, merged on 1st fetch)
    #   heartbeat 1: T+300s to T+550s (250s)
    #   heartbeat 2: T+550s to T+600s  (50s)  ← only this one survives the 2nd fetch
    builder.add_afk_event("afk", duration=250, timestamp=start_time + timedelta(seconds=300))
    builder.add_afk_event("afk", duration=50, timestamp=start_time + timedelta(seconds=550))

    # not-afk resumes at T+600s
    builder.add_afk_event("not-afk", duration=120, timestamp=start_time + timedelta(seconds=600))

    test_data = builder.build()

    from aw_export_timewarrior.main import Exporter

    config = {
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
        # Default max_mixed_interval = 240s:
        #   merged AFK (300s) passes on 1st fetch (300 > 240)
        #   heartbeat 2 (50s) is filtered on 2nd fetch (50 < 240) → no split
    }

    exporter = Exporter(
        dry_run=True,
        test_data=test_data,
        start_time=start_time,
        end_time=start_time + timedelta(minutes=15),
        config=config,
        enable_assert=True,  # Raise AssertionError instead of just logging
    )

    commands: list = []
    exporter.tracker.capture_commands = commands

    # Should NOT raise AssertionError (bug: it does)
    exporter.tick(process_all=True)

    # Additionally verify that no export start time precedes last_known_tick:
    # all 'timew start' timestamps must be in non-decreasing order.
    start_times = []
    for cmd in commands:
        if len(cmd) >= 3 and cmd[1] == "start":
            try:
                ts = datetime.fromisoformat(cmd[-1])
                start_times.append(ts)
            except ValueError:
                pass

    for i in range(1, len(start_times)):
        assert start_times[i] >= start_times[i - 1], (
            f"Export at index {i} starts at {start_times[i]} which is before "
            f"previous export at {start_times[i - 1]} — time went backwards!"
        )
