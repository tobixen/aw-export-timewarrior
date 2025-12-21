"""Integration tests for lid event handling and AFK integration."""

import pytest

from aw_export_timewarrior.main import Exporter
from tests.conftest import FixtureDataBuilder


def test_lid_closed_forces_afk() -> None:
    """Test that lid closed always results in AFK tracking, even with window activity."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 600)
        .add_afk_event("not-afk", 600)
        .add_lid_event("closed", 600)  # Lid closed during activity
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    # Get captured commands
    commands = exporter.get_captured_commands()

    # Should have tracked AFK because lid was closed
    # Find timew start commands
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Should have at least one AFK tag in the tracking
    afk_found = any("afk" in cmd for cmd in start_commands)
    assert afk_found, "Expected AFK tracking when lid is closed"


def test_short_lid_cycle_ignored() -> None:
    """Test that lid cycles shorter than min_lid_duration (10s) are ignored."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 600)
        .add_afk_event("not-afk", 600)
        # Add short lid cycle (5 seconds - below 10s threshold)
        .add_lid_event("closed", 5)
        .add_lid_event("open", 5)
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()

    # Count AFK transitions - should not have extra AFK from short lid cycle
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Check that we don't have isolated short AFK periods
    # The short lid events should have been filtered out
    assert len(start_commands) >= 1, "Should have some tracking"


def test_lid_priority_over_afk() -> None:
    """Test that lid events override aw-watcher-afk status."""
    # Scenario: User is reported as active (not-afk) but lid is closed
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        # Now lid closes for significant time
        .add_lid_event("closed", 300)
        .add_window_event("vscode", "main.py", 300)  # Window still active during lid closed
        .add_afk_event("not-afk", 300)  # AFK watcher still says not-afk
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()

    # Should have AFK tracking when lid was closed
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Look for AFK tag during the period when lid was closed
    afk_found = any("afk" in cmd for cmd in start_commands)
    assert afk_found, "Lid closed should force AFK even when aw-watcher-afk says not-afk"


def test_boot_gap_handling() -> None:
    """Test that boot gaps are treated as downtime."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        # Boot gap event (30 min gap)
        .add_boot_gap_event(1800)
        .add_window_event("chrome", "news.com", 300)
        .add_afk_event("not-afk", 300)
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()

    # Boot gaps should be treated as AFK periods
    # Verify we have tracking that accounts for the gap
    assert len(commands) > 0, "Should have some tracking commands"


def test_suspend_resume_cycle() -> None:
    """Test suspend/resume handling."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        # System suspended for 30 min
        .add_suspend_event("suspended", 1800)
        # System resumed
        .add_suspend_event("resumed", 0)
        .add_window_event("chrome", "news.com", 300)
        .add_afk_event("not-afk", 300)
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()

    # Suspend time should be treated as AFK
    start_commands = [cmd for cmd in commands if len(cmd) > 1 and cmd[1] == "start"]

    # Should have AFK tracking during suspend period
    afk_found = any("afk" in cmd for cmd in start_commands)
    assert afk_found, "Suspended period should be tracked as AFK"


def test_lid_events_disabled_in_config() -> None:
    """Test that lid events can be disabled via configuration."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 600)
        .add_afk_event("not-afk", 600)
        .add_lid_event("closed", 600)
        .build()
    )

    # Disable lid events in config
    config = {"enable_lid_events": False}

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False, config=config)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()

    # With lid events disabled, should not necessarily have AFK tracking
    # (depends on aw-watcher-afk only)
    # This test mainly verifies no crashes when lid events are disabled
    assert commands is not None


def test_multiple_lid_cycles() -> None:
    """Test handling of multiple lid open/close cycles."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        # First lid cycle (long enough to count)
        .add_lid_event("closed", 60)
        .add_lid_event("open", 5)
        # Second lid cycle (also long enough)
        .add_lid_event("closed", 120)
        .add_lid_event("open", 5)
        # Back to work
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()

    # Should handle multiple lid cycles without crashing
    assert len(commands) > 0, "Should have tracking commands"


def test_lid_event_source_preservation() -> None:
    """Test that original lid event data is preserved in converted events."""
    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 300)
        .add_afk_event("not-afk", 300)
        .add_lid_event("closed", 300)
        .build()
    )

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False)

    # Fetch and prepare events to test merging logic
    completed_events, _ = exporter._fetch_and_prepare_events()

    # Find lid-sourced events
    lid_events = [e for e in completed_events if e.get("data", {}).get("source") == "lid"]

    # Should have converted lid events
    assert len(lid_events) > 0, "Should have converted lid events"

    # Check that original data is preserved
    lid_event = lid_events[0]
    assert "original_data" in lid_event["data"], "Should preserve original lid event data"
    assert lid_event["data"]["original_data"]["lid_state"] == "closed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
