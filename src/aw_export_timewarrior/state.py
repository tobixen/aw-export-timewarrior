"""State management for the aw-export-timewarrior exporter.

This module provides a centralized state manager to replace scattered state
variables in the Exporter class. It includes:

- AfkState enum for explicit AFK state tracking
- TimeStats class for managing time statistics
- ExportRecord dataclass for tracking export history
- StateManager class for coordinating all state and statistics

See docs/STATE_MANAGEMENT_REFACTORING.md for the full refactoring plan.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum


class AfkState(Enum):
    """Enumeration for AFK states.

    Replaces the tri-state None/True/False pattern with explicit states.
    """

    UNKNOWN = "unknown"  # Initial state, no AFK information available
    AFK = "afk"  # User is away from keyboard
    ACTIVE = "active"  # User is actively using the system


@dataclass
class TimeStats:
    """Manages time statistics and tag accumulation.

    Tracks:
    - Per-tag accumulated time
    - Total time for known/unknown events
    - Total time for ignored events (below duration threshold)
    """

    tags_accumulated_time: defaultdict[str, timedelta] = field(
        default_factory=lambda: defaultdict(lambda: timedelta(0))
    )
    known_events_time: timedelta = field(default_factory=lambda: timedelta(0))
    unknown_events_time: timedelta = field(default_factory=lambda: timedelta(0))
    # Track events ignored due to being below duration threshold
    ignored_events_time: timedelta = field(default_factory=lambda: timedelta(0))
    ignored_events_count: int = 0

    def add_tag_time(self, tag: str, duration: timedelta) -> None:
        """Add time to a specific tag's accumulator."""
        self.tags_accumulated_time[tag] += duration

    def add_known_time(self, duration: timedelta) -> None:
        """Add time to the known events counter."""
        self.known_events_time += duration

    def add_unknown_time(self, duration: timedelta) -> None:
        """Add time to the unknown events counter."""
        self.unknown_events_time += duration

    def reset(self, retain_tags: set[str] | None = None, stickyness_factor: float = 1.0) -> None:
        """Reset statistics.

        Args:
            retain_tags: Set of tag names to retain (with stickyness applied).
                        If None, all tags are cleared.
            stickyness_factor: Factor to apply to retained tags (0.0-1.0).
                              1.0 = keep full time, 0.5 = keep half, 0.0 = clear
        """
        if retain_tags is None:
            # Full reset
            self.tags_accumulated_time.clear()
        else:
            # Create new dict with only retained tags
            new_tags = defaultdict(lambda: timedelta(0))
            for tag in retain_tags:
                if tag in self.tags_accumulated_time:
                    # Apply stickyness factor
                    old_time = self.tags_accumulated_time[tag]
                    new_tags[tag] = old_time * stickyness_factor
            self.tags_accumulated_time = new_tags

        self.known_events_time = timedelta(0)
        self.unknown_events_time = timedelta(0)

    def total_time(self) -> timedelta:
        """Return total time across all events."""
        return self.known_events_time + self.unknown_events_time


@dataclass
class ExportRecord:
    """Record of a single export for report generation.

    Captures the state of the tag accumulator before and after the export,
    allowing reports to show what was accumulated and exported.

    Three timestamps are involved:
    - timestamp: When the exported interval began (interval start)
    - decision_timestamp: When the export decision was triggered
    - end_timestamp: When the exported interval ended (= start of next interval)
    """

    timestamp: datetime  # Start time of the exported interval
    duration: timedelta  # Duration of the exported interval
    tags: set[str]  # Tags that were exported
    accumulator_before: dict[str, timedelta]  # Tag accumulator state before reset
    accumulator_after: dict[str, timedelta]  # Tag accumulator state after reset (with stickyness)
    decision_timestamp: datetime | None = None  # When the export decision was made

    @property
    def row_type(self) -> str:
        """Return the row type for report formatting."""
        return "export"

    @property
    def end_timestamp(self) -> datetime:
        """Return the end timestamp of the exported interval."""
        return self.timestamp + self.duration


