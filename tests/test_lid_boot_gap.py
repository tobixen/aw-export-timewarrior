"""Tests for LID boot-gap event handling.

A boot-gap event represents a period where the system was off/sleeping
(so AW had no data).  Its duration is set by the LID watcher to
'current_time - last_heartbeat_time', but heartbeats keep extending it
throughout the day, so a bedtime boot-gap can end up spanning the
entire next day.

Bug: _resolve_event_conflicts was treating boot-gap events as
authoritative AFK signals and removing all not-afk events that
overlapped them — wiping out a full day of activity.

Fix: boot-gap events represent 'unknown' time and must be clipped to
end at the first real AFK watcher event that starts after the boot-gap
start.  AFK watcher data is authoritative about when the system was
actually running.
"""

from datetime import UTC, datetime, timedelta

from aw_export_timewarrior.main import Exporter
from tests.conftest import FixtureDataBuilder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(data: dict) -> list:
    """Run the exporter in batch mode and return captured start commands."""
    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)
    return [cmd for cmd in exporter.get_captured_commands() if len(cmd) > 1 and cmd[1] == "start"]


def _tags_from_cmds(start_cmds: list) -> list[frozenset]:
    """Extract tag sets (without datetime args) from start commands."""
    result = []
    for cmd in start_cmds:
        tags = frozenset(t for t in cmd[2:] if not t.startswith("2") and "T" not in t)
        result.append(tags)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_boot_gap_does_not_erase_activity() -> None:
    """Boot-gap LID event with exaggerated duration must not remove activity.

    Scenario:
      - 5 min of work
      - bedtime AFK (8 h)
      - boot-gap LID event starting at bedtime but lasting 20 h (incorrectly
        extended by heartbeats — covers the entire next-day activity)
      - user wakes up after 8 h, works for 30 min
      - short AFK
      - 30 more minutes of work

    Expected: the post-wakeup work intervals are NOT erased.
    Without the fix, all not-afk events inside the boot-gap range are removed
    and the exporter produces only a single bedtime suggestion.
    """
    t0 = datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC)
    td = timedelta

    builder = FixtureDataBuilder(start_time=t0)

    # Initial 5 min work
    builder.add_window_event("vscode", "work.py", 300)
    builder.add_afk_event("not-afk", 300)

    bedtime_start = t0 + td(seconds=300)

    # AFK watcher: 8 h bedtime afk
    builder.add_afk_event("afk", 28800, timestamp=bedtime_start)
    # LID watcher boot-gap starting at bedtime but lasting 20 h (buggy extension)
    builder.add_lid_event("closed", 72000, timestamp=bedtime_start, boot_gap=True)

    wakeup = bedtime_start + td(seconds=28800)  # 8 h later

    # AFK watcher: active after wakeup
    builder.add_afk_event("not-afk", 1800, timestamp=wakeup)
    builder.add_window_event("vscode", "work.py", 1800, timestamp=wakeup)

    # Brief AFK
    afk2_start = wakeup + td(seconds=1800)
    builder.add_afk_event("afk", 600, timestamp=afk2_start)

    # More work
    work2_start = afk2_start + td(seconds=600)
    builder.add_afk_event("not-afk", 1800, timestamp=work2_start)
    builder.add_window_event("vscode", "work.py", 1800, timestamp=work2_start)

    data = builder.build()
    start_cmds = _run(data)

    # At minimum there must be a work interval AFTER wakeup (post-wakeup activity)
    tag_sets = _tags_from_cmds(start_cmds)
    work_tags = {"~aw"}  # work events map to ~aw (no matching rule in default test config)
    work_count = sum(1 for ts in tag_sets if work_tags.issubset(ts) and "afk" not in ts)
    assert work_count >= 1, (
        f"Expected at least one post-wakeup work interval, got {work_count}. Tag sets: {tag_sets}"
    )

    # And no single suggestion should span the entire 20-hour window
    intervals = Exporter(test_data=data, dry_run=True, enable_assert=False)
    intervals.tick(process_all=True)
    suggested = intervals.get_suggested_intervals()
    max_duration = max((iv.end - iv.start).total_seconds() for iv in suggested if iv.end)
    assert max_duration < 72000, (
        f"Longest suggested interval is {max_duration}s — boot-gap still swallowing the day. "
        f"Intervals: {suggested}"
    )


def test_boot_gap_clipped_to_first_afk_event() -> None:
    """Boot-gap duration is trimmed to end when the AFK watcher first reports.

    The pipeline's merged_afk_events must not contain a boot-gap event that
    extends beyond the first AFK watcher event in the same range.  Once the
    AFK watcher has data (at wakeup time), the boot-gap is over.
    """
    t0 = datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC)
    td = timedelta

    builder = FixtureDataBuilder(start_time=t0)
    builder.add_window_event("vscode", "work.py", 300)
    builder.add_afk_event("not-afk", 300)

    sleep_start = t0 + td(seconds=300)
    builder.add_afk_event("afk", 7200, timestamp=sleep_start)  # 2 h sleep
    # Boot-gap spans 10 h (incorrectly extended)
    builder.add_lid_event("closed", 36000, timestamp=sleep_start, boot_gap=True)

    wakeup = sleep_start + td(seconds=7200)
    builder.add_afk_event("not-afk", 1800, timestamp=wakeup)
    builder.add_window_event("chrome", "something", 1800, timestamp=wakeup)

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    pipeline = exporter._pipeline

    pipeline.last_tick = exporter.start_time or t0

    completed, _ = pipeline.fetch_and_prepare_events()

    # The merged AFK events must not contain a boot-gap that extends past wakeup
    # (the first not-afk event should survive in completed events)
    statuses = [e["data"].get("status") for e in completed]
    assert "not-afk" in statuses, (
        f"not-afk events were erased by the boot-gap. Completed event statuses: {statuses}"
    )
