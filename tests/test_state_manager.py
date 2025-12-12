"""Tests for StateManager.

This module tests the StateManager class which manages state and statistics
for the Exporter, including AFK state transitions, time boundaries, and
counter management.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

import pytest

# Import will fail until we create the module, but that's okay for now
try:
    from src.aw_export_timewarrior.state import AfkState, StateManager, TimeStats
except ImportError:
    # Module doesn't exist yet - tests will be skipped
    pytest.skip("StateManager module not yet implemented", allow_module_level=True)


class TestAfkStateEnum:
    """Test the AfkState enum."""

    def test_afk_state_values(self) -> None:
        """Test that AfkState has correct values."""
        assert AfkState.UNKNOWN.value == "unknown"
        assert AfkState.AFK.value == "afk"
        assert AfkState.ACTIVE.value == "active"

    def test_afk_state_comparison(self) -> None:
        """Test AfkState enum comparison."""
        assert AfkState.UNKNOWN == AfkState.UNKNOWN
        assert AfkState.AFK != AfkState.ACTIVE
        assert AfkState.UNKNOWN != AfkState.AFK


class TestTimeStats:
    """Test the TimeStats class."""

    def test_initial_state(self) -> None:
        """Test TimeStats initial state."""
        stats = TimeStats()

        assert stats.known_events_time == timedelta(0)
        assert stats.unknown_events_time == timedelta(0)
        assert isinstance(stats.tags_accumulated_time, defaultdict)
        assert len(stats.tags_accumulated_time) == 0

    def test_add_tag_time(self) -> None:
        """Test adding time to tags."""
        stats = TimeStats()

        stats.add_tag_time("work", timedelta(minutes=5))
        stats.add_tag_time("work", timedelta(minutes=3))
        stats.add_tag_time("break", timedelta(minutes=2))

        assert stats.tags_accumulated_time["work"] == timedelta(minutes=8)
        assert stats.tags_accumulated_time["break"] == timedelta(minutes=2)

    def test_add_known_time(self) -> None:
        """Test adding to known events time."""
        stats = TimeStats()

        stats.add_known_time(timedelta(minutes=10))
        stats.add_known_time(timedelta(minutes=5))

        assert stats.known_events_time == timedelta(minutes=15)

    def test_add_unknown_time(self) -> None:
        """Test adding to unknown events time."""
        stats = TimeStats()

        stats.add_unknown_time(timedelta(minutes=7))
        stats.add_unknown_time(timedelta(minutes=3))

        assert stats.unknown_events_time == timedelta(minutes=10)

    def test_total_time(self) -> None:
        """Test total time calculation."""
        stats = TimeStats()

        stats.add_known_time(timedelta(minutes=10))
        stats.add_unknown_time(timedelta(minutes=5))

        assert stats.total_time() == timedelta(minutes=15)

    def test_reset_without_retention(self) -> None:
        """Test resetting statistics without retaining tags."""
        stats = TimeStats()

        # Add some data
        stats.add_tag_time("work", timedelta(minutes=10))
        stats.add_tag_time("coding", timedelta(minutes=5))
        stats.add_known_time(timedelta(minutes=15))
        stats.add_unknown_time(timedelta(minutes=3))

        # Reset
        stats.reset()

        # Everything should be cleared
        assert stats.known_events_time == timedelta(0)
        assert stats.unknown_events_time == timedelta(0)
        assert len(stats.tags_accumulated_time) == 0

    def test_reset_with_retention(self) -> None:
        """Test resetting statistics while retaining specific tags."""
        stats = TimeStats()

        # Add some data
        stats.add_tag_time("work", timedelta(minutes=10))
        stats.add_tag_time("coding", timedelta(minutes=8))
        stats.add_tag_time("break", timedelta(minutes=5))

        # Reset, retaining "work" and "coding" with 0.5 factor
        stats.reset(retain_tags={"work", "coding"}, stickyness_factor=0.5)

        # Retained tags should have half their time
        assert stats.tags_accumulated_time["work"] == timedelta(minutes=5)
        assert stats.tags_accumulated_time["coding"] == timedelta(minutes=4)
        # Non-retained tag should be gone
        assert "break" not in stats.tags_accumulated_time
        # Other stats should be reset
        assert stats.known_events_time == timedelta(0)
        assert stats.unknown_events_time == timedelta(0)

    def test_reset_with_zero_stickyness(self) -> None:
        """Test that retention with 0.0 factor removes all time."""
        stats = TimeStats()

        stats.add_tag_time("work", timedelta(minutes=10))

        # Retain with 0.0 factor should result in 0 time
        stats.reset(retain_tags={"work"}, stickyness_factor=0.0)

        assert stats.tags_accumulated_time["work"] == timedelta(0)

    def test_reset_nonexistent_tag(self) -> None:
        """Test that retaining a tag that doesn't exist is safe."""
        stats = TimeStats()

        stats.add_tag_time("work", timedelta(minutes=10))

        # Try to retain a tag that doesn't exist
        stats.reset(retain_tags={"nonexistent", "work"}, stickyness_factor=0.5)

        # Only "work" should be retained
        assert stats.tags_accumulated_time["work"] == timedelta(minutes=5)
        assert "nonexistent" not in stats.tags_accumulated_time


