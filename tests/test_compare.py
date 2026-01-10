"""Tests for compare mode functionality."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aw_export_timewarrior.compare import (
    SuggestedInterval,
    TimewInterval,
    compare_intervals,
    format_diff_output,
    generate_fix_commands,
    merge_consecutive_intervals,
)


class TestTimewInterval:
    """Tests for TimewInterval class."""

    def test_overlaps_true(self) -> None:
        """Test that overlapping intervals are detected."""
        int1 = TimewInterval(
            id=1,
            start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
            tags={"tag1"},
        )
        int2 = TimewInterval(
            id=2,
            start=datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC),
            end=datetime(2025, 1, 1, 11, 30, 0, tzinfo=UTC),
            tags={"tag2"},
        )
        assert int1.overlaps(int2)
        assert int2.overlaps(int1)

    def test_overlaps_false(self) -> None:
        """Test that non-overlapping intervals are detected."""
        int1 = TimewInterval(
            id=1,
            start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
            tags={"tag1"},
        )
        int2 = TimewInterval(
            id=2,
            start=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
            end=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            tags={"tag2"},
        )
        assert not int1.overlaps(int2)
        assert not int2.overlaps(int1)

    def test_duration(self) -> None:
        """Test duration calculation."""
        interval = TimewInterval(
            id=1,
            start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            end=datetime(2025, 1, 1, 11, 30, 0, tzinfo=UTC),
            tags={"tag1"},
        )
        assert interval.duration() == timedelta(hours=1, minutes=30)


class TestMergeConsecutiveIntervals:
    """Tests for merge_consecutive_intervals function."""

    def test_merge_consecutive_with_same_tags(self) -> None:
        """Test that consecutive intervals with identical tags are merged."""
        intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 10, 15, 0, tzinfo=UTC),
                tags={"4work", "python", "~aw"},
            ),
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 15, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC),
                tags={"4work", "python", "~aw"},
            ),
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 10, 45, 0, tzinfo=UTC),
                tags={"4work", "python", "~aw"},
            ),
        ]

        merged = merge_consecutive_intervals(intervals)

        assert len(merged) == 1
        assert merged[0].start == datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        assert merged[0].end == datetime(2025, 1, 1, 10, 45, 0, tzinfo=UTC)
        assert merged[0].tags == {"4work", "python", "~aw"}

    def test_no_merge_different_tags(self) -> None:
        """Test that intervals with different tags are not merged."""
        intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 10, 15, 0, tzinfo=UTC),
                tags={"4work", "python", "~aw"},
            ),
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 15, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC),
                tags={"4work", "java", "~aw"},  # Different tag
            ),
        ]

        merged = merge_consecutive_intervals(intervals)

        assert len(merged) == 2
        assert merged[0].tags == {"4work", "python", "~aw"}
        assert merged[1].tags == {"4work", "java", "~aw"}

    def test_no_merge_non_consecutive(self) -> None:
        """Test that non-consecutive intervals are not merged."""
        intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 10, 15, 0, tzinfo=UTC),
                tags={"4work", "python", "~aw"},
            ),
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 20, 0, tzinfo=UTC),  # Gap of 5 minutes
                end=datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC),
                tags={"4work", "python", "~aw"},
            ),
        ]

        merged = merge_consecutive_intervals(intervals)

        assert len(merged) == 2

    def test_mixed_scenario(self) -> None:
        """Test a mixed scenario with some mergeable and some not."""
        intervals = [
            # These two should merge
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 10, 15, 0, tzinfo=UTC),
                tags={"4work", "python", "~aw"},
            ),
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 15, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC),
                tags={"4work", "python", "~aw"},
            ),
            # This one has different tags, so starts a new group
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 10, 45, 0, tzinfo=UTC),
                tags={"4work", "java", "~aw"},
            ),
            # These two should merge with each other
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 45, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4me", "browsing", "~aw"},
            ),
            SuggestedInterval(
                start=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 15, 0, tzinfo=UTC),
                tags={"4me", "browsing", "~aw"},
            ),
        ]

        merged = merge_consecutive_intervals(intervals)

        assert len(merged) == 3
        # First merged interval: 10:00 - 10:30
        assert merged[0].start == datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        assert merged[0].end == datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC)
        assert merged[0].tags == {"4work", "python", "~aw"}
        # Second interval: 10:30 - 10:45 (different tags)
        assert merged[1].start == datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC)
        assert merged[1].end == datetime(2025, 1, 1, 10, 45, 0, tzinfo=UTC)
        assert merged[1].tags == {"4work", "java", "~aw"}
        # Third merged interval: 10:45 - 11:15
        assert merged[2].start == datetime(2025, 1, 1, 10, 45, 0, tzinfo=UTC)
        assert merged[2].end == datetime(2025, 1, 1, 11, 15, 0, tzinfo=UTC)
        assert merged[2].tags == {"4me", "browsing", "~aw"}

    def test_empty_list(self) -> None:
        """Test that an empty list returns an empty list."""
        merged = merge_consecutive_intervals([])
        assert merged == []

    def test_single_interval(self) -> None:
        """Test that a single interval is returned unchanged."""
        intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4work", "python", "~aw"},
            )
        ]

        merged = merge_consecutive_intervals(intervals)

        assert len(merged) == 1
        assert merged[0].start == intervals[0].start
        assert merged[0].end == intervals[0].end
        assert merged[0].tags == intervals[0].tags


class TestCompareIntervals:
    """Tests for interval comparison logic."""

    def test_perfect_match(self) -> None:
        """Test intervals that match perfectly."""
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4work", "python", "not-afk"},
            )
        ]
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4work", "python", "not-afk"},
            )
        ]

        result = compare_intervals(timew_intervals, suggested_intervals)

        assert len(result["matching"]) == 1
        assert len(result["different_tags"]) == 0
        assert len(result["missing"]) == 0
        assert len(result["extra"]) == 0

    def test_different_tags(self) -> None:
        """Test intervals with different tags."""
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4work", "python"},
            )
        ]
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4work", "javascript"},  # Different tag
            )
        ]

        result = compare_intervals(timew_intervals, suggested_intervals)

        assert len(result["matching"]) == 0
        assert len(result["different_tags"]) == 1
        assert len(result["missing"]) == 0
        assert len(result["extra"]) == 0

    def test_missing_interval(self) -> None:
        """Test suggested interval missing from timew."""
        timew_intervals = []
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4work", "python"},
            )
        ]

        result = compare_intervals(timew_intervals, suggested_intervals)

        assert len(result["matching"]) == 0
        assert len(result["different_tags"]) == 0
        assert len(result["missing"]) == 1
        assert len(result["extra"]) == 0

    def test_extra_interval(self) -> None:
        """Test interval in timew but not suggested."""
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4work", "python"},
            )
        ]
        suggested_intervals = []

        result = compare_intervals(timew_intervals, suggested_intervals)

        assert len(result["matching"]) == 0
        assert len(result["different_tags"]) == 0
        assert len(result["missing"]) == 0
        assert len(result["extra"]) == 1

    def test_complex_scenario(self) -> None:
        """Test a complex scenario with multiple types of differences."""
        timew_intervals = [
            # This one matches
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4work", "python"},
            ),
            # This one has different tags
            TimewInterval(
                id=2,
                start=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
                tags={"4work", "java"},
            ),
            # This one is extra
            TimewInterval(
                id=3,
                start=datetime(2025, 1, 1, 13, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 14, 0, 0, tzinfo=UTC),
                tags={"manual-entry"},
            ),
        ]

        suggested_intervals = [
            # Matches first timew interval
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4work", "python"},
            ),
            # Different tags from second timew interval
            SuggestedInterval(
                start=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
                tags={"4work", "python"},  # Different from timew
            ),
            # Missing from timew
            SuggestedInterval(
                start=datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 13, 0, 0, tzinfo=UTC),
                tags={"4me", "browsing"},
            ),
        ]

        result = compare_intervals(timew_intervals, suggested_intervals)

        # The algorithm matches overlapping intervals (using < not <=, so touching doesn't count):
        # - First pair: perfect match (10-11)
        # - Second pair: different tags (11-12)
        # - Third pair: timew (13-14) and suggested (12-13) only TOUCH, don't overlap
        # So we get 1 matching, 1 different_tags, 1 missing (12-13), 1 extra (13-14)
        assert len(result["matching"]) == 1
        assert len(result["different_tags"]) == 1
        assert len(result["missing"]) == 1  # Suggested 12-13 not matched
        assert len(result["extra"]) == 1  # Timew 13-14 not matched


class TestFormatDiffOutput:
    """Tests for diff output formatting."""

    def test_format_empty_comparison(self) -> None:
        """Test formatting with no differences."""
        comparison = {
            "matching": [],
            "different_tags": [],
            "missing": [],
            "extra": [],
            "previously_synced": [],
        }

        output = format_diff_output(comparison, verbose=False)

        assert "Summary:" in output
        assert "Matching intervals:" in output
        assert "0" in output

    def test_format_with_differences(self) -> None:
        """Test formatting with differences."""
        missing_start = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        missing_end = datetime(2025, 1, 1, 13, 0, 0, tzinfo=UTC)

        comparison = {
            "matching": [
                (
                    TimewInterval(
                        id=1,
                        start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                        tags={"4work"},
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                        tags={"4work"},
                    ),
                )
            ],
            "different_tags": [],
            "missing": [SuggestedInterval(start=missing_start, end=missing_end, tags={"4me"})],
            "extra": [],
            "previously_synced": [],
        }

        output = format_diff_output(comparison, verbose=False)

        assert "Matching intervals:" in output and "1" in output
        assert "Missing from TimeWarrior:" in output and "1" in output
        # Times are now displayed in local time, so convert for assertion
        expected_time = f"{missing_start.astimezone().strftime('%H:%M:%S')} - {missing_end.astimezone().strftime('%H:%M:%S')}"
        assert expected_time in output  # Missing interval time (in local time)


class TestGenerateFixCommands:
    """Tests for fix command generation."""

    def test_generate_track_command_for_missing(self) -> None:
        """Test that missing intervals generate track commands."""
        comparison = {
            "matching": [],
            "different_tags": [],
            "missing": [
                SuggestedInterval(
                    start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=UTC),
                    end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=UTC),
                    tags={"4work", "python", "~aw"},
                )
            ],
            "extra": [],
        }

        commands = generate_fix_commands(comparison)

        assert len(commands) == 1
        assert commands[0].startswith("timew track")
        assert "4work" in commands[0]
        assert "python" in commands[0]
        assert "~aw" in commands[0]
        assert ":adjust" in commands[0]

    def test_generate_track_adjust_for_different_tags(self) -> None:
        """Test that intervals with different tags use track :adjust instead of retag."""
        comparison = {
            "matching": [],
            "different_tags": [
                (
                    TimewInterval(
                        id=42,
                        start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=UTC),
                        tags={"4work", "java", "~aw"},  # Has ~aw tag (auto-generated)
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=UTC),
                        tags={"4work", "python", "~aw"},
                    ),
                )
            ],
            "missing": [],
            "extra": [],
        }

        commands = generate_fix_commands(comparison)

        assert len(commands) == 1
        # Should use track :adjust (not retag)
        assert "timew track" in commands[0]
        assert ":adjust" in commands[0]
        assert "4work" in commands[0]
        assert "python" in commands[0]
        assert "~aw" in commands[0]

    def test_track_adjust_for_manual_entries(self) -> None:
        """Test that manual entries (without ~aw) generate commented commands."""
        comparison = {
            "matching": [],
            "different_tags": [
                (
                    TimewInterval(
                        id=99,
                        start=datetime(2025, 12, 10, 14, 30, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 15, 0, 0, tzinfo=UTC),
                        tags={"manual", "meeting"},  # NO ~aw tag (manually entered)
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 12, 10, 14, 30, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 15, 0, 0, tzinfo=UTC),
                        tags={"4work", "meeting", "~aw"},
                    ),
                )
            ],
            "missing": [],
            "extra": [],
        }

        commands = generate_fix_commands(comparison)

        # Manual entries should generate COMMENTED commands (not executable)
        # Format: empty line, header, commented track command, commented current tags
        assert len(commands) == 4
        assert commands[0] == ""
        assert "Manually edited" in commands[1]
        # The track command should be commented out
        assert commands[2].startswith("# timew track")
        assert "4work" in commands[2]
        assert "meeting" in commands[2]
        # Should show current tags
        assert "(current:" in commands[3]

    def test_multiple_commands_mixed(self) -> None:
        """Test generating multiple track commands for different intervals."""
        comparison = {
            "matching": [],
            "different_tags": [
                # Auto-generated (has ~aw) - should generate executable command
                (
                    TimewInterval(
                        id=1,
                        start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=UTC),
                        tags={"old-tag", "~aw"},
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=UTC),
                        tags={"new-tag", "~aw"},
                    ),
                ),
                # Manual entry (no ~aw) - should generate COMMENTED command
                (
                    TimewInterval(
                        id=2,
                        start=datetime(2025, 12, 10, 11, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 12, 0, 0, tzinfo=UTC),
                        tags={"manual"},
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 12, 10, 11, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 12, 0, 0, tzinfo=UTC),
                        tags={"auto", "~aw"},
                    ),
                ),
            ],
            "missing": [
                SuggestedInterval(
                    start=datetime(2025, 12, 10, 12, 0, 0, tzinfo=UTC),
                    end=datetime(2025, 12, 10, 13, 0, 0, tzinfo=UTC),
                    tags={"missing", "~aw"},
                )
            ],
            "extra": [],
        }

        commands = generate_fix_commands(comparison)

        # Should have:
        # - 2 executable track commands (for ~aw interval and missing interval)
        # - 4 lines for manual entry (empty, header, commented command, current tags)
        executable_commands = [c for c in commands if c.strip() and not c.startswith("#")]
        commented_commands = [c for c in commands if c.startswith("#")]

        assert len(executable_commands) == 2, (
            f"Expected 2 executable commands, got {executable_commands}"
        )
        assert len(commented_commands) >= 2, "Expected commented section for manual entry"

        # Executable commands should be track :adjust
        for cmd in executable_commands:
            assert "timew track" in cmd
            assert ":adjust" in cmd

    def test_generate_delete_command_for_extra_auto(self) -> None:
        """Test that extra auto-generated intervals get delete commands."""
        comparison = {
            "matching": [],
            "different_tags": [],
            "missing": [],
            "extra": [
                TimewInterval(
                    id=42,
                    start=datetime(2025, 12, 10, 14, 0, 0, tzinfo=UTC),
                    end=datetime(2025, 12, 10, 15, 0, 0, tzinfo=UTC),
                    tags={"UNKNOWN", "not-afk", "~aw"},
                )
            ],
        }

        commands = generate_fix_commands(comparison)

        # Should generate informational comments (no delete commands)
        assert len(commands) == 3  # Empty line + header + interval info
        assert commands[0] == ""
        assert "Extra intervals" in commands[1]
        assert "@42" in commands[2]
        assert "UNKNOWN" in commands[2]

    def test_generate_delete_command_for_extra_manual(self) -> None:
        """Test that extra manually-entered intervals are listed as comments."""
        comparison = {
            "matching": [],
            "different_tags": [],
            "missing": [],
            "extra": [
                TimewInterval(
                    id=99,
                    start=datetime(2025, 12, 10, 16, 0, 0, tzinfo=UTC),
                    end=datetime(2025, 12, 10, 17, 0, 0, tzinfo=UTC),
                    tags={"manual-work", "meeting"},  # No ~aw tag
                )
            ],
        }

        commands = generate_fix_commands(comparison)

        # Should generate informational comments (no delete commands)
        assert len(commands) == 3
        assert commands[0] == ""
        assert "Extra intervals" in commands[1]
        assert "@99" in commands[2]
        assert "manual-work" in commands[2]

    def test_generate_delete_commands_mixed(self) -> None:
        """Test generating informational comments for both auto and manual extra intervals."""
        comparison = {
            "matching": [],
            "different_tags": [],
            "missing": [],
            "extra": [
                # Auto-generated
                TimewInterval(
                    id=1,
                    start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=UTC),
                    end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=UTC),
                    tags={"auto", "~aw"},
                ),
                # Manual
                TimewInterval(
                    id=2,
                    start=datetime(2025, 12, 10, 11, 0, 0, tzinfo=UTC),
                    end=datetime(2025, 12, 10, 12, 0, 0, tzinfo=UTC),
                    tags={"manual"},
                ),
            ],
        }

        commands = generate_fix_commands(comparison)

        # Should generate informational comments listing both intervals
        assert len(commands) == 4  # Empty line + header + 2 interval infos
        assert commands[0] == ""
        assert "Extra intervals" in commands[1]
        # Should list both intervals (sorted by start time)
        assert "@1" in commands[2] or "@1" in commands[3]
        assert "@2" in commands[2] or "@2" in commands[3]

    def test_generate_commands_with_only_extra_intervals(self) -> None:
        """Test that commands with only extra intervals contain comments/empty lines.

        This reproduces the bug where --apply would crash with 'list index out of range'
        when trying to execute empty command strings.
        """
        comparison = {
            "matching": [],
            "different_tags": [],
            "missing": [],
            "extra": [
                TimewInterval(
                    id=123,
                    start=datetime(2025, 12, 11, 10, 0, 0, tzinfo=UTC),
                    end=datetime(2025, 12, 11, 11, 0, 0, tzinfo=UTC),
                    tags={"4work", "python", "~aw"},
                )
            ],
        }

        commands = generate_fix_commands(comparison)

        # Should contain comments about extra intervals but no executable commands
        assert len(commands) > 0
        # Should have at least one empty line and comment lines
        assert any(cmd.strip() == "" for cmd in commands)
        assert any(cmd.startswith("#") for cmd in commands)
        # Should NOT have any executable commands (non-empty, non-comment lines)
        executable_commands = [cmd for cmd in commands if cmd.strip() and not cmd.startswith("#")]
        assert len(executable_commands) == 0

    def test_manual_entries_without_aw_tag_are_commented(self) -> None:
        """Test that intervals without ~aw tag generate commented commands.

        When a TimeWarrior interval doesn't have the ~aw tag, it means it was
        manually edited/created. The diff command should show these intervals
        but generate COMMENTED commands (prefixed with #) so they are not
        automatically applied.

        This is a regression test for the behavior where manually edited entries
        should be shown but not overwritten.
        """
        # TimeWarrior has an interval WITHOUT ~aw (manually edited)
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4OSS", "epoxy-calc", "not-afk"},  # No ~aw tag = manually edited
            )
        ]
        # ActivityWatch suggests different tags
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4RL", "båtvedlikehold", "epoxy", "not-afk", "~aw"},
            )
        ]

        # Compare should detect the difference
        result = compare_intervals(timew_intervals, suggested_intervals)
        assert len(result["different_tags"]) == 1, "Should detect different tags"

        # Generate fix commands
        commands = generate_fix_commands(result)

        # The command for the manual entry should be COMMENTED
        # (prefixed with #) because the original interval doesn't have ~aw
        executable_commands = [cmd for cmd in commands if cmd.strip() and not cmd.startswith("#")]
        commented_commands = [cmd for cmd in commands if cmd.startswith("#")]

        assert len(executable_commands) == 0, (
            f"Manual entries (without ~aw) should NOT generate executable commands. "
            f"Found: {executable_commands}"
        )
        assert any("timew track" in cmd or "10:00" in cmd for cmd in commented_commands), (
            f"Should have a commented command showing what would be done. Commands: {commands}"
        )

    def test_aw_tagged_entries_generate_executable_commands(self) -> None:
        """Test that intervals WITH ~aw tag generate executable commands.

        Intervals with ~aw tag were created by aw-export-timewarrior and can
        be safely retagged when the suggested tags differ.
        """
        # TimeWarrior has an interval WITH ~aw (previously synced)
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4OSS", "epoxy-calc", "not-afk", "~aw"},  # Has ~aw tag
            )
        ]
        # ActivityWatch suggests different tags
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
                tags={"4RL", "båtvedlikehold", "epoxy", "not-afk", "~aw"},
            )
        ]

        # Compare should detect the difference
        result = compare_intervals(timew_intervals, suggested_intervals)
        assert len(result["different_tags"]) == 1, "Should detect different tags"

        # Generate fix commands
        commands = generate_fix_commands(result)

        # The command should be EXECUTABLE (not commented)
        # because the original interval has ~aw tag
        executable_commands = [cmd for cmd in commands if cmd.strip() and not cmd.startswith("#")]

        assert len(executable_commands) >= 1, (
            f"Entries with ~aw should generate executable commands. Commands: {commands}"
        )
        assert any("timew track" in cmd for cmd in executable_commands), (
            f"Should have a timew track command. Commands: {commands}"
        )

    def test_retag_rules_applied_to_manual_entries(self, tmp_path: Path) -> None:
        """Test that retag rules are applied to derive additional tags for manual entries.

        If a user manually adds 'bedtime' to an interval, and there's a retag rule
        that 'bedtime' implies '4BREAK', the diff should generate a command to add
        '4BREAK' to the interval.
        """
        from unittest.mock import patch

        # TimeWarrior has an interval with manually added 'bedtime' (no ~aw tag)
        comparison = {
            "matching": [],
            "different_tags": [
                (
                    TimewInterval(
                        id=42,
                        start=datetime(2025, 12, 10, 22, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 23, 0, 0, tzinfo=UTC),
                        tags={"afk", "bedtime"},  # NO ~aw - manually edited
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 12, 10, 22, 0, 0, tzinfo=UTC),
                        end=datetime(2025, 12, 10, 23, 0, 0, tzinfo=UTC),
                        tags={"afk"},  # AW suggests just "afk"
                    ),
                )
            ],
            "missing": [],
            "extra": [],
        }

        # Create a mock retag_by_rules that adds 4BREAK when bedtime is present
        def mock_retag_by_rules(tags, config):
            result = set(tags)
            if "bedtime" in tags:
                result.add("4BREAK")
            return result

        # Patch retag_by_rules in the main module (where it's imported from)
        with patch("aw_export_timewarrior.main.retag_by_rules", side_effect=mock_retag_by_rules):
            commands = generate_fix_commands(comparison)

        # Should have an executable command to add derived tags
        executable_commands = [c for c in commands if c.strip() and not c.startswith("#")]
        commented_commands = [c for c in commands if c.startswith("#")]

        # The commented part should show the manual entry with suggestion
        assert any("Manually edited" in c for c in commented_commands), (
            f"Should mention manually edited intervals. Commands: {commands}"
        )
        assert any("bedtime" in c for c in commands), (
            f"Should show bedtime tag somewhere. Commands: {commands}"
        )

        # Should have an executable 'timew tag' command to add 4BREAK
        assert any("timew tag" in c and "4BREAK" in c for c in executable_commands), (
            f"Should have an executable 'timew tag' command to add derived tag 4BREAK. "
            f"Executable commands: {executable_commands}"
        )
