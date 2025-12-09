"""
Comparison module for comparing TimeWarrior database with ActivityWatch suggestions.
"""

import json
import subprocess
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict

from termcolor import colored


class TimewInterval:
    """Represents a time interval in TimeWarrior."""

    def __init__(self, id: int, start: datetime, end: Optional[datetime], tags: Set[str]):
        self.id = id
        self.start = start
        self.end = end
        self.tags = tags

    def __repr__(self) -> str:
        end_str = self.end.isoformat() if self.end else "ongoing"
        return f"TimewInterval(id={self.id}, {self.start.isoformat()} - {end_str}, tags={self.tags})"

    def overlaps(self, other: 'TimewInterval') -> bool:
        """Check if this interval overlaps with another."""
        if not self.end or not other.end:
            return False  # Skip ongoing intervals for now
        return (self.start < other.end and other.start < self.end)

    def duration(self) -> timedelta:
        """Get the duration of this interval."""
        if not self.end:
            return timedelta(0)
        return self.end - self.start


class SuggestedInterval:
    """Represents a suggested interval from ActivityWatch."""

    def __init__(self, start: datetime, end: datetime, tags: Set[str]):
        self.start = start
        self.end = end
        self.tags = tags

    def __repr__(self) -> str:
        return f"SuggestedInterval({self.start.isoformat()} - {self.end.isoformat()}, tags={self.tags})"

    def duration(self) -> timedelta:
        """Get the duration of this interval."""
        return self.end - self.start


def fetch_timew_intervals(start_time: datetime, end_time: datetime) -> List[TimewInterval]:
    """
    Fetch intervals from TimeWarrior using `timew export`.

    Args:
        start_time: Start of time range
        end_time: End of time range

    Returns:
        List of TimewInterval objects
    """
    # Format times for timew export command (timew expects local time)
    start_str = start_time.astimezone().strftime('%Y-%m-%dT%H:%M:%S')
    end_str = end_time.astimezone().strftime('%Y-%m-%dT%H:%M:%S')

    try:
        result = subprocess.run(
            ['timew', 'export', f'{start_str}', '-', f'{end_str}'],
            capture_output=True,
            text=True,
            check=True
        )

        data = json.loads(result.stdout)
        intervals = []

        for entry in data:
            # Parse start time
            start = datetime.strptime(entry['start'], '%Y%m%dT%H%M%SZ')
            start = start.replace(tzinfo=timezone.utc)

            # Parse end time (may not exist for ongoing intervals)
            end = None
            if 'end' in entry:
                end = datetime.strptime(entry['end'], '%Y%m%dT%H%M%SZ')
                end = end.replace(tzinfo=timezone.utc)

            # Parse tags
            tags = set(entry.get('tags', []))

            intervals.append(TimewInterval(
                id=entry.get('id', 0),
                start=start,
                end=end,
                tags=tags
            ))

        return intervals

    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to fetch timew data: {e.stderr}")
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse timew export output: {e}")


def compare_intervals(timew_intervals: List[TimewInterval],
                     suggested_intervals: List[SuggestedInterval]) -> Dict[str, List]:
    """
    Compare TimeWarrior intervals with suggested intervals.

    Returns:
        Dict with keys: 'missing', 'extra', 'different_tags', 'matching'
    """
    result = {
        'missing': [],      # Intervals suggested but not in timew
        'extra': [],        # Intervals in timew but not suggested
        'different_tags': [],  # Intervals that exist but with different tags
        'matching': [],     # Intervals that match perfectly
    }

    # Create a working copy of timew intervals
    unmatched_timew = list(timew_intervals)

    for suggested in suggested_intervals:
        # Find overlapping timew intervals
        overlapping = [tw for tw in unmatched_timew
                      if tw.end and tw.start <= suggested.end and suggested.start <= tw.end]

        if not overlapping:
            # No timew interval found for this suggestion
            result['missing'].append(suggested)
            continue

        # Find best matching interval (most overlap)
        best_match = max(overlapping, key=lambda tw: min(tw.end, suggested.end) - max(tw.start, suggested.start))

        # Check if tags match
        if best_match.tags == suggested.tags:
            result['matching'].append((best_match, suggested))
        else:
            result['different_tags'].append((best_match, suggested))

        # Remove from unmatched
        unmatched_timew.remove(best_match)

    # Remaining timew intervals are "extra" (not suggested by AW)
    result['extra'] = unmatched_timew

    return result


