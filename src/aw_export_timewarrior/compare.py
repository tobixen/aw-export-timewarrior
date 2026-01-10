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

    Applies recursive tag rules to both TimeWarrior and suggested tags before comparison,
    so that manually-entered tags that imply other tags are recognized as equivalent.

    Detects partial coverage: if a suggested interval is only partially covered by TimeWarrior,
    generates "missing" intervals for the uncovered gaps to ensure continuous tracking.

    Returns:
        Dict with keys: 'missing', 'extra', 'different_tags', 'matching', 'previously_synced'
    """
    # Import here to avoid circular dependency
    from .config import config
    from .main import retag_by_rules

    result = {
        "missing": [],  # Intervals suggested but not in timew
        "extra": [],  # Intervals in timew but not suggested (manual or external)
        "previously_synced": [],  # Intervals tagged with ~aw but not in current suggestion
        "different_tags": [],  # Intervals that exist but with different tags
        "matching": [],  # Intervals that match perfectly
    }

    # Create a working copy of timew intervals
    unmatched_timew = list(timew_intervals)
    matched_timew = []  # Track which timew intervals have been matched

    for suggested in suggested_intervals:
        # Find ALL overlapping timew intervals (not just the best one)
        # Use < instead of <= to exclude intervals that only touch at a single point
        overlapping = [
            tw
            for tw in timew_intervals
            if tw.end and tw.start < suggested.end and suggested.start < tw.end
        ]

        if not overlapping:
            # No timew interval found for this suggestion - completely missing
            result["missing"].append(suggested)
            continue

        # Calculate total coverage by merging overlapping TimeWarrior intervals
        # Sort by start time to make merging easier
        overlapping_sorted = sorted(overlapping, key=lambda tw: tw.start)

        # Find gaps in coverage and portions with different tags
        uncovered_gaps = []
        current_pos = suggested.start

        for tw in overlapping_sorted:
            # Gap before this timew interval?
            if tw.start > current_pos:
                # There's a gap - create a missing interval for it
                gap_start = current_pos
                gap_end = min(tw.start, suggested.end)
                # Only create missing interval if gap is at least 1 second
                # (ignore tiny gaps due to timestamp precision)
                if (gap_end - gap_start).total_seconds() >= 1.0:
                    uncovered_gaps.append(
                        SuggestedInterval(start=gap_start, end=gap_end, tags=suggested.tags)
                    )

            # Calculate overlap between suggested and this timew interval
            overlap_start = max(current_pos, tw.start)
            overlap_end = min(suggested.end, tw.end)

            if overlap_start < overlap_end:
                # There's actual overlap - check if tags match
                timew_tags_expanded = retag_by_rules(tw.tags, config)
                suggested_tags_expanded = retag_by_rules(suggested.tags, config)

                # Create interval objects for the overlapping portion
                overlapping_suggested = SuggestedInterval(
                    start=overlap_start, end=overlap_end, tags=suggested.tags
                )

                if timew_tags_expanded == suggested_tags_expanded:
                    # Tags match - this portion is "matching"
                    result["matching"].append((tw, overlapping_suggested))
                else:
                    # Tags differ - this portion needs retagging
                    result["different_tags"].append((tw, overlapping_suggested))

                # Mark this timew interval as matched
                if tw in unmatched_timew:
                    unmatched_timew.remove(tw)
                if tw not in matched_timew:
                    matched_timew.append(tw)

                # Move current position forward
                current_pos = overlap_end

        # Check if there's a gap at the end (minimum 1 second to avoid timestamp precision issues)
        if current_pos < suggested.end and (suggested.end - current_pos).total_seconds() >= 1.0:
            uncovered_gaps.append(
                SuggestedInterval(start=current_pos, end=suggested.end, tags=suggested.tags)
            )

        # Add all gaps to "missing"
        result["missing"].extend(uncovered_gaps)

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
                    f"  - {start_local} - {end_local} ({duration.total_seconds() / 60:.1f}min)",
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
                    f"  + {start_local} - {end_local} ({duration.total_seconds() / 60:.1f}min)",
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
                    f"  • {start_local} - {end_local} ({duration.total_seconds() / 60:.1f}min)",
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

    # Different tags - group by timew interval to avoid duplicates
    if comparison["different_tags"]:
        lines.append(f"\n{colored('Intervals with different tags:', 'cyan', attrs=['bold'])}")

        # Group by timew interval (same start/end)
        from collections import defaultdict

        grouped: dict[tuple, list] = defaultdict(list)
        for timew_int, suggested in comparison["different_tags"]:
            key = (timew_int.start, timew_int.end, frozenset(timew_int.tags))
            grouped[key].append((timew_int, suggested))

        for _key, entries in grouped.items():
            timew_int = entries[0][0]  # All have same timew_int
            timew_tags = timew_int.tags
            display_timew_tags = {t for t in timew_tags if not t.startswith("~")}

            # Convert to local time for display
            start_local = timew_int.start.astimezone().strftime("%H:%M:%S")
            end_local = (
                timew_int.end.astimezone().strftime("%H:%M:%S") if timew_int.end else "ongoing"
            )
            lines.append(f"  {start_local} - {end_local}")

            if display_timew_tags:
                lines.append(
                    colored(f"    - In timew:  {', '.join(sorted(display_timew_tags))}", "red")
                )

            # Sort suggested intervals by start time
            sorted_entries = sorted(entries, key=lambda x: x[1].start)

            # Check if all suggested intervals have the same tags
            all_same_tags = len({frozenset(s.tags) for _, s in sorted_entries}) == 1

            if all_same_tags:
                # All sub-intervals have the same tags - show once
                suggested = sorted_entries[0][1]
                only_in_suggested = suggested.tags - timew_tags
                display_only_suggested = {t for t in only_in_suggested if not t.startswith("~")}
                if display_only_suggested:
                    lines.append(
                        colored(
                            f"    + Suggested: {', '.join(sorted(display_only_suggested))}", "green"
                        )
                    )
            else:
                # Multiple sub-intervals with different tags - show each separately
                for _, suggested in sorted_entries:
                    sub_start = suggested.start.astimezone().strftime("%H:%M:%S")
                    sub_end = suggested.end.astimezone().strftime("%H:%M:%S")
                    display_suggested = {t for t in suggested.tags if not t.startswith("~")}
                    if display_suggested:
                        lines.append(
                            colored(
                                f"    + {sub_start}-{sub_end}: {', '.join(sorted(display_suggested))}",
                                "green",
                            )
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
                    f"  ✓ {start_local} - {end_local} ({duration.total_seconds() / 60:.1f}min)",
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

    Uses only 'timew track :adjust' for all changes. The :adjust flag automatically
    handles both creating new intervals in gaps AND adjusting/replacing existing
    intervals with different tags. This approach:
    - Avoids convergence issues from multiple retag commands on same interval
    - Maintains continuous tracking without gaps
    - Simplifies command generation logic

    Args:
        comparison: Result from compare_intervals

    Returns:
        List of timew command strings (may include commented lines)
    """
    # Import here to avoid circular dependency
    from .config import config
    from .main import retag_by_rules

    commands = []

    # Collect all suggested intervals that need to be tracked:
    # 1. Missing intervals (gaps in TimeWarrior)
    # 2. Intervals with different tags WHERE the original has ~aw tag
    all_suggested = []
    manual_entries = []  # Intervals without ~aw tag (manually edited)

    # Add missing intervals
    all_suggested.extend(comparison["missing"])

    # Add suggested portions from intervals with different tags
    # These are tuples of (timew_int, suggested_interval)
    for timew_int, suggested in comparison["different_tags"]:
        if "~aw" in timew_int.tags:
            # Original was created by aw-export-timewarrior, safe to retag
            all_suggested.append(suggested)
        else:
            # Original was manually edited (no ~aw tag), don't overwrite
            manual_entries.append((timew_int, suggested))

    # Merge consecutive intervals with the same tags before generating commands
    merged_suggested = merge_consecutive_intervals(all_suggested)

    # Generate track commands for all suggested intervals
    for suggested in merged_suggested:
        # Format: timew track 2025-12-08T10:00:00 - 2025-12-08T11:00:00 tag1 tag2 :adjust
        # NOTE: Using :adjust to handle both gaps AND retagging existing intervals
        start_str = suggested.start.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        end_str = suggested.end.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        # Apply recursive tag rules before generating command
        final_tags = retag_by_rules(suggested.tags, config)
        tags = " ".join(sorted(final_tags))
        commands.append(f"timew track {start_str} - {end_str} {tags} :adjust")

    # For manually edited entries (no ~aw tag), we:
    # 1. Show commented track commands (what AW would suggest) for reference
    # 2. Apply retag rules to derive additional tags that should be added
    # E.g., if user added "bedtime", retag rules might imply "4BREAK" should also be added.
    retag_commands = []

    if manual_entries:
        commands.append("")
        commands.append("# Manually edited intervals (no ~aw tag, not overwriting):")
        for timew_int, suggested in sorted(manual_entries, key=lambda x: x[1].start):
            start_str = suggested.start.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
            end_str = suggested.end.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
            final_tags = retag_by_rules(suggested.tags, config)
            tags = " ".join(sorted(final_tags))
            old_tags = " ".join(sorted(timew_int.tags))
            commands.append(f"# timew track {start_str} - {end_str} {tags} :adjust")
            commands.append(f"#   (current: {old_tags})")

            # Apply retag rules to the current TimeWarrior tags
            current_tags = timew_int.tags - {"~aw"}  # Exclude internal marker
            expanded_tags = retag_by_rules(current_tags, config)

            # Find tags that should be added (derived from retag rules but not yet in timew)
            derived_tags = expanded_tags - current_tags
            if derived_tags:
                # Generate command to add derived tags
                tags_to_add = " ".join(sorted(derived_tags))
                retag_commands.append(f"timew tag @{timew_int.id} {tags_to_add}")

    # Add retag commands for derived tags from manual entries
    if retag_commands:
        commands.append("")
        commands.append("# Apply retag rules to manually added tags:")
        commands.extend(retag_commands)

    # NOTE: "extra" intervals (in TimeWarrior but not in ActivityWatch) are intentionally
    # not deleted to maintain continuous tracking. The :adjust flag on track commands
    # will handle merging/adjusting boundaries to absorb small gaps.
    # However, we still apply retag rules to derive additional tags if needed.
    if comparison["extra"]:
        extra_retag_commands = []
        extra_info = []

        for timew_int in sorted(comparison["extra"], key=lambda x: x.start):
            # Apply retag rules to the current TimeWarrior tags
            current_tags = timew_int.tags - {"~aw"}  # Exclude internal marker
            expanded_tags = retag_by_rules(current_tags, config)

            # Find tags that should be added (derived from retag rules but not yet in timew)
            derived_tags = expanded_tags - current_tags

            timestamp_str = timew_int.start.astimezone().strftime("%Y-%m-%d %H:%M")
            end_str = timew_int.end.astimezone().strftime("%H:%M") if timew_int.end else "ongoing"
            tags_str = " ".join(sorted(current_tags))

            if derived_tags:
                # Generate command to add derived tags
                tags_to_add = " ".join(sorted(derived_tags))
                extra_retag_commands.append(f"timew tag @{timew_int.id} {tags_to_add}")
                extra_info.append(
                    f"#   @{timew_int.id}: {timestamp_str} - {end_str} ({tags_str}) → +{', '.join(sorted(derived_tags))}"
                )
            else:
                extra_info.append(f"#   @{timew_int.id}: {timestamp_str} - {end_str} ({tags_str})")

        # Add retag commands for extra intervals
        if extra_retag_commands:
            commands.append("")
            commands.append("# Apply retag rules to extra intervals in TimeWarrior:")
            commands.extend(extra_retag_commands)

        # Show info about extra intervals
        commands.append("")
        commands.append("# Extra intervals in TimeWarrior (not deleting to maintain continuity):")
        commands.extend(extra_info)

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

    # Show full date for end time if it's a different day
    if start_local.date() == end_local.date():
        end_str = end_local.strftime("%H:%M:%S")
    else:
        end_str = end_local.strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"Time range: {start_local.strftime('%Y-%m-%d %H:%M:%S')} - {end_str}")
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
                # AW interval continuing from previous time point
                # Check if timew has a new interval starting here with different tags
                any_timew_starts_here = any(iv.start == time_point for iv in timew_active)
                if any_timew_starts_here:
                    # Timew has a new interval - check if tags differ from AW
                    timew_tags = set().union(*[iv.tags for iv in timew_active])
                    suggested_tags = set().union(*[iv.tags for iv in suggested_active])
                    if timew_tags != suggested_tags:
                        # Show actual AW tags when they differ from timew
                        suggested_str = ", ".join(
                            [", ".join(sorted(iv.tags)) for iv in suggested_active]
                        )
                        if len(suggested_str) > 38:
                            suggested_str = suggested_str[:35] + "..."
                    else:
                        # Tags match - just show "(continuing)"
                        suggested_str = colored("(continuing)", "white", attrs=["dark"])
                else:
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