class TestStateManagerInitialization:
    """Test StateManager initialization."""

    def test_default_initialization(self) -> None:
        """Test StateManager with default values."""
        sm = StateManager()

        assert sm.last_tick is None
        assert sm.last_known_tick is None
        assert sm.last_start_time is None
        assert sm.last_not_afk is None
        assert sm.afk_state == AfkState.UNKNOWN
        assert sm.manual_tracking is True
        assert isinstance(sm.stats, TimeStats)
        assert sm.enable_validation is True

    def test_custom_initialization(self) -> None:
        """Test StateManager with custom initial values."""
        now = datetime.now(UTC)
        stats = TimeStats()
        stats.add_tag_time("work", timedelta(minutes=5))

        sm = StateManager(
            last_tick=now,
            afk_state=AfkState.ACTIVE,
            manual_tracking=False,
            stats=stats,
            enable_validation=False
        )

        assert sm.last_tick == now
        assert sm.afk_state == AfkState.ACTIVE
        assert sm.manual_tracking is False
        assert sm.stats.tags_accumulated_time["work"] == timedelta(minutes=5)
        assert sm.enable_validation is False


class TestAfkStateQueries:
    """Test AFK state query methods."""

    def test_is_afk_when_unknown(self) -> None:
        """Test is_afk() returns None when state is UNKNOWN."""
        sm = StateManager()
        assert sm.is_afk() is None

    def test_is_afk_when_afk(self) -> None:
        """Test is_afk() returns True when state is AFK."""
        sm = StateManager(afk_state=AfkState.AFK)
        assert sm.is_afk() is True

    def test_is_afk_when_active(self) -> None:
        """Test is_afk() returns False when state is ACTIVE."""
        sm = StateManager(afk_state=AfkState.ACTIVE)
        assert sm.is_afk() is False


class TestAfkStateTransitions:
    """Test AFK state machine transitions."""

    def test_transition_unknown_to_afk(self) -> None:
        """Test transition from UNKNOWN to AFK."""
        sm = StateManager()
        sm.set_afk_state(AfkState.AFK, reason="User went idle")

        assert sm.afk_state == AfkState.AFK
        assert sm.is_afk() is True

    def test_transition_unknown_to_active(self) -> None:
        """Test transition from UNKNOWN to ACTIVE."""
        sm = StateManager()
        sm.set_afk_state(AfkState.ACTIVE, reason="User is active")

        assert sm.afk_state == AfkState.ACTIVE
        assert sm.is_afk() is False

    def test_transition_afk_to_active(self) -> None:
        """Test transition from AFK to ACTIVE."""
        sm = StateManager()
        sm.set_afk_state(AfkState.AFK)
        sm.set_afk_state(AfkState.ACTIVE, reason="User returned")

        assert sm.is_afk() is False

    def test_transition_active_to_afk(self) -> None:
        """Test transition from ACTIVE to AFK."""
        sm = StateManager()
        sm.set_afk_state(AfkState.ACTIVE)
        sm.set_afk_state(AfkState.AFK, reason="User went idle")

        assert sm.is_afk() is True

    def test_cannot_transition_to_unknown(self) -> None:
        """Test that transitioning TO unknown is invalid."""
        sm = StateManager()
        sm.set_afk_state(AfkState.ACTIVE)

        with pytest.raises(ValueError, match="transition.*UNKNOWN"):
            sm.set_afk_state(AfkState.UNKNOWN)

    def test_cannot_transition_to_unknown_from_afk(self) -> None:
        """Test that transitioning TO unknown from AFK is also invalid."""
        sm = StateManager()
        sm.set_afk_state(AfkState.AFK)

        with pytest.raises(ValueError, match="transition.*UNKNOWN"):
            sm.set_afk_state(AfkState.UNKNOWN)

    def test_transition_with_validation_disabled(self) -> None:
        """Test that validation can be disabled."""
        sm = StateManager(enable_validation=False)
        sm.set_afk_state(AfkState.ACTIVE)

        # This would normally raise, but validation is disabled
        sm.set_afk_state(AfkState.UNKNOWN)
        assert sm.afk_state == AfkState.UNKNOWN

    def test_same_state_transition_allowed(self) -> None:
        """Test that transitioning to same state is allowed (no-op)."""
        sm = StateManager()
        sm.set_afk_state(AfkState.ACTIVE)
        sm.set_afk_state(AfkState.ACTIVE, reason="Redundant transition")

        assert sm.is_afk() is False


