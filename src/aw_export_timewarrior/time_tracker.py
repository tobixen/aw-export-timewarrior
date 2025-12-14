"""Abstract interface for time tracking backends.

This module provides the TimeTracker ABC that allows aw-export-timewarrior
to work with multiple time tracking tools (TimeWarrior, Toggl, Clockify, etc.)
through a common API.

Future: When migrating to aw_export_tags, implementations will be
pluggable backends selected by user configuration.
"""

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

    def __init__(self) -> None:
        """Initialize the dry-run tracker."""
        self.current_tracking: dict[str, Any] | None = None
        self.intervals: list[dict[str, Any]] = []

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
        self.current_tracking = {
            'id': len(self.intervals) + 1,
            'start': start_time,
            'tags': tags
        }
        print(f"DRY RUN: Would start tracking {tags} at {start_time}")

    def stop_tracking(self) -> None:
        """Stop simulated tracking."""
        if self.current_tracking:
            print(f"DRY RUN: Would stop tracking {self.current_tracking['tags']}")
            self.current_tracking = None

    def retag(self, tags: set[str]) -> None:
        """Change tags on simulated current entry.

        Args:
            tags: New tags to apply
        """
        if self.current_tracking:
            print(f"DRY RUN: Would retag to {tags}")
            self.current_tracking['tags'] = tags

    def get_intervals(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Get simulated tracked intervals in time range.

        Args:
            start: Range start
            end: Range end

        Returns:
            List of intervals with 'start', 'end', 'tags'
        """
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
        """Record a simulated past interval.

        Args:
            start: Interval start
            end: Interval end
            tags: Tags for interval
        """
        self.intervals.append({
            'start': start,
            'end': end,
            'tags': tags
        })
        print(f"DRY RUN: Would track {tags} from {start} to {end}")
