"""
Comparison module for comparing TimeWarrior database with ActivityWatch suggestions.
"""

import json
import subprocess
from datetime import UTC, datetime, timedelta

from termcolor import colored


class TimewInterval:
    """Represents a time interval in TimeWarrior."""

    def __init__(self, id: int, start: datetime, end: datetime | None, tags: set[str]):
        self.id = id
        self.start = start
        self.end = end
        self.tags = tags

    def __repr__(self) -> str:
        end_str = self.end.isoformat() if self.end else "ongoing"
        return (
            f"TimewInterval(id={self.id}, {self.start.isoformat()} - {end_str}, tags={self.tags})"
        )

    def overlaps(self, other: "TimewInterval") -> bool:
        """Check if this interval overlaps with another."""
        if not self.end or not other.end:
            return False  # Skip ongoing intervals for now
        return self.start < other.end and other.start < self.end

    def duration(self) -> timedelta:
        """Get the duration of this interval."""
        if not self.end:
            return timedelta(0)
        return self.end - self.start


class SuggestedInterval:
    """Represents a suggested interval from ActivityWatch."""

    def __init__(self, start: datetime, end: datetime, tags: set[str]):
        self.start = start
        self.end = end
        self.tags = tags

    def __repr__(self) -> str:
        return f"SuggestedInterval({self.start.isoformat()} - {self.end.isoformat()}, tags={self.tags})"

    def duration(self) -> timedelta:
        """Get the duration of this interval."""
        return self.end - self.start


def fetch_timew_intervals(start_time: datetime, end_time: datetime) -> list[TimewInterval]:
    """
    Fetch intervals from TimeWarrior using `timew export`.

    Args:
        start_time: Start of time range
        end_time: End of time range

    Returns:
        List of TimewInterval objects
    """
    # Format times for timew export command (timew expects local time)
    start_str = start_time.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_time.astimezone().strftime("%Y-%m-%dT%H:%M:%S")

    try:
        result = subprocess.run(
            ["timew", "export", f"{start_str}", "-", f"{end_str}"],
            capture_output=True,
            text=True,
            check=True,
        )

        data = json.loads(result.stdout)
        intervals = []

        for entry in data:
            # Parse start time
            start = datetime.strptime(entry["start"], "%Y%m%dT%H%M%SZ")
            start = start.replace(tzinfo=UTC)

            # Parse end time (may not exist for ongoing intervals)
            end = None
            if "end" in entry:
                end = datetime.strptime(entry["end"], "%Y%m%dT%H%M%SZ")
                end = end.replace(tzinfo=UTC)

            # Parse tags
            tags = set(entry.get("tags", []))

            intervals.append(TimewInterval(id=entry.get("id", 0), start=start, end=end, tags=tags))

        return intervals

    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to fetch timew data: {e.stderr}") from e
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse timew export output: {e}") from e


def compare_intervals(
    timew_intervals: list[TimewInterval], suggested_intervals: list[SuggestedInterval]
) -> dict[str, list]:
    """
    Compare TimeWarrior intervals with suggested intervals.

    Returns:
        Dict with keys: 'missing', 'extra', 'different_tags', 'matching', 'previously_synced'
    """
    result = {
        "missing": [],  # Intervals suggested but not in timew
        "extra": [],  # Intervals in timew but not suggested (manual or external)
        "previously_synced": [],  # Intervals tagged with ~aw but not in current suggestion
        "different_tags": [],  # Intervals that exist but with different tags
        "matching": [],  # Intervals that match perfectly
    }

    # Create a working copy of timew intervals
    unmatched_timew = list(timew_intervals)

    for suggested in suggested_intervals:
        # Find overlapping timew intervals
        # Use < instead of <= to exclude intervals that only touch at a single point
        overlapping = [
            tw
            for tw in unmatched_timew
            if tw.end and tw.start < suggested.end and suggested.start < tw.end
        ]

        if not overlapping:
            # No timew interval found for this suggestion
            result["missing"].append(suggested)
            continue

        # Find best matching interval (most overlap)
        best_match = max(
            overlapping, key=lambda tw: min(tw.end, suggested.end) - max(tw.start, suggested.start)
        )

        # Check if tags match
        if best_match.tags == suggested.tags:
            result["matching"].append((best_match, suggested))
        else:
            result["different_tags"].append((best_match, suggested))

        # Remove from unmatched
        unmatched_timew.remove(best_match)

    # Separate unmatched timew intervals into "previously_synced" and "extra"
    for tw in unmatched_timew:
        if "~aw" in tw.tags:
            result["previously_synced"].append(tw)
        else:
            result["extra"].append(tw)

    return result