class TestTimeBounds:
    """Test time boundary management."""

    def test_update_single_time_bound(self) -> None:
        """Test updating a single time boundary."""
        sm = StateManager()
        now = datetime.now(UTC)

        sm.update_time_bounds(last_tick=now)

        assert sm.last_tick == now
        assert sm.last_known_tick is None
        assert sm.last_start_time is None

    def test_update_multiple_time_bounds(self) -> None:
        """Test updating multiple time boundaries at once."""
        sm = StateManager()
        now = datetime.now(UTC)

        sm.update_time_bounds(
            last_tick=now,
            last_known_tick=now - timedelta(minutes=5),
            last_start_time=now - timedelta(minutes=10)
        )

        assert sm.last_tick == now
        assert sm.last_known_tick == now - timedelta(minutes=5)
        assert sm.last_start_time == now - timedelta(minutes=10)

    def test_time_bounds_validation_start_before_known(self) -> None:
        """Test that last_start_time must be <= last_known_tick."""
        sm = StateManager()
        now = datetime.now(UTC)

        with pytest.raises(ValueError, match="last_start_time.*last_known_tick"):
            sm.update_time_bounds(
                last_start_time=now,
                last_known_tick=now - timedelta(seconds=10)
            )

    def test_time_bounds_validation_known_before_tick(self) -> None:
        """Test that last_known_tick must be <= last_tick."""
        sm = StateManager()
        now = datetime.now(UTC)

        with pytest.raises(ValueError, match="last_known_tick.*last_tick"):
            sm.update_time_bounds(
                last_known_tick=now,
                last_tick=now - timedelta(seconds=10)
            )

    def test_time_bounds_validation_all_in_order(self) -> None:
        """Test validation of complete time ordering."""
        sm = StateManager()
        now = datetime.now(UTC)

        with pytest.raises(ValueError):
            sm.update_time_bounds(
                last_start_time=now,
                last_known_tick=now - timedelta(minutes=5),
                last_tick=now - timedelta(minutes=10)
            )

    def test_valid_time_bounds_accepted(self) -> None:
        """Test that valid time bounds are accepted."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Should not raise
        sm.update_time_bounds(
            last_start_time=now - timedelta(minutes=10),
            last_known_tick=now - timedelta(minutes=5),
            last_tick=now
        )

        assert sm.last_start_time == now - timedelta(minutes=10)
        assert sm.last_known_tick == now - timedelta(minutes=5)
        assert sm.last_tick == now

    def test_update_time_bounds_with_validation_disabled(self) -> None:
        """Test that time bounds validation can be disabled."""
        sm = StateManager(enable_validation=False)
        now = datetime.now(UTC)

        # This would normally raise, but validation is disabled
        sm.update_time_bounds(
            last_start_time=now,
            last_known_tick=now - timedelta(seconds=10)
        )

        assert sm.last_start_time == now
        assert sm.last_known_tick == now - timedelta(seconds=10)


class TestTimeQueries:
    """Test time-related query methods."""

    def test_time_since_last_export_none_when_not_set(self) -> None:
        """Test that time_since_last_export returns None when not set."""
        sm = StateManager()
        assert sm.time_since_last_export() is None

    def test_time_since_last_export_none_when_partially_set(self) -> None:
        """Test that time_since_last_export returns None if either value missing."""
        sm = StateManager()
        now = datetime.now(UTC)

        sm.update_time_bounds(last_tick=now)
        assert sm.time_since_last_export() is None

        sm = StateManager()
        sm.update_time_bounds(last_known_tick=now)
        assert sm.time_since_last_export() is None

    def test_time_since_last_export_calculated(self) -> None:
        """Test time_since_last_export calculation."""
        sm = StateManager()
        now = datetime.now(UTC)

        sm.update_time_bounds(
            last_known_tick=now - timedelta(minutes=10),
            last_tick=now
        )

        assert sm.time_since_last_export() == timedelta(minutes=10)

    def test_time_since_last_start_none_when_not_set(self) -> None:
        """Test that time_since_last_start returns None when not set."""
        sm = StateManager()
        assert sm.time_since_last_start() is None

    def test_time_since_last_start_calculated(self) -> None:
        """Test time_since_last_start calculation."""
        sm = StateManager()
        now = datetime.now(UTC)

        sm.update_time_bounds(
            last_start_time=now - timedelta(minutes=15),
            last_tick=now
        )

        assert sm.time_since_last_start() == timedelta(minutes=15)


class TestDominantTags:
    """Test dominant tags functionality."""

    def test_get_dominant_tags_empty(self) -> None:
        """Test getting dominant tags when no tags accumulated."""
        sm = StateManager()

        dominant = sm.get_dominant_tags(min_time=timedelta(minutes=5))
        assert dominant == set()

    def test_get_dominant_tags_none_meet_threshold(self) -> None:
        """Test when no tags meet the threshold."""
        sm = StateManager()

        sm.stats.add_tag_time("work", timedelta(minutes=2))
        sm.stats.add_tag_time("break", timedelta(minutes=1))

        dominant = sm.get_dominant_tags(min_time=timedelta(minutes=5))
        assert dominant == set()

    def test_get_dominant_tags_some_meet_threshold(self) -> None:
        """Test getting tags above threshold."""
        sm = StateManager()

        sm.stats.add_tag_time("work", timedelta(minutes=10))
        sm.stats.add_tag_time("coding", timedelta(minutes=8))
        sm.stats.add_tag_time("meeting", timedelta(minutes=3))
        sm.stats.add_tag_time("break", timedelta(minutes=1))

        dominant = sm.get_dominant_tags(min_time=timedelta(minutes=5))
        assert dominant == {"work", "coding"}

    def test_get_dominant_tags_all_meet_threshold(self) -> None:
        """Test when all tags meet the threshold."""
        sm = StateManager()

        sm.stats.add_tag_time("work", timedelta(minutes=10))
        sm.stats.add_tag_time("coding", timedelta(minutes=8))

        dominant = sm.get_dominant_tags(min_time=timedelta(minutes=5))
        assert dominant == {"work", "coding"}

    def test_get_dominant_tags_exact_threshold(self) -> None:
        """Test tag exactly at threshold is included."""
        sm = StateManager()

        sm.stats.add_tag_time("work", timedelta(minutes=5))

        dominant = sm.get_dominant_tags(min_time=timedelta(minutes=5))
        assert dominant == {"work"}


class TestRecordExport:
    """Test recording exports."""

    def test_record_export_updates_time_bounds(self) -> None:
        """Test that record_export updates time boundaries."""
        sm = StateManager()
        now = datetime.now(UTC)
        start = now - timedelta(minutes=10)
        end = now

        sm.record_export(start, end, {"work", "coding"})

        assert sm.last_start_time == start
        assert sm.last_known_tick == end
        assert sm.last_tick == end

    def test_record_export_resets_stats_by_default(self) -> None:
        """Test that record_export resets statistics by default."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Add some stats
        sm.stats.add_tag_time("work", timedelta(minutes=5))
        sm.stats.add_known_time(timedelta(minutes=10))
        sm.stats.add_unknown_time(timedelta(minutes=2))

        # Record export
        sm.record_export(now - timedelta(minutes=10), now, {"work"})

        # Stats should be reset
        assert sm.stats.known_events_time == timedelta(0)
        assert sm.stats.unknown_events_time == timedelta(0)
        assert len(sm.stats.tags_accumulated_time) == 0

    def test_record_export_can_skip_stats_reset(self) -> None:
        """Test that record_export can skip statistics reset."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Add some stats
        sm.stats.add_tag_time("work", timedelta(minutes=5))

        # Record export without resetting stats
        sm.record_export(
            now - timedelta(minutes=10),
            now,
            {"work"},
            reset_stats=False
        )

        # Stats should NOT be reset
        assert sm.stats.tags_accumulated_time["work"] == timedelta(minutes=5)

    def test_record_export_retains_specified_tags(self) -> None:
        """Test that record_export can retain specific tags."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Add some stats
        sm.stats.add_tag_time("work", timedelta(minutes=10))
        sm.stats.add_tag_time("coding", timedelta(minutes=8))
        sm.stats.add_tag_time("break", timedelta(minutes=5))

        # Record export, retaining "work" and "coding" with 0.5 factor
        sm.record_export(
            now - timedelta(minutes=15),
            now,
            {"work", "coding"},
            retain_tags={"work", "coding"},
            stickyness_factor=0.5
        )

        # Retained tags should have half their time
        assert sm.stats.tags_accumulated_time["work"] == timedelta(minutes=5)
        assert sm.stats.tags_accumulated_time["coding"] == timedelta(minutes=4)
        # Non-retained tag should be gone
        assert "break" not in sm.stats.tags_accumulated_time

    def test_record_export_sets_manual_tracking(self) -> None:
        """Test that record_export sets manual_tracking flag."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Default is True
        assert sm.manual_tracking is True

        # Set to False
        sm.record_export(
            now - timedelta(minutes=10),
            now,
            {"work"},
            manual=False
        )
        assert sm.manual_tracking is False

        # Set back to True
        sm.record_export(
            now - timedelta(minutes=5),
            now,
            {"work"},
            manual=True
        )
        assert sm.manual_tracking is True


class TestHandleAfkTransition:
    """Test AFK transition handling."""

    def test_handle_afk_transition_sets_state(self) -> None:
        """Test that handle_afk_transition sets the AFK state."""
        sm = StateManager()
        now = datetime.now(UTC)

        sm.handle_afk_transition(AfkState.AFK, now, reason="User idle")

        assert sm.is_afk() is True

    def test_handle_afk_transition_resets_stats(self) -> None:
        """Test that handle_afk_transition resets statistics."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Add some stats
        sm.stats.add_tag_time("work", timedelta(minutes=5))
        sm.stats.add_known_time(timedelta(minutes=10))

        # Go AFK
        sm.handle_afk_transition(AfkState.AFK, now, reason="User idle")

        # Stats should be reset
        assert len(sm.stats.tags_accumulated_time) == 0
        assert sm.stats.known_events_time == timedelta(0)

    def test_going_afk_updates_last_known_tick(self) -> None:
        """Test that going AFK marks activity as known."""
        sm = StateManager()
        now = datetime.now(UTC)

        sm.handle_afk_transition(AfkState.AFK, now, reason="User idle")

        assert sm.last_known_tick == now
        assert sm.last_tick == now
        assert sm.last_not_afk is None

    def test_returning_from_afk_sets_last_not_afk(self) -> None:
        """Test that returning from AFK sets last_not_afk."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Go AFK then return
        sm.handle_afk_transition(AfkState.AFK, now - timedelta(minutes=10))
        sm.handle_afk_transition(AfkState.ACTIVE, now, reason="User returned")

        assert sm.last_not_afk == now
        assert sm.is_afk() is False

    def test_handle_afk_transition_from_unknown(self) -> None:
        """Test AFK transition from UNKNOWN state."""
        sm = StateManager()
        now = datetime.now(UTC)

        assert sm.is_afk() is None

        sm.handle_afk_transition(AfkState.ACTIVE, now, reason="Initial state")

        assert sm.is_afk() is False
        assert sm.last_not_afk == now

    def test_handle_afk_transition_cannot_go_to_unknown(self) -> None:
        """Test that handle_afk_transition rejects UNKNOWN state."""
        sm = StateManager()
        now = datetime.now(UTC)

        with pytest.raises(ValueError, match="Cannot transition to UNKNOWN"):
            sm.handle_afk_transition(AfkState.UNKNOWN, now)

    def test_multiple_afk_transitions(self) -> None:
        """Test multiple AFK transitions in sequence."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Start active
        sm.handle_afk_transition(AfkState.ACTIVE, now)
        assert sm.is_afk() is False
        assert sm.last_not_afk == now

        # Go AFK
        afk_time = now + timedelta(minutes=30)
        sm.handle_afk_transition(AfkState.AFK, afk_time, reason="Idle")
        assert sm.is_afk() is True
        assert sm.last_known_tick == afk_time
        assert sm.last_not_afk is None

        # Return
        return_time = afk_time + timedelta(minutes=15)
        sm.handle_afk_transition(AfkState.ACTIVE, return_time, reason="Returned")
        assert sm.is_afk() is False
        assert sm.last_not_afk == return_time


