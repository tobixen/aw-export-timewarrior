"""Integration tests for split ask-away event handling."""

from datetime import UTC, datetime, timedelta

from aw_export_timewarrior.main import Exporter
from tests.conftest import FixtureDataBuilder


def test_split_events_not_duplicated_in_captured_commands() -> None:
    """Regression test (dcdce6e): split ask-away events are double-exported.

    Bug: the outer loop in find_next_activity() calls ensure_tag_exported a SECOND
    time when an AFK event enters AFK state AND split events overlap — even though
    ensure_tag_exported was already called inside check_and_handle_afk_state_change.
    This causes duplicate timew start commands for the split intervals, and resets
    last_known_tick to the morning AFK start so subsequent work events may be
    incorrectly tagged as UNKNOWN.

    Verify each split activity appears exactly once in the exported commands.
    """
    t0 = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
    td = timedelta

    builder = FixtureDataBuilder(start_time=t0)
    builder.add_window_event("vscode", "work.py", 300)
    builder.add_afk_event("not-afk", 300)

    # AFK with split events: t0+300 .. t0+900
    afk_start = t0 + td(seconds=300)
    builder.add_afk_event("afk", 600, timestamp=afk_start)
    builder.add_split_ask_away_events([("epoxy", 300), ("tea", 300)], timestamp=afk_start)

    # Return to work: t0+900 .. t0+1500
    builder.add_window_event("vscode", "work.py", 600, timestamp=t0 + td(seconds=900))
    builder.add_afk_event("not-afk", 600, timestamp=t0 + td(seconds=900))

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]
    all_tags = [tag for cmd in start_commands for tag in cmd]

    epoxy_count = all_tags.count("epoxy")
    tea_count = all_tags.count("tea")
    assert epoxy_count == 1, f"Expected 'epoxy' exactly once, got {epoxy_count}: {start_commands}"
    assert tea_count == 1, f"Expected 'tea' exactly once, got {tea_count}: {start_commands}"


def test_non_split_ask_away_exported_when_afk2_extended_past_gap() -> None:
    """Regression test (dcdce6e): non-split ask-away activity is silently dropped when
    _extend_afk_events_to_ask_away_start extends AFK2 backwards past a >5-min gap,
    causing AFK2 to be processed via the 'already AFK' path without calling
    ensure_tag_exported.

    The outer loop only calls ensure_tag_exported when SPLIT events overlap; for
    non-split events it is never called in the 'already AFK' branch.

    Scenario:
      work → AFK1 (short, no ask-away) → [>5 min gap] → AFK2 (with non-split "ror"
      ask-away that starts in the gap) → work.

    _extend_afk_events_to_ask_away_start extends AFK2 backwards to the ask-away start,
    creating a gap of >300 s from AFK1 so the two AFKs are NOT merged by
    _merge_consecutive_afk_events.  In the next pipeline call (still in AFK state from
    AFK1), the extended AFK2 arrives and the 'already AFK' handler skips 'ror'.
    """
    t0 = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
    td = timedelta

    builder = FixtureDataBuilder(start_time=t0)
    builder.add_window_event("vscode", "work.py", 300)
    builder.add_afk_event("not-afk", 300)

    # AFK1: t0+300 .. t0+600  (no ask-away overlapping)
    afk1_start = t0 + td(seconds=300)
    builder.add_afk_event("afk", 300, timestamp=afk1_start)

    # Ask-away "ror" starts at t0+910, inside the gap between AFK1 and AFK2.
    # _extend_afk_events_to_ask_away_start will extend AFK2 backwards to t0+910.
    # Gap from AFK1.end (t0+600) to AFK2-extended.start (t0+910) = 310s > 300s (5 min)
    # → the two AFK events are NOT merged by _merge_consecutive_afk_events.
    ask_away_start = t0 + td(seconds=910)
    builder.add_ask_away_event("ror", 300, timestamp=ask_away_start)

    # AFK2: t0+1200 .. t0+1500  (original start; extended back to t0+910 by pipeline)
    afk2_start = t0 + td(seconds=1200)
    builder.add_afk_event("afk", 300, timestamp=afk2_start)

    # Return to work after AFK2: t0+1500 .. t0+1800
    builder.add_window_event("vscode", "work.py", 300, timestamp=t0 + td(seconds=1500))
    builder.add_afk_event("not-afk", 300, timestamp=t0 + td(seconds=1500))

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]
    all_tags = [tag for cmd in start_commands for tag in cmd]

    assert "ror" in all_tags, (
        f"Expected 'ror' tag from non-split ask-away in commands: {start_commands}"
    )


