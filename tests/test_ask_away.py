"""Integration tests for ask-away event handling."""

from datetime import timedelta

from aw_export_timewarrior.main import Exporter
from tests.conftest import FixtureDataBuilder


def test_ask_away_message_appears_as_tag() -> None:
    """Test that ask-away messages are converted to tags on AFK periods."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        # AFK period with ask-away message
        .add_afk_event("afk", 600)
        .add_ask_away_event("housework", 600)
        # Back to work
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    # Get captured commands
    commands = exporter.get_captured_commands()

    # Find timew start commands
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Should have a command with both "afk" and "housework" tags
    housework_found = any("housework" in cmd for cmd in start_commands)
    assert housework_found, f"Expected 'housework' tag in commands: {start_commands}"


def test_ask_away_multi_word_message() -> None:
    """Test that multi-word ask-away messages are split into multiple tags."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        # AFK period with multi-word message
        .add_afk_event("afk", 600)
        .add_ask_away_event("lunch break", 600)
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Should have both "lunch" and "break" tags
    lunch_found = any("lunch" in cmd for cmd in start_commands)
    break_found = any("break" in cmd for cmd in start_commands)

    assert lunch_found, f"Expected 'lunch' tag in commands: {start_commands}"
    assert break_found, f"Expected 'break' tag in commands: {start_commands}"


def test_ask_away_overlap_matching() -> None:
    """Test that ask-away events match by overlap, not exact timestamp/duration."""
    builder = FixtureDataBuilder()

    # Add window and not-afk events
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    # Add an AFK event with slightly different timestamp than ask-away
    # This simulates the real-world scenario where ask-away creates events
    # based on gaps in non-afk events, which may differ slightly from
    # the actual AFK events in the aw-watcher-afk bucket
    afk_start = builder.current_time
    builder.add_afk_event("afk", 600)

    # Add ask-away event with slight offset (2 seconds later, 10 seconds shorter)
    # This should still match by overlap
    from datetime import timedelta

    ask_away_start = afk_start + timedelta(seconds=2)
    builder.add_ask_away_event("meeting", 590, timestamp=ask_away_start)

    # Back to work
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Despite the timestamp/duration mismatch, "meeting" should still be found
    meeting_found = any("meeting" in cmd for cmd in start_commands)
    assert meeting_found, f"Expected 'meeting' tag despite timestamp offset: {start_commands}"