def format_diff_output(comparison: dict[str, list], verbose: bool = False) -> str:
    """
    Format the comparison results for display.

    Args:
        comparison: Result from compare_intervals
        verbose: If True, show more details

    Returns:
        Formatted string for output
    """
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append(colored("TimeWarrior vs ActivityWatch Comparison", attrs=["bold"]))
    lines.append("=" * 80)

    # Summary
    lines.append(f"\n{colored('Summary:', attrs=['bold'])}")
    lines.append(f"  ✓ Matching intervals:       {len(comparison['matching'])}")
    lines.append(f"  ⚠ Different tags:           {len(comparison['different_tags'])}")
    lines.append(f"  - Missing from TimeWarrior:  {len(comparison['missing'])}")
    lines.append(f"  + Extra in TimeWarrior:      {len(comparison['extra'])}")
    if comparison.get("previously_synced"):
        lines.append(
            f"  • Previously synced (~aw):   {len(comparison['previously_synced'])} (outside diff range)"
        )

    # Missing intervals (suggested but not in timew)
    if comparison["missing"]:
        lines.append(
            f"\n{colored('Missing from TimeWarrior (suggested by ActivityWatch):', 'red', attrs=['bold'])}"
        )
        for suggested in comparison["missing"]:
            duration = suggested.duration()
            # Convert to local time for display
            start_local = suggested.start.astimezone().strftime("%H:%M:%S")
            end_local = suggested.end.astimezone().strftime("%H:%M:%S")
            lines.append(
                colored(
                    f"  - {start_local} - {end_local} " f"({duration.total_seconds()/60:.1f}min)",
                    "red",
                )
            )
            lines.append(colored(f"    Tags: {', '.join(sorted(suggested.tags))}", "red"))

    # Extra intervals (in timew but not suggested)
    if comparison["extra"]:
        lines.append(
            f"\n{colored('Extra in TimeWarrior (not suggested by ActivityWatch):', 'yellow', attrs=['bold'])}"
        )
        for timew_int in comparison["extra"]:
            duration = timew_int.duration()
            # Convert to local time for display
            start_local = timew_int.start.astimezone().strftime("%H:%M:%S")
            end_local = (
                timew_int.end.astimezone().strftime("%H:%M:%S") if timew_int.end else "ongoing"
            )
            lines.append(
                colored(
                    f"  + {start_local} - {end_local} " f"({duration.total_seconds()/60:.1f}min)",
                    "yellow",
                )
            )
            lines.append(colored(f"    Tags: {', '.join(sorted(timew_int.tags))}", "yellow"))

    # Previously synced intervals (verbose mode or when explicitly requested)
    if comparison.get("previously_synced") and verbose:
        lines.append(
            f"\n{colored('Previously synced intervals (outside current diff range):', 'blue', attrs=['bold'])}"
        )
        lines.append(
            colored(
                "  Note: These intervals have ~aw tag but don't match current suggestions.",
                "blue",
            )
        )
        lines.append(
            colored(
                "  This is normal when running diff on a time range subset of a previous sync.",
                "blue",
            )
        )
        for timew_int in comparison["previously_synced"][:5]:  # Limit to first 5
            duration = timew_int.duration()
            start_local = timew_int.start.astimezone().strftime("%H:%M:%S")
            end_local = (
                timew_int.end.astimezone().strftime("%H:%M:%S") if timew_int.end else "ongoing"
            )
            lines.append(
                colored(
                    f"  • {start_local} - {end_local} " f"({duration.total_seconds()/60:.1f}min)",
                    "blue",
                )
            )
        if len(comparison["previously_synced"]) > 5:
            lines.append(
                colored(
                    f"  ... and {len(comparison['previously_synced']) - 5} more",
                    "blue",
                )
            )

    # Different tags
    if comparison["different_tags"]:
        lines.append(f"\n{colored('Intervals with different tags:', 'cyan', attrs=['bold'])}")
        for timew_int, suggested in comparison["different_tags"]:
            # Convert to local time for display
            start_local = timew_int.start.astimezone().strftime("%H:%M:%S")
            end_local = (
                timew_int.end.astimezone().strftime("%H:%M:%S") if timew_int.end else "ongoing"
            )
            lines.append(f"  {start_local} - {end_local}")

            # Show tag differences
            timew_tags = timew_int.tags
            suggested_tags = suggested.tags

            only_in_timew = timew_tags - suggested_tags
            only_in_suggested = suggested_tags - timew_tags
            common = timew_tags & suggested_tags

            if common and verbose:
                lines.append(colored(f"    Common:    {', '.join(sorted(common))}", "white"))
            if only_in_timew:
                lines.append(colored(f"    - In timew:  {', '.join(sorted(only_in_timew))}", "red"))
            if only_in_suggested:
                lines.append(
                    colored(f"    + Suggested: {', '.join(sorted(only_in_suggested))}", "green")
                )

    # Matching intervals (if verbose)
    if verbose and comparison["matching"]:
        lines.append(f"\n{colored('Matching intervals:', 'green', attrs=['bold'])}")
        for timew_int, _suggested in comparison["matching"]:
            duration = timew_int.duration()
            # Convert to local time for display
            start_local = timew_int.start.astimezone().strftime("%H:%M:%S")
            end_local = (
                timew_int.end.astimezone().strftime("%H:%M:%S") if timew_int.end else "ongoing"
            )
            lines.append(
                colored(
                    f"  ✓ {start_local} - {end_local} " f"({duration.total_seconds()/60:.1f}min)",
                    "green",
                )
            )
            if verbose:
                lines.append(colored(f"    Tags: {', '.join(sorted(timew_int.tags))}", "green"))

    lines.append("\n" + "=" * 80 + "\n")

    return "\n".join(lines)


