# Exporter Class Refactoring Plan

**Status:** Planning Phase
**Target Completion:** 2-3 weeks
**Priority:** High (from REFACTORING_PRIORITIES.md #5)

---

## Executive Summary

The current `Exporter` class is a "God Class" with 1475 lines handling all aspects of the export workflow. This refactoring will split it into focused, single-responsibility components with clean interfaces, making the codebase more maintainable, testable, and extensible.

**Critical Design Goal:** Keep TimeWarrior logic completely isolated to enable future migration to `aw_export_tags` (supporting multiple time tracking backends like Toggl, Clockify, etc.).

---

## Current State Analysis

### Problems with Current Architecture

**File:** `src/aw_export_timewarrior/main.py:207-1682`

```
Exporter (1475 lines)
├── Data Fetching (ActivityWatch client, buckets, events)
├── Tag Extraction (app, browser, editor, AFK matching)
├── State Management (counters, ticks, AFK state)
├── TimeWarrior Integration (timew commands, retag, get info)
├── Business Logic (tick loop, activity finding, export)
├── Comparison/Diff (compare with timew, generate fixes)
├── Reporting (unmatched events, statistics)
└── Configuration (loading, validation)
```

### Key Issues

1. **Single Responsibility Violation:** One class doing 8+ different things
2. **Hard to Test:** Requires mocking entire world for unit tests
3. **TimeWarrior Coupling:** Timew logic scattered throughout, hard to extract
4. **Future-Proofing:** Cannot easily support other time trackers
5. **Cognitive Load:** 60+ attributes, impossible to understand at a glance
6. **Modification Risk:** Changing one aspect affects everything

---

## Target Architecture

### High-Level Component Structure

```
┌──────────────────────────────────────────────────────────┐
│                   CLI Layer (cli.py)                      │
│              Argument parsing, user interaction           │
└────────────────────┬─────────────────────────────────────┘
                     │
                     v
┌──────────────────────────────────────────────────────────┐
│              Orchestrator (Exporter)                      │
│         Coordinates workflow, minimal logic               │
└─────┬──────┬──────┬──────┬──────┬──────┬──────┬─────────┘
      │      │      │      │      │      │      │
      v      v      v      v      v      v      v
   ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐
   │ AW │ │Tag │ │Stat│ │Time│ │Comp│ │Rept│ │Cfg │
   │Fetc│ │Extr│ │eMgr│ │Back│ │arer│ │ortr│ │    │
   │her │ │actr│ │    │ │end │ │    │ │    │ │    │
   └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘
```

### Component Responsibilities

| Component | File | Responsibility | Lines (est.) |
|-----------|------|----------------|--------------|
| **EventFetcher** | `aw_client.py` | Fetch events from ActivityWatch | 200 |
| **TagExtractor** | `tag_extractor.py` | Extract tags from events using rules | 400 |
| **StateManager** | `state.py` | Track state, counters, statistics | ✅ Exists (360) |
| **TimeTracker (ABC)** | `time_tracker.py` | Abstract interface for time tracking | 50 |
| **TimewTracker** | `timew_tracker.py` | TimeWarrior-specific implementation | 200 |
| **Comparer** | `comparer.py` | Compare AW vs TimeWarrior intervals | 250 |
| **Reporter** | `reporter.py` | Generate reports, show unmatched | 150 |
| **Exporter** | `exporter.py` | Orchestrate workflow, minimal logic | 300 |

**Total:** ~1910 lines across 8 files (vs 1475 in one file)
**Benefit:** Each file is focused, testable, and under 400 lines

---

## Detailed Component Design

### 1. EventFetcher (`aw_client.py`)

**Purpose:** Isolate all ActivityWatch data access

```python
"""ActivityWatch event fetching and bucket management."""

from datetime import datetime
from typing import Any


class EventFetcher:
    """Fetches events from ActivityWatch (or test data).

    Responsible for:
    - Connecting to ActivityWatch
    - Managing buckets (window, AFK, browser, editor)
    - Fetching events with time ranges
    - Finding corresponding sub-events (browser URLs, editor files)
    - Test data loading
    """

    def __init__(
        self,
        test_data: dict[str, Any] | None = None,
        client_name: str = "aw-export"
    ):
        """Initialize event fetcher.

        Args:
            test_data: Optional test data (avoids AW connection)
            client_name: ActivityWatch client name
        """
        if test_data:
            self.buckets = test_data.get('buckets', {})
            self.aw = None
        else:
            from aw_client import ActivityWatchClient
            self.aw = ActivityWatchClient(client_name=client_name)
            self.buckets = self.aw.get_buckets()

        self._init_bucket_mappings()

    def _init_bucket_mappings(self) -> None:
        """Create lookup structures for bucket access."""
        from collections import defaultdict

        self.bucket_by_client = defaultdict(list)
        self.bucket_short = {}

        for bucket_id, bucket in self.buckets.items():
            # Parse last_updated timestamp
            lu = bucket.get('last_updated')
            if lu:
                bucket['last_updated_dt'] = datetime.fromisoformat(lu)

            # Index by client type
            client = bucket['client']
            self.bucket_by_client[client].append(bucket_id)

            # Short name lookup (e.g., "aw-watcher-window" -> bucket)
            bucket_short = bucket_id[:bucket_id.find('_')]
            self.bucket_short[bucket_short] = bucket

    def get_events(
        self,
        bucket_id: str,
        start: datetime,
        end: datetime
    ) -> list[dict]:
        """Fetch events from a bucket.

        Args:
            bucket_id: Bucket identifier
            start: Start time (inclusive)
            end: End time (exclusive)

        Returns:
            List of events (dicts with timestamp, duration, data)
        """
        if self.aw:
            return self.aw.get_events(bucket_id, start=start, end=end)
        else:
            # Test data path
            return self._get_events_from_test_data(bucket_id, start, end)

    def get_corresponding_event(
        self,
        window_event: dict,
        bucket_id: str,
        ignorable: bool = False
    ) -> dict | None:
        """Find corresponding sub-event (browser URL, editor file).

        Args:
            window_event: Main window event
            bucket_id: Sub-event bucket (browser/editor)
            ignorable: Whether to ignore timing mismatches

        Returns:
            Corresponding event or None
        """
        # Implementation from current get_corresponding_event()
        # Lines 770-830 in current main.py
        ...

    def check_bucket_freshness(self, warn_threshold: float = 300.0) -> None:
        """Check if buckets have recent data.

        Args:
            warn_threshold: Warn if bucket older than this (seconds)
        """
        # Implementation from current check_bucket_updated()
        # Lines 184-204 in current main.py
        ...

    def get_window_bucket(self) -> str:
        """Get window watcher bucket ID."""
        return self.bucket_by_client['aw-watcher-window'][0]

    def get_afk_bucket(self) -> str:
        """Get AFK watcher bucket ID."""
        return self.bucket_by_client['aw-watcher-afk'][0]
```

**Key Benefits:**
- All AW interaction in one place
- Easy to mock for testing
- Can swap for other data sources
- Clear API surface

---

### 2. TagExtractor (`tag_extractor.py`)

**Purpose:** Determine tags for events using configured rules

```python
"""Tag extraction from ActivityWatch events."""

from typing import Any


class TagExtractor:
    """Extracts tags from events using configured rules.

    Responsible for:
    - Matching app/title against configured patterns
    - Extracting browser URL-based tags
    - Extracting editor file/project-based tags
    - Handling AFK status
    - Applying retagging rules
    - Checking exclusive tag groups
    """

    def __init__(self, config: dict, event_fetcher: 'EventFetcher'):
        """Initialize tag extractor.

        Args:
            config: Configuration dictionary with tag rules
            event_fetcher: EventFetcher for getting sub-events
        """
        self.config = config
        self.fetcher = event_fetcher

        # Cache processed config for efficiency
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns from config."""
        import re

        self.compiled_patterns = {}

        # Compile all regex patterns from config
        for category, rules in self.config.get('tags', {}).items():
            # ... compile patterns ...

    def get_tags(self, event: dict) -> set[str] | None | False:
        """Determine tags for an event.

        Returns:
            set[str]: Tags if matched
            None: Event should be ignored (too short)
            False: No matching rules found
        """
        # Try each extraction method in order
        for method in [
            self.get_afk_tags,
            self.get_app_tags,
            self.get_browser_tags,
            self.get_editor_tags
        ]:
            result = method(event)
            if result is not None and result is not False:
                return result

        return False  # No rules matched

    def get_afk_tags(self, event: dict) -> set[str] | False:
        """Extract AFK status tags.

        Implementation from current get_afk_tags()
        Lines 831-836 in current main.py
        """
        ...

    def get_app_tags(self, event: dict) -> set[str] | False:
        """Extract tags from app/title matching.

        Implementation from current get_app_tags()
        Lines 838-875 in current main.py
        """
        ...

    def get_browser_tags(self, event: dict) -> set[str] | False:
        """Extract tags from browser URL matching.

        Implementation from current get_browser_tags()
        Lines 877-954 in current main.py
        """
        ...

    def get_editor_tags(self, event: dict) -> set[str] | False:
        """Extract tags from editor file/project matching.

        Implementation from current get_editor_tags()
        Lines 956-1036 in current main.py
        """
        ...

    def apply_retag_rules(self, tags: set[str]) -> set[str]:
        """Apply retagging rules to expand tags.

        Implementation from retag_by_rules()
        Lines 131-158 in current main.py
        """
        ...

    def check_exclusive_groups(self, tags: set[str]) -> bool:
        """Check if tags violate exclusive group rules.

        Returns:
            True if tags are valid (no conflicts)

        Implementation from exclusive_overlapping()
        Lines 107-129 in current main.py
        """
        ...
```

**Key Benefits:**
- All tag logic centralized
- Easy to add new tag sources
- Testable in isolation
- Config changes don't affect other components

---

### 3. TimeTracker Interface (`time_tracker.py`)

**Purpose:** Abstract interface for any time tracking backend

```python
"""Abstract interface for time tracking backends."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class TimeTracker(ABC):
    """Abstract base class for time tracking backends.

    This interface allows aw-export to work with multiple time tracking
    tools (TimeWarrior, Toggl, Clockify, etc.) by providing a common API.

    Future: When migrating to aw_export_tags, implementations will be
    pluggable backends selected by user configuration.
    """

    @abstractmethod
    def get_current_tracking(self) -> dict[str, Any] | None:
        """Get currently active tracking entry.

        Returns:
            Dictionary with:
                - 'id': Entry identifier
                - 'start': Start timestamp (datetime)
                - 'tags': Set of tags
            Or None if nothing is being tracked
        """
        pass

    @abstractmethod
    def start_tracking(
        self,
        tags: set[str],
        start_time: datetime
    ) -> None:
        """Start tracking with tags.

        Args:
            tags: Tags to track
            start_time: When to start tracking from
        """
        pass

    @abstractmethod
    def stop_tracking(self) -> None:
        """Stop current tracking."""
        pass

    @abstractmethod
    def retag(self, tags: set[str]) -> None:
        """Change tags on current entry.

        Args:
            tags: New tags to apply
        """
        pass

    @abstractmethod
    def get_intervals(
        self,
        start: datetime,
        end: datetime
    ) -> list[dict[str, Any]]:
        """Get tracked intervals in time range.

        Args:
            start: Range start
            end: Range end

        Returns:
            List of intervals with 'start', 'end', 'tags'
        """
        pass

    @abstractmethod
    def track_interval(
        self,
        start: datetime,
        end: datetime,
        tags: set[str]
    ) -> None:
        """Record a past interval (for diff/fix mode).

        Args:
            start: Interval start
            end: Interval end
            tags: Tags for interval
        """
        pass


class DryRunTracker(TimeTracker):
    """No-op implementation for dry-run mode.

    Simulates tracking without actually calling any backend.
    Useful for testing and previewing changes.
    """

    def __init__(self):
        self.current_tracking = None
        self.intervals = []

    def get_current_tracking(self) -> dict[str, Any] | None:
        return self.current_tracking

    def start_tracking(self, tags: set[str], start_time: datetime) -> None:
        self.current_tracking = {
            'id': len(self.intervals) + 1,
            'start': start_time,
            'tags': tags
        }
        print(f"DRY RUN: Would start tracking {tags} at {start_time}")

    def stop_tracking(self) -> None:
        if self.current_tracking:
            print(f"DRY RUN: Would stop tracking {self.current_tracking['tags']}")
            self.current_tracking = None

    def retag(self, tags: set[str]) -> None:
        if self.current_tracking:
            print(f"DRY RUN: Would retag to {tags}")
            self.current_tracking['tags'] = tags

    def get_intervals(self, start: datetime, end: datetime) -> list[dict]:
        return [
            i for i in self.intervals
            if i['start'] >= start and i['end'] <= end
        ]

    def track_interval(
        self,
        start: datetime,
        end: datetime,
        tags: set[str]
    ) -> None:
        self.intervals.append({
            'start': start,
            'end': end,
            'tags': tags
        })
        print(f"DRY RUN: Would track {tags} from {start} to {end}")
```

**Key Benefits:**
- **Future-Proof:** Easy to add Toggl, Clockify, etc.
- **Testable:** DryRunTracker for all tests
- **Clear Contract:** What any backend must provide
- **Isolation:** TimeWarrior knowledge only in TimewTracker

---

### 4. TimewTracker (`timew_tracker.py`)

**Purpose:** TimeWarrior-specific implementation (MINIMAL AND ISOLATED)

```python
"""TimeWarrior-specific time tracking implementation."""

import json
import subprocess
from datetime import datetime
from typing import Any

from .time_tracker import TimeTracker


class TimewTracker(TimeTracker):
    """TimeWarrior backend implementation.

    This is the ONLY place that knows about TimeWarrior commands.
    All timew interaction goes through this class.

    When migrating to aw_export_tags, this becomes one of many
    pluggable backend implementations.
    """

    def __init__(self, grace_time: float = 10.0):
        """Initialize TimeWarrior tracker.

        Args:
            grace_time: Seconds to wait after timew commands
        """
        self.grace_time = grace_time
        self._current_cache = None  # Cache current tracking

    def _run_timew(self, args: list[str]) -> subprocess.CompletedProcess:
        """Execute a timew command.

        Args:
            args: Command arguments (e.g., ['start', 'tag1', 'tag2'])

        Returns:
            Completed process
        """
        import time

        cmd = ['timew'] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )

        # Wait grace period for timew to settle
        time.sleep(self.grace_time)

        # Invalidate cache
        self._current_cache = None

        return result

    def get_current_tracking(self) -> dict[str, Any] | None:
        """Get current TimeWarrior tracking state.

        Implementation from get_timew_info()
        Lines 1366-1391 in current main.py
        """
        if self._current_cache:
            return self._current_cache

        try:
            result = subprocess.check_output(
                ['timew', 'get', 'dom.active.json'],
                stderr=subprocess.DEVNULL
            )
            data = json.loads(result)

            # Parse into standard format
            tracking = {
                'id': data.get('id'),
                'start': datetime.strptime(
                    data['start'],
                    '%Y%m%dT%H%M%SZ'
                ).replace(tzinfo=datetime.timezone.utc),
                'tags': set(data.get('tags', []))
            }

            self._current_cache = tracking
            return tracking

        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            return None

    def start_tracking(self, tags: set[str], start_time: datetime) -> None:
        """Start TimeWarrior tracking.

        Args:
            tags: Tags to track
            start_time: When to start from
        """
        args = ['start'] + list(tags) + [
            start_time.astimezone().strftime('%FT%H:%M:%S')
        ]
        self._run_timew(args)

    def stop_tracking(self) -> None:
        """Stop TimeWarrior tracking."""
        self._run_timew(['stop'])

    def retag(self, tags: set[str]) -> None:
        """Retag current TimeWarrior interval.

        Implementation from timew_retag()
        Lines 1393-1427 in current main.py
        """
        args = ['retag', '@1'] + list(tags)
        self._run_timew(args)

    def get_intervals(
        self,
        start: datetime,
        end: datetime
    ) -> list[dict[str, Any]]:
        """Get TimeWarrior intervals in time range.

        Implementation from fetch_timew_intervals()
        Lines in compare.py
        """
        # Use timew export to get intervals as JSON
        result = subprocess.run(
            [
                'timew', 'export',
                start.strftime('%Y%m%dT%H%M%SZ'),
                end.strftime('%Y%m%dT%H%M%SZ')
            ],
            capture_output=True,
            text=True,
            check=True
        )

        data = json.loads(result.stdout)

        # Convert to standard format
        intervals = []
        for entry in data:
            intervals.append({
                'start': datetime.strptime(
                    entry['start'],
                    '%Y%m%dT%H%M%SZ'
                ).replace(tzinfo=datetime.timezone.utc),
                'end': datetime.strptime(
                    entry.get('end', entry['start']),
                    '%Y%m%dT%H%M%SZ'
                ).replace(tzinfo=datetime.timezone.utc) if 'end' in entry else None,
                'tags': set(entry.get('tags', [])),
                'id': entry.get('id')
            })

        return intervals

    def track_interval(
        self,
        start: datetime,
        end: datetime,
        tags: set[str]
    ) -> None:
        """Record a past interval in TimeWarrior.

        Args:
            start: Interval start
            end: Interval end
            tags: Tags for interval
        """
        args = [
            'track',
            start.strftime('%Y%m%dT%H%M%SZ'),
            'to',
            end.strftime('%Y%m%dT%H%M%SZ')
        ] + list(tags)

        self._run_timew(args)
```

**CRITICAL:** This is the ONLY file that imports or calls `timew`. All TimeWarrior knowledge is isolated here.

**Lines of Code:** ~200 (vs currently scattered across 500+ lines)

---

### 5. Comparer (`comparer.py`)

**Purpose:** Compare ActivityWatch expectations vs actual time tracker state

```python
"""Comparison logic for AW intervals vs time tracker intervals."""

from datetime import datetime
from typing import Any


class Comparer:
    """Compares suggested intervals with actual tracked intervals.

    Responsible for:
    - Comparing two sets of intervals
    - Identifying missing, extra, and mismatched intervals
    - Generating fix commands
    - Formatting diff output
    """

    def __init__(self, time_tracker: 'TimeTracker'):
        """Initialize comparer.

        Args:
            time_tracker: Time tracker backend for getting actual intervals
        """
        self.tracker = time_tracker

    def compare_intervals(
        self,
        suggested: list[dict],
        start: datetime,
        end: datetime
    ) -> dict[str, Any]:
        """Compare suggested intervals with actual tracking.

        Args:
            suggested: Intervals from ActivityWatch processing
            start: Comparison range start
            end: Comparison range end

        Returns:
            Comparison results with missing, extra, mismatched

        Implementation from compare_intervals()
        Lines 110-161 in compare.py
        """
        actual = self.tracker.get_intervals(start, end)

        # Implementation...
        return {
            'missing': [],
            'extra': [],
            'mismatched': [],
            'matching': []
        }

    def generate_fix_commands(
        self,
        comparison: dict[str, Any]
    ) -> list[str]:
        """Generate commands to fix differences.

        Implementation from generate_fix_commands()
        Lines 244-336 in compare.py
        """
        ...

    def format_diff_output(
        self,
        comparison: dict[str, Any],
        show_timeline: bool = False
    ) -> str:
        """Format comparison results for display.

        Implementation from format_diff_output()
        Lines 164-242 in compare.py
        """
        ...
```

---

### 6. Reporter (`reporter.py`)

**Purpose:** Generate reports and statistics

```python
"""Reporting and statistics generation."""

from typing import Any


class Reporter:
    """Generates reports and statistics.

    Responsible for:
    - Collecting unmatched events
    - Generating activity reports
    - Formatting statistics
    - Export summaries
    """

    def __init__(self):
        self.unmatched_events = []

    def record_unmatched(self, event: dict) -> None:
        """Record an event that didn't match any rules."""
        self.unmatched_events.append(event)

    def show_unmatched_report(self) -> None:
        """Display report of unmatched events.

        Implementation from show_unmatched_events_report()
        Lines 1560-1591 in current main.py
        """
        ...

    def generate_activity_report(
        self,
        event_fetcher: 'EventFetcher',
        tag_extractor: 'TagExtractor',
        start: datetime,
        end: datetime,
        format: str = 'table'
    ) -> None:
        """Generate detailed activity report.

        Uses existing report.py functionality
        """
        from .report import collect_report_data, format_as_table

        # Implementation...
```

---

### 7. Exporter (Orchestrator)

**Purpose:** Coordinate the workflow, minimal business logic

```python
"""Main export orchestrator."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .aw_client import EventFetcher
from .comparer import Comparer
from .reporter import Reporter
from .state import StateManager
from .tag_extractor import TagExtractor
from .time_tracker import TimeTracker
from .timew_tracker import TimewTracker, DryRunTracker


@dataclass
class Exporter:
    """Orchestrates export from ActivityWatch to time tracking backend.

    This is a thin coordination layer that delegates all actual work
    to specialized components. It should contain minimal logic itself.

    Responsibilities:
    - Initialize and wire together components
    - Implement tick loop
    - Coordinate component interactions
    - Handle dry-run vs real modes
    """

    # Configuration
    config: dict = None
    config_path: str = None

    # Display/debug options
    dry_run: bool = False
    verbose: bool = False
    show_diff: bool = False
    show_unmatched: bool = False
    enable_pdb: bool = False
    enable_assert: bool = True

    # Time boundaries
    start_time: datetime = None
    end_time: datetime = None

    # Test data
    test_data: dict = None

    # Components (created in __post_init__)
    event_fetcher: EventFetcher = field(init=False)
    tag_extractor: TagExtractor = field(init=False)
    state: StateManager = field(default_factory=StateManager)
    tracker: TimeTracker = field(init=False)
    comparer: Comparer = field(init=False)
    reporter: Reporter = field(init=False)

    def __post_init__(self):
        """Initialize components."""
        # Load config
        if not self.config:
            from .config import load_config
            self.config = load_config(self.config_path)

        # Create components
        self.event_fetcher = EventFetcher(
            test_data=self.test_data,
            client_name="aw-export-test" if self.dry_run else "aw-export"
        )

        self.tag_extractor = TagExtractor(
            config=self.config,
            event_fetcher=self.event_fetcher
        )

        # Time tracker backend
        if self.dry_run:
            self.tracker = DryRunTracker()
        else:
            self.tracker = TimewTracker(
                grace_time=self.config.get('grace_time', 10.0)
            )

        self.comparer = Comparer(time_tracker=self.tracker)
        self.reporter = Reporter()

    def tick(self, process_all: bool = False) -> bool:
        """Process one iteration of event synchronization.

        This is the main workflow method. It delegates to components:
        1. event_fetcher: Get events from ActivityWatch
        2. tag_extractor: Determine tags for events
        3. state: Track progress and statistics
        4. tracker: Update time tracking backend

        Args:
            process_all: Process all events until end_time

        Returns:
            True if should continue, False if done

        Implementation from current tick()
        Lines 1429-1495 in current main.py

        Key changes:
        - Delegate to components instead of doing work inline
        - Business logic extracted to helper methods
        """
        # Initialize if first tick
        if not self.state.last_tick:
            self._initialize_from_tracker()

        # Find and process next activity
        if process_all:
            while self._process_next_activity():
                pass
            return False
        else:
            return self._process_next_activity()

    def _initialize_from_tracker(self) -> None:
        """Initialize state from current tracker state."""
        current = self.tracker.get_current_tracking()
        if current:
            self.state.last_tick = current['start']
            self.state.last_known_tick = current['start']
            self.state.last_start_time = current['start']

    def _process_next_activity(self) -> bool:
        """Find and process next activity to export.

        Simplified version of find_next_activity()
        Delegates actual work to components
        """
        # Get events from ActivityWatch
        window_id = self.event_fetcher.get_window_bucket()
        events = self.event_fetcher.get_events(
            window_id,
            start=self.state.last_tick,
            end=self.end_time or datetime.now()
        )

        # Process each event
        for event in events:
            # Ask tag extractor for tags
            tags = self.tag_extractor.get_tags(event)

            if tags is None:
                # Ignored (too short)
                continue

            if tags is False:
                # No match - report if enabled
                if self.show_unmatched:
                    self.reporter.record_unmatched(event)
                continue

            # Export tags to tracker
            self.ensure_tag_exported(tags, event)
            return True

        return False

    def ensure_tag_exported(self, tags: set[str], event: dict) -> None:
        """Ensure tags are exported to time tracker.

        Simplified version of current ensure_tag_exported()
        Delegates to tracker instead of calling timew directly
        """
        # Update state
        self.state.set_known_tick_stats(...)
        self.state.stats.reset(retain_tags=tags)

        # Get current tracking
        current = self.tracker.get_current_tracking()

        # Determine if we need to update
        if self._should_update_tracking(current, tags):
            # Stop old, start new
            if current:
                self.tracker.stop_tracking()

            self.tracker.start_tracking(tags, event['timestamp'])

    def _should_update_tracking(
        self,
        current: dict | None,
        new_tags: set[str]
    ) -> bool:
        """Determine if tracking needs updating."""
        if not current:
            return True

        if 'override' in current['tags']:
            return False

        if new_tags == current['tags']:
            return False

        return True

    def run_comparison(self) -> dict:
        """Run comparison mode (diff).

        Delegates to comparer component
        """
        # Get suggested intervals from processing
        suggested = self._get_suggested_intervals()

        # Compare with tracker
        comparison = self.comparer.compare_intervals(
            suggested,
            self.start_time,
            self.end_time
        )

        # Show results if requested
        if self.show_diff:
            output = self.comparer.format_diff_output(
                comparison,
                show_timeline=self.show_timeline
            )
            print(output)

        return comparison
```

**Key Points:**
- ~300 lines (down from 1475)
- Minimal logic - mostly delegation
- Clear workflow visible in tick()
- Easy to understand and modify

---

## Migration Strategy

### Phase 1: Extract Components (Week 1)

**Goal:** Create new component files without breaking existing code

**Tasks:**

1. **Create EventFetcher** (Day 1-2)
   - New file: `src/aw_export_timewarrior/aw_client.py`
   - Copy AW-related methods from Exporter
   - Add tests: `tests/test_aw_client.py`
   - Don't integrate yet - just ensure it works standalone

2. **Create TagExtractor** (Day 2-3)
   - New file: `src/aw_export_timewarrior/tag_extractor.py`
   - Copy tag extraction methods from Exporter
   - Add tests: `tests/test_tag_extractor.py` (can reuse existing test_tag_extraction.py)
   - Standalone validation

3. **Create TimeTracker Interface** (Day 3-4)
   - New file: `src/aw_export_timewarrior/time_tracker.py`
   - Define ABC with DryRunTracker
   - Add tests: `tests/test_time_tracker.py`

4. **Create TimewTracker** (Day 4-5)
   - New file: `src/aw_export_timewarrior/timew_tracker.py`
   - **Extract ALL timew logic from main.py and compare.py**
   - This is CRITICAL - no timew knowledge should remain elsewhere
   - Functions to move:
     - `get_timew_info()` → `get_current_tracking()`
     - `timew_run()` → `_run_timew()`
     - `timew_retag()` → `retag()`
     - `fetch_timew_intervals()` → `get_intervals()`
   - Add tests: `tests/test_timew_tracker.py`

**Validation:** Run existing tests - all should still pass (components not integrated yet)

---

### Phase 2: Integration (Week 2)

**Goal:** Wire new components into Exporter

**Tasks:**

1. **Update Exporter __post_init__** (Day 6)
   - Initialize new components
   - Keep old code alongside new components
   - Add feature flag: `USE_NEW_ARCHITECTURE = False`

2. **Migrate tick() method** (Day 7-8)
   - Rewrite `tick()` to use new components
   - Use feature flag to switch between old/new
   - Verify both paths work with tests

3. **Migrate ensure_tag_exported()** (Day 9)
   - Rewrite to use `tracker.start_tracking()` instead of `timew_run()`
   - Use feature flag
   - Test both paths

4. **Migrate find_next_activity()** (Day 10)
   - Rewrite to use `event_fetcher` and `tag_extractor`
   - Simplify control flow
   - Test both paths

**Validation:** All tests pass with both `USE_NEW_ARCHITECTURE=True` and `False`

---

### Phase 3: Cleanup and Finalize (Week 3)

**Goal:** Remove old code, finalize architecture

**Tasks:**

1. **Remove old code** (Day 11-12)
   - Delete old methods from Exporter
   - Remove feature flag
   - Update all call sites

2. **Create Comparer and Reporter** (Day 13-14)
   - Extract comparison logic to `comparer.py`
   - Extract reporting logic to `reporter.py`
   - Update Exporter to use them

3. **Documentation** (Day 15)
   - Update architecture diagrams
   - Document component APIs
   - Update README with new structure
   - Write migration guide for future backends

4. **Final Testing** (Day 16-17)
   - Full test suite
   - Integration tests
   - Manual testing with real data
   - Performance comparison

**Validation:**
- All 200+ tests pass
- No performance regression
- Code coverage maintained/improved

---

## Testing Strategy

### Unit Tests

Each component gets its own test file with comprehensive coverage:

```
tests/
├── test_aw_client.py          # EventFetcher tests
├── test_tag_extractor.py      # TagExtractor tests (reuse existing)
├── test_time_tracker.py       # TimeTracker ABC + DryRunTracker
├── test_timew_tracker.py      # TimewTracker (mock subprocess)
├── test_comparer.py           # Comparer tests (exists, enhance)
├── test_reporter.py           # Reporter tests
└── test_exporter.py           # Orchestration tests
```

### Integration Tests

Test component interactions:

```python
def test_full_export_workflow():
    """Test complete workflow with mocked components."""
    # Given: Mocked EventFetcher, TagExtractor, etc.
    # When: Run tick()
    # Then: Verify correct component calls in sequence
```

### Backwards Compatibility Tests

Ensure behavior doesn't change:

```python
def test_same_output_as_before():
    """Verify new architecture produces same results."""
    # Run with old test data
    # Compare suggested intervals
    # Should be identical
```

---

## Future Extensibility: aw_export_tags

### Vision

With this refactoring, migrating to `aw_export_tags` becomes straightforward:

```
aw_export_tags/
├── core/
│   ├── event_fetcher.py      # Copy from aw_export_timewarrior
│   ├── tag_extractor.py      # Copy from aw_export_timewarrior
│   ├── state.py              # Copy from aw_export_timewarrior
│   └── exporter.py           # Copy from aw_export_timewarrior
├── backends/
│   ├── time_tracker.py       # ABC (copy)
│   ├── timew_tracker.py      # TimeWarrior backend (copy)
│   ├── toggl_tracker.py      # NEW: Toggl backend
│   ├── clockify_tracker.py   # NEW: Clockify backend
│   └── csv_tracker.py        # NEW: CSV export backend
└── cli.py
```

### Configuration Example

```toml
# config.toml for aw_export_tags

[backend]
type = "toggl"  # or "timewarrior", "clockify", "csv"

[backend.toggl]
api_token = "..."
workspace_id = "..."

[backend.timewarrior]
grace_time = 10.0

[tags]
# Same tag configuration works for all backends!
programming = { app = "vscode", add = ["coding", "work"] }
```

### Backend Implementation Example

```python
# backends/toggl_tracker.py

import requests
from .time_tracker import TimeTracker


class TogglTracker(TimeTracker):
    """Toggl Track backend implementation."""

    def __init__(self, api_token: str, workspace_id: str):
        self.api_token = api_token
        self.workspace_id = workspace_id
        self.base_url = "https://api.track.toggl.com/api/v9"

    def get_current_tracking(self) -> dict | None:
        """Get current Toggl time entry."""
        response = requests.get(
            f"{self.base_url}/me/time_entries/current",
            auth=(self.api_token, "api_token")
        )
        # ... convert to standard format ...

    def start_tracking(self, tags: set[str], start_time: datetime) -> None:
        """Start Toggl time entry."""
        payload = {
            "workspace_id": self.workspace_id,
            "start": start_time.isoformat(),
            "tags": list(tags),
            "created_with": "aw-export-tags"
        }
        requests.post(
            f"{self.base_url}/workspaces/{self.workspace_id}/time_entries",
            json=payload,
            auth=(self.api_token, "api_token")
        )

    # ... implement other methods ...
```

**Total effort to add Toggl support:** ~200 lines of code, no changes to core!

---

## Success Criteria

### Code Quality Metrics

- ✅ No single file > 400 lines
- ✅ Exporter class < 350 lines
- ✅ All methods < 50 lines
- ✅ Cyclomatic complexity < 10 per method
- ✅ 100% of functions have type annotations
- ✅ Test coverage > 85%

### Functional Requirements

- ✅ All 200+ existing tests pass
- ✅ No behavior changes (backwards compatible)
- ✅ Performance: No more than 5% slower
- ✅ Memory: No significant increase

### Architectural Requirements

- ✅ **TimeWarrior logic isolated to ONE file** (`timew_tracker.py`)
- ✅ No `timew` mentions outside `timew_tracker.py`
- ✅ Clear component boundaries with documented APIs
- ✅ Components testable in isolation
- ✅ Easy to add new TimeTracker backends

---

## Risks and Mitigation

### Risk 1: Breaking Existing Functionality

**Mitigation:**
- Comprehensive test suite before starting
- Feature flag for dual-path validation
- Incremental migration with validation at each step
- Keep old code until new code proven

### Risk 2: Performance Degradation

**Mitigation:**
- Benchmark current performance
- Profile after each phase
- Component overhead should be minimal (just delegation)
- Optimize if needed (unlikely)

### Risk 3: Schedule Overrun

**Mitigation:**
- Conservative 3-week estimate
- Each phase independently valuable
- Can pause after Phase 1 if needed
- Daily progress tracking

### Risk 4: Incomplete TimeWarrior Isolation

**Mitigation:**
- Strict code review: search for "timew" in all files
- Only `timew_tracker.py` should mention timewarrior
- Automated check in CI: `grep -r "timew" --exclude=timew_tracker.py src/`
- Test with mocked TimeTracker to ensure no direct timew calls

---

## Timeline Summary

| Phase | Duration | Key Deliverable |
|-------|----------|-----------------|
| **Phase 1: Extract** | Week 1 (5 days) | All components created, tested standalone |
| **Phase 2: Integrate** | Week 2 (5 days) | Components wired into Exporter, dual-path validated |
| **Phase 3: Finalize** | Week 3 (5 days) | Old code removed, docs updated, production-ready |
| **Total** | 15 working days | Clean, modular, extensible architecture |

---

## Next Steps

1. **Review this plan** - Gather feedback, adjust as needed
2. **Create tracking issue** - GitHub issue with checklist
3. **Set up branch** - `refactor/split-exporter-class`
4. **Begin Phase 1** - Start with EventFetcher
5. **Daily updates** - Track progress, adjust timeline

---

## Appendix: File Size Comparison

### Before Refactoring

```
src/aw_export_timewarrior/
├── main.py                 1682 lines (EVERYTHING)
├── state.py                 360 lines
├── compare.py               340 lines
├── config.py                 80 lines
└── report.py                350 lines
```

### After Refactoring

```
src/aw_export_timewarrior/
├── exporter.py              300 lines (orchestration only)
├── aw_client.py             200 lines (AW interaction)
├── tag_extractor.py         400 lines (tag matching)
├── time_tracker.py           50 lines (ABC interface)
├── timew_tracker.py         200 lines (ONLY timew code)
├── comparer.py              250 lines (comparison logic)
├── reporter.py              150 lines (reporting)
├── state.py                 360 lines (unchanged)
├── config.py                 80 lines (unchanged)
└── report.py                350 lines (unchanged)
```

**Total:** 2340 lines across 10 focused files (vs 2812 lines across 5 files)

**Key Win:** TimeWarrior knowledge in ONE 200-line file instead of scattered across 1000+ lines

---

**Document Version:** 1.0
**Last Updated:** 2025-12-13
**Author:** AI-assisted refactoring plan
**Status:** Ready for review and implementation
