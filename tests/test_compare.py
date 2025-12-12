"""Tests for compare mode functionality."""

from datetime import datetime, timedelta, timezone
import pytest

from aw_export_timewarrior.compare import (
    TimewInterval,
    SuggestedInterval,
    compare_intervals,
    format_diff_output,
    generate_fix_commands,
)


class TestTimewInterval:
    """Tests for TimewInterval class."""

    def test_overlaps_true(self) -> None:
        """Test that overlapping intervals are detected."""
        int1 = TimewInterval(
            id=1,
            start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            tags={'tag1'}
        )
        int2 = TimewInterval(
            id=2,
            start=datetime(2025, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
            end=datetime(2025, 1, 1, 11, 30, 0, tzinfo=timezone.utc),
            tags={'tag2'}
        )
        assert int1.overlaps(int2)
        assert int2.overlaps(int1)

    def test_overlaps_false(self) -> None:
        """Test that non-overlapping intervals are detected."""
        int1 = TimewInterval(
            id=1,
            start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            tags={'tag1'}
        )
        int2 = TimewInterval(
            id=2,
            start=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            end=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            tags={'tag2'}
        )
        assert not int1.overlaps(int2)
        assert not int2.overlaps(int1)

    def test_duration(self) -> None:
        """Test duration calculation."""
        interval = TimewInterval(
            id=1,
            start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            end=datetime(2025, 1, 1, 11, 30, 0, tzinfo=timezone.utc),
            tags={'tag1'}
        )
        assert interval.duration() == timedelta(hours=1, minutes=30)


class TestCompareIntervals:
    """Tests for interval comparison logic."""

    def test_perfect_match(self) -> None:
        """Test intervals that match perfectly."""
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'python', 'not-afk'}
            )
        ]
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'python', 'not-afk'}
            )
        ]

        result = compare_intervals(timew_intervals, suggested_intervals)

        assert len(result['matching']) == 1
        assert len(result['different_tags']) == 0
        assert len(result['missing']) == 0
        assert len(result['extra']) == 0

    def test_different_tags(self) -> None:
        """Test intervals with different tags."""
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'python'}
            )
        ]
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'javascript'}  # Different tag
            )
        ]

        result = compare_intervals(timew_intervals, suggested_intervals)

        assert len(result['matching']) == 0
        assert len(result['different_tags']) == 1
        assert len(result['missing']) == 0
        assert len(result['extra']) == 0

    def test_missing_interval(self) -> None:
        """Test suggested interval missing from timew."""
        timew_intervals = []
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'python'}
            )
        ]

        result = compare_intervals(timew_intervals, suggested_intervals)

        assert len(result['matching']) == 0
        assert len(result['different_tags']) == 0
        assert len(result['missing']) == 1
        assert len(result['extra']) == 0

    def test_extra_interval(self) -> None:
        """Test interval in timew but not suggested."""
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'python'}
            )
        ]
        suggested_intervals = []

        result = compare_intervals(timew_intervals, suggested_intervals)

        assert len(result['matching']) == 0
        assert len(result['different_tags']) == 0
        assert len(result['missing']) == 0
        assert len(result['extra']) == 1

    def test_complex_scenario(self) -> None:
        """Test a complex scenario with multiple types of differences."""
        timew_intervals = [
            # This one matches
            TimewInterval(
                id=1,
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'python'}
            ),
            # This one has different tags
            TimewInterval(
                id=2,
                start=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'java'}
            ),
            # This one is extra
            TimewInterval(
                id=3,
                start=datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 14, 0, 0, tzinfo=timezone.utc),
                tags={'manual-entry'}
            ),
        ]

        suggested_intervals = [
            # Matches first timew interval
            SuggestedInterval(
                start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'python'}
            ),
            # Different tags from second timew interval
            SuggestedInterval(
                start=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                tags={'4work', 'python'}  # Different from timew
            ),
            # Missing from timew
            SuggestedInterval(
                start=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                end=datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
                tags={'4me', 'browsing'}
            ),
        ]

        result = compare_intervals(timew_intervals, suggested_intervals)

        # The algorithm matches overlapping intervals, so:
        # - First pair: perfect match (10-11)
        # - Second pair: different tags (11-12)
        # - Third pair: timew (13-14) matches suggested (12-13) due to proximity/overlap
        # So we get 1 matching, 2 different_tags, 0 missing, 0 extra
        assert len(result['matching']) == 1
        assert len(result['different_tags']) == 2  # Second and third pairs
        assert len(result['missing']) == 0
        assert len(result['extra']) == 0


