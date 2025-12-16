"""Integration tests for ask-away event handling."""

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
