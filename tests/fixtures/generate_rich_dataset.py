#!/usr/bin/env python3
"""Generate a rich test dataset with many events matching different rules.

This creates a dataset that stress-tests the tag accumulator by having:
- Rapid tag switches (many short events)
- Events matching different rule types (editor, app, browser)
- AFK transitions
- Events that trigger exclusive tag handling
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add parent directory to path to import conftest
sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import FixtureDataBuilder


def generate_rich_dataset():
    """Generate a dataset with complex event patterns."""
    # Start at 9:00 AM
    start_time = datetime(2025, 12, 15, 9, 0, 0, tzinfo=UTC)
    builder = FixtureDataBuilder(start_time=start_time)

    # Scenario: Morning coding session with frequent context switches
    # This will stress the tag accumulator

    # 9:00-9:02: Check emails (2min)
    builder.add_window_event("chromium", "Gmail - Inbox", duration=120, timestamp=start_time)
    builder.add_browser_event(
        "https://mail.google.com/inbox", "Gmail - Inbox", duration=120, timestamp=start_time
    )
    builder.add_afk_event("not-afk", duration=120, timestamp=start_time)

    # 9:02-9:05: Quick look at Python docs (3min) - matches learning rule
    current_time = start_time + timedelta(minutes=2)
    builder.add_window_event(
        "chromium", "Python Documentation", duration=180, timestamp=current_time
    )
    builder.add_browser_event(
        "https://docs.python.org/3/library/datetime.html",
        "Python Documentation",
        duration=180,
        timestamp=current_time,
    )
    builder.add_afk_event("not-afk", duration=180, timestamp=current_time)

    # 9:05-9:15: Coding in VSCode with many file switches (10min)
    # Rapid switches every 30-60 seconds to stress accumulator
    coding_start = start_time + timedelta(minutes=5)
    files = [
        "main.py",
        "utils.py",
        "test_main.py",
        "config.py",
        "main.py",  # Back to main
        "utils.py",  # Back to utils
        "README.md",  # Non-Python file
        "main.py",  # Back to main
        "test_utils.py",
        "main.py",
    ]

    offset = 0
    for i, filename in enumerate(files):
        duration = 50 + (i % 3) * 10  # 50-70 seconds each
        builder.add_window_event(
            "Code",
            f"{filename} - VSCode",
            duration=duration,
            timestamp=coding_start + timedelta(seconds=offset),
        )
        builder.add_editor_event(
            f"/home/user/project/{filename}",
            project="my-project",
            duration=duration,
            timestamp=coding_start + timedelta(seconds=offset),
        )
        builder.add_afk_event(
            "not-afk", duration=duration, timestamp=coding_start + timedelta(seconds=offset)
        )
        offset += duration

    # 9:15-9:17: Quick terminal command check (2min)
    terminal_time = coding_start + timedelta(seconds=offset)
    builder.add_window_event("foot", "git status", duration=120, timestamp=terminal_time)
    builder.add_afk_event("not-afk", duration=120, timestamp=terminal_time)

    # 9:17-9:22: GitHub PR review (5min)
    github_time = terminal_time + timedelta(minutes=2)
    builder.add_window_event(
        "chromium",
        "Pull Request #123 - GitHub",
        duration=300,
        timestamp=github_time,
    )
    builder.add_browser_event(
        "https://github.com/user/repo/pull/123",
        "Pull Request #123 - GitHub",
        duration=300,
        timestamp=github_time,
    )
    builder.add_afk_event("not-afk", duration=300, timestamp=github_time)

    # 9:22-9:40: AFK (coffee break - 18min)
    afk_start = github_time + timedelta(minutes=5)
    builder.add_afk_event("afk", duration=1080, timestamp=afk_start)

    # 9:40-9:50: Return and code review comments (10min) - rapid switches
    return_time = afk_start + timedelta(minutes=18)
    activities = [
        ("chromium", "Pull Request #123 - GitHub", "https://github.com/user/repo/pull/123"),
        ("Code", "main.py - VSCode", None),
        ("chromium", "Pull Request #123 - GitHub", "https://github.com/user/repo/pull/123"),
        ("Code", "utils.py - VSCode", None),
        ("chromium", "Pull Request #123 - GitHub", "https://github.com/user/repo/pull/123"),
    ]

    offset = 0
    for app, title, url in activities:
        duration = 120  # 2 minutes each
        builder.add_window_event(
            app, title, duration=duration, timestamp=return_time + timedelta(seconds=offset)
        )
        if url:
            builder.add_browser_event(
                url, title, duration=duration, timestamp=return_time + timedelta(seconds=offset)
            )
        builder.add_afk_event(
            "not-afk", duration=duration, timestamp=return_time + timedelta(seconds=offset)
        )
        offset += duration

    # 9:50-10:00: Final coding session (10min)
    final_coding = return_time + timedelta(seconds=offset)
    builder.add_window_event("Code", "main.py - VSCode", duration=600, timestamp=final_coding)
    builder.add_editor_event(
        "/home/user/project/main.py",
        project="my-project",
        duration=600,
        timestamp=final_coding,
    )
    builder.add_afk_event("not-afk", duration=600, timestamp=final_coding)

    return builder.build()


if __name__ == "__main__":
    data = generate_rich_dataset()

    # Write to fixture file
    output_path = Path(__file__).parent / "rich_accumulator_test.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Generated rich test dataset: {output_path}")
    print(f"Time range: {data['metadata']['start_time']} to {data['metadata']['end_time']}")
    print("Total events:")
    for bucket_name, events in data["events"].items():
        print(f"  {bucket_name}: {len(events)} events")
