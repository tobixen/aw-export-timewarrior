# State Management Refactoring Plan

## Problem Analysis: Unsafe Counter/State Management

### Executive Summary

The `Exporter` class in `main.py` has **unsafe and scattered state management** that violates encapsulation principles and creates hard-to-track bugs. State is modified in multiple places without clear ownership, counters are reset inconsistently, and the control flow for state transitions is complex and error-prone.

**TODOs in code:**
- Line 212: "TODO: Resetting counters should be done through explicit methods in this class and not through arbitrary assignments in unrelated methods"
- Line 604: "TODO: move all dealings with statistics to explicit statistics-handling methods"
- Line 965: "TODO: self.afk should ONLY be set here and on initialization"

---

## Current State: What's Wrong?

### 1. **Scattered State Modifications**

#### Problem: `tags_accumulated_time` Reset in 2 Places

**Declared:** Line 223
```python
tags_accumulated_time: defaultdict = field(default_factory=lambda: defaultdict(timedelta))
```

**Modified directly:**
- Line 597 in `set_known_tick_stats()`: `self.tags_accumulated_time = defaultdict(timedelta)`
- Line 987 in `_afk_change_stats()`: `self.tags_accumulated_time = defaultdict(timedelta)`

**Why this is unsafe:**
- No single source of truth for when/why this counter is reset
- Different methods have different conditions for resetting
- Hard to audit what state transitions are valid
- No way to add logging/debugging for state changes
- Violates encapsulation

#### Problem: `afk` State Set in 6 Places

**Declared:** Line 238
```python
afk: bool = None  # Can be None, True, or False (tri-state!)
```

**Modified in 6 different places:**
1. Line 637 in `ensure_tag_exported()`: `self.afk = True`
2. Line 989 in `_afk_change_stats()`: `self.afk = afk=='afk'`
3. Line 1007 in `check_and_handle_afk_state_change()`: `self.afk = True`
4. Line 1009 in `check_and_handle_afk_state_change()`: `self.afk = False`
5. Line 1259 in `set_timew_info()`: `self.afk = True`
6. Line 1261 in `set_timew_info()`: `self.afk = False`

**Why this is unsafe:**
- State machine has no explicit transitions
- Can be modified from anywhere
- No validation that transition is valid
- Comment says "TODO: self.afk should ONLY be set here" but it's set in 5 other places!
- Tri-state (None/True/False) with unclear semantics

#### Problem: `total_time_known_events` Reset Once, Used Everywhere

**Declared:** Line 246
```python
total_time_known_events: timedelta = timedelta(0)
```

**Only reset:** Line 601 in `set_known_tick_stats()`
```python
self.total_time_known_events = timedelta(0)
```

**Used/incremented in:**
- `ensure_tag_exported()` - accumulates time
- `find_next_activity()` - checked for validity
- Logging statements throughout

**Why this is unsafe:**
- Counter can only be reset by calling `set_known_tick_stats()`
- No clear lifecycle for this counter
- Mixed concerns: statistics tracking AND validation logic

---

### 2. **Unclear State Lifecycle**

The current code has multiple overlapping state concepts with unclear relationships:

| State Variable | Purpose | Reset Conditions | Modified By |
|----------------|---------|------------------|-------------|
| `last_tick` | End time of last event handled | Multiple places | 6+ methods |
| `last_known_tick` | End time when tags were exported | `set_known_tick_stats()` | 3 methods |
| `last_start_time` | Start time when tags were exported | `set_known_tick_stats()` | 1 method |
| `last_not_afk` | Start of not-afk period | `_afk_change_stats()` | 2 methods |
| `afk` | AFK state (tri-state!) | Never explicitly reset | 6 methods |
| `manual_tracking` | User manually tracked | `set_known_tick_stats()` | 2 methods |
| `tags_accumulated_time` | Time per tag since last export | `set_known_tick_stats()`, `_afk_change_stats()` | Multiple |
| `total_time_known_events` | Total tracked time | `set_known_tick_stats()` | Multiple |
| `total_time_unknown_events` | Total untracked time | `set_known_tick_stats()` | Multiple |

