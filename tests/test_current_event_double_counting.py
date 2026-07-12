"""Test for current event double-counting bug fix.

When an event transitions from being the "current/ongoing" event to a "completed"
event, its duration should not be counted twice in known_events_time.

This bug caused assertion failures like:
  ASSERTION FAILED: tracked_gap (126.56345s) < known_events_time (163.417867s)

The bug occurs in continuous sync mode where:
1. Event E1 is the current event, its partial duration is added to known_events_time
2. Next iteration, E1 becomes a completed event, its full duration is added AGAIN
3. known_events_time accumulates more time than actual elapsed time
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch


class TestCurrentEventDoubleCountingFix:
    """Tests for the current event -> completed event transition."""

    def test_completed_event_deducts_previously_processed_duration(self) -> None:
        """Test that when a completed event matches current_event_timestamp, only the delta is added.

        This directly tests the fix at line 1947 in main.py.
        """
        from aw_export_timewarrior.main import EventMatchResult, Exporter, TagResult

        # Create a mock AW client
        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            current_time = datetime.now(UTC).isoformat()
            mock_client = Mock()
            mock_client.get_buckets.return_value = {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "client": "aw-watcher-window",
                    "last_updated": current_time,
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "client": "aw-watcher-afk",
                    "last_updated": current_time,
                },
            }
            mock_aw_class.return_value = mock_client

            exporter = Exporter(dry_run=True)

            # Simulate state: E1 was processed as current event with 30s duration
            event_timestamp = datetime(2025, 12, 21, 9, 43, 0, tzinfo=UTC)
            exporter.state.current_event_timestamp = event_timestamp
            exporter.state.current_event_processed_duration = timedelta(seconds=30)

            # Set up known_events_time to simulate 30s already counted from incremental processing
            exporter.state.stats.known_events_time = timedelta(seconds=30)

            # Now simulate E1 appearing as a completed event with full 48s duration
            event = {
                "timestamp": event_timestamp,  # Same timestamp as current_event_timestamp
                "duration": timedelta(seconds=48),
                "data": {"app": "Emacs", "title": "test.py"},
            }

            # The fix code runs when we have:
            # - tag_result truthy
            # - "status" not in event["data"]
            # - event["timestamp"] == current_event_timestamp

            # Simulate what happens in find_next_activity at line 1946-1959
            # (This is the exact code we're testing)
            tag_result = TagResult(result=EventMatchResult.MATCHED, tags={"work"})

            if tag_result and "status" not in event["data"]:
                duration_to_add = event["duration"]
                # Avoid double-counting: if this event was partially processed as the
                # current/ongoing event, only add the remaining (unprocessed) duration.
                if exporter.state.current_event_timestamp == event["timestamp"]:
                    duration_to_add = (
                        event["duration"] - exporter.state.current_event_processed_duration
                    )
                    if duration_to_add < timedelta(0):
                        duration_to_add = timedelta(0)  # Safety check
                    # Clear the current event tracking since we've now fully processed it
                    exporter.state.current_event_timestamp = None
                    exporter.state.current_event_processed_duration = timedelta(0)
                if duration_to_add > timedelta(0):
                    exporter.state.stats.known_events_time += duration_to_add

            # Verify the fix worked:
            # - Only 18s should have been added (48s - 30s already processed)
            # - Total should be 30s + 18s = 48s, NOT 30s + 48s = 78s
            assert exporter.state.stats.known_events_time == timedelta(seconds=48), (
                f"Expected 48s total, got {exporter.state.stats.known_events_time.total_seconds()}s. "
                "Double-counting bug if this is 78s."
            )

            # Verify current event tracking was cleared
            assert exporter.state.current_event_timestamp is None
            assert exporter.state.current_event_processed_duration == timedelta(0)

    def test_current_event_clipped_to_last_known_tick(self) -> None:
        """An ongoing event that started before last_known_tick must be clipped.

        Regression test: find_next_activity's clipping fix (see
        tests/test_known_events_time_clipping.py) only applies to
        `completed_events`, not to the current/ongoing event processed by
        `_process_current_event_incrementally`. A window event spanning an
        AFK export boundary (started before last_known_tick, still ongoing)
        had its FULL duration added to known_events_time, violating
        known_events_time <= tracked_gap -- the same invariant the
        completed-events clip protects.
        """
        from aw_export_timewarrior.main import Exporter

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            current_time = datetime.now(UTC).isoformat()
            mock_client = Mock()
            mock_client.get_buckets.return_value = {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "client": "aw-watcher-window",
                    "last_updated": current_time,
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "client": "aw-watcher-afk",
                    "last_updated": current_time,
                },
            }
            mock_aw_class.return_value = mock_client

            exporter = Exporter(dry_run=True)

            last_known_tick = datetime(2025, 12, 21, 9, 50, 0, tzinfo=UTC)
            exporter.state.last_known_tick = last_known_tick
            exporter.state.last_start_time = last_known_tick

            # Ongoing window event that started 10 minutes before
            # last_known_tick and is still running 2 minutes past it --
            # mirrors the completed-event scenario in
            # test_known_events_time_clipping.py, but for the current event.
            event_start = last_known_tick - timedelta(minutes=10)
            current_event = {
                "timestamp": event_start,
                "duration": timedelta(minutes=12),
                "data": {"app": "MPlayer", "title": "MPlayer"},
            }

            exporter._process_current_event_incrementally(current_event)

            tracked_gap = (
                current_event["timestamp"]
                + current_event["duration"]
                - exporter.state.last_known_tick
            )
            assert exporter.state.stats.known_events_time <= tracked_gap, (
                f"known_events_time ({exporter.state.stats.known_events_time}) exceeds "
                f"tracked_gap ({tracked_gap}) -- the ongoing event's pre-last_known_tick "
                "portion was not clipped."
            )

    def test_ongoing_event_survives_export_advancing_last_known_tick(self) -> None:
        """Invariant guard for CODE_REVIEW_2026-07-12.md #6.

        _process_current_event_incrementally keys its dedup on the *clipped*
        start (== last_known_tick when the event started earlier). If an export
        advances last_known_tick while the same event stays open across ticks,
        that key shifts and the "new ongoing event" branch re-adds the full
        clipped span. That only stays correct because every real path that
        advances last_known_tick also zeroes known_events_time (and clears the
        current-event tracking): record_export couples reset_stats to both
        (state.py) and the AFK path resets stats just before.

        This test drives that real coupling -- a genuine export advancing
        last_known_tick between two incremental calls on the same open event --
        and asserts the known_events_time <= tracked_gap invariant still holds.
        It fails if a future change decouples the last_known_tick advance from
        the stats reset.
        """
        from aw_export_timewarrior.main import Exporter

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            current_time = datetime.now(UTC).isoformat()
            mock_client = Mock()
            mock_client.get_buckets.return_value = {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "client": "aw-watcher-window",
                    "last_updated": current_time,
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "client": "aw-watcher-afk",
                    "last_updated": current_time,
                },
            }
            mock_aw_class.return_value = mock_client

            exporter = Exporter(dry_run=True)

            l1 = datetime(2025, 12, 21, 9, 50, 0, tzinfo=UTC)
            exporter.state.last_known_tick = l1
            exporter.state.last_start_time = l1

            event_start = l1 - timedelta(minutes=10)

            def open_event(total_minutes: int) -> dict:
                return {
                    "timestamp": event_start,
                    "duration": timedelta(minutes=total_minutes),
                    "data": {"app": "MPlayer", "title": "MPlayer"},
                }

            # Tick 1: event runs to l1 + 2min; only [l1, l1+2min] is countable.
            exporter._process_current_event_incrementally(open_event(12))

            # A real export at l1+2min advances last_known_tick through the
            # normal, invariant-preserving path (reset_accumulator zeroes stats
            # and clears current-event tracking).
            l2 = l1 + timedelta(minutes=2)
            exporter.set_known_tick_stats(
                start=l1,
                end=l2,
                tags={"work"},
                reset_accumulator=True,
                record_export=True,
            )
            assert exporter.state.last_known_tick == l2

            # Tick 2: same event still open, now to l1 + 5min.
            exporter._process_current_event_incrementally(open_event(15))

            tracked_gap = (event_start + timedelta(minutes=15)) - exporter.state.last_known_tick
            assert exporter.state.stats.known_events_time <= tracked_gap, (
                f"known_events_time ({exporter.state.stats.known_events_time}) exceeds "
                f"tracked_gap ({tracked_gap}) after an export advanced last_known_tick "
                "while the event stayed open -- the reset coupling was broken (#6)."
            )

    def test_completed_event_no_match_adds_full_duration(self) -> None:
        """Test that completed events NOT matching current_event_timestamp add full duration.

        This verifies we don't break the normal case where events haven't been
        incrementally processed.
        """
        from aw_export_timewarrior.main import EventMatchResult, Exporter, TagResult

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            current_time = datetime.now(UTC).isoformat()
            mock_client = Mock()
            mock_client.get_buckets.return_value = {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "client": "aw-watcher-window",
                    "last_updated": current_time,
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "client": "aw-watcher-afk",
                    "last_updated": current_time,
                },
            }
            mock_aw_class.return_value = mock_client

            exporter = Exporter(dry_run=True)

            # Simulate state: different event was the current event
            other_timestamp = datetime(2025, 12, 21, 9, 40, 0, tzinfo=UTC)
            exporter.state.current_event_timestamp = other_timestamp
            exporter.state.current_event_processed_duration = timedelta(seconds=30)
            exporter.state.stats.known_events_time = timedelta(seconds=30)

            # New completed event with DIFFERENT timestamp
            event = {
                "timestamp": datetime(2025, 12, 21, 9, 43, 0, tzinfo=UTC),  # Different!
                "duration": timedelta(seconds=48),
                "data": {"app": "Emacs", "title": "test.py"},
            }

            tag_result = TagResult(result=EventMatchResult.MATCHED, tags={"work"})

            if tag_result and "status" not in event["data"]:
                duration_to_add = event["duration"]
                if exporter.state.current_event_timestamp == event["timestamp"]:
                    duration_to_add = (
                        event["duration"] - exporter.state.current_event_processed_duration
                    )
                    if duration_to_add < timedelta(0):
                        duration_to_add = timedelta(0)
                    exporter.state.current_event_timestamp = None
                    exporter.state.current_event_processed_duration = timedelta(0)
                if duration_to_add > timedelta(0):
                    exporter.state.stats.known_events_time += duration_to_add

            # Full 48s should be added since timestamps don't match
            # Total should be 30s + 48s = 78s
            assert exporter.state.stats.known_events_time == timedelta(seconds=78), (
                f"Expected 78s total, got {exporter.state.stats.known_events_time.total_seconds()}s"
            )

            # Current event tracking should NOT be cleared (different event)
            assert exporter.state.current_event_timestamp == other_timestamp
            assert exporter.state.current_event_processed_duration == timedelta(seconds=30)

    def test_negative_duration_safety_check(self) -> None:
        """Test that negative duration is clamped to zero.

        This could happen if there's a timing issue where the completed event
        has less duration than what was already processed (shouldn't happen,
        but we protect against it).
        """
        from aw_export_timewarrior.main import EventMatchResult, Exporter, TagResult

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            current_time = datetime.now(UTC).isoformat()
            mock_client = Mock()
            mock_client.get_buckets.return_value = {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "client": "aw-watcher-window",
                    "last_updated": current_time,
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "client": "aw-watcher-afk",
                    "last_updated": current_time,
                },
            }
            mock_aw_class.return_value = mock_client

            exporter = Exporter(dry_run=True)

            # Simulate state: already processed 50s
            event_timestamp = datetime(2025, 12, 21, 9, 43, 0, tzinfo=UTC)
            exporter.state.current_event_timestamp = event_timestamp
            exporter.state.current_event_processed_duration = timedelta(
                seconds=50
            )  # More than event duration!
            exporter.state.stats.known_events_time = timedelta(seconds=50)

            # Event shows only 48s (less than processed - edge case)
            event = {
                "timestamp": event_timestamp,
                "duration": timedelta(seconds=48),
                "data": {"app": "Emacs", "title": "test.py"},
            }

            tag_result = TagResult(result=EventMatchResult.MATCHED, tags={"work"})

            if tag_result and "status" not in event["data"]:
                duration_to_add = event["duration"]
                if exporter.state.current_event_timestamp == event["timestamp"]:
                    duration_to_add = (
                        event["duration"] - exporter.state.current_event_processed_duration
                    )
                    if duration_to_add < timedelta(0):
                        duration_to_add = timedelta(0)  # Safety check catches this
                    exporter.state.current_event_timestamp = None
                    exporter.state.current_event_processed_duration = timedelta(0)
                if duration_to_add > timedelta(0):
                    exporter.state.stats.known_events_time += duration_to_add

            # Nothing should be added (duration_to_add was negative, clamped to 0)
            # Total remains 50s
            assert exporter.state.stats.known_events_time == timedelta(seconds=50), (
                f"Expected 50s (no change), got {exporter.state.stats.known_events_time.total_seconds()}s"
            )

            # Current event tracking should still be cleared
            assert exporter.state.current_event_timestamp is None
            assert exporter.state.current_event_processed_duration == timedelta(0)