class TestStateSummary:
    """Test state summary for debugging."""

    def test_get_state_summary_initial(self) -> None:
        """Test state summary with initial state."""
        sm = StateManager()

        summary = sm.get_state_summary()

        assert summary["afk_state"] == "unknown"
        assert summary["is_afk"] is None
        assert summary["manual_tracking"] is True
        assert summary["last_tick"] is None
        assert summary["last_known_tick"] is None
        assert summary["last_start_time"] is None
        assert summary["last_not_afk"] is None
        assert summary["time_since_export"] is None
        assert summary["accumulated_tags"] == {}

    def test_get_state_summary_with_data(self) -> None:
        """Test state summary with actual data."""
        sm = StateManager()
        now = datetime.now(UTC)

        sm.set_afk_state(AfkState.ACTIVE)
        sm.update_time_bounds(
            last_tick=now,
            last_known_tick=now - timedelta(minutes=10),
            last_start_time=now - timedelta(minutes=15)
        )
        sm.stats.add_tag_time("work", timedelta(minutes=5))
        sm.stats.add_tag_time("coding", timedelta(minutes=3))
        sm.stats.add_known_time(timedelta(minutes=8))

        summary = sm.get_state_summary()

        assert summary["afk_state"] == "active"
        assert summary["is_afk"] is False
        assert summary["last_tick"] is not None
        assert summary["time_since_export"] == "0:10:00"
        assert summary["known_events_time"] == "0:08:00"
        assert "work" in summary["accumulated_tags"]
        assert summary["accumulated_tags"]["work"] == "0:05:00"
        assert summary["accumulated_tags"]["coding"] == "0:03:00"

    def test_get_state_summary_iso_format(self) -> None:
        """Test that summary contains ISO-formatted timestamps."""
        sm = StateManager()
        now = datetime(2025, 12, 10, 15, 30, 0, tzinfo=UTC)

        sm.update_time_bounds(last_tick=now)

        summary = sm.get_state_summary()

        assert summary["last_tick"] == "2025-12-10T15:30:00+00:00"


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_negative_time_duration(self) -> None:
        """Test handling of negative time durations."""
        stats = TimeStats()

        # Adding negative time should work but be unusual
        stats.add_tag_time("work", timedelta(minutes=-5))

        assert stats.tags_accumulated_time["work"] == timedelta(minutes=-5)

    def test_very_large_time_values(self) -> None:
        """Test handling of very large time values."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Record export with very long interval (30 days)
        sm.record_export(
            now - timedelta(days=30),
            now,
            {"work"}
        )

        assert sm.time_since_last_start() == timedelta(days=30)

    def test_empty_tags_set(self) -> None:
        """Test record_export with empty tags set."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Should not raise
        sm.record_export(now - timedelta(minutes=10), now, set())

        assert sm.last_known_tick == now

    def test_concurrent_modifications(self) -> None:
        """Test that state remains consistent with multiple modifications."""
        sm = StateManager()
        now = datetime.now(UTC)

        # Simulate multiple updates in quick succession
        sm.update_time_bounds(last_tick=now)
        sm.stats.add_tag_time("work", timedelta(minutes=5))
        sm.set_afk_state(AfkState.ACTIVE)
        sm.update_time_bounds(last_known_tick=now - timedelta(minutes=5))
        sm.stats.add_known_time(timedelta(minutes=5))

        # State should remain consistent
        summary = sm.get_state_summary()
        assert summary["is_afk"] is False
        assert summary["accumulated_tags"]["work"] == "0:05:00"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