def test_split_events_exported_in_order() -> None:
    """Test that split events are exported to timewarrior in the correct order."""
    builder = FixtureDataBuilder()
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    # AFK period with split events
    afk_start = builder.last_window_event_start
    builder.add_afk_event("afk", 600)
    builder.add_split_ask_away_events([("toilet", 300), ("laundry", 300)], timestamp=afk_start)

    # Back to work
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Should have commands with both "toilet" and "laundry" tags
    toilet_found = any("toilet" in cmd for cmd in start_commands)
    laundry_found = any("laundry" in cmd for cmd in start_commands)

    assert toilet_found, f"Expected 'toilet' tag in commands: {start_commands}"
    assert laundry_found, f"Expected 'laundry' tag in commands: {start_commands}"


def test_split_events_have_metadata() -> None:
    """Test that split events contain proper split metadata."""
    builder = FixtureDataBuilder()
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    afk_start = builder.last_window_event_start
    builder.add_afk_event("afk", 900)
    builder.add_split_ask_away_events(
        [("task1", 300), ("task2", 300), ("task3", 300)], timestamp=afk_start
    )

    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    data = builder.build()

    # Verify the test data has correct metadata
    ask_away_events = data["events"]["aw-watcher-ask-away_test"]
    assert len(ask_away_events) == 3

    for i, event in enumerate(ask_away_events):
        assert event["data"]["split"] is True
        assert event["data"]["split_count"] == 3
        assert event["data"]["split_index"] == i
        assert "split_id" in event["data"]


def test_split_events_match_afk_period() -> None:
    """Test that split events are matched to AFK period by overlap."""
    builder = FixtureDataBuilder()

    # Add initial work
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    # Add AFK period - starts at last_window_event_start
    afk_start = builder.last_window_event_start
    builder.add_afk_event("afk", 900)

    # Add split events with slight offset (simulating real-world scenario)
    # Split events start 2 seconds after AFK period
    split_start = afk_start + timedelta(seconds=2)
    builder.add_split_ask_away_events(
        [
            ("coffee", 300),
            ("meeting", 300),
            ("email", 296),
        ],  # Total: 896 seconds (2 second offset + end 2 seconds early)
        timestamp=split_start,
    )

    # Back to work
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # All three split activities should be found despite timestamp offset
    coffee_found = any("coffee" in cmd for cmd in start_commands)
    meeting_found = any("meeting" in cmd for cmd in start_commands)
    email_found = any("email" in cmd for cmd in start_commands)

    assert coffee_found, f"Expected 'coffee' tag: {start_commands}"
    assert meeting_found, f"Expected 'meeting' tag: {start_commands}"
    assert email_found, f"Expected 'email' tag: {start_commands}"


def test_split_events_preserve_order() -> None:
    """Test that split events are processed in the correct chronological order."""
    builder = FixtureDataBuilder()
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    afk_start = builder.last_window_event_start
    builder.add_afk_event("afk", 1200)
    builder.add_split_ask_away_events(
        [("first", 200), ("second", 400), ("third", 300), ("fourth", 300)], timestamp=afk_start
    )

    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Find the indices of each activity in the commands
    first_idx = next((i for i, cmd in enumerate(start_commands) if "first" in cmd), None)
    second_idx = next((i for i, cmd in enumerate(start_commands) if "second" in cmd), None)
    third_idx = next((i for i, cmd in enumerate(start_commands) if "third" in cmd), None)
    fourth_idx = next((i for i, cmd in enumerate(start_commands) if "fourth" in cmd), None)

    assert first_idx is not None, "Expected 'first' activity"
    assert second_idx is not None, "Expected 'second' activity"
    assert third_idx is not None, "Expected 'third' activity"
    assert fourth_idx is not None, "Expected 'fourth' activity"

    # Verify chronological order
    assert first_idx < second_idx < third_idx < fourth_idx, (
        f"Activities not in correct order. Indices: first={first_idx}, "
        f"second={second_idx}, third={third_idx}, fourth={fourth_idx}"
    )


def test_split_multi_word_messages() -> None:
    """Test that multi-word messages in split events are handled correctly."""
    builder = FixtureDataBuilder()
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    afk_start = builder.last_window_event_start
    builder.add_afk_event("afk", 600)
    builder.add_split_ask_away_events(
        [("lunch break", 300), ("phone call", 300)], timestamp=afk_start
    )

    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Multi-word messages should be split into tags
    lunch_found = any("lunch" in cmd for cmd in start_commands)
    break_found = any("break" in cmd for cmd in start_commands)
    phone_found = any("phone" in cmd for cmd in start_commands)
    call_found = any("call" in cmd for cmd in start_commands)

    assert lunch_found, f"Expected 'lunch' tag: {start_commands}"
    assert break_found, f"Expected 'break' tag: {start_commands}"
    assert phone_found, f"Expected 'phone' tag: {start_commands}"
    assert call_found, f"Expected 'call' tag: {start_commands}"


