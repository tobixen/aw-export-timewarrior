"""Test for AFK event overlap bug.

Reproduces issue where a long window event is not properly split by AFK periods.
"""

from datetime import UTC, datetime, timedelta

from aw_export_timewarrior.main import Exporter


def test_long_window_event_split_by_afk() -> None:
    """Test that a long window event is properly split when user goes AFK mid-event.

    Scenario:
    - 11:37:00 - 11:37:41: not-afk (41s)
    - 11:37:40 - 13:32:34: git log window event (1h54m54s)
    - 11:39:42 - 13:32:26: afk (1h52m44s)
    - 13:32:27 - 13:32:60: not-afk (33s)

    Expected behavior:
    - git log should be split into two parts:
      1. 11:37:40 - 11:39:42: git log + not-afk (2m2s)
      2. 11:39:42 - 13:32:26: afk (1h52m44s) - no window activity tracked
      3. 13:32:27 - 13:32:34: git log + not-afk (7s)

    Bug: Currently the entire git log event is being tracked as not-afk
    even though most of it overlaps with the AFK period.
    """
    # Create test data
    test_data = {
        "metadata": {
            "start_time": "2025-12-14T11:37:00+00:00",
            "end_time": "2025-12-14T13:33:00+00:00",
        },
        "events": {
            "aw-watcher-window_archlinux": [
                {
                    "id": 1,
                    "timestamp": datetime(2025, 12, 14, 11, 37, 40, tzinfo=UTC),
                    "duration": timedelta(seconds=6894),  # 1h54m54s until 13:32:34
                    "data": {"app": "foot", "title": "git log"},
                }
            ],
            "aw-watcher-afk_archlinux": [
                {
                    "id": 2,
                    "timestamp": datetime(2025, 12, 14, 11, 37, 0, tzinfo=UTC),
                    "duration": timedelta(seconds=41),  # Until 11:37:41
                    "data": {"status": "not-afk"},
                },
                {
                    "id": 3,
                    "timestamp": datetime(2025, 12, 14, 11, 39, 42, tzinfo=UTC),
                    "duration": timedelta(seconds=6764),  # 1h52m44s until 13:32:26
                    "data": {"status": "afk"},
                },
                {
                    "id": 4,
                    "timestamp": datetime(2025, 12, 14, 13, 32, 27, tzinfo=UTC),
                    "duration": timedelta(seconds=33),  # Until 13:33:00
                    "data": {"status": "not-afk"},
                },
            ],
        },
    }

    # Create exporter with test data
    exporter = Exporter(
        dry_run=True,
        test_data=test_data,
        start_time=datetime(2025, 12, 14, 11, 37, tzinfo=UTC),
        end_time=datetime(2025, 12, 14, 13, 33, tzinfo=UTC),
    )

    # Capture commands
    commands: list = []
    exporter.tracker.capture_commands = commands

    # Process events
    exporter.tick(process_all=True)

    # Expected tracking:
    # 1. Start with git log from 11:37:40
    # 2. At 11:39:42, go AFK - should stop git log tracking
    # 3. At 13:32:27, return from AFK - should resume git log tracking
    # 4. At 13:32:34, git log window event ends

    # Check that we have the expected commands
    # Should have at least 3 tracking periods:
    # 1. Initial activity before AFK
    # 2. AFK period
    # 3. Activity after returning from AFK

    print("\nCaptured commands:")
    for cmd in commands:
        print(f"  {' '.join(cmd)}")

    # Find the git log tracking commands (should be split by AFK)
    git_log_cmds = [cmd for cmd in commands if "git" in " ".join(cmd).lower()]
    afk_cmds = [cmd for cmd in commands if "afk" in " ".join(cmd)]

    print(f"\nGit log commands: {len(git_log_cmds)}")
    print(f"AFK commands: {len(afk_cmds)}")

    # Should have at least 1 AFK command
    assert len(afk_cmds) >= 1, f"Expected at least 1 AFK command, got {len(afk_cmds)}"

    # The git log activity should be interrupted by AFK
    # TODO: Add more specific assertions once we fix the bug
    # For now, this test documents the expected behavior
