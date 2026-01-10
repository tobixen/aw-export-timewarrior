"""Activity report generation module.

Generates detailed reports showing ActivityWatch events with columns for:
- Timestamp
- Window title
- Specialized watcher data (file paths for editors, URLs for browsers)
- AFK status
- Determined tags
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .main import Exporter

# Available columns for report output
AVAILABLE_COLUMNS = [
    "timestamp",
    "duration",
    "window_title",
    "app",
    "specialized_type",
    "specialized_data",
    "afk_status",
    "tags",
    "matched_rule",
]

# Default columns shown in table mode
DEFAULT_COLUMNS = [
    "timestamp",
    "duration",
    "window_title",
    "specialized_data",
    "afk_status",
    "tags",
]


def format_accumulator(accumulator: dict[str, timedelta]) -> str:
    """Format an accumulator dict for display.

    Args:
        accumulator: Dict mapping tag names to accumulated timedeltas

    Returns:
        Formatted string representation, e.g., "work:5m, coding:3m30s"
    """
    if not accumulator:
        return "-"

    parts = []
    for tag, duration in sorted(accumulator.items()):
        total_seconds = int(duration.total_seconds())
        if total_seconds < 60:
            parts.append(f"{tag}:{total_seconds}s")
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            if seconds:
                parts.append(f"{tag}:{minutes}m{seconds}s")
            else:
                parts.append(f"{tag}:{minutes}m")
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            if minutes:
                parts.append(f"{tag}:{hours}h{minutes}m")
            else:
                parts.append(f"{tag}:{hours}h")

    return ", ".join(parts)


def interleave_exports(
    events: list[dict[str, Any]],
    exports: list[Any],  # ExportRecord from state module
) -> list[dict[str, Any]]:
    """Interleave export records with event data by timestamp.

    Each export is represented as three entries in the timeline:
    1. export_start: Marks when the exported interval began
    2. export_decision: Marks when the export decision was triggered
    3. export_end: Marks when the exported interval ended (= start of next interval)

    Args:
        events: List of event dictionaries with 'timestamp' key
        exports: List of ExportRecord objects

    Returns:
        Combined list sorted by timestamp, with export records converted to dicts
    """
    # Convert exports to dict format for consistent handling
    # Each export creates three entries: start, decision, and end markers
    export_dicts = []
    for export in exports:
        # Start marker - when the exported interval began
        start_dict = {
            "timestamp": export.timestamp,
            "duration": export.duration,
            "tags": export.tags,
            "row_type": "export_start",
        }
        export_dicts.append(start_dict)

        # Decision marker - when the export decision was triggered
        # (only if decision_timestamp is available)
        if export.decision_timestamp is not None:
            decision_dict = {
                "timestamp": export.decision_timestamp,
                "duration": export.duration,
                "tags": export.tags,
                "accumulator_before": export.accumulator_before,
                "row_type": "export_decision",
            }
            export_dicts.append(decision_dict)

        # End marker - when the exported interval ended (= start of next interval)
        end_dict = {
            "timestamp": export.end_timestamp,
            "duration": export.duration,
            "tags": export.tags,
            "accumulator_before": export.accumulator_before,
            "accumulator_after": export.accumulator_after,
            "row_type": "export_end",
        }
        export_dicts.append(end_dict)

    # Mark events with row_type if not already set
    for event in events:
        if "row_type" not in event:
            event["row_type"] = "event"

    # Combine and sort by timestamp
    combined = events + export_dicts
    combined.sort(key=lambda x: x["timestamp"])

    return combined


def show_unmatched_events_report(
    unmatched_events: list[dict],
    limit: int = 10,
    verbose: bool = False,
    exporter: "Exporter | None" = None,
) -> None:
    """Display a report of events that didn't match any rules.

    Args:
        unmatched_events: List of event dictionaries that didn't match any rules
        limit: Maximum number of output lines to show (default: 10)
        verbose: If True, show additional context (URLs, paths, tmux info)
        exporter: Exporter instance for fetching sub-events (required for verbose)
    """
    # Check for ignored events (below duration threshold)
    ignored_count = 0
    ignored_time = timedelta(0)
    if exporter:
        ignored_count = exporter.state.stats.ignored_events_count
        ignored_time = exporter.state.stats.ignored_events_time

    if not unmatched_events and ignored_count == 0:
        print("\nNo unmatched events found - all events matched configuration rules.")
        return

    print("\n" + "=" * 80)
    print("Events Not Matching Any Rules")
    print("=" * 80)

    # Calculate total unmatched time
    total_unmatched_seconds = sum((e["duration"].total_seconds() for e in unmatched_events), 0)

    if unmatched_events:
        print(
            f"\nFound {len(unmatched_events)} unmatched events, {total_unmatched_seconds / 60:.1f} min total:\n"
        )
    else:
        print("\nNo unmatched events above duration threshold.")

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
        title_events: dict[str, list] = defaultdict(list)  # For verbose mode
        for event in events:
            title = event["data"].get("title", "(no title)")
            title_durations[title] += event["duration"].total_seconds()
            title_count[title] += 1
            if verbose:
                title_events[title].append(event)

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

            # In verbose mode, show specialized data for this title's events
            if verbose and exporter:
                specialized_seen: set[str] = set()
                for event in title_events[title][:3]:  # Limit to 3 examples per title
                    spec_data = exporter.tag_extractor.get_specialized_context(event)
                    if spec_data["data"]:
                        data_str = spec_data["data"]
                        if data_str not in specialized_seen:
                            specialized_seen.add(data_str)
                            # Truncate long data
                            if len(data_str) > 70:
                                data_str = data_str[:67] + "..."
                            print(f"         └─ {spec_data['type']}: {data_str}")
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

    # Show ignored events summary (events below duration threshold)
    if ignored_count > 0:
        ignored_minutes = ignored_time.total_seconds() / 60
        print(f"\nAdditionally, {ignored_count} events ({ignored_minutes:.1f} min) were below the")
        print("duration threshold and not tracked. Use --ignore-interval to adjust.")

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
                # retry=0: Don't sleep waiting for events - we're just reading history
                sub_event = exporter.event_fetcher.get_corresponding_event(
                    window_event, bucket_id, ignorable=ignorable, retry=0
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
                # retry=0: Don't sleep waiting for events - we're just reading history
                sub_event = exporter.event_fetcher.get_corresponding_event(
                    window_event, bucket_id, retry=0
                )

                if sub_event:
                    url = sub_event["data"].get("url", "")
                    # Skip internal pages (same check as in get_browser_tags())
                    if url and url not in ("chrome://newtab/", "about:newtab"):
                        result["specialized_data"] = url
        except Exception:
            pass

    # Check for terminal apps that might have tmux data
    elif app in exporter.config.get("terminal_apps", []):
        result["specialized_type"] = "terminal"
        try:
            tmux_bucket = exporter.event_fetcher.get_tmux_bucket()
            if tmux_bucket:
                # retry=0: Don't sleep waiting for events - we're just reading history
                sub_event = exporter.event_fetcher.get_corresponding_event(
                    window_event, tmux_bucket, retry=0
                )
                if sub_event:
                    # Build tmux info string
                    cmd = sub_event["data"].get("pane_current_command", "")
                    path = sub_event["data"].get("pane_current_path", "")
                    pane_title = sub_event["data"].get("pane_title", "")
                    if cmd or path:
                        parts = []
                        if cmd:
                            parts.append(f"cmd:{cmd}")
                        if path:
                            # Shorten home directory
                            if path.startswith("/home/"):
                                path = "~/" + "/".join(path.split("/")[3:])
                            parts.append(f"path:{path}")
                        if pane_title and pane_title not in (cmd, path):
                            parts.append(f"title:{pane_title}")
                        result["specialized_data"] = " | ".join(parts)
        except Exception:
            pass

    return result


def collect_report_data(
    exporter: "Exporter",
    start_time: datetime,
    end_time: datetime,
    include_rule: bool = False,
) -> list[dict[str, Any]]:
    """Collect activity data for the report.

    Args:
        exporter: Exporter instance
        start_time: Start of time range
        end_time: End of time range
        include_rule: If True, include which rule matched each event

    Returns a list of dictionaries with keys:
    - timestamp: Event start time
    - duration: Event duration
    - window_title: Window title
    - app: Application name
    - specialized_type: 'editor', 'browser', or None
    - specialized_data: File path or URL
    - afk_status: 'afk', 'not-afk', or 'unknown'
    - tags: Set of determined tags
    - matched_rule: Rule that matched (if include_rule=True)
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

        # Determine tags using exporter's tag_extractor
        result_tags = exporter.tag_extractor.get_tags(window_event)
        matched_rule = exporter.tag_extractor.last_matched_rule if include_rule else None

        tags = set(result_tags) if result_tags and result_tags is not False else {"UNMATCHED"}

        row_data = {
            "timestamp": event_start,
            "duration": window_event["duration"],
            "window_title": window_event["data"].get("title", ""),
            "app": specialized["app"],
            "specialized_type": specialized["specialized_type"],
            "specialized_data": specialized["specialized_data"] or "",
            "afk_status": afk_status,
            "tags": tags,
        }

        if include_rule:
            row_data["matched_rule"] = matched_rule

        report_data.append(row_data)

    # Sort by timestamp
    report_data.sort(key=lambda x: x["timestamp"])

    return report_data