def format_diff_output(comparison: Dict[str, List], verbose: bool = False) -> str:
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
    lines.append(colored("TimeWarrior vs ActivityWatch Comparison", attrs=['bold']))
    lines.append("=" * 80)

    # Summary
    lines.append(f"\n{colored('Summary:', attrs=['bold'])}")
    lines.append(f"  ✓ Matching intervals:      {len(comparison['matching'])}")
    lines.append(f"  ⚠ Different tags:          {len(comparison['different_tags'])}")
    lines.append(f"  - Missing from TimeWarrior: {len(comparison['missing'])}")
    lines.append(f"  + Extra in TimeWarrior:     {len(comparison['extra'])}")

    # Missing intervals (suggested but not in timew)
    if comparison['missing']:
        lines.append(f"\n{colored('Missing from TimeWarrior (suggested by ActivityWatch):', 'red', attrs=['bold'])}")
        for suggested in comparison['missing']:
            duration = suggested.duration()
            lines.append(colored(f"  - {suggested.start.strftime('%H:%M:%S')} - {suggested.end.strftime('%H:%M:%S')} "
                               f"({duration.total_seconds()/60:.1f}min)", 'red'))
            lines.append(colored(f"    Tags: {', '.join(sorted(suggested.tags))}", 'red'))

    # Extra intervals (in timew but not suggested)
    if comparison['extra']:
        lines.append(f"\n{colored('Extra in TimeWarrior (not suggested by ActivityWatch):', 'yellow', attrs=['bold'])}")
        for timew_int in comparison['extra']:
            duration = timew_int.duration()
            end_str = timew_int.end.strftime('%H:%M:%S') if timew_int.end else 'ongoing'
            lines.append(colored(f"  + {timew_int.start.strftime('%H:%M:%S')} - {end_str} "
                               f"({duration.total_seconds()/60:.1f}min)", 'yellow'))
            lines.append(colored(f"    Tags: {', '.join(sorted(timew_int.tags))}", 'yellow'))

    # Different tags
    if comparison['different_tags']:
        lines.append(f"\n{colored('Intervals with different tags:', 'cyan', attrs=['bold'])}")
        for timew_int, suggested in comparison['different_tags']:
            lines.append(f"  {timew_int.start.strftime('%H:%M:%S')} - "
                        f"{timew_int.end.strftime('%H:%M:%S') if timew_int.end else 'ongoing'}")

            # Show tag differences
            timew_tags = timew_int.tags
            suggested_tags = suggested.tags

            only_in_timew = timew_tags - suggested_tags
            only_in_suggested = suggested_tags - timew_tags
            common = timew_tags & suggested_tags

            if common and verbose:
                lines.append(colored(f"    Common:    {', '.join(sorted(common))}", 'white'))
            if only_in_timew:
                lines.append(colored(f"    - In timew:  {', '.join(sorted(only_in_timew))}", 'red'))
            if only_in_suggested:
                lines.append(colored(f"    + Suggested: {', '.join(sorted(only_in_suggested))}", 'green'))

    # Matching intervals (if verbose)
    if verbose and comparison['matching']:
        lines.append(f"\n{colored('Matching intervals:', 'green', attrs=['bold'])}")
        for timew_int, suggested in comparison['matching']:
            duration = timew_int.duration()
            lines.append(colored(f"  ✓ {timew_int.start.strftime('%H:%M:%S')} - "
                               f"{timew_int.end.strftime('%H:%M:%S') if timew_int.end else 'ongoing'} "
                               f"({duration.total_seconds()/60:.1f}min)", 'green'))
            if verbose:
                lines.append(colored(f"    Tags: {', '.join(sorted(timew_int.tags))}", 'green'))

    lines.append("\n" + "=" * 80 + "\n")

    return "\n".join(lines)


def generate_fix_commands(comparison: Dict[str, List]) -> List[str]:
    """
    Generate timew track commands to fix differences.

    Args:
        comparison: Result from compare_intervals

    Returns:
        List of timew command strings
    """
    commands = []

    # Add missing intervals
    for suggested in comparison['missing']:
        # Format: timew track 2025-12-08T10:00:00 - 2025-12-08T11:00:00 tag1 tag2 :adjust
        start_str = suggested.start.astimezone().strftime('%Y-%m-%dT%H:%M:%S')
        end_str = suggested.end.astimezone().strftime('%Y-%m-%dT%H:%M:%S')
        tags = ' '.join(sorted(suggested.tags))
        commands.append(f"timew track {start_str} - {end_str} {tags} :adjust")

    # Fix intervals with different tags
    for timew_int, suggested in comparison['different_tags']:
        # Format: timew track 2025-12-08T10:00:00 - 2025-12-08T11:00:00 tag1 tag2 :adjust
        start_str = suggested.start.astimezone().strftime('%Y-%m-%dT%H:%M:%S')
        end_str = suggested.end.astimezone().strftime('%Y-%m-%dT%H:%M:%S')
        tags = ' '.join(sorted(suggested.tags))
        commands.append(f"timew track {start_str} - {end_str} {tags} :adjust")

    return commands
