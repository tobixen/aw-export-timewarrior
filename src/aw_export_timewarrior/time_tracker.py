"""Abstract interface for time tracking backends.

This module provides the TimeTracker ABC that allows aw-export-timewarrior
to work with multiple time tracking tools (TimeWarrior, Toggl, Clockify, etc.)
through a common API.

Future: When migrating to aw_export_tags, implementations will be
pluggable backends selected by user configuration.
"""

import sys
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
    def start_tracking(self, tags: set[str], start_time: datetime) -> None:
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
    def get_intervals(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Get tracked intervals in time range.

        Args:
            start: Range start
            end: Range end

        Returns:
            List of intervals with 'start', 'end', 'tags'
        """
        pass

    @abstractmethod
    def track_interval(self, start: datetime, end: datetime, tags: set[str]) -> None:
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

    def __init__(self, capture_commands: list | None = None, hide_output: bool = False) -> None:
        """Initialize the dry-run tracker.

        Args:
            capture_commands: Optional list to capture commands for testing
            hide_output: If True, don't print "DRY RUN" messages
        """
        self.current_tracking: dict[str, Any] | None = None
        self.intervals: list[dict[str, Any]] = []
        self.capture_commands = capture_commands
        self.hide_output = hide_output

    def get_current_tracking(self) -> dict[str, Any] | None:
        """Get currently active tracking entry.

        Returns:
            The simulated current tracking entry, or None
        """
        return self.current_tracking

    def start_tracking(self, tags: set[str], start_time: datetime) -> None:
        """Start simulated tracking.

        Args:
            tags: Tags to track
            start_time: When to start tracking from
        """
        self.current_tracking = {"id": len(self.intervals) + 1, "start": start_time, "tags": tags}

        # Capture command in same format as TimewTracker
        if self.capture_commands is not None:
            cmd = (
                ["timew", "start"]
                + sorted(tags)
                + [start_time.astimezone().strftime("%Y-%m-%dT%H:%M:%S")]
            )
            self.capture_commands.append(cmd)

        if not self.hide_output:
            print(f"DRY RUN: Would start tracking {tags} at {start_time}", file=sys.stderr)

    def stop_tracking(self) -> None:
        """Stop simulated tracking."""
        if self.current_tracking:
            if self.capture_commands is not None:
                self.capture_commands.append(["timew", "stop"])

            if not self.hide_output:
                print(
                    f"DRY RUN: Would stop tracking {self.current_tracking['tags']}", file=sys.stderr
                )
            self.current_tracking = None

    def retag(self, tags: set[str]) -> None:
        """Change tags on simulated current entry.

        Args:
            tags: New tags to apply
        """
        if self.current_tracking:
            if self.capture_commands is not None:
                self.capture_commands.append(["timew", "tag", "@1"] + sorted(tags))

            if not self.hide_output:
                print(f"DRY RUN: Would retag to {tags}", file=sys.stderr)
            self.current_tracking["tags"] = tags

    def get_intervals(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Get tracked intervals in time range.

        In dry-run mode, returns simulated intervals filtered by time range.

        Args:
            start: Range start
            end: Range end

        Returns:
            List of intervals with 'start', 'end', 'tags'
        """
        # Filter simulated intervals by time range
        filtered = []
        for interval in self.intervals:
            interval_start = interval["start"]
            interval_end = interval.get("end")

            # Include if: interval_start is in range OR interval_end is in range OR interval spans the entire range
            in_range = False
            if start <= interval_start <= end or (interval_end and start <= interval_end <= end):
                in_range = True
            elif interval_end and interval_start < start and interval_end > end:
                # Interval spans the entire range
                in_range = True

            if in_range:
                filtered.append(interval)

        return filtered

    def track_interval(self, start: datetime, end: datetime, tags: set[str]) -> None:
        """Record a simulated past interval.

        Args:
            start: Interval start
            end: Interval end
            tags: Tags for interval
        """
        if self.capture_commands is not None:
            start_str = start.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
            end_str = end.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
            self.capture_commands.append(["timew", "track", start_str, "-", end_str] + sorted(tags))

        self.intervals.append({"start": start, "end": end, "tags": tags})
        print(f"DRY RUN: Would track {tags} from {start} to {end}", file=sys.stderr)