def test_split_events_with_same_split_id() -> None:
    """Test that events with the same split_id are recognized as part of same split."""
    builder = FixtureDataBuilder()
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    afk_start = builder.last_window_event_start
    builder.add_afk_event("afk", 600)
    builder.add_split_ask_away_events([("activity1", 200), ("activity2", 400)], timestamp=afk_start)

    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    data = builder.build()

    # Verify events have the same split_id
    ask_away_events = data["events"]["aw-watcher-ask-away_test"]
    split_ids = [event["data"]["split_id"] for event in ask_away_events]

    assert len(set(split_ids)) == 1, "All split events should have the same split_id"

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    activity1_found = any("activity1" in cmd for cmd in start_commands)
    activity2_found = any("activity2" in cmd for cmd in start_commands)

    assert activity1_found and activity2_found, (
        f"Both activities should be exported: {start_commands}"
    )


def test_regular_and_split_events_mixed() -> None:
    """Test that split events can be distinguished from regular events via metadata."""
    builder = FixtureDataBuilder()
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    # AFK period with mixed events: 1 regular + 2 split
    # Note: This tests the metadata distinction, not the actual export behavior
    # since the exporter will pick up split events first if they exist
    afk_start = builder.last_window_event_start
    builder.add_afk_event("afk", 900)

    # Add split events
    builder.add_split_ask_away_events([("lunch", 450), ("walk", 450)], timestamp=afk_start)

    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Should find split events
    lunch_found = any("lunch" in cmd for cmd in start_commands)
    walk_found = any("walk" in cmd for cmd in start_commands)

    assert lunch_found, f"Expected 'lunch' (split event): {start_commands}"
    assert walk_found, f"Expected 'walk' (split event): {start_commands}"


def test_empty_split_message_skipped() -> None:
    """Test that split events with empty messages are skipped during export."""
    builder = FixtureDataBuilder()
    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    afk_start = builder.last_window_event_start
    builder.add_afk_event("afk", 600)
    builder.add_split_ask_away_events(
        [("first", 200), ("", 200), ("third", 200)], timestamp=afk_start
    )

    builder.add_window_event("vscode", "main.py", 300)
    builder.add_afk_event("not-afk", 300)

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Should only find "first" and "third", not the empty one
    first_found = any("first" in cmd for cmd in start_commands)
    third_found = any("third" in cmd for cmd in start_commands)

    assert first_found, f"Expected 'first' activity: {start_commands}"
    assert third_found, f"Expected 'third' activity: {start_commands}"


def test_split_events_after_short_afk_same_tags() -> None:
    """Regression test: split ask-away events skipped when preceding short AFK leaves
    timew_info tagged as {afk, ~aw} and the big AFK's final_tags matches.

    The bug: ensure_tag_exported returned early when final_tags == timew_info["tags"],
    skipping the split-event handling block.  This happens when a short AFK sets
    timew_info to {afk, ~aw}, a brief not-afk event is too short to create new
    tracking (so timew_info stays {afk, ~aw}), and then the big AFK with split
    events arrives with the same plain {afk, ~aw} final_tags.
    """
    from datetime import datetime

    t0 = datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
    td = timedelta

    # Work period: t0+0 to t0+300
    builder = FixtureDataBuilder(start_time=t0)
    builder.add_window_event("vscode", "work.py", 300)  # t0+0 .. t0+300
    builder.add_afk_event("not-afk", 300)  # overlaps window

    # Short AFK: t0+300 .. t0+600  (300 s, explicit timestamp)
    builder.add_afk_event("afk", 300, timestamp=t0 + td(seconds=300))

    # Brief not-afk return: t0+600 .. t0+610 (10 s — too short to produce new tracking)
    builder.add_window_event("vscode", "brief.py", 10, timestamp=t0 + td(seconds=600))
    builder.add_afk_event("not-afk", 10, timestamp=t0 + td(seconds=600))

    # Big AFK with split ask-away events: t0+610 .. t0+2410 (1800 s)
    big_afk_start = t0 + td(seconds=610)
    builder.add_afk_event("afk", 1800, timestamp=big_afk_start)
    builder.add_split_ask_away_events(
        [("dinner", 900), ("dishwash", 900)],
        timestamp=big_afk_start,
    )

    # Return to work after big AFK: t0+2410 .. t0+2710
    builder.add_window_event("vscode", "work.py", 300, timestamp=t0 + td(seconds=2410))
    builder.add_afk_event("not-afk", 300, timestamp=t0 + td(seconds=2410))

    data = builder.build()

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]
    all_tags_in_commands = [tag for cmd in start_commands for tag in cmd]

    assert "dinner" in all_tags_in_commands, (
        f"Expected 'dinner' tag from split ask-away in commands: {start_commands}"
    )
    assert "dishwash" in all_tags_in_commands, (
        f"Expected 'dishwash' tag from split ask-away in commands: {start_commands}"
    )