def merge_consecutive_intervals(intervals: list[SuggestedInterval]) -> list[SuggestedInterval]:
    """
    Merge consecutive intervals with identical tags into single continuous intervals.

    Args:
        intervals: List of SuggestedInterval objects (should be sorted by start time)

    Returns:
        List of merged SuggestedInterval objects
    """
    if not intervals:
        return []

    # Sort intervals by start time to ensure consecutive ones are adjacent
    sorted_intervals = sorted(intervals, key=lambda x: x.start)

    merged = []
    current = sorted_intervals[0]

    for next_interval in sorted_intervals[1:]:
        # Check if the next interval is consecutive (or overlapping) and has the same tags
        if current.end == next_interval.start and current.tags == next_interval.tags:
            # Merge: extend the current interval to include the next one
            current = SuggestedInterval(
                start=current.start, end=next_interval.end, tags=current.tags
            )
        else:
            # Not consecutive or different tags - add current to results and start new
            merged.append(current)
            current = next_interval

    # Add the last interval
    merged.append(current)

    return merged


def generate_fix_commands(comparison: dict[str, list]) -> list[str]:
    """
    Generate timew commands to fix differences.

    Uses 'timew track' for missing intervals, 'timew retag' for intervals
    with different tags, and 'timew delete' for extra intervals.

    Commands for manually-entered events (those without ~aw tag) are commented out
    to prevent accidental deletion/overwriting.

    Args:
        comparison: Result from compare_intervals

    Returns:
        List of timew command strings (may include commented lines)
    """
    # Import here to avoid circular dependency
    from .config import config
    from .main import retag_by_rules

    commands = []

    # Merge consecutive intervals with the same tags before generating commands
    merged_missing = merge_consecutive_intervals(comparison["missing"])

    # Add missing intervals using 'timew track'
    for suggested in merged_missing:
        # Format: timew track 2025-12-08T10:00:00 - 2025-12-08T11:00:00 tag1 tag2 :adjust
        # NOTE: Using :adjust to maintain continuous tracking without gaps
        start_str = suggested.start.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        end_str = suggested.end.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        # Apply recursive tag rules before generating command
        final_tags = retag_by_rules(suggested.tags, config)
        tags = " ".join(sorted(final_tags))
        commands.append(f"timew track {start_str} - {end_str} {tags} :adjust")

    # Fix intervals with different tags using 'timew retag'
    # Sort in reverse ID order to avoid issues if any intervals get deleted during retag
    sorted_different = sorted(comparison["different_tags"], key=lambda x: x[0].id, reverse=True)

    for timew_int, suggested in sorted_different:
        # Use the timew interval's ID for retag command
        # Format: timew retag @<id> tag1 tag2 tag3
        # First, remove all existing tags, then add the suggested ones
        # This is done by specifying all new tags - timew retag replaces all tags
        # Apply recursive tag rules before generating command
        final_tags = retag_by_rules(suggested.tags, config)
        tags = " ".join(sorted(final_tags))

        # Format timestamp for comment
        timestamp_str = timew_int.start.astimezone().strftime("%Y-%m-%d %H:%M")

        # Format old tags for comment
        old_tags_str = " ".join(sorted(timew_int.tags))

        # Check if this is a manually-entered event (no ~aw tag)
        is_manual = "~aw" not in timew_int.tags

        # Build the command with comment
        base_cmd = f"timew retag @{timew_int.id} {tags}"
        comment = f"  # {timestamp_str} - old tags: {old_tags_str}"

        # Comment out the entire command if it's a manually-entered event
        if is_manual:
            commands.append(f"# {base_cmd}{comment}")
        else:
            commands.append(f"{base_cmd}{comment}")

    # NOTE: "extra" intervals (in TimeWarrior but not in ActivityWatch) are intentionally
    # not deleted to maintain continuous tracking. The :adjust flag on track commands
    # will handle merging/adjusting boundaries to absorb small gaps.
    # For reference, extra intervals found (not generating delete commands):
    if comparison["extra"]:
        commands.append("")
        commands.append("# Extra intervals in TimeWarrior (not deleting to maintain continuity):")
        for timew_int in sorted(comparison["extra"], key=lambda x: x.start):
            timestamp_str = timew_int.start.astimezone().strftime("%Y-%m-%d %H:%M")
            end_str = timew_int.end.astimezone().strftime("%H:%M") if timew_int.end else "ongoing"
            tags_str = " ".join(sorted(timew_int.tags))
            commands.append(f"#   @{timew_int.id}: {timestamp_str} - {end_str} ({tags_str})")

    return commands


