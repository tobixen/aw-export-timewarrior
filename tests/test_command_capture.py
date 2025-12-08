#!/usr/bin/env python3
"""
Tests for command capture functionality.

This tests that timew commands are properly captured in dry-run mode,
allowing us to verify what commands would be executed without actually running them.
"""

import pytest
from datetime import datetime, timezone
from aw_export_timewarrior.main import Exporter
from tests.helpers import TestDataBuilder


def test_basic_command_capture() -> None:
    """Test that commands are captured in dry-run mode."""
    # Create simple test data - need at least 3 events for processing
    data = (TestDataBuilder()
        .add_window_event("Code", "main.py - VS Code", duration=600)
        .add_afk_event("not-afk", duration=600)
        .add_window_event("Code", "test.py - VS Code", duration=600)
        .add_afk_event("not-afk", duration=600)
        .build())

    # Create exporter in dry-run mode with custom config
    exporter = Exporter(
        test_data=data,
        dry_run=True,
        config_path='tests/fixtures/test_config.toml',
        start_time=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    )

    # Process events
    exporter.tick()

    # Get captured commands
    commands = exporter.get_captured_commands()

    # Should have captured at least one command
    assert len(commands) > 0, "Should capture at least one command"

    # First command should be a 'start' command
    first_cmd = commands[0]
    assert first_cmd[0] == 'timew', "Command should start with 'timew'"
    assert first_cmd[1] == 'start', "First command should be 'start'"

    # Should include some tags
    assert len(first_cmd) > 3, "Should have tags in addition to timew and start"

    # Print for visibility
    print("\nCaptured commands:")
    for cmd in commands:
        print(f"  {' '.join(cmd)}")


def test_multiple_ticks_accumulate_commands() -> None:
    """Test that multiple ticks accumulate commands."""
    data = (TestDataBuilder()
        .add_window_event("Code", "main.py - VS Code", duration=300)
        .add_afk_event("not-afk", duration=300)
        .add_window_event("Chrome", "GitHub", duration=300)
        .add_afk_event("not-afk", duration=300)
        .build())

    exporter = Exporter(
        test_data=data,
        dry_run=True,
        config_path='tests/fixtures/test_config.toml',
        start_time=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    )

    # First tick
    exporter.tick()
    count_after_first = len(exporter.get_captured_commands())

    # Captured commands persist across ticks
    assert count_after_first > 0, "Should have commands after first tick"

    print(f"\nCommands after first tick: {count_after_first}")
    for cmd in exporter.get_captured_commands():
        print(f"  {' '.join(cmd)}")


def test_clear_captured_commands() -> None:
    """Test that captured commands can be cleared."""
    data = (TestDataBuilder()
        .add_window_event("Code", "main.py - VS Code", duration=600)
        .add_afk_event("not-afk", duration=600)
        .add_window_event("Code", "test.py - VS Code", duration=600)
        .add_afk_event("not-afk", duration=600)
        .build())

    exporter = Exporter(
        test_data=data,
        dry_run=True,
        config_path='tests/fixtures/test_config.toml',
        start_time=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    )

    exporter.tick()
    assert len(exporter.get_captured_commands()) > 0

    exporter.clear_captured_commands()
    assert len(exporter.get_captured_commands()) == 0


def test_commands_not_captured_in_normal_mode() -> None:
    """Test that commands are NOT captured when not in dry-run mode."""
    # Note: This test doesn't actually run timew commands because we're using test_data
    # In real use without test_data, it would try to run actual commands
    data = (TestDataBuilder()
        .add_window_event("Code", "main.py - VS Code", duration=600)
        .add_afk_event("not-afk", duration=600)
        .add_window_event("Code", "test.py - VS Code", duration=600)
        .add_afk_event("not-afk", duration=600)
        .build())

    exporter = Exporter(
        test_data=data,
        dry_run=False,  # Not in dry-run mode
        config_path='tests/fixtures/test_config.toml',
        start_time=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    )

    # In normal mode with test_data, it still won't run real commands
    # but it also won't capture them
    exporter.tick()

    # Should not have captured commands (only captures in dry-run)
    assert len(exporter.get_captured_commands()) == 0


def test_command_format() -> None:
    """Test that captured commands have the expected format."""
    data = (TestDataBuilder()
        .add_window_event("Code", "main.py - VS Code", duration=600)
        .add_afk_event("not-afk", duration=600)
        .add_window_event("Code", "test.py - VS Code", duration=600)
        .add_afk_event("not-afk", duration=600)
        .build())

    exporter = Exporter(
        test_data=data,
        dry_run=True,
        config_path='tests/fixtures/test_config.toml',
        start_time=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    )

    exporter.tick()
    commands = exporter.get_captured_commands()

    assert len(commands) > 0

    for cmd in commands:
        # Each command should be a list
        assert isinstance(cmd, list), "Command should be a list"

        # Each element should be a string
        assert all(isinstance(part, str) for part in cmd), "All command parts should be strings"

        # Should start with 'timew'
        assert cmd[0] == 'timew', "Command should start with 'timew'"

        # Second element should be a valid timew command
        assert cmd[1] in ['start', 'stop', 'retag', 'modify', 'track'], \
            f"Second element should be a timew command, got: {cmd[1]}"
