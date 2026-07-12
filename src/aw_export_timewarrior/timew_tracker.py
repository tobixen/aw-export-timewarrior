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
        cache_ttl: float | None = None,
    ) -> None:
        """Initialize TimeWarrior tracker.

        Args:
            grace_time: Seconds to wait after timew commands (defaults to AW2TW_GRACE_TIME env var or 10)
            capture_commands: Optional list to capture commands for testing
            hide_output: If True, don't print "Running" messages
            cache_ttl: Max age in seconds for the cached current-tracking state
                before it's refetched, so a manual `timew start`/`timew stop` run
                by the user in another terminal is eventually noticed even though
                it doesn't go through `_run_timew` (defaults to AW2TW_CACHE_TTL env
                var or 5)
        """
        if grace_time is None:
            grace_time = float(os.environ.get("AW2TW_GRACE_TIME", 10))
        if cache_ttl is None:
            cache_ttl = float(os.environ.get("AW2TW_CACHE_TTL", 5))
        self.grace_time = grace_time
        self.cache_ttl = cache_ttl
        self.capture_commands = capture_commands
        self.hide_output = hide_output
        self._current_cache: dict[str, Any] | None = None
        self._cache_time: float = 0.0

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

        if result.returncode != 0:
            # Fail loud rather than silently: callers (e.g. ensure_tag_exported)
            # advance internal tracking state assuming the command succeeded, so
            # a swallowed failure (db lock, hook rejection) would desync that
            # state from what TimeWarrior actually recorded.
            detail = f"\n{result.stderr.strip()}" if result.stderr else ""
            raise RuntimeError(
                f"timew command failed (exit {result.returncode}): {' '.join(cmd)}{detail}"
            )

        if show_undo_message and not self.hide_output:
            from .output import user_output

            user_output(
                f"Use timew undo if you don't agree! You have {self.grace_time} seconds to press ctrl^c",
                attrs=["bold"],
            )

        # Wait grace period for timew to settle. This exists to give the user
        # a window to react to the undo message just printed above; with
        # hide_output=True that message is never shown, so sleeping serves no
        # purpose and only slows down batches of commands (e.g. retag.py's
        # bulk retag loop, or a `timew tag`+`untag` pair in retag()).
        if not self.hide_output:
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
        now = time.monotonic()
        if self._current_cache is not None and (now - self._cache_time) < self.cache_ttl:
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
            self._cache_time = now
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

        Uses the atomic `timew retag` command to replace the whole tag set in
        a single call, so a failure (db lock, hook rejection) leaves the
        original tags intact instead of a partially-applied mix (see
        CODE_REVIEW_2026-07-12.md #1: separate `untag`+`tag` commands could
        leave tags stripped with no rollback if the second command failed).

        Args:
            tags: New tags to apply (replaces all existing tags)
        """
        current = self.get_current_tracking()
        current_tags = current["tags"] if current else set()

        if current_tags != tags:
            self._run_timew(["retag", "@1"] + sorted(tags))

    def retag_interval_by_id(self, interval_id: int, tags: set[str]) -> None:
        """Set the tag list on a specific (not necessarily current) interval.

        Unlike retag(), which diffs against the current interval (@1) and
        issues incremental tag/untag commands, this directly replaces the
        tag list on any interval addressed by TimeWarrior's relative `@N`
        scheme via `timew retag`, for bulk maintenance use cases (e.g.
        re-applying rules to historical intervals).

        Args:
            interval_id: TimeWarrior's relative interval id (the N in @N)
            tags: New tags to apply
        """
        self._run_timew(["retag", f"@{interval_id}"] + sorted(tags))

    def get_intervals(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Get TimeWarrior intervals in time range.

        Args:
            start: Range start
            end: Range end

        Returns:
            List of intervals with 'start', 'end', 'tags', 'id'
        """
        start_str = start.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end.astimezone().strftime("%Y-%m-%dT%H:%M:%S")

        try:
            try:
                # Ask timew to narrow the export itself, so we don't parse the
                # entire (potentially huge, ever-growing) database on every call.
                result = subprocess.run(
                    ["timew", "export", start_str, "-", end_str],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError:
                # Older timew versions may not support this range syntax;
                # fall back to exporting everything and filtering below.
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

                # Filter by date range: standard overlap test (interval_start <= end
                # AND interval_end >= start). An ongoing interval (interval_end is
                # None) has no upper bound yet, so treat it as unbounded rather than
                # requiring interval_end to exist - otherwise an ongoing interval
                # that started before `start` is invisible even though it's still
                # running and clearly overlaps the query range.
                effective_end = (
                    interval_end if interval_end is not None else datetime.max.replace(tzinfo=UTC)
                )
                in_range = interval_start <= end and effective_end >= start

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
