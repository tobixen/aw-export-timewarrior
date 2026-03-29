"""Tests for the 2-minute idle-countdown gap fix.

Background
----------
When using Wayland's idle protocol, the AFK watcher fires only after a
configurable idle timeout (typically 2 minutes).  During that 2-minute
countdown the window watcher keeps sending heartbeats even though the
user has already stopped interacting.

This creates a systematic ~2-minute overlap:

    T=0      T=120     T=300        T=600
    |---work--|--cntdn--|----afk-----|---work--|
              ^not-afk  ^afk bucket
              end       event start

  • ask-away gap covers T=120 to T=600 (from not-afk end to user return)
  • AFK event in the bucket covers T=300 to T=600
  • Window events exist from T=0 to T=300 (including the countdown)

Without the fix, window events in T=120-300 overlap with the ask-away
period but are NOT removed by _split_window_events_by_afk (because the
AFK bucket event only starts at T=300).

The fix: before calling _split_window_events_by_afk, extend the AFK event
backwards to match the ask-away event start (T=120), so the split
correctly removes the conflicting window events.
"""

from datetime import UTC, datetime, timedelta

from tests.conftest import FixtureDataBuilder

# ---------------------------------------------------------------------------
# Unit tests for _extend_afk_events_to_ask_away_start
# ---------------------------------------------------------------------------


def _make_afk_event(start: datetime, duration_s: float, status: str = "afk") -> dict:
    return {
        "id": 1,
        "timestamp": start,
        "duration": timedelta(seconds=duration_s),
        "data": {"status": status},
    }


def _make_ask_away_event(start: datetime, duration_s: float, message: str = "reading") -> dict:
    return {
        "id": 1,
        "timestamp": start,
        "duration": timedelta(seconds=duration_s),
        "data": {"message": message},
    }


def _make_pipeline():
    """Return a minimal EventPipeline instance for unit testing methods."""
    from aw_export_timewarrior.event_pipeline import EventPipeline, EventPipelineConfig

    return EventPipeline(event_fetcher=None, pipeline_config=EventPipelineConfig())


BASE = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)


def test_extend_afk_to_ask_away_start_basic():
    """AFK event is extended backwards to the ask-away event start.

    ask-away: T=0 to T=480  (user described gap starting at not-afk end)
    AFK event: T=120 to T=480  (idle timeout started 2 min after last interaction)

    Expected: AFK event extended to T=0, duration unchanged end point T=480.
    """
    pipeline = _make_pipeline()
    ask_away = _make_ask_away_event(BASE, 480)  # T=0 .. T=480
    afk_event = _make_afk_event(BASE + timedelta(seconds=120), 360)  # T=120 .. T=480

    result = pipeline._extend_afk_events_to_ask_away_start([afk_event], [ask_away])

    assert len(result) == 1
    assert result[0]["timestamp"] == BASE  # extended back to ask-away start
    assert result[0]["duration"] == timedelta(seconds=480)  # end point unchanged


def test_extend_afk_no_ask_away_unchanged():
    """AFK events are not modified when there are no ask-away events."""
    pipeline = _make_pipeline()
    afk_event = _make_afk_event(BASE + timedelta(seconds=120), 360)

    result = pipeline._extend_afk_events_to_ask_away_start([afk_event], [])

    assert result[0]["timestamp"] == BASE + timedelta(seconds=120)
    assert result[0]["duration"] == timedelta(seconds=360)


def test_extend_afk_not_afk_status_unchanged():
    """not-afk events are not extended."""
    pipeline = _make_pipeline()
    not_afk = _make_afk_event(BASE + timedelta(seconds=120), 360, status="not-afk")
    ask_away = _make_ask_away_event(BASE, 480)

    result = pipeline._extend_afk_events_to_ask_away_start([not_afk], [ask_away])

    # not-afk event should be untouched
    assert result[0]["timestamp"] == BASE + timedelta(seconds=120)
    assert result[0]["duration"] == timedelta(seconds=360)