**Problems:**
- 9 state variables with overlapping purposes
- No clear state machine diagram
- Unclear which combinations are valid
- No invariant checking
- Reset logic is scattered and inconsistent

---

### 3. **Complex State Transitions**

Example from `ensure_tag_exported()` (lines 605-676):

```python
def ensure_tag_exported(self, tags, event, since=None):
    # ... 70 lines of complex logic mixing:
    # 1. State checking (is afk? is manual? is override?)
    # 2. Statistics accumulation
    # 3. TimeWarrior interaction
    # 4. State modification (self.afk = True/False)
    # 5. Counter updates
    # 6. Logging
```

**Issues:**
- Single method does too many things
- State transitions hidden in control flow
- Hard to understand pre/post conditions
- Difficult to test in isolation

---

### 4. **Lack of Invariant Checking**

No validation that state is consistent. Examples of potential inconsistencies:

- `last_known_tick > last_tick` (impossible, but no check)
- `afk=True` but `tags_accumulated_time` has non-afk tags
- `manual_tracking=True` but timew_info says otherwise
- `total_time_known_events + total_time_unknown_events != (last_tick - last_start_time)`

---

## Refactoring Plan

### Phase 1: Extract State Manager (Week 1)

#### Step 1.1: Create `StateManager` Class

Create new file: `src/aw_export_timewarrior/state.py`

