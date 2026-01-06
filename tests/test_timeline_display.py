"""Test timeline display accuracy.

The timeline should accurately show the ActivityWatch suggestions even when
they differ from TimeWarrior intervals. When a timew interval has different
tags from the overlapping AW suggestion, the timeline should show the actual
AW tags, not just "(continuing)".

Real-world case from Dec 22, 2025:
- AW suggests "personal admin" (diary writing) from 01:45 to 02:26
- User has various timew entries with different tags (4RL, oss-contrib, etc.)
  during this period
- Timeline should show that AW suggests different tags, not "(continuing)"
"""

from datetime import UTC, datetime

from aw_export_timewarrior.compare import (
    SuggestedInterval,
    TimewInterval,
    format_timeline,
)


class TestTimelineDisplay:
    """Test that timeline accurately displays AW suggestions."""

    def test_timeline_shows_aw_tags_when_timew_differs(self):
        """When timew has different tags, timeline should show actual AW tags.

        Scenario:
        - AW suggests "personal-admin" from 01:45 to 02:30
        - Timew has "personal-admin" at 01:45, then "work" at 02:00
        - Timeline should show AW tags at 02:00, not "(continuing)"
        """
        start_time = datetime(2025, 12, 22, 1, 45, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 22, 2, 30, 0, tzinfo=UTC)

        # TimeWarrior intervals - user switched to different activity at 02:00
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 12, 22, 1, 45, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 0, 0, tzinfo=UTC),
                tags={"personal-admin", "diary", "4ME"},
            ),
            TimewInterval(
                id=2,
                start=datetime(2025, 12, 22, 2, 0, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 15, 0, tzinfo=UTC),
                tags={"work", "coding", "4RL"},
            ),
            TimewInterval(
                id=3,
                start=datetime(2025, 12, 22, 2, 15, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 30, 0, tzinfo=UTC),
                tags={"personal-admin", "diary", "4ME"},
            ),
        ]

        # AW suggests personal-admin for the entire period
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 12, 22, 1, 45, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 30, 0, tzinfo=UTC),
                tags={"personal-admin", "diary", "4ME"},
            ),
        ]

        timeline = format_timeline(timew_intervals, suggested_intervals, start_time, end_time)

        # The timeline shows times in local timezone
        # Look for the line where timew has "work" tags (different from AW)
        lines = timeline.split("\n")

        # Find the line where timew shows "work" or "4RL" tags
        work_line = None
        for line in lines:
            if "work" in line or "4RL" in line:
                work_line = line
                break

        assert work_line is not None, (
            f"Should have a line with timew 'work' tags. Timeline:\n{timeline}"
        )

        # When timew has different tags from AW, the AW column should show the actual
        # AW tags (personal-admin, diary, 4ME), not just "(continuing)"
        assert "continuing" not in work_line.lower(), (
            f"When timew has different tags, timeline should show actual AW tags, not '(continuing)'. Got: {work_line}"
        )

    def test_timeline_shows_continuing_when_both_match(self):
        """When both timew and AW have same tags, "(continuing)" is acceptable.

        If timew changes to an interval that happens to have the same tags
        as what AW suggests, we don't need to repeat the tags.
        """
        start_time = datetime(2025, 12, 22, 1, 45, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 22, 2, 30, 0, tzinfo=UTC)

        # TimeWarrior intervals - two intervals but same tags
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 12, 22, 1, 45, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 0, 0, tzinfo=UTC),
                tags={"personal-admin", "diary", "4ME"},
            ),
            TimewInterval(
                id=2,
                start=datetime(2025, 12, 22, 2, 0, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 30, 0, tzinfo=UTC),
                tags={"personal-admin", "diary", "4ME"},  # Same tags
            ),
        ]

        # AW suggests the same tags for the entire period
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 12, 22, 1, 45, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 30, 0, tzinfo=UTC),
                tags={"personal-admin", "diary", "4ME"},
            ),
        ]

        timeline = format_timeline(timew_intervals, suggested_intervals, start_time, end_time)

        # When tags match, "(continuing)" or blank is fine
        # This test just ensures we don't crash
        assert "Timeline:" in timeline
        assert "TimeWarrior" in timeline

    def test_timeline_multiple_aw_intervals_with_different_tags(self):
        """Test that timeline shows changes when AW has multiple intervals.

        When ActivityWatch suggests different activities at different times,
        the timeline should show all of them.
        """
        start_time = datetime(2025, 12, 22, 1, 0, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 22, 3, 0, 0, tzinfo=UTC)

        # TimeWarrior has one long interval
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 12, 22, 1, 0, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 3, 0, 0, tzinfo=UTC),
                tags={"work", "4RL"},
            ),
        ]

        # AW suggests different activities at different times
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 12, 22, 1, 0, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 0, 0, tzinfo=UTC),
                tags={"personal-admin", "4ME"},
            ),
            SuggestedInterval(
                start=datetime(2025, 12, 22, 2, 0, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 3, 0, 0, tzinfo=UTC),
                tags={"entertainment", "4BREAK"},
            ),
        ]

        timeline = format_timeline(timew_intervals, suggested_intervals, start_time, end_time)

        # Both AW activities should appear in the timeline
        assert "personal-admin" in timeline or "4ME" in timeline, (
            "Timeline should show first AW interval tags"
        )
        assert "entertainment" in timeline or "4BREAK" in timeline, (
            "Timeline should show second AW interval tags"
        )

    def test_timeline_shows_discrepancy_clearly(self):
        """Timeline should make tag discrepancies obvious.

        When timew has tags that don't match AW suggestion for a time slice,
        both sets of tags should be visible for comparison.
        """
        start_time = datetime(2025, 12, 22, 2, 0, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 22, 2, 30, 0, tzinfo=UTC)

        # Timew: working on oss-contrib
        timew_intervals = [
            TimewInterval(
                id=1,
                start=datetime(2025, 12, 22, 2, 0, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 30, 0, tzinfo=UTC),
                tags={"oss-contrib", "activitywatch", "4RL"},
            ),
        ]

        # AW: suggests personal admin
        suggested_intervals = [
            SuggestedInterval(
                start=datetime(2025, 12, 22, 2, 0, 0, tzinfo=UTC),
                end=datetime(2025, 12, 22, 2, 30, 0, tzinfo=UTC),
                tags={"personal-admin", "diary", "4ME"},
            ),
        ]

        timeline = format_timeline(timew_intervals, suggested_intervals, start_time, end_time)

        # At 02:00:00, both sets of tags should be visible
        # Timew tags
        assert "oss-contrib" in timeline or "activitywatch" in timeline, (
            "Timeline should show timew tags"
        )
        # AW tags
        assert "personal-admin" in timeline or "diary" in timeline, (
            "Timeline should show AW suggested tags"
        )
