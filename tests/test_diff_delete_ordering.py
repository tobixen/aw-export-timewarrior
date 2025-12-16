"""Test that diff generates delete commands in correct order to avoid ID shifting issues."""

from datetime import UTC, datetime

from aw_export_timewarrior.compare import (
    SuggestedInterval,
    TimewInterval,
    compare_intervals,
    generate_fix_commands,
)


def test_extra_intervals_not_deleted() -> None:
    """Test that extra intervals are NOT deleted but instead listed in comments.

    The behavior changed to preserve continuous tracking by not deleting extra
    intervals. The :adjust flag on track commands handles boundary adjustments.
    """
    # Create timew intervals with increasing IDs
    # These represent "extra" intervals (in TimeWarrior but not ActivityWatch)
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

    # No suggested intervals (all timew intervals have ~aw so they're "previously_synced")
    suggested_intervals = []

    # Compare - all timew intervals should be marked as "previously_synced" (they have ~aw tag)
    comparison = compare_intervals(timew_intervals, suggested_intervals)

    assert (
        len(comparison["previously_synced"]) == 3
    ), "All 3 intervals should be marked as previously_synced"
    assert len(comparison["extra"]) == 0
    assert len(comparison["matching"]) == 0
    assert len(comparison["missing"]) == 0
    assert len(comparison["different_tags"]) == 0

    # Generate fix commands
    commands = generate_fix_commands(comparison)

    # Verify NO delete commands are generated
    delete_commands = [cmd for cmd in commands if cmd.startswith("timew delete")]
    assert (
        len(delete_commands) == 0
    ), f"Expected 0 delete commands (previously synced intervals are ignored), got {len(delete_commands)}"

    # Verify no commands are generated for previously_synced intervals (they're already synced)
    # Previously synced intervals with ~aw tag are from previous runs and should be left alone
    assert len(commands) == 0, "Expected no commands for previously_synced intervals"

    print("✓ Previously synced intervals correctly ignored (no commands generated)")


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


def test_mixed_commands_track_then_retag() -> None:
    """Test that when we have track and retag commands, they're in the right order.

    The order should be:
    1. track (creates new intervals)
    2. retag (modifies existing intervals)
    3. extra intervals documented in comments (not deleted)

    This ensures we don't have ordering issues.
    """
    # Timew has: @100 (extra), @101 (needs retag)
    timew_intervals = [
        TimewInterval(
            id=100,
            start=datetime(2025, 12, 15, 12, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 12, 5, 0, tzinfo=UTC),
            tags={"extra-interval", "~aw"},
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

    # Verify we have track and retag, but NO delete
    assert len(track_cmds) == 1, "Should have 1 track command"
    assert len(retag_cmds) == 1, "Should have 1 retag command"
    assert len(delete_cmds) == 0, "Should have 0 delete commands (extra intervals preserved)"

    # Verify order: track < retag
    assert track_cmds[0] < retag_cmds[0], (
        "Commands must be ordered: track, then retag. "
        f"Got indices: track={track_cmds[0]}, retag={retag_cmds[0]}"
    )

    # Verify previously_synced interval (@100 with ~aw tag) doesn't generate commands
    # It's from a previous sync and should be left alone
    assert len(comparison["previously_synced"]) == 1, "Should have 1 previously_synced interval"
    assert comparison["previously_synced"][0].id == 100, "Interval @100 should be previously_synced"

    print("✓ Mixed commands in correct order: track → retag, previously_synced ignored")