```python
"""State management for the Exporter."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Set
from collections import defaultdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AfkState(Enum):
    """AFK state of the user."""
    UNKNOWN = "unknown"  # Just started, don't know yet
    AFK = "afk"         # User is away from keyboard
    ACTIVE = "active"   # User is actively using computer


@dataclass
class TimeStats:
    """Statistics about tracked and untracked time."""

    known_events_time: timedelta = timedelta(0)
    """Total time spent on tag-generating activities since last export."""

    unknown_events_time: timedelta = timedelta(0)
    """Total time spent on activities without tags since last export."""

    tags_accumulated_time: defaultdict = field(
        default_factory=lambda: defaultdict(timedelta)
    )
    """Time accumulated per tag since last export."""

    def reset(self, retain_tags: Optional[Set[str]] = None, stickyness_factor: float = 0.0):
        """
        Reset statistics counters.

        Args:
            retain_tags: Tags to retain with reduced time
            stickyness_factor: Factor to multiply retained tag time by (0.0-1.0)
        """
        self.known_events_time = timedelta(0)
        self.unknown_events_time = timedelta(0)

        if retain_tags:
            new_accumulator = defaultdict(timedelta)
            for tag in retain_tags:
                if tag in self.tags_accumulated_time:
                    new_accumulator[tag] = self.tags_accumulated_time[tag] * stickyness_factor
            self.tags_accumulated_time = new_accumulator
        else:
            self.tags_accumulated_time = defaultdict(timedelta)

    def add_tag_time(self, tag: str, duration: timedelta):
        """Add time to a specific tag's accumulator."""
        self.tags_accumulated_time[tag] += duration

    def add_known_time(self, duration: timedelta):
        """Add to known events time."""
        self.known_events_time += duration

    def add_unknown_time(self, duration: timedelta):
        """Add to unknown events time."""
        self.unknown_events_time += duration

    def total_time(self) -> timedelta:
        """Get total tracked time (known + unknown)."""
        return self.known_events_time + self.unknown_events_time


@dataclass
class StateManager:
    """
    Manages state and statistics for the Exporter.

    Responsibilities:
    - Track time boundaries (last_tick, last_known_tick, etc.)
    - Manage AFK state with explicit transitions
    - Maintain statistics counters
    - Validate state transitions
    - Provide single source of truth for state queries
    """

    # Time boundaries
    last_tick: Optional[datetime] = None
    """End time of the last event that was processed."""

    last_known_tick: Optional[datetime] = None
    """End time when tags were last exported to TimeWarrior."""

    last_start_time: Optional[datetime] = None
    """Start time of the interval that was last exported."""

    last_not_afk: Optional[datetime] = None
    """Start time of the current not-afk period (if active)."""

    # State flags
    afk_state: AfkState = AfkState.UNKNOWN
    """Current AFK state of the user."""

    manual_tracking: bool = True
    """Whether user has manually modified TimeWarrior tracking."""

    # Statistics
    stats: TimeStats = field(default_factory=TimeStats)
    """Time statistics and accumulators."""

    # Configuration (injected)
    enable_validation: bool = True
    """Whether to validate state transitions (disable for tests)."""

    def __post_init__(self):
        """Initialize logger."""
        self.logger = logging.getLogger(f"{__name__}.StateManager")

    # ============================================================
    # Public API: State Queries
    # ============================================================

    def is_afk(self) -> Optional[bool]:
        """
        Get current AFK state.

        Returns:
            True if AFK, False if active, None if unknown
        """
        if self.afk_state == AfkState.UNKNOWN:
            return None
        return self.afk_state == AfkState.AFK

    def time_since_last_export(self) -> Optional[timedelta]:
        """
        Get time since last export.

        Returns:
            Time duration, or None if never exported
        """
        if not self.last_known_tick or not self.last_tick:
            return None
        return self.last_tick - self.last_known_tick

    def time_since_last_start(self) -> Optional[timedelta]:
        """
        Get time since the start of the last exported interval.

        Returns:
            Time duration, or None if never exported
        """
        if not self.last_start_time or not self.last_tick:
            return None
        return self.last_tick - self.last_start_time

    def get_dominant_tags(self, min_time: timedelta) -> Set[str]:
        """
        Get tags that have accumulated at least min_time.

        Args:
            min_time: Minimum time threshold

        Returns:
            Set of tag names meeting the threshold
        """
        return {
            tag for tag, time in self.stats.tags_accumulated_time.items()
            if time >= min_time
        }

    # ============================================================
    # Public API: State Transitions
    # ============================================================

    def set_afk_state(self, new_state: AfkState, reason: str = ""):
        """
        Transition to a new AFK state.

        Args:
            new_state: New AFK state
            reason: Reason for transition (for logging)

        Raises:
            ValueError: If transition is invalid
        """
        old_state = self.afk_state

        # Validate transition if enabled
        if self.enable_validation:
            self._validate_afk_transition(old_state, new_state)

        # Log transition
        if old_state != new_state:
            self.logger.info(
                f"AFK state transition: {old_state.value} → {new_state.value}",
                extra={"reason": reason, "old_state": old_state.value, "new_state": new_state.value}
            )

        self.afk_state = new_state

    def update_time_bounds(
        self,
        last_tick: Optional[datetime] = None,
        last_known_tick: Optional[datetime] = None,
        last_start_time: Optional[datetime] = None,
        last_not_afk: Optional[datetime] = None
    ):
        """
        Update time boundary values.

        Args:
            last_tick: New last_tick value
            last_known_tick: New last_known_tick value
            last_start_time: New last_start_time value
            last_not_afk: New last_not_afk value

        Raises:
            ValueError: If new values violate invariants
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

        # Validate invariants
        if self.enable_validation:
            self._validate_time_bounds()

    def record_export(
        self,
        start: datetime,
        end: datetime,
        tags: Set[str],
        manual: bool = False,
        reset_stats: bool = True,
        retain_tags: Optional[Set[str]] = None,
        stickyness_factor: float = 0.0
    ):
        """
        Record that an interval was exported to TimeWarrior.

        This is the main method for updating state after export.

        Args:
            start: Start time of exported interval
            end: End time of exported interval
            tags: Tags that were exported
            manual: Whether this was manual tracking
            reset_stats: Whether to reset statistics
            retain_tags: Tags to retain in accumulator
            stickyness_factor: Factor for retained tags (0.0-1.0)
        """
        self.logger.info(
            f"Recording export: {start} → {end} with tags {tags}",
            extra={"start": start, "end": end, "tags": list(tags), "manual": manual}
        )

        # Update time bounds
        self.last_known_tick = end
        self.last_tick = end
        self.last_start_time = start
        self.manual_tracking = manual

        # Reset statistics if requested
        if reset_stats:
            self.stats.reset(retain_tags=retain_tags, stickyness_factor=stickyness_factor)

        # Validate
        if self.enable_validation:
            self._validate_time_bounds()

    def handle_afk_transition(
        self,
        new_state: AfkState,
        event_end: datetime,
        reason: str = ""
    ):
        """
        Handle AFK state transition with associated state resets.

        This method should be called when user goes AFK or returns.
        It handles the state transition AND the associated statistics reset.

        Args:
            new_state: New AFK state (AFK or ACTIVE)
            event_end: End time of the event causing the transition
            reason: Reason for transition

        Raises:
            ValueError: If new_state is UNKNOWN
        """
        if new_state == AfkState.UNKNOWN:
            raise ValueError("Cannot transition to UNKNOWN state")

        old_state = self.afk_state

        # Set the new state
        self.set_afk_state(new_state, reason=reason)

        # Reset statistics on AFK transitions
        self.stats.reset()

        # Update time boundaries based on transition type
        if new_state == AfkState.AFK:
            # Going AFK - mark activity as known up to this point
            self.last_known_tick = event_end
            self.last_tick = event_end
            self.last_not_afk = None  # Not in not-afk period anymore

        elif new_state == AfkState.ACTIVE:
            # Returning from AFK - start tracking not-afk time
            self.last_not_afk = event_end
            # Note: We don't update last_known_tick here because
            # we haven't exported anything yet

    # ============================================================
    # Private: Validation
    # ============================================================

    def _validate_afk_transition(self, old_state: AfkState, new_state: AfkState):
        """
        Validate AFK state transition.

        Valid transitions:
        - UNKNOWN → AFK
        - UNKNOWN → ACTIVE
        - AFK ↔ ACTIVE

        Invalid:
        - * → UNKNOWN (can only start in UNKNOWN)
        """
        # Can't transition TO unknown (only start there)
        if new_state == AfkState.UNKNOWN and old_state != AfkState.UNKNOWN:
            raise ValueError(f"Invalid transition {old_state.value} → UNKNOWN")

        # All other transitions are valid

    def _validate_time_bounds(self):
        """
        Validate time boundary invariants.

        Invariants:
        1. If last_known_tick is set, last_start_time must be set
        2. last_start_time <= last_known_tick <= last_tick
        3. All times must be in the past (or very recent)
        """
        if self.last_known_tick and not self.last_start_time:
            raise ValueError("last_known_tick set but last_start_time is None")

        if self.last_start_time and self.last_known_tick:
            if self.last_start_time > self.last_known_tick:
                raise ValueError(
                    f"last_start_time ({self.last_start_time}) > "
                    f"last_known_tick ({self.last_known_tick})"
                )

        if self.last_known_tick and self.last_tick:
            if self.last_known_tick > self.last_tick:
                raise ValueError(
                    f"last_known_tick ({self.last_known_tick}) > "
                    f"last_tick ({self.last_tick})"
                )

    # ============================================================
    # Public API: Debugging
    # ============================================================

    def get_state_summary(self) -> dict:
        """
        Get a summary of current state for debugging.

        Returns:
            Dictionary with current state values
        """
        return {
            "afk_state": self.afk_state.value,
            "is_afk": self.is_afk(),
            "manual_tracking": self.manual_tracking,
            "last_tick": self.last_tick.isoformat() if self.last_tick else None,
            "last_known_tick": self.last_known_tick.isoformat() if self.last_known_tick else None,
            "last_start_time": self.last_start_time.isoformat() if self.last_start_time else None,
            "last_not_afk": self.last_not_afk.isoformat() if self.last_not_afk else None,
            "time_since_export": str(self.time_since_last_export()) if self.time_since_last_export() else None,
            "known_events_time": str(self.stats.known_events_time),
            "unknown_events_time": str(self.stats.unknown_events_time),
            "total_time": str(self.stats.total_time()),
            "accumulated_tags": {tag: str(time) for tag, time in self.stats.tags_accumulated_time.items()},
        }
```