def format_timeline(
    timew_intervals: list[TimewInterval],
    suggested_intervals: list[SuggestedInterval],
    start_time: datetime,
    end_time: datetime,
) -> str:
    """
    Format a timeline view showing TimeWarrior vs ActivityWatch intervals side-by-side.

    Args:
        timew_intervals: List of intervals from TimeWarrior
        suggested_intervals: List of suggested intervals from ActivityWatch
        start_time: Start of the time range
        end_time: End of the time range

    Returns:
        Formatted timeline string
    """
    lines = []
    lines.append("=" * 100)
    lines.append("Timeline: TimeWarrior vs ActivityWatch")
    lines.append("=" * 100)
    lines.append("")

    # Convert to local time for display
    start_local = start_time.astimezone()
    end_local = end_time.astimezone()

    lines.append(
        f"Time range: {start_local.strftime('%Y-%m-%d %H:%M:%S')} - {end_local.strftime('%H:%M:%S')}"
    )
    lines.append("")

    # Collect all time points from timew intervals (include those starting before start_time)
    # and from suggested intervals (only those within the requested window)
    time_points = set()

    # Add all timew interval boundaries that overlap with or extend into the display window
    for interval in timew_intervals:
        interval_end = interval.end if interval.end else datetime.max.replace(tzinfo=UTC)
        # Skip intervals that end before the window starts
        if interval_end <= start_time:
            continue
        # Skip intervals that start after the window ends
        if interval.start >= end_time:
            continue
        # Add start time (even if before start_time - we'll show it)
        time_points.add(interval.start)
        # Add end time if it exists
        if interval.end:
            time_points.add(interval.end)

    # Add suggested interval boundaries only within the requested window
    for interval in suggested_intervals:
        # Skip intervals completely outside the window
        if interval.end <= start_time or interval.start >= end_time:
            continue
        # Add start/end times only if within the window
        if interval.start >= start_time:
            time_points.add(interval.start)
        if interval.end <= end_time:
            time_points.add(interval.end)

    # Always include the requested window boundaries
    time_points.add(start_time)
    time_points.add(end_time)

    # Sort time points
    time_points = sorted(time_points)

    # Create timeline entries
    lines.append(f"{'Time':<20} {'TimeWarrior':<40} {'ActivityWatch':<40}")
    lines.append("-" * 100)

    # Track previous intervals to detect continuations

    for i, time_point in enumerate(time_points[:-1]):
        next_point = time_points[i + 1]
        time_local = time_point.astimezone()
        time_str = time_local.strftime("%H:%M:%S")

        # Check if this time slice is within the requested window
        in_requested_window = time_point >= start_time and next_point <= end_time

        # Find what's active in this time slice [time_point, next_point)
        # An interval is active if it overlaps with this time slice
        timew_active = []
        for interval in timew_intervals:
            # Check if interval overlaps with [time_point, next_point)
            interval_end = interval.end if interval.end else datetime.max.replace(tzinfo=UTC)
            if interval.start < next_point and interval_end > time_point:
                timew_active.append(interval)

        suggested_active = []
        for interval in suggested_intervals:
            # Check if interval overlaps with [time_point, next_point)
            if interval.start < next_point and interval.end > time_point:
                suggested_active.append(interval)

        # Format the TimeWarrior intervals
        if timew_active:
            # Check if any interval starts exactly at this time point
            any_interval_starts_here = any(iv.start == time_point for iv in timew_active)

            if any_interval_starts_here:
                # Show tags when interval(s) start here
                timew_str = ", ".join([", ".join(sorted(iv.tags)) for iv in timew_active])
                if len(timew_str) > 38:
                    timew_str = timew_str[:35] + "..."
            else:
                # Continuing from previous time point - show blank
                timew_str = ""
        else:
            timew_str = colored("(no tracking)", "red")

        # Format the ActivityWatch intervals
        if not in_requested_window:
            # Outside requested window - mark as N/A
            suggested_str = "(N/A - outside window)"
        elif suggested_active:
            # Check if any interval starts exactly at this time point
            any_aw_starts_here = any(iv.start == time_point for iv in suggested_active)

            if any_aw_starts_here:
                # Show tags when interval(s) start here
                suggested_str = ", ".join([", ".join(sorted(iv.tags)) for iv in suggested_active])
                if len(suggested_str) > 38:
                    suggested_str = suggested_str[:35] + "..."
            else:
                # Continuing from previous time point - show blank
                suggested_str = ""
        else:
            suggested_str = colored("(no activity)", "yellow")

        # Color code based on match status (only for time slices within requested window)
        # Only color when we have actual text to display (not blank continuation lines)
        if (
            in_requested_window
            and timew_str
            and suggested_str
            and timew_active
            and suggested_active
        ):
            # Both have something - check if tags match
            timew_tags = set().union(*[iv.tags for iv in timew_active])
            suggested_tags = set().union(*[iv.tags for iv in suggested_active])
            if timew_tags == suggested_tags:
                # Perfect match
                timew_str = colored(timew_str, "green")
                suggested_str = colored(suggested_str, "green")
            else:
                # Different tags
                timew_str = colored(timew_str, "yellow")
                suggested_str = colored(suggested_str, "yellow")

        # Color suggested intervals red when missing from timew (only when we display tags, not blanks)
        if in_requested_window and not timew_active and suggested_active and suggested_str:
            suggested_str = colored(suggested_str, "red")

        lines.append(f"{time_str:<20} {timew_str:<50} {suggested_str:<50}")

    lines.append("")
    lines.append("Legend:")
    lines.append(f"  {colored('Green', 'green')}  - Matching intervals")
    lines.append(f"  {colored('Yellow', 'yellow')} - Different tags")
    lines.append(f"  {colored('Red', 'red')}    - Missing from TimeWarrior")
    lines.append("")

    return "\n".join(lines)