def format_as_table(
    data: list[dict[str, Any]],
    all_columns: bool = False,
    truncate: bool = True,
    show_rule: bool = False,
    columns: list[str] | None = None,
    show_exports: bool = False,
) -> None:
    """Format and print report data as a table.

    Args:
        data: List of report data dictionaries (may include export rows)
        all_columns: If True, show all columns; otherwise show main columns only
        truncate: If True, truncate long values to fit
        show_rule: If True, show the matched_rule column
        columns: Specific columns to show (overrides all_columns if set)
        show_exports: If True, data may contain export rows to be displayed
    """
    from termcolor import colored

    if not data:
        print("No data to display")
        return

    # Define column widths
    col_widths = {
        "time": 8,  # HH:MM:SS
        "duration": 8,  # HH:MM:SS
        "window": 50 if truncate else None,
        "app": 15,
        "type": 8,
        "specialized": 60 if truncate else None,
        "afk": 8,
        "tags": 40 if truncate else None,
        "rule": 30 if truncate else None,
    }

    # Build header based on columns to show
    if columns:
        # Custom column selection (future feature)
        pass
    elif all_columns:
        header_parts = [
            f"{'Time':<8}",
            f"{'Dur':<8}",
            f"{'Window Title':<50}",
            f"{'App':<15}",
            f"{'Type':<8}",
            f"{'File/URL':<60}",
            f"{'AFK':<8}",
            f"{'Tags':<40}" if show_rule else "Tags",
        ]
        if show_rule:
            header_parts.append("Rule")
        print(" ".join(header_parts))
        print("=" * (210 if show_rule else 180))
    else:
        header_parts = [
            f"{'Time':<8}",
            f"{'Dur':<8}",
            f"{'Window Title':<50}",
            f"{'File/URL':<60}",
            f"{'AFK':<8}",
            f"{'Tags':<40}" if show_rule else "Tags",
        ]
        if show_rule:
            header_parts.append("Rule")
        print(" ".join(header_parts))
        print("=" * (175 if show_rule else 145))

    # Print data rows
    for row in data:
        # Convert timestamp to local time for display
        local_time = row["timestamp"].astimezone()
        time_str = local_time.strftime("%H:%M:%S")
        duration_str = format_duration(row["duration"])

        # Check if this is an export row
        row_type = row.get("row_type", "event")

        if row_type == "export_start" and show_exports:
            # Export start marker - shows when the exported interval began
            tags_str = ", ".join(sorted(row["tags"]))
            if truncate:
                tags_str = truncate_string(tags_str, 40)

            export_marker = "[EXPORT START]"
            line = f"{time_str:<8} {duration_str:<8} {export_marker} {tags_str}"

            # Print with color (green for export start)
            print(colored(line, "green"))

        elif row_type == "export_decision" and show_exports:
            # Export decision marker - shows when threshold was reached
            tags_str = ", ".join(sorted(row["tags"]))
            acc_before = format_accumulator(row.get("accumulator_before", {}))

            if truncate:
                tags_str = truncate_string(tags_str, 30)
                acc_before = truncate_string(acc_before, 50)

            export_marker = "[EXPORT DECISION]"
            export_info = f"{export_marker} {tags_str} | accumulated: {acc_before}"
            line = f"{time_str:<8} {duration_str:<8} {export_info}"

            # Print with color (yellow for export decision)
            print(colored(line, "yellow"))

        elif row_type == "export_end" and show_exports:
            # Export end marker - shows when export decision was made (with details)
            tags_str = ", ".join(sorted(row["tags"]))
            acc_before = format_accumulator(row.get("accumulator_before", {}))
            acc_after = format_accumulator(row.get("accumulator_after", {}))

            if truncate:
                tags_str = truncate_string(tags_str, 30)
                acc_before = truncate_string(acc_before, 40)
                acc_after = truncate_string(acc_after, 40)

            export_marker = "[EXPORT END]"
            export_info = f"{export_marker} {tags_str} | before: {acc_before} | after: {acc_after}"
            line = f"{time_str:<8} {duration_str:<8} {export_info}"

            # Print with color (cyan bold for export end)
            print(colored(line, "cyan", attrs=["bold"]))

        elif row_type == "export" and show_exports:
            # Legacy single-line export format (for backwards compatibility)
            tags_str = ", ".join(sorted(row["tags"]))
            acc_before = format_accumulator(row.get("accumulator_before", {}))
            acc_after = format_accumulator(row.get("accumulator_after", {}))

            if truncate:
                tags_str = truncate_string(tags_str, 30)
                acc_before = truncate_string(acc_before, 40)
                acc_after = truncate_string(acc_after, 40)

            export_marker = "[EXPORT]"
            export_info = f"{export_marker} {tags_str} | before: {acc_before} | after: {acc_after}"
            line = f"{time_str:<8} {duration_str:<8} {export_info}"

            print(colored(line, "cyan", attrs=["bold"]))
        else:
            # Regular event row
            window_title = row.get("window_title", "")
            specialized = row.get("specialized_data", "")
            afk = row.get("afk_status", "unknown")
            tags_str = ", ".join(sorted(row["tags"]))
            rule_str = row.get("matched_rule", "") or ""

            if truncate:
                window_title = truncate_string(window_title, col_widths["window"])
                specialized = truncate_string(specialized, col_widths["specialized"])
                tags_str = truncate_string(tags_str, col_widths["tags"])
                rule_str = truncate_string(rule_str, col_widths["rule"])

            if all_columns:
                app = truncate_string(row.get("app", ""), 15) if truncate else row.get("app", "")
                spec_type = row.get("specialized_type") or "-"
                line = (
                    f"{time_str:<8} {duration_str:<8} {window_title:<50} {app:<15} {spec_type:<8} {specialized:<60} {afk:<8} {tags_str:<40}"
                    if show_rule
                    else f"{time_str:<8} {duration_str:<8} {window_title:<50} {app:<15} {spec_type:<8} {specialized:<60} {afk:<8} {tags_str}"
                )
                if show_rule:
                    line += f" {rule_str}"
                print(line)
            else:
                line = (
                    f"{time_str:<8} {duration_str:<8} {window_title:<50} {specialized:<60} {afk:<8} {tags_str:<40}"
                    if show_rule
                    else f"{time_str:<8} {duration_str:<8} {window_title:<50} {specialized:<60} {afk:<8} {tags_str}"
                )
                if show_rule:
                    line += f" {rule_str}"
                print(line)