#### Step 1.2: Write Tests for StateManager

Create `tests/test_state_manager.py`:

```python
"""Tests for StateManager."""

import pytest
from datetime import datetime, timedelta, timezone
from src.aw_export_timewarrior.state import StateManager, AfkState, TimeStats


class TestAfkStateTransitions:
    """Test AFK state machine."""

    def test_initial_state_is_unknown(self):
        """Test that initial state is UNKNOWN."""
        sm = StateManager()
        assert sm.afk_state == AfkState.UNKNOWN
        assert sm.is_afk() is None

    def test_transition_unknown_to_afk(self):
        """Test transition from UNKNOWN to AFK."""
        sm = StateManager()
        sm.set_afk_state(AfkState.AFK, reason="User went AFK")
        assert sm.is_afk() is True

    def test_transition_unknown_to_active(self):
        """Test transition from UNKNOWN to ACTIVE."""
        sm = StateManager()
        sm.set_afk_state(AfkState.ACTIVE, reason="User is active")
        assert sm.is_afk() is False

    def test_transition_afk_to_active(self):
        """Test transition from AFK to ACTIVE."""
        sm = StateManager()
        sm.set_afk_state(AfkState.AFK)
        sm.set_afk_state(AfkState.ACTIVE, reason="User returned")
        assert sm.is_afk() is False

    def test_cannot_transition_to_unknown(self):
        """Test that transitioning TO unknown is invalid."""
        sm = StateManager()
        sm.set_afk_state(AfkState.ACTIVE)

        with pytest.raises(ValueError, match="transition.*UNKNOWN"):
            sm.set_afk_state(AfkState.UNKNOWN)


class TestTimeBoundsValidation:
    """Test time boundary validation."""

    def test_last_start_before_last_known_tick(self):
        """Test that last_start_time must be <= last_known_tick."""
        sm = StateManager()
        now = datetime.now(timezone.utc)

        with pytest.raises(ValueError, match="last_start_time.*last_known_tick"):
            sm.update_time_bounds(
                last_start_time=now,
                last_known_tick=now - timedelta(seconds=10)
            )

    def test_last_known_tick_before_last_tick(self):
        """Test that last_known_tick must be <= last_tick."""
        sm = StateManager()
        now = datetime.now(timezone.utc)

        with pytest.raises(ValueError, match="last_known_tick.*last_tick"):
            sm.update_time_bounds(
                last_known_tick=now,
                last_tick=now - timedelta(seconds=10)
            )

    def test_valid_time_bounds(self):
        """Test that valid time bounds are accepted."""
        sm = StateManager()
        now = datetime.now(timezone.utc)

        sm.update_time_bounds(
            last_start_time=now - timedelta(minutes=10),
            last_known_tick=now - timedelta(minutes=5),
            last_tick=now
        )

        assert sm.last_start_time == now - timedelta(minutes=10)
        assert sm.last_known_tick == now - timedelta(minutes=5)
        assert sm.last_tick == now


class TestRecordExport:
    """Test recording exports."""

    def test_record_export_updates_time_bounds(self):
        """Test that record_export updates time boundaries."""
        sm = StateManager()
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=10)
        end = now

        sm.record_export(start, end, {"work", "coding"})

        assert sm.last_start_time == start
        assert sm.last_known_tick == end
        assert sm.last_tick == end

    def test_record_export_resets_stats(self):
        """Test that record_export resets statistics."""
        sm = StateManager()
        now = datetime.now(timezone.utc)

        # Add some stats
        sm.stats.add_tag_time("work", timedelta(minutes=5))
        sm.stats.add_known_time(timedelta(minutes=10))

        # Record export
        sm.record_export(now - timedelta(minutes=10), now, {"work"})

        # Stats should be reset
        assert sm.stats.known_events_time == timedelta(0)
        assert len(sm.stats.tags_accumulated_time) == 0

    def test_record_export_retains_tags(self):
        """Test that record_export can retain specific tags."""
        sm = StateManager()
        now = datetime.now(timezone.utc)

        # Add some stats
        sm.stats.add_tag_time("work", timedelta(minutes=10))
        sm.stats.add_tag_time("break", timedelta(minutes=5))

        # Record export, retaining "work" tag with 0.5 factor
        sm.record_export(
            now - timedelta(minutes=15),
            now,
            {"work"},
            retain_tags={"work"},
            stickyness_factor=0.5
        )

        # "work" should be retained with half the time, "break" should be gone
        assert sm.stats.tags_accumulated_time["work"] == timedelta(minutes=5)
        assert "break" not in sm.stats.tags_accumulated_time


class TestHandleAfkTransition:
    """Test AFK transition handling."""

    def test_going_afk_resets_stats(self):
        """Test that going AFK resets statistics."""
        sm = StateManager()
        now = datetime.now(timezone.utc)

        # Add some stats
        sm.stats.add_tag_time("work", timedelta(minutes=5))

        # Go AFK
        sm.handle_afk_transition(AfkState.AFK, now, reason="User idle")

        # Stats should be reset
        assert len(sm.stats.tags_accumulated_time) == 0

    def test_going_afk_updates_last_known_tick(self):
        """Test that going AFK marks activity as known."""
        sm = StateManager()
        now = datetime.now(timezone.utc)

        sm.handle_afk_transition(AfkState.AFK, now, reason="User idle")

        assert sm.last_known_tick == now
        assert sm.last_tick == now
        assert sm.last_not_afk is None

    def test_returning_from_afk_sets_last_not_afk(self):
        """Test that returning from AFK sets last_not_afk."""
        sm = StateManager()
        now = datetime.now(timezone.utc)

        # Go AFK then return
        sm.handle_afk_transition(AfkState.AFK, now - timedelta(minutes=10))
        sm.handle_afk_transition(AfkState.ACTIVE, now, reason="User returned")

        assert sm.last_not_afk == now
        assert sm.is_afk() is False


class TestStatistics:
    """Test statistics tracking."""

    def test_add_tag_time(self):
        """Test adding time to tags."""
        stats = TimeStats()

        stats.add_tag_time("work", timedelta(minutes=5))
        stats.add_tag_time("work", timedelta(minutes=3))
        stats.add_tag_time("break", timedelta(minutes=2))

        assert stats.tags_accumulated_time["work"] == timedelta(minutes=8)
        assert stats.tags_accumulated_time["break"] == timedelta(minutes=2)

    def test_total_time(self):
        """Test total time calculation."""
        stats = TimeStats()

        stats.add_known_time(timedelta(minutes=10))
        stats.add_unknown_time(timedelta(minutes=5))

        assert stats.total_time() == timedelta(minutes=15)

    def test_get_dominant_tags(self):
        """Test getting tags above threshold."""
        sm = StateManager()

        sm.stats.add_tag_time("work", timedelta(minutes=10))
        sm.stats.add_tag_time("coding", timedelta(minutes=8))
        sm.stats.add_tag_time("meeting", timedelta(minutes=3))

        dominant = sm.get_dominant_tags(min_time=timedelta(minutes=5))

        assert dominant == {"work", "coding"}


class TestDebugging:
    """Test debugging conftest."""

    def test_get_state_summary(self):
        """Test state summary for debugging."""
        sm = StateManager()
        now = datetime.now(timezone.utc)

        sm.set_afk_state(AfkState.ACTIVE)
        sm.update_time_bounds(last_tick=now)
        sm.stats.add_tag_time("work", timedelta(minutes=5))

        summary = sm.get_state_summary()

        assert summary["afk_state"] == "active"
        assert summary["is_afk"] is False
        assert "accumulated_tags" in summary
        assert summary["accumulated_tags"]["work"] == "0:05:00"
```

