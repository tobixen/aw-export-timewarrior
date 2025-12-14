"""
Export ActivityWatch data to JSON/YAML for testing and analysis.

This module provides functionality to record real ActivityWatch data
for use in tests and debugging.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aw_client

from .utils import parse_datetime


def serialize_event(event: Any) -> dict[str, Any]:
    """
    Convert an ActivityWatch event object to a JSON-serializable dict.

    Args:
        event: AW event object

    Returns:
        Dictionary with event data
    """
    return {
        "id": getattr(event, "id", None),
        "timestamp": event.timestamp.isoformat() if hasattr(event, "timestamp") else None,
        "duration": event.duration.total_seconds() if hasattr(event, "duration") else 0,
        "data": event.data if hasattr(event, "data") else {},
    }


def export_aw_data(
    start: str | datetime,
    end: str | datetime,
    output_file: str | Path,
    format: str = "json",
    anonymize: bool = False,
) -> None:
    """
    Export ActivityWatch data for a time period.

    Args:
        start: Start time (datetime or string)
        end: End time (datetime or string)
        output_file: Output file path (use '-' for stdout)
        format: Output format ('json' or 'yaml')
        anonymize: If True, anonymize sensitive data (URLs, titles, etc.)
    """
    import sys

    # Check if output is stdout (for directing progress messages)
    use_stdout = str(output_file) == "-"
    progress_output = sys.stderr if use_stdout else sys.stdout

    # Parse datetime strings if needed
    if isinstance(start, str):
        start = parse_datetime(start)
    if isinstance(end, str):
        end = parse_datetime(end)

    # Connect to ActivityWatch
    aw = aw_client.ActivityWatchClient("data-exporter")
    buckets = aw.get_buckets()

    # Collect data from all relevant buckets
    data = {
        "metadata": {
            "export_time": datetime.now(UTC).isoformat(),
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "duration_seconds": (end - start).total_seconds(),
            "anonymized": anonymize,
        },
        "buckets": {},
        "events": {},
    }

    # Export bucket metadata
    for bucket_id, bucket in buckets.items():
        data["buckets"][bucket_id] = {
            "id": bucket["id"],
            "name": bucket.get("name", bucket_id),
            "type": bucket.get("type", "unknown"),
            "client": bucket.get("client", "unknown"),
            "hostname": bucket.get("hostname", "unknown"),
            "created": bucket.get("created", None),
        }

    # Export events from each bucket
    for bucket_id in buckets:
        try:
            events = aw.get_events(bucket_id, start=start, end=end)

            if events:
                serialized_events = [serialize_event(e) for e in events]

                # Anonymize if requested
                if anonymize:
                    serialized_events = [anonymize_event(e) for e in serialized_events]

                data["events"][bucket_id] = serialized_events
                print(f"  {bucket_id}: {len(events)} events", file=progress_output)
            else:
                print(f"  {bucket_id}: No events", file=progress_output)

        except Exception as e:
            print(f"  {bucket_id}: Error - {e}", file=progress_output)
            data["events"][bucket_id] = {"error": str(e)}

    # Write output file or stdout
    # (use_stdout already determined above)

    if not use_stdout:
        output_path = Path(output_file)
        # Determine format from file extension if not explicitly set
        if format == "json" and output_path.suffix in [".yaml", ".yml"]:
            format = "yaml"
    else:
        output_path = None
        # Default to JSON for stdout unless explicitly set
        if format != "yaml":
            format = "json"

    # Write YAML format
    if format == "yaml":
        try:
            import yaml

            if use_stdout:
                yaml.dump(data, sys.stdout, default_flow_style=False, sort_keys=False)
            else:
                with open(output_path, "w") as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        except ImportError:
            print("Warning: PyYAML not installed, using JSON instead", file=sys.stderr)
            format = "json"

    # Write JSON format
    if format == "json":
        if use_stdout:
            json.dump(data, sys.stdout, indent=2, sort_keys=False)
            sys.stdout.write("\n")  # Add newline at end
        else:
            with open(output_path, "w") as f:
                json.dump(data, f, indent=2, sort_keys=False)

    # Print summary to stderr when using stdout, otherwise to stdout
    summary_output = sys.stderr if use_stdout else sys.stdout
    print(
        f"\nExported {sum(len(e) if isinstance(e, list) else 0 for e in data['events'].values())} total events",
        file=summary_output,
    )


def anonymize_event(event: dict[str, Any]) -> dict[str, Any]:
    """
    Anonymize sensitive data in an event.

    Replaces URLs, titles, file paths, etc. with generic placeholders
    while preserving the structure and patterns.

    Args:
        event: Event dictionary

    Returns:
        Anonymized event dictionary
    """
    anon_event = event.copy()
    data = anon_event.get("data", {}).copy()

    # Anonymize URLs
    if "url" in data:
        from urllib.parse import urlparse

        parsed = urlparse(data["url"])
        # Keep domain pattern but anonymize specifics
        domain_parts = parsed.netloc.split(".")
        if len(domain_parts) >= 2:
            anon_domain = f"{domain_parts[-2]}.{domain_parts[-1]}"  # Keep TLD
        else:
            anon_domain = "example.com"
        data["url"] = f"{parsed.scheme}://{anon_domain}/[path]"

    # Anonymize titles
    if "title" in data:
        # Keep length and basic structure
        words = data["title"].split()
        data["title"] = " ".join(["X" * min(len(w), 10) for w in words[:5]])

    # Anonymize file paths
    if "file" in data:
        path = Path(data["file"])
        # Keep file extension and directory depth
        data["file"] = "/".join(["dir"] * (len(path.parts) - 1) + [f"file{path.suffix}"])

    # Anonymize project names
    if "project" in data:
        data["project"] = "project_name"

    anon_event["data"] = data
    return anon_event


def load_test_data(file_path: str | Path) -> dict[str, Any]:
    """
    Load test data from a JSON or YAML file.

    Args:
        file_path: Path to test data file

    Returns:
        Dictionary with test data
    """
    path = Path(file_path)

    if path.suffix in [".yaml", ".yml"]:
        import yaml

        with open(path) as f:
            return yaml.safe_load(f)
    else:
        with open(path) as f:
            return json.load(f)


def create_minimal_fixture(
    events: list[dict[str, Any]], description: str, expected_output: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Create a minimal test fixture from events.

    Args:
        events: List of event dictionaries
        description: Description of what this fixture tests
        expected_output: Expected output (timew commands, tags, etc.)

    Returns:
        Test fixture dictionary
    """
    return {"description": description, "events": events, "expected_output": expected_output or {}}