def test_extend_afk_ask_away_after_afk_unchanged():
    """AFK event is not extended when ask-away starts AFTER the AFK event."""
    pipeline = _make_pipeline()
    afk_event = _make_afk_event(BASE, 300)  # T=0..T=300
    ask_away = _make_ask_away_event(BASE + timedelta(seconds=350), 150)  # T=350..T=500 (after AFK)

    result = pipeline._extend_afk_events_to_ask_away_start([afk_event], [ask_away])

    assert result[0]["timestamp"] == BASE
    assert result[0]["duration"] == timedelta(seconds=300)


# ---------------------------------------------------------------------------
# Integration test: window events in the 2-min countdown are excluded
# ---------------------------------------------------------------------------


def test_window_events_in_countdown_excluded_from_ask_away_period():
    """Window events during the idle countdown are excluded when ask-away covers the period.

    Timeline:
      T=0   - T=300 : window event (foot terminal) — spans whole work+countdown period
      T=0   - T=120 : not-afk heartbeats
      T=120 - T=300 : idle countdown (no not-afk, window still heartbeating)
      T=300 - T=600 : afk event (idle timeout triggered)
      T=0   - T=600 : ask-away event covering the gap from not-afk end to user return
      T=600 - T=900 : not-afk + window (user back)

    Expected: the window event should only appear tagged up to T=120 at most;
    no window-tagged intervals should overlap the ask-away period (T=0..T=600 here,
    or effectively T=120..T=300 since that is the problematic slice).
    """
    start = datetime(2025, 3, 26, 10, 0, 0, tzinfo=UTC)

    builder = FixtureDataBuilder(start_time=start)

    # T=0..T=120: active work — not-afk + window
    builder.add_afk_event("not-afk", 120, timestamp=start)
    builder.add_window_event("foot", "bash", 300, timestamp=start)  # spans T=0..T=300

    # T=300: idle timeout → afk event
    builder.add_afk_event("afk", 300, timestamp=start + timedelta(seconds=300))

    # ask-away covers the whole gap (T=0..T=600) — simulating what afk-prompt records
    builder.add_ask_away_event("reading", 600, timestamp=start)

    # T=600: user returns
    builder.add_afk_event("not-afk", 300, timestamp=start + timedelta(seconds=600))
    builder.add_window_event("foot", "bash", 300, timestamp=start + timedelta(seconds=600))

    test_data = builder.build()

    from aw_export_timewarrior.main import Exporter

    config = {
        "rules": {"app": {"terminal": {"app_names": ["foot"], "tags": ["terminal"]}}},
        "exclusive": {},
        "tags": {},
        "terminal_apps": ["foot"],
    }

    exporter = Exporter(
        dry_run=True,
        test_data=test_data,
        start_time=start,
        end_time=start + timedelta(seconds=900),
        config=config,
    )
    commands: list = []
    exporter.tracker.capture_commands = commands
    exporter.tick(process_all=True)

    print("\nCaptured commands:")
    for cmd in commands:
        print(f"  {' '.join(str(x) for x in cmd)}")

    all_cmds_str = [" ".join(str(x) for x in cmd) for cmd in commands]

    # Primary assertion: no terminal-tagged command should have a timestamp before T=600.
    # Without the fix, the window event spanning T=0-T=300 would produce a terminal
    # interval in the countdown window (T=120..T=300).
    # With the fix, the extended AFK event covers T=0..T=600 and removes that slice.
    from aw_export_timewarrior.utils import normalize_timestamp

    afk_end = start + timedelta(seconds=600)
    for cmd_str in all_cmds_str:
        if "terminal" not in cmd_str:
            continue
        for part in cmd_str.split():
            try:
                ts = normalize_timestamp(part)
                assert ts >= afk_end, (
                    f"Terminal event tracked before AFK period ended (before T=600): {cmd_str}"
                )
            except (ValueError, TypeError):
                continue

    # Secondary assertion: terminal activity AFTER user returns (T=600+) is tracked
    terminal_after_return = [cmd for cmd in all_cmds_str if "terminal" in cmd]
    assert len(terminal_after_return) >= 1, "Expected terminal activity after user returned"