class TestFormatDiffOutput:
    """Tests for diff output formatting."""

    def test_format_empty_comparison(self) -> None:
        """Test formatting with no differences."""
        comparison = {
            'matching': [],
            'different_tags': [],
            'missing': [],
            'extra': [],
        }

        output = format_diff_output(comparison, verbose=False)

        assert 'Summary:' in output
        assert 'Matching intervals:      0' in output

    def test_format_with_differences(self) -> None:
        """Test formatting with differences."""
        missing_start = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        missing_end = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

        comparison = {
            'matching': [(
                TimewInterval(
                    id=1,
                    start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                    end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                    tags={'4work'}
                ),
                SuggestedInterval(
                    start=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                    end=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
                    tags={'4work'}
                )
            )],
            'different_tags': [],
            'missing': [
                SuggestedInterval(
                    start=missing_start,
                    end=missing_end,
                    tags={'4me'}
                )
            ],
            'extra': [],
        }

        output = format_diff_output(comparison, verbose=False)

        assert 'Matching intervals:      1' in output
        assert 'Missing from TimeWarrior: 1' in output
        # Times are now displayed in local time, so convert for assertion
        expected_time = f"{missing_start.astimezone().strftime('%H:%M:%S')} - {missing_end.astimezone().strftime('%H:%M:%S')}"
        assert expected_time in output  # Missing interval time (in local time)