---

### Phase 2: Integrate StateManager (Week 2)

#### Step 2.1: Update Exporter to Use StateManager

Modify `main.py`:

```python
@dataclass
class Exporter:
    """
    Main exporter class - now delegates state management to StateManager.
    """

    # Remove old state fields and replace with StateManager
    state: StateManager = field(default_factory=StateManager)

    # Keep TimeWarrior info (not part of state management)
    timew_info: dict = None

    # ... rest of fields ...

    def set_known_tick_stats(self, start=None, end=None, event=None, tags=set(),
                             manual=False, reset_accumulator=True,
                             retain_accumulator=False):
        """
        DEPRECATED: Use state.record_export() instead.

        This method is kept for backward compatibility during refactoring.
        """
        if event and not start:
            start = event['timestamp']
        if event and not end:
            end = event['timestamp'] + event['duration']
        if start and not end:
            end = start

        # Delegate to state manager
        self.state.record_export(
            start=start,
            end=end,
            tags=tags,
            manual=manual,
            reset_stats=reset_accumulator,
            retain_tags=tags if retain_accumulator else None,
            stickyness_factor=STICKYNESS_FACTOR if retain_accumulator else 0.0
        )
```

#### Step 2.2: Update Methods to Use state.* Instead of self.*

Replace:
- `self.afk` → `self.state.is_afk()`
- `self.last_tick` → `self.state.last_tick`
- `self.tags_accumulated_time` → `self.state.stats.tags_accumulated_time`
- etc.

