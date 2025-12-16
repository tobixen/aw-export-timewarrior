"""Test that diff generates delete commands in correct order to avoid ID shifting issues."""

from datetime import UTC, datetime

from aw_export_timewarrior.compare import (
    SuggestedInterval,
    TimewInterval,
    compare_intervals,
    generate_fix_commands,
)


def test_delete_commands_ordered_by_reverse_id() -> None:
    """Test that delete commands are generated in reverse ID order.

    This is critical because when you delete an interval in TimeWarrior,
    all subsequent interval IDs shift down by 1. If we delete in forward
    order (e.g., @110, @111, @112), after deleting @110, interval @111
    becomes @110, so we end up deleting the wrong intervals.

    The fix is to delete in REVERSE order (@112, @111, @110) so that
    deleting a higher ID doesn't affect lower IDs.

    This test would FAIL before the fix (commands in wrong order) and
    PASS after the fix (commands in correct order).
    """
    # Create timew intervals with increasing IDs
    # These represent "extra" intervals that need to be deleted
    timew_intervals = [
        TimewInterval(
            id=110,
            start=datetime(2025, 12, 15, 10, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 10, 5, 0, tzinfo=UTC),
            tags={"old-tag", "~aw"},
        ),
        TimewInterval(
            id=111,
            start=datetime(2025, 12, 15, 10, 5, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 10, 10, 0, tzinfo=UTC),
            tags={"old-tag", "~aw"},
        ),
        TimewInterval(
            id=112,
            start=datetime(2025, 12, 15, 10, 10, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 10, 15, 0, tzinfo=UTC),
            tags={"old-tag", "~aw"},
        ),
    ]

    # No suggested intervals (we want to delete all timew intervals)
    suggested_intervals = []

    # Compare - all timew intervals should be marked as "extra"
    comparison = compare_intervals(timew_intervals, suggested_intervals)

    assert len(comparison["extra"]) == 3, "All 3 intervals should be marked as extra"
    assert len(comparison["matching"]) == 0
    assert len(comparison["missing"]) == 0
    assert len(comparison["different_tags"]) == 0

    # Generate fix commands
    commands = generate_fix_commands(comparison)

    # Extract delete commands (filter out any retag/track commands)
    delete_commands = [cmd for cmd in commands if cmd.startswith("timew delete")]

    assert len(delete_commands) == 3, f"Expected 3 delete commands, got {len(delete_commands)}"

    # Extract IDs from delete commands
    # Format: "timew delete @<id> :yes  # ..."
    ids = []
    for cmd in delete_commands:
        # Parse "@<id>" from command
        import re

        match = re.search(r"@(\d+)", cmd)
        assert match, f"Could not find @ID in command: {cmd}"
        ids.append(int(match.group(1)))

    print(f"\nDelete commands generated in order: {ids}")

    # CRITICAL ASSERTION: IDs must be in DESCENDING order (highest first)
    # This ensures that deleting @112 doesn't affect @111 and @110
    assert ids == [112, 111, 110], (
        f"Delete commands must be in REVERSE ID order (highest first)!\n"
        f"Got: {ids}\n"
        f"Expected: [112, 111, 110]\n"
        f"This prevents ID shifting when deleting intervals in TimeWarrior."
    )

    print("✓ Delete commands correctly ordered in reverse ID sequence")


