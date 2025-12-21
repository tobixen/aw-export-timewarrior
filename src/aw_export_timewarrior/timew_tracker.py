"""TimeWarrior-specific time tracking implementation.

This is the ONLY place that knows about TimeWarrior commands.
All timew interaction goes through this class.

When migrating to aw_export_tags, this becomes one of many
pluggable backend implementations.
"""

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from typing import Any

from .time_tracker import TimeTracker


class TimewTracker(TimeTracker):
    """TimeWarrior backend implementation.

    This is the ONLY place that knows about TimeWarrior commands.
    All timew interaction goes through this class.

    When migrating to aw_export_tags, this becomes one of many
    pluggable backend implementations.
    """

    def __init__(
        self,
        grace_time: float | None = None,
        capture_commands: list | None = None,
        hide_output: bool = False,
    ) -> None:
        """Initialize TimeWarrior tracker.

        Args:
            grace_time: Seconds to wait after timew commands (defaults to AW2TW_GRACE_TIME env var or 10)
            capture_commands: Optional list to capture commands for testing
            hide_output: If True, don't print "Running" messages
        """
        if grace_time is None:
            grace_time = float(os.environ.get("AW2TW_GRACE_TIME", 10))
        self.grace_time = grace_time
        self.capture_commands = capture_commands
        self.hide_output = hide_output
        self._current_cache: dict[str, Any] | None = None

    def _run_timew(
        self, args: list[str], show_undo_message: bool = True
    ) -> subprocess.CompletedProcess:
        """Execute a timew command.

        Args:
            args: Command arguments (e.g., ['start', 'tag1', 'tag2'])
            show_undo_message: If True, show the "use timew undo" message

        Returns:
            Completed process
        """
        cmd = ["timew"] + args

        # Capture for testing
        if self.capture_commands is not None:
            self.capture_commands.append(cmd)

        if not self.hide_output:
            from .output import user_output

            user_output(f"Running: {' '.join(cmd)}")

        # Only capture output in test mode (when capture_commands is set)
        # In normal mode, let timew output go to terminal
        result = subprocess.run(
            cmd, capture_output=self.capture_commands is not None, text=True, check=False
        )

        if show_undo_message and not self.hide_output:
            from .output import user_output

            user_output(
                f"Use timew undo if you don't agree! You have {self.grace_time} seconds to press ctrl^c",
                attrs=["bold"],
            )

        # Wait grace period for timew to settle
        time.sleep(self.grace_time)

        # Invalidate cache
        self._current_cache = None

        return result

    def get_current_tracking(self) -> dict[str, Any] | None:
        """Get current TimeWarrior tracking state.

        Returns:
            Dictionary with:
                - 'id': Entry identifier
                - 'start': Start timestamp (datetime with UTC timezone)
                - 'start_dt': Alias for 'start' (for backward compatibility)
                - 'tags': Set of tags
            Or None if nothing is being tracked
        """
        if self._current_cache:
            return self._current_cache

        try:
            result = subprocess.check_output(
                ["timew", "get", "dom.active.json"], stderr=subprocess.DEVNULL
            )
            data = json.loads(result)

            # Parse start time
            start_dt = datetime.strptime(data["start"], "%Y%m%dT%H%M%SZ")
            start_dt = start_dt.replace(tzinfo=UTC)

            # Build tracking info in format compatible with existing code
            tracking = {
                "id": data.get("id"),
                "start": data["start"],  # Keep original string format
                "start_dt": start_dt,  # Parsed datetime
                "tags": set(data.get("tags", [])),
            }

            self._current_cache = tracking
            return tracking

        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            # No active tracking, empty database, or invalid data
            return None

    def start_tracking(self, tags: set[str], start_time: datetime) -> None:
        """Start TimeWarrior tracking.

        Args:
            tags: Tags to track
            start_time: When to start from
        """
        # Convert to local time for timew
        args = ["start"] + sorted(tags) + [start_time.astimezone().strftime("%Y-%m-%dT%H:%M:%S")]
        self._run_timew(args)

    def stop_tracking(self) -> None:
        """Stop TimeWarrior tracking."""
        self._run_timew(["stop"])

    def retag(self, tags: set[str]) -> None:
        """Retag current TimeWarrior interval.

        Args:
            tags: New tags to apply (replaces all existing tags)
        """
        args = ["tag", "@1"] + sorted(tags)
        self._run_timew(args)

    def get_intervals(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Get TimeWarrior intervals in time range.

        Args:
            start: Range start
            end: Range end

        Returns:
            List of intervals with 'start', 'end', 'tags', 'id'
        """
        try:
            # Export all intervals (date range syntax varies by timew version, so export all and filter)
            result = subprocess.run(
                ["timew", "export"],
                capture_output=True,
                text=True,
                check=True,
            )

            data = json.loads(result.stdout)

            # Convert to standard format and filter by date range
            intervals = []
            for entry in data:
                # Parse start time
                interval_start = datetime.strptime(entry["start"], "%Y%m%dT%H%M%SZ")
                interval_start = interval_start.replace(tzinfo=UTC)

                # Parse end time (may not exist for ongoing intervals)
                interval_end = None
                if "end" in entry:
                    interval_end = datetime.strptime(entry["end"], "%Y%m%dT%H%M%SZ")
                    interval_end = interval_end.replace(tzinfo=UTC)

                # Filter by date range
                # Include if: interval_start is in range OR interval_end is in range OR interval spans the entire range
                in_range = False
                if start <= interval_start <= end or interval_end and start <= interval_end <= end:
                    in_range = True
                elif interval_end and interval_start < start and interval_end > end:
                    # Interval spans the entire range
                    in_range = True

                if in_range:
                    intervals.append(
                        {
                            "id": entry.get("id", 0),
                            "start": interval_start,
                            "end": interval_end,
                            "tags": set(entry.get("tags", [])),
                        }
                    )

            return intervals

        except subprocess.CalledProcessError as e:
            # timew export failed
            raise RuntimeError(f"Failed to fetch TimeWarrior intervals: {e}") from e

    def track_interval(self, start: datetime, end: datetime, tags: set[str]) -> None:
        """Record a past interval in TimeWarrior.

        Args:
            start: Interval start
            end: Interval end
            tags: Tags for interval
        """
        # Format times for timew track command
        start_str = start.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end.astimezone().strftime("%Y-%m-%dT%H:%M:%S")

        args = ["track", start_str, "-", end_str] + sorted(tags)

        self._run_timew(args)