---

### Phase 3: Remove Old Code (Week 3)

1. Remove deprecated `set_known_tick_stats()` wrapper
2. Remove old state fields from Exporter dataclass
3. Update all call sites to use StateManager API
4. Remove old TODO comments about state management

---

## Migration Strategy

### Step-by-Step Migration

1. **Week 1, Day 1-2**: Implement `StateManager` class and `TimeStats` class
2. **Week 1, Day 3-4**: Write comprehensive tests (aim for 100% coverage)
3. **Week 1, Day 5**: Add `StateManager` to `Exporter` as new field (keep old fields)
4. **Week 2, Day 1-2**: Update `set_known_tick_stats()` to delegate to StateManager
5. **Week 2, Day 3-4**: Update `_afk_change_stats()` and `check_and_handle_afk_state_change()`
6. **Week 2, Day 5**: Update `ensure_tag_exported()` to use StateManager
7. **Week 3, Day 1-2**: Update remaining methods to use StateManager
8. **Week 3, Day 3**: Remove old fields and deprecated wrappers
9. **Week 3, Day 4**: Run full test suite and fix any issues
10. **Week 3, Day 5**: Code review and documentation updates

### Testing Strategy

- **Unit tests**: Test StateManager in isolation (see above)
- **Integration tests**: Test that Exporter still works with StateManager
- **Regression tests**: Ensure all 97 existing tests still pass
- **Manual testing**: Run against real ActivityWatch data