@dataclass
class StateManager:
    """Manages state and statistics for the Exporter.

    This class centralizes all state management that was previously scattered
    across the Exporter class, providing:

    - Clear state lifecycle
    - Validation of state transitions
    - Single source of truth for statistics
    - Easier testing and debugging
    """

    # Time tracking
    last_tick: datetime | None = None
    last_known_tick: datetime | None = None
    last_start_time: datetime | None = None
    last_not_afk: datetime | None = None

    # AFK state
    afk_state: AfkState = AfkState.UNKNOWN

    # Tracking mode
    manual_tracking: bool = True

    # Statistics
    stats: TimeStats = field(default_factory=TimeStats)

    # Current ongoing event tracking (for idempotent incremental processing)
    current_event_timestamp: datetime | None = None
    current_event_processed_duration: timedelta = field(default_factory=lambda: timedelta(0))

    # Configuration
    enable_validation: bool = True

    # Export history tracking (for report generation)
    track_exports: bool = False  # Disabled by default for performance
    export_history: list[ExportRecord] = field(default_factory=list)

    def is_afk(self) -> bool | None:
        """Return AFK status.

        Returns:
            True if AFK, False if active, None if unknown
        """
        if self.afk_state == AfkState.UNKNOWN:
            return None
        return self.afk_state == AfkState.AFK

    def set_afk_state(self, new_state: AfkState, reason: str = "") -> None:
        """Set the AFK state with validation.

        Args:
            new_state: The new AFK state to transition to
            reason: Optional reason for the transition (for logging)

        Raises:
            ValueError: If the transition is invalid (when validation enabled)
        """
        if self.enable_validation:
            self._validate_afk_transition(new_state)
        self.afk_state = new_state

    def _validate_afk_transition(self, new_state: AfkState) -> None:
        """Validate that an AFK state transition is allowed.

        Rules:
        - Cannot transition to UNKNOWN (only valid as initial state)

        Args:
            new_state: The state to transition to

        Raises:
            ValueError: If the transition is invalid
        """
        if new_state == AfkState.UNKNOWN:
            raise ValueError(
                "Cannot transition to UNKNOWN state. UNKNOWN is only valid as an initial state."
            )

    def update_time_bounds(
        self,
        last_tick: datetime | None = None,
        last_known_tick: datetime | None = None,
        last_start_time: datetime | None = None,
        last_not_afk: datetime | None = None,
    ) -> None:
        """Update time boundary tracking with validation.

        Args:
            last_tick: Most recent tick (any event)
            last_known_tick: Most recent tick with known events
            last_start_time: Start time of last export
            last_not_afk: Last time user was not AFK

        Raises:
            ValueError: If time ordering is invalid (when validation enabled)
        """
        # Update values
        if last_tick is not None:
            self.last_tick = last_tick
        if last_known_tick is not None:
            self.last_known_tick = last_known_tick
        if last_start_time is not None:
            self.last_start_time = last_start_time
        if last_not_afk is not None:
            self.last_not_afk = last_not_afk

        # Validate ordering if enabled
        if self.enable_validation:
            self._validate_time_bounds()

    def _validate_time_bounds(self) -> None:
        """Validate that time bounds are in correct order.

        Invariants:
        - last_known_tick should not be after last_tick
        - last_start_time should not be after last_known_tick

        Raises:
            ValueError: If invariants are violated
        """
        if (
            self.last_known_tick is not None
            and self.last_tick is not None
            and self.last_known_tick > self.last_tick
        ):
            raise ValueError(
                f"Invalid time bounds: last_known_tick ({self.last_known_tick}) "
                f"is after last_tick ({self.last_tick})"
            )

        if (
            self.last_start_time is not None
            and self.last_known_tick is not None
            and self.last_start_time > self.last_known_tick
        ):
            raise ValueError(
                f"Invalid time bounds: last_start_time ({self.last_start_time}) "
                f"is after last_known_tick ({self.last_known_tick})"
            )

    def record_export(
        self,
        start: datetime,
        end: datetime,
        tags: set[str],
        reset_stats: bool = True,
        retain_tags: set[str] | None = None,
        stickyness_factor: float = 0.5,
        manual: bool = True,
        record_export_history: bool = False,
        decision_timestamp: datetime | None = None,
        accumulator_before: dict[str, timedelta] | None = None,
    ) -> None:
        """Record an export with associated statistics.

        This is the single entry point for recording exports, ensuring
        consistent state updates.

        Args:
            start: Export start time
            end: Export end time
            tags: Tags for this export
            reset_stats: Whether to reset statistics after recording
            retain_tags: Tags to retain when resetting (with stickyness applied)
            stickyness_factor: Factor to apply to retained tags (0.0-1.0)
            manual: Whether this is manual tracking
            record_export_history: Whether to record this as an export for reporting
            decision_timestamp: When the export decision was triggered
            accumulator_before: Pre-computed accumulator state before stickyness applied.
                               If None, captures current accumulator state (post-stickyness).
        """
        # Use provided accumulator_before or capture current state
        if accumulator_before is None:
            accumulator_before = {}
            if self.track_exports and record_export_history:
                accumulator_before = dict(self.stats.tags_accumulated_time)
        elif not self.track_exports or not record_export_history:
            # Don't use accumulator_before if we're not recording history
            accumulator_before = {}

        # Set manual tracking mode
        self.manual_tracking = manual

        # Update time bounds
        self.update_time_bounds(
            last_tick=end,
            last_known_tick=end,
            last_start_time=start,
        )

        # Reset stats if requested (before adding new data)
        if reset_stats:
            self.stats.reset(retain_tags=retain_tags, stickyness_factor=stickyness_factor)
            # Also reset current event tracking when starting a new export period
            self.current_event_timestamp = None
            self.current_event_processed_duration = timedelta(0)

        # Record export to history if requested
        if self.track_exports and record_export_history:
            accumulator_after = dict(self.stats.tags_accumulated_time)
            export_record = ExportRecord(
                timestamp=start,
                duration=end - start,
                tags=set(tags),
                accumulator_before=accumulator_before,
                accumulator_after=accumulator_after,
                decision_timestamp=decision_timestamp,
            )
            self.export_history.append(export_record)

    def handle_afk_transition(
        self,
        new_state: AfkState,
        current_time: datetime | None = None,
        reason: str = "",
        reset_stats: bool = True,
    ) -> None:
        """Handle a transition in AFK state.

        This method handles the state transition and any associated cleanup,
        such as resetting statistics on any AFK state change.

        Args:
            new_state: The new AFK state
            current_time: Time of the transition (defaults to now)
            reason: Optional reason for transition
            reset_stats: Whether to reset statistics on any state transition
        """
        old_state = self.afk_state

        # Set the new state (validates transition)
        self.set_afk_state(new_state, reason)

        # Update last_not_afk based on new state
        if new_state == AfkState.ACTIVE:
            # Becoming active - set last_not_afk to current time
            if current_time is None:
                current_time = datetime.now(UTC)
            self.last_not_afk = current_time
        elif new_state == AfkState.AFK:
            # Going AFK - clear last_not_afk
            self.last_not_afk = None

        # Handle AFK state transitions: reset statistics on any transition
        # (both going AFK and returning from AFK)
        if old_state != new_state and reset_stats:
            self.stats.reset(retain_tags=None)

        # Update last_known_tick and last_tick when going AFK
        if new_state == AfkState.AFK:
            if current_time is None:
                current_time = datetime.now(UTC)
            self.update_time_bounds(last_known_tick=current_time, last_tick=current_time)

    def get_dominant_tags(self, min_time: timedelta | None = None) -> set[str]:
        """Get tags that have accumulated significant time.

        Args:
            min_time: Minimum time threshold. If None, returns all tags.

        Returns:
            Set of tag names that meet the threshold
        """
        if min_time is None:
            # Return all tags
            return set(self.stats.tags_accumulated_time.keys())

        # Filter by minimum time
        return {tag for tag, time in self.stats.tags_accumulated_time.items() if time >= min_time}

    def time_since_last_export(self) -> timedelta | None:
        """Calculate time since the last export ended.

        Uses current time as the reference point.

        Returns:
            Time since last export, or None if insufficient data
        """
        # Need both last_tick and last_known_tick to calculate
        if self.last_tick is None or self.last_known_tick is None:
            return None

        # Time since last known event (which is when last export happened)
        return self.last_tick - self.last_known_tick

    def time_since_last_start(self) -> timedelta | None:
        """Calculate time since the last export started.

        Uses last_tick as the reference point (or current time if not set).

        Returns:
            Time since last export start, or None if no exports yet
        """
        if self.last_start_time is None:
            return None

        # Use last_tick as reference if available, otherwise current time
        if self.last_tick is not None:
            return self.last_tick - self.last_start_time
        else:
            current_time = datetime.now(UTC)
            return current_time - self.last_start_time

    def get_state_summary(self) -> dict:
        """Get a summary of current state for debugging.

        Returns:
            Dictionary with current state information
        """
        # Calculate time since export
        time_since_export = self.time_since_last_export()

        # Build accumulated tags dict with formatted strings
        accumulated_tags = {}
        for tag, duration in self.stats.tags_accumulated_time.items():
            # Format as H:MM:SS
            total_seconds = int(duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            accumulated_tags[tag] = f"{hours}:{minutes:02d}:{seconds:02d}"

        return {
            "afk_state": self.afk_state.value,
            "is_afk": self.is_afk(),
            "manual_tracking": self.manual_tracking,
            "last_tick": self.last_tick.isoformat() if self.last_tick else None,
            "last_known_tick": self.last_known_tick.isoformat() if self.last_known_tick else None,
            "last_start_time": self.last_start_time.isoformat() if self.last_start_time else None,
            "last_not_afk": self.last_not_afk.isoformat() if self.last_not_afk else None,
            "time_since_export": str(time_since_export) if time_since_export else None,
            "known_events_time": str(self.stats.known_events_time),
            "unknown_events_time": str(self.stats.unknown_events_time),
            "total_time": str(self.stats.total_time()),
            "tags_with_time": len(self.stats.tags_accumulated_time),
            "accumulated_tags": accumulated_tags,
        }

    def get_exports_in_range(self, start: datetime, end: datetime) -> list[ExportRecord]:
        """Get exports within a time range.

        Args:
            start: Range start time
            end: Range end time

        Returns:
            List of ExportRecords within the time range
        """
        return [export for export in self.export_history if start <= export.timestamp <= end]