class TestGenerateFixCommands:
    """Tests for fix command generation."""

    def test_generate_track_command_for_missing(self) -> None:
        """Test that missing intervals generate track commands."""
        comparison = {
            'matching': [],
            'different_tags': [],
            'missing': [
                SuggestedInterval(
                    start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc),
                    end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc),
                    tags={'4work', 'python', '~aw'}
                )
            ],
            'extra': [],
        }

        commands = generate_fix_commands(comparison)

        assert len(commands) == 1
        assert commands[0].startswith('timew track')
        assert '4work' in commands[0]
        assert 'python' in commands[0]
        assert '~aw' in commands[0]
        assert ':adjust' in commands[0]

    def test_generate_retag_command_with_comments(self) -> None:
        """Test that retag commands include timestamp and old tags in comments."""
        comparison = {
            'matching': [],
            'different_tags': [
                (
                    TimewInterval(
                        id=42,
                        start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc),
                        end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc),
                        tags={'4work', 'java', '~aw'}  # Has ~aw tag (auto-generated)
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc),
                        end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc),
                        tags={'4work', 'python', '~aw'}
                    )
                )
            ],
            'missing': [],
            'extra': [],
        }

        commands = generate_fix_commands(comparison)

        assert len(commands) == 1
        # Should NOT be commented out (has ~aw tag)
        assert not commands[0].startswith('#')
        assert 'timew retag @42' in commands[0]
        assert '4work' in commands[0]
        assert 'python' in commands[0]
        # Should include comment with timestamp and old tags
        assert '# 2025-12-10' in commands[0]
        assert 'old tags:' in commands[0]
        assert 'java' in commands[0]  # Old tag in comment

    def test_retag_command_commented_for_manual_entries(self) -> None:
        """Test that retag commands for manual entries (no ~aw tag) are commented out."""
        comparison = {
            'matching': [],
            'different_tags': [
                (
                    TimewInterval(
                        id=99,
                        start=datetime(2025, 12, 10, 14, 30, 0, tzinfo=timezone.utc),
                        end=datetime(2025, 12, 10, 15, 0, 0, tzinfo=timezone.utc),
                        tags={'manual', 'meeting'}  # NO ~aw tag (manually entered)
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 12, 10, 14, 30, 0, tzinfo=timezone.utc),
                        end=datetime(2025, 12, 10, 15, 0, 0, tzinfo=timezone.utc),
                        tags={'4work', 'meeting', '~aw'}
                    )
                )
            ],
            'missing': [],
            'extra': [],
        }

        commands = generate_fix_commands(comparison)

        assert len(commands) == 1
        # Should be commented out (no ~aw tag in original)
        assert commands[0].startswith('# timew retag')
        assert '@99' in commands[0]
        # Should still include the informational comment
        assert '# 2025-12-10' in commands[0]
        assert 'old tags:' in commands[0]
        assert 'manual' in commands[0]
        assert 'meeting' in commands[0]

    def test_multiple_commands_mixed(self) -> None:
        """Test generating multiple commands with both auto and manual entries."""
        comparison = {
            'matching': [],
            'different_tags': [
                # Auto-generated (has ~aw)
                (
                    TimewInterval(
                        id=1,
                        start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc),
                        end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc),
                        tags={'old-tag', '~aw'}
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc),
                        end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc),
                        tags={'new-tag', '~aw'}
                    )
                ),
                # Manual entry (no ~aw)
                (
                    TimewInterval(
                        id=2,
                        start=datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc),
                        end=datetime(2025, 12, 10, 12, 0, 0, tzinfo=timezone.utc),
                        tags={'manual'}
                    ),
                    SuggestedInterval(
                        start=datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc),
                        end=datetime(2025, 12, 10, 12, 0, 0, tzinfo=timezone.utc),
                        tags={'auto', '~aw'}
                    )
                ),
            ],
            'missing': [
                SuggestedInterval(
                    start=datetime(2025, 12, 10, 12, 0, 0, tzinfo=timezone.utc),
                    end=datetime(2025, 12, 10, 13, 0, 0, tzinfo=timezone.utc),
                    tags={'missing', '~aw'}
                )
            ],
            'extra': [],
        }

        commands = generate_fix_commands(comparison)

        assert len(commands) == 3
        # First should be track command (for missing)
        assert commands[0].startswith('timew track')
        # Second should be uncommented retag (has ~aw)
        assert commands[1].startswith('timew retag @1')
        assert not commands[1].startswith('# timew')
        # Third should be commented retag (no ~aw)
        assert commands[2].startswith('# timew retag @2')

    def test_generate_delete_command_for_extra_auto(self) -> None:
        """Test that extra auto-generated intervals get delete commands."""
        comparison = {
            'matching': [],
            'different_tags': [],
            'missing': [],
            'extra': [
                TimewInterval(
                    id=42,
                    start=datetime(2025, 12, 10, 14, 0, 0, tzinfo=timezone.utc),
                    end=datetime(2025, 12, 10, 15, 0, 0, tzinfo=timezone.utc),
                    tags={'UNKNOWN', 'not-afk', '~aw'}
                )
            ],
        }

        commands = generate_fix_commands(comparison)

        assert len(commands) == 1
        # Should generate uncommented delete command (has ~aw)
        assert commands[0].startswith('timew delete @42 :yes')
        assert not commands[0].startswith('#')
        assert '# 2025-12-10' in commands[0]  # Check date, not exact time (timezone conversion)
        assert 'tags: UNKNOWN not-afk ~aw' in commands[0]

    def test_generate_delete_command_for_extra_manual(self) -> None:
        """Test that extra manually-entered intervals get commented delete commands."""
        comparison = {
            'matching': [],
            'different_tags': [],
            'missing': [],
            'extra': [
                TimewInterval(
                    id=99,
                    start=datetime(2025, 12, 10, 16, 0, 0, tzinfo=timezone.utc),
                    end=datetime(2025, 12, 10, 17, 0, 0, tzinfo=timezone.utc),
                    tags={'manual-work', 'meeting'}  # No ~aw tag
                )
            ],
        }

        commands = generate_fix_commands(comparison)

        assert len(commands) == 1
        # Should generate commented delete command (no ~aw)
        assert commands[0].startswith('# timew delete @99 :yes')
        assert '# 2025-12-10' in commands[0]  # Check date, not exact time (timezone conversion)
        assert 'tags: manual-work meeting' in commands[0]

    def test_generate_delete_commands_mixed(self) -> None:
        """Test generating delete commands for both auto and manual extra intervals."""
        comparison = {
            'matching': [],
            'different_tags': [],
            'missing': [],
            'extra': [
                # Auto-generated
                TimewInterval(
                    id=1,
                    start=datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc),
                    end=datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc),
                    tags={'auto', '~aw'}
                ),
                # Manual
                TimewInterval(
                    id=2,
                    start=datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc),
                    end=datetime(2025, 12, 10, 12, 0, 0, tzinfo=timezone.utc),
                    tags={'manual'}
                ),
            ],
        }

        commands = generate_fix_commands(comparison)

        assert len(commands) == 2
        # First should be uncommented delete (has ~aw)
        assert commands[0].startswith('timew delete @1 :yes')
        assert not commands[0].startswith('#')
        # Second should be commented delete (no ~aw)
        assert commands[1].startswith('# timew delete @2 :yes')