### Backward Compatibility

During migration, both old and new state will coexist:

```python
# Old way (deprecated)
self.afk = True

# New way
self.state.set_afk_state(AfkState.AFK, reason="User idle")

# Transition wrapper to keep old code working
@property
def afk(self):
    return self.state.is_afk()

@afk.setter
def afk(self, value):
    warnings.warn("Direct afk assignment is deprecated, use state.set_afk_state()")
    if value:
        self.state.set_afk_state(AfkState.AFK)
    else:
        self.state.set_afk_state(AfkState.ACTIVE)
```

---

## Benefits After Refactoring

### 1. **Single Source of Truth**
- All state modifications go through StateManager
- Easy to add logging/debugging for state changes
- Can trace all state transitions

### 2. **Explicit State Machine**
- AFK state is now an enum with clear transitions
- Validation ensures only valid transitions occur
- Easy to visualize and document

### 3. **Testability**
- StateManager can be tested in isolation
- Mock StateManager for testing Exporter
- Easy to set up specific state for tests

### 4. **Debugging**
- `get_state_summary()` shows complete state at any time
- Logging shows all state transitions with reasons
- Invariant checking catches bugs early

### 5. **Maintainability**
- Clear separation of concerns
- Easy to add new state variables
- Less risk of bugs when modifying state logic

---

## Success Metrics

After refactoring:

- ✅ All 97 tests pass
- ✅ StateManager has 100% test coverage
- ✅ No direct assignments to state variables (all go through StateManager)
- ✅ All state transitions are logged
- ✅ No TODO comments about state management
- ✅ `afk` is no longer a tri-state (None/True/False), but proper enum
- ✅ Time boundaries have invariant checking
- ✅ Statistics can be queried without direct field access

---

## Risk Mitigation

### Risks

1. **Breaking existing functionality**: Changing core state management could break things
2. **Performance**: Additional validation might slow things down
3. **Complexity**: New abstraction might be harder to understand initially

### Mitigation

1. **Incremental migration**: Keep old code working during transition
2. **Comprehensive testing**: Write tests first, then refactor
3. **Disable validation in production**: Use `enable_validation=False` if needed
4. **Documentation**: Document StateManager API clearly
5. **Code review**: Get feedback before removing old code

---

*Last updated: 2025-12-10*
