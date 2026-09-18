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
from datetime import UTC, datetime, timedelta
from typing import Any

from .time_tracker import ProtectedIntervalError, TimeTracker
from .utils import effective_end, ts2str


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
        # Whether `timew export <start> - <end>` (ranged export) is supported by
        # the installed timew version. Starts optimistic; get_intervals() sets
        # this to False after the first failure so it doesn't pay a failed
        # subprocess call on every subsequent call for an old install.
        self._ranged_export_supported: bool = True

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
        # The :adjust hint (trailing, so timew parses it as a hint rather than
        # a tag) lets timew clip an existing interval when start_time lands
        # inside history -- e.g. a bedtime/boot-gap AFK event whose true start
        # precedes the current open interval.  Plain `timew start` refuses such
        # a start with "You cannot overlap intervals" (exit 255), which crash-
        # loops the sync daemon.
        #
        # But :adjust on `start` overwrites EVERY interval from start_time to
        # now, regardless of tags (pinned by tests/test_timew_adjust_safety.py
        # against the real binary), so it needs two safeguards:
        #
        # 1. Refuse outright when that would *destroy* manually-curated
        #    (non-'~aw') data -- see _first_protected_interval.
        # 2. When closed history follows start_time, do not use the open-ended
        #    form at all: it would delete the exporter's own already-exported
        #    intervals.  Fill just the hole with the bounded `track` form,
        #    which only touches [start, end].
        intervals = self._overlap_probe(start_time)
        blocking = self._first_protected_interval(start_time, intervals)
        if blocking is not None:
            raise ProtectedIntervalError(
                f"Refusing to start tracking at {ts2str(start_time)}: `timew start "
                f"... :adjust` would overwrite a manually-curated (non-'~aw') "
                f"TimeWarrior interval starting at {ts2str(blocking['start'])} "
                f"({' '.join(sorted(blocking['tags']))}). Resolve the overlap by "
                f"hand (e.g. `timew stop`, or retag it '~aw') if the exporter "
                f"should own that time."
            )
        # Convert to local time for timew.
        next_start = self._next_closed_interval_start(start_time, intervals)
        if next_start is None:
            args = ["start"] + sorted(tags) + [ts2str(start_time), ":adjust"]
        else:
            args = (
                ["track", ts2str(start_time), "-", ts2str(next_start)] + sorted(tags) + [":adjust"]
            )
        self._run_timew(args)

    def _overlap_probe(self, start_time: datetime) -> list[dict[str, Any]]:
        """The intervals `timew start <start_time> :adjust` could touch.

        Normally a `timew export` over the week before ``start_time``, which is
        a subprocess (and, on an install without ranged export, a parse of the
        entire database) per call -- once per activity block in a batch run.

        The shortcut: TimeWarrior never records closed history after the open
        interval (pinned by test_closed_interval_cannot_follow_the_open_one),
        so when the open interval began at or before ``start_time``, every
        closed interval ends at or before it as well and `:adjust` can touch
        nothing but that open interval -- which one `timew get dom.active.json`
        answers, instead of exporting and parsing a week of history.  Anything
        else -- no open interval, or one starting after ``start_time``
        (backfilling into a hole) -- falls back to the full probe.

        The current-tracking cache is deliberately dropped first: a cache_ttl-
        old answer is fine for reporting, but here it would let a manual `timew
        start` from a second ago go unseen, and `:adjust` would swallow the
        interval the full export would have caught.
        """
        self._current_cache = None
        current = self.get_current_tracking()
        if current is not None and current["start_dt"] <= start_time:
            return [
                {
                    "id": current.get("id") or 0,
                    "start": current["start_dt"],
                    "end": None,
                    "tags": current["tags"],
                }
            ]

        return self.get_intervals(start_time - timedelta(days=7), datetime.now(UTC))

    @staticmethod
    def _next_closed_interval_start(
        start_time: datetime, intervals: list[dict[str, Any]]
    ) -> datetime | None:
        """Start of the earliest *closed* interval beginning after ``start_time``.

        ``None`` when nothing closed follows, which is the ordinary live case:
        the exporter appends to the end of history, and the only interval
        `:adjust` can touch is the open one (clipping it is the intent).

        A datetime means the new start lands in a *hole* in existing history.
        The open-ended form would delete everything after it, so the caller
        bounds the command at this timestamp instead.  The open interval is
        deliberately not considered: replacing it is what a takeover is.
        """
        later = [
            interval["start"]
            for interval in intervals
            if interval["end"] is not None and interval["start"] > start_time
        ]
        return min(later) if later else None

    def _first_protected_interval(
        self, start_time: datetime, intervals: list[dict[str, Any]] | None = None
    ) -> dict[str, Any] | None:
        """The first foreign interval `timew start <start_time> :adjust` would destroy.

        `:adjust` on `start` overwrites every interval whose end falls after
        ``start_time``.  The exporter owns intervals tagged '~aw' (the same
        ownership discriminator compare.py uses) and may freely overwrite them;
        a foreign (non-'~aw') interval must never be destroyed.  Return the
        first such interval, or ``None`` when the start is safe.

        The distinction the user asked for is historic vs. current:

        * A *closed* foreign interval is hand-entered history -- protect it
          whenever `:adjust` would touch it at all (``end > start_time``), even
          a partial clip, since that rewrites data with a user-set end.
        * The *ongoing* (open, ``end is None``) foreign interval is the current
          manual activity and may be **stopped** -- but stopping means clipping
          it to ``[interval.start, start_time]``, which only happens when the
          new start falls strictly inside it (``start_time > interval.start``).
          When ``start_time <= interval.start`` `:adjust` would *delete* the
          whole interval, not stop it, so refuse -- e.g. backfilling activity
          from before a still-open manual `timew start` must not wipe it.

        This guards the live `sync` path only, which is the only caller of
        start_tracking().  `diff --apply` builds its own bounded `timew track`
        commands and skips foreign intervals in compare.py.
        """
        if intervals is None:
            intervals = self._overlap_probe(start_time)
        for interval in intervals:
            if "~aw" in interval["tags"]:
                # Exporter-owned -- safe to clip, and never deleted wholesale
                # (see _next_closed_interval_start).
                continue
            end = interval["end"]
            if end is None:
                # Ongoing manual interval: stoppable (clipped) only if the new
                # start lands inside it; otherwise :adjust deletes it wholesale.
                if start_time <= interval["start"]:
                    return interval
                continue
            if end <= start_time:
                # Ends at or before the new start -- untouched by :adjust.
                continue
            # Closed foreign interval that :adjust would clip or delete.
            return interval
        return None

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
        start_str = ts2str(start)
        end_str = ts2str(end)

        # Ask timew to narrow the export itself, so we don't parse the entire
        # (potentially huge, ever-growing) database on every call. Older timew
        # versions may not support this range syntax, so fall back to
        # exporting everything and filtering below - remembered per-instance
        # so an unsupported install doesn't pay a failed subprocess call on
        # every subsequent get_intervals().
        candidates = []
        if self._ranged_export_supported:
            candidates.append((True, ["timew", "export", start_str, "-", end_str]))
        candidates.append((False, ["timew", "export"]))

        try:
            result = None
            ranged_failed = False
            for is_ranged, cmd in candidates:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                    break
                except subprocess.CalledProcessError:
                    if not is_ranged:
                        raise
                    ranged_failed = True

            # Only latch off ranged export when the ranged attempt failed *and*
            # the plain-export fallback then succeeded (result is set): that
            # combination indicates the range *syntax* is unsupported. A
            # transient failure (db lock, hook rejection) would typically also
            # fail the immediate fallback and re-raise, leaving the flag on so
            # the next call retries ranged - rather than permanently degrading
            # every later get_intervals() to a full-DB export after one blip.
            if ranged_failed and result is not None:
                self._ranged_export_supported = False

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
                in_range = interval_start <= end and effective_end(interval_end) >= start

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
        start_str = ts2str(start)
        end_str = ts2str(end)

        args = ["track", start_str, "-", end_str] + sorted(tags)

        self._run_timew(args)
