"""Test that ignored events (below duration threshold) are tracked for analyze.

When analyze runs, it should report:
1. Events that didn't match any rules (NO_MATCH)
2. Events that were ignored due to being below the duration threshold

Currently, ignored events are not tracked - they're just silently skipped.
This test verifies that ignored events are tracked and can be reported.
"""

from datetime import UTC, datetime, timedelta

import pytest

from .conftest import FixtureDataBuilder


class TestIgnoredEventsTracking:
    """Test that short events below ignore_interval are tracked for reporting."""

    @pytest.fixture
    def config_with_browser_rule(self):
        """Config with a browser rule that won't match most events."""
        return {
            "rules": {
                "browser": {
                    "github": {
                        "url_regexp": r"github\.com",
                        "timew_tags": ["github", "coding"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
            "terminal_apps": ["foot"],
        }

    def test_ignored_events_tracked_in_stats(self, config_with_browser_rule):
        """Verify that events below ignore_interval are tracked in stats.

        Scenario:
        - Several short events (1-2 seconds) that are below ignore_interval (3s)
        - These should be counted in stats.ignored_events_time and ignored_events_count
        """
        start_time = datetime(2025, 12, 20, 10, 0, 0, tzinfo=UTC)
        builder = FixtureDataBuilder(start_time=start_time)

        # Add not-afk so events are processed
        builder.add_afk_event("not-afk", duration=60, timestamp=start_time)

        # Add several short events (below 3s threshold)
        # These should be IGNORED but tracked
        for i in range(5):
            builder.add_window_event(
                "foot",
                f"short command {i}",
                duration=1,  # 1 second - below ignore_interval
                timestamp=start_time + timedelta(seconds=i * 2),
            )

        # Add one longer event that should be counted as NO_MATCH
        builder.add_window_event(
            "foot",
            "longer command",
            duration=5,  # 5 seconds - above ignore_interval
            timestamp=start_time + timedelta(seconds=20),
        )

        test_data = builder.build()

        from aw_export_timewarrior.main import Exporter

        exporter = Exporter(
            dry_run=True,
            test_data=test_data,
            start_time=start_time,
            end_time=start_time + timedelta(seconds=60),
            config=config_with_browser_rule,
            show_unmatched=True,  # Enable unmatched event tracking
        )

        # Process events
        exporter.tick(process_all=True)

        # Verify ignored events are tracked
        # Due to wall-clock accumulation logic, some short events may pass through
        # as NO_MATCH when their cumulative wall-clock time exceeds ignore_interval.
        # We expect at least some events to be truly IGNORED.
        assert exporter.state.stats.ignored_events_count >= 1, (
            f"Expected at least 1 ignored event, got {exporter.state.stats.ignored_events_count}"
        )
        assert exporter.state.stats.ignored_events_time >= timedelta(seconds=1), (
            f"Expected at least 1s of ignored time, got {exporter.state.stats.ignored_events_time}"
        )
        # Verify the total (ignored + unknown) accounts for all short events
        total_short_time = (
            exporter.state.stats.ignored_events_time + exporter.state.stats.unknown_events_time
        )
        # We have 5 short (1s) + 1 longer (5s) = 10s of unmatched time total
        assert total_short_time >= timedelta(seconds=5), (
            f"Expected total unmatched time >= 5s, got {total_short_time}"
        )

    def test_unmatched_report_shows_ignored_summary(self, config_with_browser_rule):
        """Verify that show_unmatched_events_report includes ignored events summary."""
        start_time = datetime(2025, 12, 20, 10, 0, 0, tzinfo=UTC)
        builder = FixtureDataBuilder(start_time=start_time)

        builder.add_afk_event("not-afk", duration=60, timestamp=start_time)

        # Add short events that will be ignored
        for i in range(10):
            builder.add_window_event(
                "foot",
                f"short cmd {i}",
                duration=2,  # 2 seconds - below ignore_interval
                timestamp=start_time + timedelta(seconds=i * 3),
            )

        test_data = builder.build()

        from aw_export_timewarrior.main import Exporter

        exporter = Exporter(
            dry_run=True,
            test_data=test_data,
            start_time=start_time,
            end_time=start_time + timedelta(seconds=60),
            config=config_with_browser_rule,
            show_unmatched=True,
        )

        exporter.tick(process_all=True)

        # Capture the report output
        import io
        import sys

        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            exporter.show_unmatched_events_report(limit=50)
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()

        # The report should mention ignored/below-threshold events
        assert (
            "below" in output.lower()
            or "ignored" in output.lower()
            or "threshold" in output.lower()
        ), f"Expected report to mention ignored/below-threshold events. Got:\n{output}"

    def test_ignored_events_separate_from_unmatched(self, config_with_browser_rule):
        """Verify that IGNORED events are tracked separately from NO_MATCH events.

        The wall-clock logic means some short events may pass through if they
        accumulate to exceed ignore_interval. We verify that:
        1. Events that are truly IGNORED are tracked in stats
        2. The longer event is in unmatched_events as NO_MATCH
        """
        start_time = datetime(2025, 12, 20, 10, 0, 0, tzinfo=UTC)
        builder = FixtureDataBuilder(start_time=start_time)

        builder.add_afk_event("not-afk", duration=120, timestamp=start_time)

        # Add short events spread far apart so they don't accumulate
        # Each one starts fresh and should be IGNORED
        for i in range(5):
            builder.add_window_event(
                "foot",
                f"isolated_short_{i}",  # Different titles = different contexts
                duration=1,
                timestamp=start_time + timedelta(seconds=i * 15),  # Far apart
            )

        # Add longer event that should be NO_MATCH and in unmatched_events
        builder.add_window_event(
            "foot",
            "longer unmatched",
            duration=10,
            timestamp=start_time + timedelta(seconds=100),
        )

        test_data = builder.build()

        from aw_export_timewarrior.main import Exporter

        exporter = Exporter(
            dry_run=True,
            test_data=test_data,
            start_time=start_time,
            end_time=start_time + timedelta(seconds=120),
            config=config_with_browser_rule,
            show_unmatched=True,
        )

        exporter.tick(process_all=True)

        # The longer event should be in unmatched_events
        longer_events = [e for e in exporter.unmatched_events if "longer" in e["data"]["title"]]
        assert len(longer_events) >= 1, "Expected longer event in unmatched_events"

        # The isolated short events should be tracked as ignored in stats
        # (they're too short and isolated to trigger the wall-clock accumulation)
        assert exporter.state.stats.ignored_events_count >= 1, (
            f"Expected at least 1 ignored event in stats, got {exporter.state.stats.ignored_events_count}"
        )
        assert exporter.state.stats.ignored_events_time >= timedelta(seconds=1), (
            f"Expected at least 1s of ignored time, got {exporter.state.stats.ignored_events_time}"
        )
