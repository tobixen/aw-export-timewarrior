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

    assert len(comparison["previously_synced"]) == 3, (
        "All 3 intervals should be marked as previously_synced"
    )
    assert len(comparison["extra"]) == 0
    assert len(comparison["matching"]) == 0
    assert len(comparison["missing"]) == 0
    assert len(comparison["different_tags"]) == 0

    # Generate fix commands
    commands = generate_fix_commands(comparison)

    # Verify NO delete commands are generated
    delete_commands = [cmd for cmd in commands if cmd.startswith("timew delete")]
    assert len(delete_commands) == 0, (
        f"Expected 0 delete commands (previously synced intervals are ignored), got {len(delete_commands)}"
    )

    # Verify no commands are generated for previously_synced intervals (they're already synced)
    # Previously synced intervals with ~aw tag are from previous runs and should be left alone
    assert len(commands) == 0, "Expected no commands for previously_synced intervals"

    print("✓ Previously synced intervals correctly ignored (no commands generated)")


def test_track_adjust_for_different_tags() -> None:
    """Test that intervals with different tags now use track :adjust instead of retag."""
    # Create timew intervals with old tags
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

    # Should generate track :adjust commands (not retag)
    # Consecutive intervals with same tags get merged into one
    track_commands = [cmd for cmd in commands if cmd.startswith("timew track")]

    assert len(track_commands) == 1, (
        f"Expected 1 track command (consecutive intervals merged), got {len(track_commands)}"
    )

    # Should have :adjust flag and cover the full range
    cmd = track_commands[0]
    assert ":adjust" in cmd
    assert "new-tag" in cmd
    assert "~aw" in cmd
    # Merged command should cover 11:00-11:15
    assert "12:00:00" in cmd and "12:15:00" in cmd

    print("✓ Track :adjust command generated for different tags (consecutive intervals merged)")


def test_mixed_commands_all_track_adjust() -> None:
    """Test that all changes now use track :adjust (no retag).

    Now everything uses track :adjust:
    1. Missing intervals (gaps) get track commands
    2. Intervals with different tags get track commands
    3. Extra intervals documented in comments (not deleted)
    """
    # Timew has: @100 (previously synced), @101 (different tags)
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

    # Suggested: one interval with different tags, one new interval
    suggested_intervals = [
        SuggestedInterval(
            start=datetime(2025, 12, 15, 12, 5, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 12, 10, 0, tzinfo=UTC),
            tags={"new-tag", "~aw"},  # Different tags for @101
        ),
        SuggestedInterval(
            start=datetime(2025, 12, 15, 12, 10, 0, tzinfo=UTC),
            end=datetime(2025, 12, 15, 12, 15, 0, tzinfo=UTC),
            tags={"track-me", "~aw"},  # New interval (missing)
        ),
    ]

    comparison = compare_intervals(timew_intervals, suggested_intervals)

    commands = generate_fix_commands(comparison)

    # Classify commands
    track_cmds = [i for i, cmd in enumerate(commands) if cmd.startswith("timew track")]
    retag_cmds = [i for i, cmd in enumerate(commands) if cmd.startswith("timew retag")]
    delete_cmds = [i for i, cmd in enumerate(commands) if cmd.startswith("timew delete")]

    # All changes now use track :adjust
    assert len(track_cmds) == 2, f"Should have 2 track commands, got {len(track_cmds)}"
    assert len(retag_cmds) == 0, (
        f"Should have 0 retag commands (using track :adjust), got {len(retag_cmds)}"
    )
    assert len(delete_cmds) == 0, "Should have 0 delete commands (extra intervals preserved)"

    # Verify previously_synced interval (@100 with ~aw tag) doesn't generate commands
    # It's from a previous sync and should be left alone
    assert len(comparison["previously_synced"]) == 1, "Should have 1 previously_synced interval"
    assert comparison["previously_synced"][0].id == 100, "Interval @100 should be previously_synced"

    print("✓ All changes use track :adjust, previously_synced ignored")