def test_ask_away_no_message_no_tags() -> None:
    """Test that AFK periods without ask-away messages don't get extra tags."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        # AFK period WITHOUT ask-away message
        .add_afk_event("afk", 600)
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Find the AFK command
    afk_commands = [cmd for cmd in start_commands if "afk" in cmd]
    assert len(afk_commands) > 0, "Should have at least one AFK command"

    # The AFK command should only have standard tags, no extra message-derived tags
    # Standard tags are: "afk" and "~aw"
    for cmd in afk_commands:
        # Remove standard tags and quotes
        cmd_str = " ".join(cmd)
        # Should not have unexpected tags beyond afk and ~aw
        assert "housework" not in cmd_str
        assert "meeting" not in cmd_str


def test_ask_away_within_afk_does_not_extend_future_afk() -> None:
    """Regression test: ask_away that starts WITHIN an AFK period must not
    be matched to a later AFK period and extend it backwards.

    Bug: _extend_afk_events_to_ask_away_start checked only
    `ask_start < afk_start`, which is trivially true for any future AFK
    event.  This caused a far-future AFK event to be extended backwards to
    the ask_away start, swallowing all window events between the two AFK
    periods.

    Explicit timeline (all timestamps are absolute to avoid builder placement
    artefacts from last_window_event_start):
      T+0     active window starts
      T+0     not-afk starts (300s)
      T+5min  AFK period 1 starts (600s)
      T+6min  ask_away starts within afk1 (300s, ends T+11min) — WITHIN afk1
      T+15min AFK period 1 ends, active window starts (300s)
      T+15min not-afk starts (300s)
      T+20min AFK period 2 starts (400s)  ← must NOT be extended back to T+6min
      T+26:40 active window starts (300s)
    """
    from datetime import UTC, datetime

    t0 = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)

    builder = FixtureDataBuilder(start_time=t0)

    # Active phase before first AFK (T+0 .. T+5min)
    builder.add_window_event("vscode", "main.py", 300, timestamp=t0)
    builder.add_afk_event("not-afk", 300, timestamp=t0)

    # AFK period 1: T+5min .. T+15min
    afk1_start = t0 + timedelta(minutes=5)
    afk1_end = t0 + timedelta(minutes=15)
    builder.add_afk_event("afk", 600, timestamp=afk1_start)

    # Ask-away: T+6min .. T+11min (starts WITHIN afk1, ends well before afk1_end)
    ask_start = t0 + timedelta(minutes=6)
    builder.add_ask_away_event("UNKNOWN", 300, timestamp=ask_start)

    # Active between AFKs: T+15min .. T+20min
    active2_start = afk1_end  # T+15min
    active2_end = t0 + timedelta(minutes=20)
    builder.add_window_event("vscode", "active_between_afk.py", 300, timestamp=active2_start)
    builder.add_afk_event("not-afk", 300, timestamp=active2_start)

    # AFK period 2: T+20min .. T+26:40  — must NOT be extended back
    afk2_start = active2_end  # T+20min
    builder.add_afk_event("afk", 400, timestamp=afk2_start)

    # Active after AFK 2: T+26:40 .. T+31:40
    after_afk2_start = t0 + timedelta(seconds=20 * 60 + 400)
    builder.add_window_event("vscode", "after_afk2.py", 300, timestamp=after_afk2_start)
    builder.add_afk_event("not-afk", 300, timestamp=after_afk2_start)

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # The AFK1 export should start at T+5min and AFK2 at T+20min.
    # With the bug, afk2 is extended back to T+6min (the ask_away start), so its
    # export would be timestamped at T+6min instead of T+20min.
    afk_commands = [cmd for cmd in start_commands if "afk" in cmd]
    assert len(afk_commands) >= 2, f"Expected at least 2 AFK exports, got: {afk_commands}"

    # Extract timestamps from AFK commands (last element of each command)
    afk_timestamps = [cmd[-1] for cmd in afk_commands]

    # afk1 must start at T+5min (09:05 UTC) and afk2 at T+20min (09:20 UTC).
    # Timestamps in commands are local-time strings; match just the minute part.
    # With the bug, afk2 would be extended back to T+6min (ask_away start).
    def ts_minutes(ts: str) -> str:
        """Extract HH:MM from an ISO timestamp string."""
        # e.g. "2025-01-01T10:05:00" -> "10:05", or "...t09:05:00+00:00" -> "09:05"
        return ts[11:16]

    afk_minutes = [ts_minutes(ts) for ts in afk_timestamps]

    # afk1 = T+5min (09:05 UTC). Allow local offsets ±1h.
    afk1_expected_utc = (t0 + timedelta(minutes=5)).strftime("%H:%M")
    assert any(
        afk1_expected_utc in ts
        or ts
        in {f"{int(afk1_expected_utc[:2]) + h:02d}{afk1_expected_utc[2:]}" for h in range(-1, 2)}
        for ts in afk_minutes
    ), f"AFK1 export expected near T+5min, got timestamps: {afk_timestamps}"

    # afk2 = T+20min. The bug would produce T+6min instead.
    afk2_expected_utc = (t0 + timedelta(minutes=20)).strftime("%H:%M")
    afk2_buggy_utc = (t0 + timedelta(minutes=6)).strftime("%H:%M")
    assert not any(afk2_buggy_utc in ts for ts in afk_minutes), (
        f"Bug still present: AFK2 extended back to T+6min. Timestamps: {afk_timestamps}"
    )
    assert any(
        afk2_expected_utc in ts
        or ts
        in {f"{int(afk2_expected_utc[:2]) + h:02d}{afk2_expected_utc[2:]}" for h in range(-1, 2)}
        for ts in afk_minutes
    ), f"AFK2 export expected near T+20min, got timestamps: {afk_timestamps}"