def test_retag_commands_ordered_by_reverse_id() -> None:
    """Test that retag commands are also generated in reverse ID order.

    While retag doesn't delete intervals, sorting in reverse is still
    safer in case of any edge cases or future changes.
    """
    # Create timew intervals that need retagging
    timew_intervals = [
        TimewInterval(
            id=120,
            start=datetime(2025, 12, 15, 11, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 11, 5, 0, tzinfo=UTC),
            tags={"old-tag", "~aw"},
        ),
        TimewInterval(
            id=121,
            start=datetime(2025, 12, 15, 11, 5, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 11, 10, 0, tzinfo=UTC),
            tags={"old-tag", "~aw"},
        ),
        TimewInterval(
            id=122,
            start=datetime(2025, 12, 15, 11, 10, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 11, 15, 0, tzinfo=UTC),
            tags={"old-tag", "~aw"},
        ),
    ]

    # Create suggested intervals with different tags
    suggested_intervals = [
        SuggestedInterval(
            start=datetime(2025, 12, 15, 11, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 11, 5, 0, tzinfo=UTC),
            tags={"new-tag", "~aw"},
        ),
        SuggestedInterval(
            start=datetime(2025, 12, 15, 11, 5, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 11, 10, 0, tzinfo=UTC),
            tags={"new-tag", "~aw"},
        ),
        SuggestedInterval(
            start=datetime(2025, 12, 15, 11, 10, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 11, 15, 0, tzinfo=UTC),
            tags={"new-tag", "~aw"},
        ),
    ]

    # Compare - all intervals should have different tags
    comparison = compare_intervals(timew_intervals, suggested_intervals)

    assert len(comparison["different_tags"]) == 3
    assert len(comparison["matching"]) == 0
    assert len(comparison["missing"]) == 0
    assert len(comparison["extra"]) == 0

    # Generate fix commands
    commands = generate_fix_commands(comparison)

    # Extract retag commands
    retag_commands = [cmd for cmd in commands if cmd.startswith("timew retag")]

    assert len(retag_commands) == 3, f"Expected 3 retag commands, got {len(retag_commands)}"

    # Extract IDs from retag commands
    ids = []
    for cmd in retag_commands:
        import re

        match = re.search(r"@(\d+)", cmd)
        assert match, f"Could not find @ID in command: {cmd}"
        ids.append(int(match.group(1)))

    print(f"\nRetag commands generated in order: {ids}")

    # Retag commands should also be in descending order
    assert ids == [122, 121, 120], (
        f"Retag commands should be in REVERSE ID order for consistency!\n"
        f"Got: {ids}\n"
        f"Expected: [122, 121, 120]"
    )

    print("✓ Retag commands correctly ordered in reverse ID sequence")


def test_mixed_commands_delete_after_track_and_retag() -> None:
    """Test that when we have track, retag, and delete commands, they're in the right order.

    The order should be:
    1. track (creates new intervals)
    2. retag (modifies existing intervals)
    3. delete (removes intervals) - in reverse ID order

    This ensures we don't delete intervals before retagging them.
    """
    # Timew has: @100 (extra), @101 (needs retag)
    timew_intervals = [
        TimewInterval(
            id=100,
            start=datetime(2025, 12, 15, 12, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 12, 5, 0, tzinfo=UTC),
            tags={"to-delete", "~aw"},
        ),
        TimewInterval(
            id=101,
            start=datetime(2025, 12, 15, 12, 5, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 12, 10, 0, tzinfo=UTC),
            tags={"old-tag", "~aw"},
        ),
    ]

    # Suggested: one interval to retag, one new interval to track
    suggested_intervals = [
        SuggestedInterval(
            start=datetime(2025, 12, 15, 12, 5, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 12, 10, 0, tzinfo=UTC),
            tags={"new-tag", "~aw"},  # Retag @101
        ),
        SuggestedInterval(
            start=datetime(2025, 12, 15, 12, 10, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 12, 15, 0, tzinfo=UTC),
            tags={"track-me", "~aw"},  # New interval to track
        ),
    ]

    comparison = compare_intervals(timew_intervals, suggested_intervals)

    commands = generate_fix_commands(comparison)

    # Classify commands
    track_cmds = [i for i, cmd in enumerate(commands) if cmd.startswith("timew track")]
    retag_cmds = [i for i, cmd in enumerate(commands) if cmd.startswith("timew retag")]
    delete_cmds = [i for i, cmd in enumerate(commands) if cmd.startswith("timew delete")]

    # Verify we have all three types
    assert len(track_cmds) == 1, "Should have 1 track command"
    assert len(retag_cmds) == 1, "Should have 1 retag command"
    assert len(delete_cmds) == 1, "Should have 1 delete command"

    # Verify order: track < retag < delete
    assert track_cmds[0] < retag_cmds[0] < delete_cmds[0], (
        "Commands must be ordered: track, then retag, then delete. "
        f"Got indices: track={track_cmds[0]}, retag={retag_cmds[0]}, delete={delete_cmds[0]}"
    )

    print("✓ Mixed commands in correct order: track → retag → delete")
