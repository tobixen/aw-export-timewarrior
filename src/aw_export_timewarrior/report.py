"""Activity report generation module.

Generates detailed reports showing ActivityWatch events with columns for:
- Timestamp
- Window title
- Specialized watcher data (file paths for editors, URLs for browsers)
- AFK status
- Determined tags
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .main import Exporter


def show_unmatched_events_report(unmatched_events: list[dict], limit: int = 10) -> None:
    """Display a report of events that didn't match any rules.

    Args:
        unmatched_events: List of event dictionaries that didn't match any rules
        limit: Maximum number of output lines to show (default: 10)
    """
    if not unmatched_events:
        print("\nNo unmatched events found - all events matched configuration rules.")
        return

    print("\n" + "=" * 80)
    print("Events Not Matching Any Rules")
    print("=" * 80)

    # Calculate total unmatched time
    total_unmatched_seconds = sum((e["duration"].total_seconds() for e in unmatched_events), 0)
    print(
        f"\nFound {len(unmatched_events)} unmatched events, {total_unmatched_seconds / 60:.1f} min total:\n"
    )

    # Group by app and title for easier analysis
    by_app: dict[str, list] = defaultdict(list)

    for event in unmatched_events:
        app = event["data"].get("app", "unknown")
        by_app[app].append(event)

    # Sort apps by total duration (descending)
    app_durations = [
        (app, sum(e["duration"].total_seconds() for e in events)) for app, events in by_app.items()
    ]
    app_durations.sort(key=lambda x: x[1], reverse=True)

    lines_printed = 5  # Header + summary lines already printed
    for app, app_total_seconds in app_durations:
        if lines_printed >= limit:
            remaining_apps = len(app_durations) - app_durations.index((app, app_total_seconds))
            print(f"\n... and {remaining_apps} more apps (use --limit to show more)")
            break

        events = by_app[app]
        print(f"\n{app} ({len(events)} events, {app_total_seconds / 60:.1f} min total):")
        lines_printed += 2  # App header + blank line

        # Group by title and sum durations
        title_durations: dict[str, float] = defaultdict(float)
        title_count: dict[str, int] = defaultdict(int)
        for event in events:
            title = event["data"].get("title", "(no title)")
            title_durations[title] += event["duration"].total_seconds()
            title_count[title] += 1

        # Sort titles by duration (descending) and show top titles
        sorted_titles = sorted(title_durations.items(), key=lambda x: x[1], reverse=True)

        # Calculate how many titles we can show
        remaining_lines = limit - lines_printed
        # Reserve 1 line for potential long tail summary, but show all titles if space allows
        max_titles = max(0, remaining_lines - 1) if remaining_lines > 1 else 0

        for title, duration_seconds in sorted_titles[:max_titles]:
            count = title_count[title]
            title_display = title[:60] + "..." if len(title) > 60 else title
            print(f"  {duration_seconds / 60:5.1f}min ({count:2d}x) - {title_display}")
            lines_printed += 1

        # Show "long tail" summary
        if len(sorted_titles) > max_titles:
            remaining_count = len(sorted_titles) - max_titles
            remaining_time = sum(duration for _, duration in sorted_titles[max_titles:])
            remaining_events = sum(title_count[title] for title, _ in sorted_titles[max_titles:])
            print(
                f"  {remaining_time / 60:5.1f}min ({remaining_events:2d}x) - ... and {remaining_count} other titles"
            )
            lines_printed += 1

    print("\n" + "=" * 80 + "\n")


def truncate_string(s: str, max_length: int = 50) -> str:
    """Truncate a string to max_length, adding ellipsis if needed."""
    if len(s) <= max_length:
        return s
    return s[: max_length - 3] + "..."


def format_duration(duration: timedelta) -> str:
    """Format a timedelta as HH:MM:SS."""
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def extract_specialized_data(exporter: "Exporter", window_event: dict) -> dict[str, Any]:
    """Extract specialized watcher data (file path for editors, URL for browsers).

    Uses the exporter's existing get_corresponding_event() method which already
    handles all the logic of finding specialized watcher events (browsers, editors).
    This mirrors the same approach used in get_browser_tags() and get_editor_tags().

    Args:
        exporter: The Exporter instance with access to buckets
        window_event: The window event to analyze

    Returns:
        Dictionary with keys: app, specialized_type, specialized_data
    """
    result = {
        "app": window_event["data"].get("app", ""),
        "specialized_type": None,
        "specialized_data": None,
    }

    app = result["app"].lower()

    # Check for editor events - mirrors logic from get_editor_tags()
    if app in ("emacs", "vi", "vim"):
        result["specialized_type"] = "editor"
        try:
            # Use same bucket pattern as get_editor_tags()
            bucket_key = f"aw-watcher-{app}"
            if bucket_key in exporter.event_fetcher.bucket_short:
                bucket_id = exporter.event_fetcher.bucket_short[bucket_key]["id"]
                ignorable = exporter._is_ignorable_event(app, window_event)
                # Use the public get_corresponding_event() method
                sub_event = exporter.event_fetcher.get_corresponding_event(
                    window_event, bucket_id, ignorable=ignorable
                )

                if sub_event:
                    file_path = sub_event["data"].get("file", "")
                    project = sub_event["data"].get("project", "")
                    if file_path:
                        result["specialized_data"] = file_path
                    elif project:
                        result["specialized_data"] = f"project:{project}"
        except Exception:
            pass

    # Check for browser events - mirrors logic from get_browser_tags()
    elif app in ("chromium", "chrome", "firefox"):
        result["specialized_type"] = "browser"
        try:
            # Normalize app name as done in get_browser_tags()
            app_normalized = "chrome" if app == "chromium" else app
            bucket_key = f"aw-watcher-web-{app_normalized}"

            if bucket_key in exporter.event_fetcher.bucket_short:
                bucket_id = exporter.event_fetcher.bucket_short[bucket_key]["id"]
                # Use the public get_corresponding_event() method
                sub_event = exporter.event_fetcher.get_corresponding_event(window_event, bucket_id)

                if sub_event:
                    url = sub_event["data"].get("url", "")
                    # Skip internal pages (same check as in get_browser_tags())
                    if url and url not in ("chrome://newtab/", "about:newtab"):
                        result["specialized_data"] = url
        except Exception:
            pass

    return result


def collect_report_data(
    exporter: "Exporter", start_time: datetime, end_time: datetime
) -> list[dict[str, Any]]:
    """Collect activity data for the report.

    Returns a list of dictionaries with keys:
    - timestamp: Event start time
    - duration: Event duration
    - window_title: Window title
    - app: Application name
    - specialized_type: 'editor', 'browser', or None
    - specialized_data: File path or URL
    - afk_status: 'afk', 'not-afk', or 'unknown'
    - tags: Set of determined tags
    """
    # Get window and AFK buckets
    window_id = exporter.event_fetcher.bucket_by_client["aw-watcher-window"][0]
    afk_id = exporter.event_fetcher.bucket_by_client["aw-watcher-afk"][0]

    # Fetch window events
    window_events = exporter.event_fetcher.get_events(window_id, start=start_time, end=end_time)
    afk_events = exporter.event_fetcher.get_events(afk_id, start=start_time, end=end_time)

    # Create AFK status lookup
    afk_status_map = {}
    for afk_event in afk_events:
        afk_start = afk_event["timestamp"]
        afk_end = afk_start + afk_event["duration"]
        status = afk_event["data"].get("status", "unknown")
        afk_status_map[(afk_start, afk_end)] = status

    # Process window events
    report_data = []
    for window_event in window_events:
        # Determine AFK status for this event
        event_start = window_event["timestamp"]
        event_end = event_start + window_event["duration"]
        afk_status = "unknown"

        # Find overlapping AFK event
        for (afk_start, afk_end), status in afk_status_map.items():
            # Check if there's overlap
            if event_start < afk_end and event_end > afk_start:
                afk_status = status
                break

        # Extract specialized data
        specialized = extract_specialized_data(exporter, window_event)

        # Determine tags using exporter's tag_extractor logic
        tags = set()
        for method in (
            exporter.tag_extractor.get_afk_tags,
            exporter.tag_extractor.get_app_tags,
            exporter.tag_extractor.get_browser_tags,
            exporter.tag_extractor.get_editor_tags,
        ):
            try:
                result_tags = method(window_event)
                if result_tags and result_tags is not False:
                    tags.update(result_tags)
                    break
            except Exception:
                pass

        # If no tags found, mark as unmatched
        if not tags:
            tags = {"UNMATCHED"}

        report_data.append(
            {
                "timestamp": event_start,
                "duration": window_event["duration"],
                "window_title": window_event["data"].get("title", ""),
                "app": specialized["app"],
                "specialized_type": specialized["specialized_type"],
                "specialized_data": specialized["specialized_data"] or "",
                "afk_status": afk_status,
                "tags": tags,
            }
        )

    # Sort by timestamp
    report_data.sort(key=lambda x: x["timestamp"])

    return report_data


def format_as_table(
    data: list[dict[str, Any]], all_columns: bool = False, truncate: bool = True
) -> None:
    """Format and print report data as a table.

    Args:
        data: List of report data dictionaries
        all_columns: If True, show all columns; otherwise show main columns only
        truncate: If True, truncate long values to fit
    """
    if not data:
        print("No data to display")
        return

    # Define column widths
    if truncate:
        col_widths = {
            "time": 8,  # HH:MM:SS
            "duration": 8,  # HH:MM:SS
            "window": 50,
            "specialized": 60,
            "afk": 8,
            "tags": 40,
        }
    else:
        col_widths = {
            "time": 8,
            "duration": 8,
            "window": None,
            "specialized": None,
            "afk": 8,
            "tags": None,
        }

    # Print header
    if all_columns:
        print(
            f"{'Time':<8} {'Dur':<8} {'Window Title':<50} {'App':<15} {'Type':<8} {'File/URL':<60} {'AFK':<8} {'Tags'}"
        )
        print("=" * 180)
    else:
        print(f"{'Time':<8} {'Dur':<8} {'Window Title':<50} {'File/URL':<60} {'AFK':<8} {'Tags'}")
        print("=" * 145)

    # Print data rows
    for row in data:
        # Convert timestamp to local time for display
        local_time = row["timestamp"].astimezone()
        time_str = local_time.strftime("%H:%M:%S")
        duration_str = format_duration(row["duration"])
        window_title = row["window_title"]
        specialized = row["specialized_data"]
        afk = row["afk_status"]
        tags_str = ", ".join(sorted(row["tags"]))

        if truncate:
            window_title = truncate_string(window_title, col_widths["window"])
            specialized = truncate_string(specialized, col_widths["specialized"])
            tags_str = truncate_string(tags_str, col_widths["tags"])

        if all_columns:
            app = truncate_string(row["app"], 15) if truncate else row["app"]
            spec_type = row["specialized_type"] or "-"
            print(
                f"{time_str:<8} {duration_str:<8} {window_title:<50} {app:<15} {spec_type:<8} {specialized:<60} {afk:<8} {tags_str}"
            )
        else:
            print(
                f"{time_str:<8} {duration_str:<8} {window_title:<50} {specialized:<60} {afk:<8} {tags_str}"
            )


def format_as_csv(
    data: list[dict[str, Any]], all_columns: bool = False, delimiter: str = ","
) -> None:
    """Format and print report data as CSV/TSV.

    Args:
        data: List of report data dictionaries
        all_columns: If True, include all columns; otherwise main columns only
        delimiter: Field delimiter (',' for CSV, '\t' for TSV)
    """
    writer = csv.writer(sys.stdout, delimiter=delimiter)

    # Write header
    if all_columns:
        headers = [
            "timestamp",
            "duration_seconds",
            "window_title",
            "app",
            "specialized_type",
            "specialized_data",
            "afk_status",
            "tags",
        ]
    else:
        headers = [
            "timestamp",
            "duration_seconds",
            "window_title",
            "specialized_data",
            "afk_status",
            "tags",
        ]
    writer.writerow(headers)

    # Write data
    for row in data:
        tags_str = ",".join(sorted(row["tags"]))
        duration_sec = int(row["duration"].total_seconds())

        if all_columns:
            writer.writerow(
                [
                    row["timestamp"].isoformat(),
                    duration_sec,
                    row["window_title"],
                    row["app"],
                    row["specialized_type"] or "",
                    row["specialized_data"],
                    row["afk_status"],
                    tags_str,
                ]
            )
        else:
            writer.writerow(
                [
                    row["timestamp"].isoformat(),
                    duration_sec,
                    row["window_title"],
                    row["specialized_data"],
                    row["afk_status"],
                    tags_str,
                ]
            )


def generate_activity_report(
    exporter: "Exporter",
    all_columns: bool = False,
    format: str = "table",
    truncate: bool = True,
) -> None:
    """Generate and display an activity report.

    Args:
        exporter: Exporter instance configured for reading ActivityWatch data
        all_columns: Whether to show all available columns
        format: Output format ('table', 'csv', 'tsv')
        truncate: Whether to truncate long values (table mode only)
    """
    # Collect report data
    data = collect_report_data(exporter, exporter.start_time, exporter.end_time)

    # Format and output
    if format == "table":
        format_as_table(data, all_columns=all_columns, truncate=truncate)
    elif format == "csv":
        format_as_csv(data, all_columns=all_columns, delimiter=",")
    elif format == "tsv":
        format_as_csv(data, all_columns=all_columns, delimiter="\t")
    else:
        raise ValueError(f"Unknown format: {format}")

    # Print summary to stderr
    print(f"\nTotal events: {len(data)}", file=sys.stderr)
    total_duration = sum((row["duration"] for row in data), timedelta())
    print(f"Total duration: {format_duration(total_duration)}", file=sys.stderr)