def format_as_csv(
    data: list[dict[str, Any]],
    all_columns: bool = False,
    delimiter: str = ",",
    include_rule: bool = False,
) -> None:
    """Format and print report data as CSV/TSV.

    Args:
        data: List of report data dictionaries
        all_columns: If True, include all columns; otherwise main columns only
        delimiter: Field delimiter (',' for CSV, '\t' for TSV)
        include_rule: If True, include the matched_rule column
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
    if include_rule:
        headers.append("matched_rule")
    writer.writerow(headers)

    # Write data
    for row in data:
        tags_str = ",".join(sorted(row["tags"]))
        duration_sec = int(row["duration"].total_seconds())

        if all_columns:
            row_data = [
                row["timestamp"].isoformat(),
                duration_sec,
                row["window_title"],
                row["app"],
                row["specialized_type"] or "",
                row["specialized_data"],
                row["afk_status"],
                tags_str,
            ]
        else:
            row_data = [
                row["timestamp"].isoformat(),
                duration_sec,
                row["window_title"],
                row["specialized_data"],
                row["afk_status"],
                tags_str,
            ]
        if include_rule:
            row_data.append(row.get("matched_rule", "") or "")
        writer.writerow(row_data)


def _build_json_record(
    row: dict[str, Any],
    output_columns: list[str],
    include_exports: bool = False,
) -> dict[str, Any] | None:
    """Build a JSON record from a data row.

    Args:
        row: The data row to convert
        output_columns: List of columns to include for event rows
        include_exports: If True, include export rows in output

    Returns:
        A dictionary representing the JSON record, or None if the row should be skipped
    """
    row_type = row.get("row_type", "event")

    if row_type == "export_start" and include_exports:
        # Format export start marker
        return {
            "row_type": "export_start",
            "timestamp": row["timestamp"].isoformat(),
            "duration_seconds": int(row["duration"].total_seconds()),
            "tags": sorted(row["tags"]),
        }
    elif row_type == "export_decision" and include_exports:
        # Format export decision marker
        return {
            "row_type": "export_decision",
            "timestamp": row["timestamp"].isoformat(),
            "duration_seconds": int(row["duration"].total_seconds()),
            "tags": sorted(row["tags"]),
            "accumulator_before": {
                tag: int(duration.total_seconds())
                for tag, duration in row.get("accumulator_before", {}).items()
            },
        }
    elif row_type == "export_end" and include_exports:
        # Format export end marker (with accumulator details)
        return {
            "row_type": "export_end",
            "timestamp": row["timestamp"].isoformat(),
            "duration_seconds": int(row["duration"].total_seconds()),
            "tags": sorted(row["tags"]),
            "accumulator_before": {
                tag: int(duration.total_seconds())
                for tag, duration in row.get("accumulator_before", {}).items()
            },
            "accumulator_after": {
                tag: int(duration.total_seconds())
                for tag, duration in row.get("accumulator_after", {}).items()
            },
        }
    elif row_type == "export" and include_exports:
        # Legacy single-line export format
        return {
            "row_type": "export",
            "timestamp": row["timestamp"].isoformat(),
            "duration_seconds": int(row["duration"].total_seconds()),
            "tags": sorted(row["tags"]),
            "accumulator_before": {
                tag: int(duration.total_seconds())
                for tag, duration in row.get("accumulator_before", {}).items()
            },
            "accumulator_after": {
                tag: int(duration.total_seconds())
                for tag, duration in row.get("accumulator_after", {}).items()
            },
        }
    elif (
        row_type in ("export_start", "export_decision", "export_end", "export")
        and not include_exports
    ):
        # Skip export rows if not included
        return None
    else:
        # Format event row
        record: dict[str, Any] = {"row_type": "event"} if include_exports else {}
        for col in output_columns:
            if col == "timestamp":
                record["timestamp"] = row["timestamp"].isoformat()
            elif col == "duration":
                record["duration_seconds"] = int(row["duration"].total_seconds())
            elif col == "tags":
                record["tags"] = sorted(row["tags"])
            elif col == "matched_rule":
                record["matched_rule"] = row.get("matched_rule")
            elif col in row:
                record[col] = row[col]
        return record


def _get_output_columns(
    all_columns: bool = False,
    columns: list[str] | None = None,
    include_rule: bool = False,
) -> list[str]:
    """Determine which columns to output for events.

    Args:
        all_columns: If True, include all columns
        columns: Specific columns to include (overrides all_columns if set)
        include_rule: If True, include the matched_rule column

    Returns:
        List of column names to include
    """
    if columns:
        return columns
    elif all_columns:
        output_columns = AVAILABLE_COLUMNS.copy()
        if not include_rule:
            output_columns = [c for c in output_columns if c != "matched_rule"]
        return output_columns
    else:
        output_columns = DEFAULT_COLUMNS.copy()
        if include_rule:
            output_columns.append("matched_rule")
        return output_columns


def format_as_json(
    data: list[dict[str, Any]],
    all_columns: bool = False,
    columns: list[str] | None = None,
    include_rule: bool = False,
    include_exports: bool = False,
) -> None:
    """Format and print report data as a valid JSON array.

    Args:
        data: List of report data dictionaries (may include export rows)
        all_columns: If True, include all columns
        columns: Specific columns to include (overrides all_columns if set)
        include_rule: If True, include the matched_rule column
        include_exports: If True, data may contain export rows to be output
    """
    output_columns = _get_output_columns(all_columns, columns, include_rule)

    records = []
    for row in data:
        record = _build_json_record(row, output_columns, include_exports)
        if record is not None:
            records.append(record)

    print(json.dumps(records, indent=2))


def format_as_ndjson(
    data: list[dict[str, Any]],
    all_columns: bool = False,
    columns: list[str] | None = None,
    include_rule: bool = False,
    include_exports: bool = False,
) -> None:
    """Format and print report data as NDJSON (newline-delimited JSON, one JSON object per line).

    Args:
        data: List of report data dictionaries (may include export rows)
        all_columns: If True, include all columns
        columns: Specific columns to include (overrides all_columns if set)
        include_rule: If True, include the matched_rule column
        include_exports: If True, data may contain export rows to be output
    """
    output_columns = _get_output_columns(all_columns, columns, include_rule)

    for row in data:
        record = _build_json_record(row, output_columns, include_exports)
        if record is not None:
            print(json.dumps(record))


def generate_activity_report(
    exporter: "Exporter",
    all_columns: bool = False,
    format: str = "table",
    truncate: bool = True,
    show_rule: bool = False,
    show_exports: bool = False,
) -> None:
    """Generate and display an activity report.

    Args:
        exporter: Exporter instance configured for reading ActivityWatch data
        all_columns: Whether to show all available columns
        format: Output format ('table', 'csv', 'tsv', 'json')
        truncate: Whether to truncate long values (table mode only)
        show_rule: Whether to show which rule matched each event
        show_exports: Whether to show export decisions interleaved with events
    """
    # Include rule data if explicitly requested OR if showing all columns
    include_rule = show_rule or all_columns

    # Collect report data
    data = collect_report_data(
        exporter, exporter.start_time, exporter.end_time, include_rule=include_rule
    )

    # If showing exports, run the exporter to track export decisions
    exports = []
    if show_exports:
        # Enable export tracking
        exporter.state.track_exports = True
        # Process all events to trigger export decisions
        exporter.tick(process_all=True)
        # Get exports in the time range
        exports = exporter.state.get_exports_in_range(exporter.start_time, exporter.end_time)
        # Interleave exports with events
        if exports:
            data = interleave_exports(data, exports)

    # Format and output
    if format == "table":
        format_as_table(
            data,
            all_columns=all_columns,
            truncate=truncate,
            show_rule=include_rule,
            show_exports=show_exports,
        )
    elif format == "csv":
        format_as_csv(data, all_columns=all_columns, delimiter=",", include_rule=include_rule)
    elif format == "tsv":
        format_as_csv(data, all_columns=all_columns, delimiter="\t", include_rule=include_rule)
    elif format == "json":
        format_as_json(
            data, all_columns=all_columns, include_rule=include_rule, include_exports=show_exports
        )
    elif format == "ndjson":
        format_as_ndjson(
            data, all_columns=all_columns, include_rule=include_rule, include_exports=show_exports
        )
    else:
        raise ValueError(f"Unknown format: {format}")

    # Print summary to stderr (skip for JSON/NDJSON formats to keep output clean)
    if format not in ("json", "ndjson"):
        event_count = sum(1 for row in data if row.get("row_type", "event") == "event")
        export_count = sum(1 for row in data if row.get("row_type") == "export")
        print(f"\nTotal events: {event_count}", file=sys.stderr)
        if show_exports and export_count > 0:
            print(f"Total exports: {export_count}", file=sys.stderr)
        total_duration = sum(
            (row["duration"] for row in data if row.get("row_type", "event") == "event"),
            timedelta(),
        )
        print(f"Total duration: {format_duration(total_duration)}", file=sys.stderr)
