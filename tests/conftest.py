"""
Helper utilities for creating test fixtures and test data.

This module provides a builder pattern for creating test scenarios
and fixtures for aw-export-timewarrior.
"""

import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sleep_counter = 0

# Guard state for _guard_real_timew / timew_sandbox (see below). Only the
# `timew_sandbox` fixture may set this True, and only for its own duration.
_real_timew_calls_allowed = False


def _is_timew_command(cmd: Any) -> bool:
    return isinstance(cmd, (list, tuple)) and len(cmd) > 0 and cmd[0] == "timew"


def _timew_env_is_isolated() -> bool:
    """True if TIMEWARRIORDB or XDG_DATA_HOME points under the system temp dir.

    Some pre-existing functional tests (test_functional.py,
    test_functional_timew.py) isolate real timew calls this way already,
    via pytest's tmp_path or tempfile.mkdtemp(), predating the
    `timew_sandbox` fixture below -- recognize that pattern too rather than
    requiring every real-timew test to switch to `timew_sandbox`.
    """
    tmp_root = os.path.realpath(tempfile.gettempdir())
    for var in ("TIMEWARRIORDB", "XDG_DATA_HOME"):
        value = os.environ.get(var)
        if not value:
            continue
        real_value = os.path.realpath(value)
        if real_value == tmp_root or real_value.startswith(tmp_root + os.sep):
            return True
    return False


@pytest.fixture(autouse=True)
def _guard_real_timew(monkeypatch):
    """Fail hard on any unmocked subprocess call to the real 'timew' binary.

    Every current use of subprocess.run/check_output in this codebase is a
    timew invocation, so a call that reaches here means a test forgot to
    mock subprocess -- without this guard it would silently execute against
    the developer's real, live TimeWarrior database instead of failing the
    test. Tests that genuinely need real TimeWarrior must use the
    `timew_sandbox` fixture (or point TIMEWARRIORDB/XDG_DATA_HOME at a temp
    dir themselves), which lifts this guard for their duration.
    """
    real_run = subprocess.run
    real_check_output = subprocess.check_output

    def is_blocked(cmd) -> bool:
        return (
            not _real_timew_calls_allowed
            and not _timew_env_is_isolated()
            and _is_timew_command(cmd)
        )

    def guarded_run(cmd, *args, **kwargs):
        if is_blocked(cmd):
            raise RuntimeError(
                f"Blocked unmocked real 'timew' subprocess call: {cmd}. Mock "
                "subprocess.run, or use the `timew_sandbox` fixture for a "
                "real, isolated integration test."
            )
        return real_run(cmd, *args, **kwargs)

    def guarded_check_output(cmd, *args, **kwargs):
        if is_blocked(cmd):
            raise RuntimeError(
                f"Blocked unmocked real 'timew' subprocess call: {cmd}. Mock "
                "subprocess.check_output, or use the `timew_sandbox` fixture "
                "for a real, isolated integration test."
            )
        return real_check_output(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(subprocess, "check_output", guarded_check_output)


@pytest.fixture
def timew_sandbox(_guard_real_timew, monkeypatch):
    """Provide a real, isolated TimeWarrior database for integration tests.

    Points TIMEWARRIORDB at a fresh temp directory (auto-initialized by
    timew on first use, no interactive prompts) and lifts the
    `_guard_real_timew` safety net for the test's duration, so the test
    exercises the real `timew` binary without ever touching the developer's
    actual tracking data.
    """
    if shutil.which("timew") is None:
        pytest.skip("TimeWarrior (timew) is not installed")

    global _real_timew_calls_allowed

    tmp_db = tempfile.mkdtemp(prefix="aw-export-timew-test-")
    monkeypatch.setenv("TIMEWARRIORDB", tmp_db)

    _real_timew_calls_allowed = True
    try:
        yield tmp_db
    finally:
        _real_timew_calls_allowed = False


@pytest.fixture(autouse=True)  # Applies to all tests automatically
def no_sleep(monkeypatch):
    global sleep_counter
    sleep_counter = 0

    def fake_sleep(seconds):
        global sleep_counter
        sleep_counter += 1
        assert sleep_counter < 200
        print(f"SLEEP requested for {seconds}seconds")

    import time

    from aw_export_timewarrior import main

    monkeypatch.setattr(time, "sleep", fake_sleep)
    monkeypatch.setattr(main, "sleep", fake_sleep)


@pytest.fixture(autouse=True)
def reset_config():
    """Reset the global config to default after each test.

    This prevents test pollution where one test's config changes
    affect subsequent tests.
    """
    from aw_core.config import load_config_toml

    from aw_export_timewarrior import config as config_module

    yield

    # Restore original config after test
    # Re-load from default to ensure clean state
    config_module.config.clear()
    default_config = load_config_toml("aw-export-timewarrior", config_module.default_config)
    config_module.config.update(default_config)


class FixtureDataBuilder:
    """
    Builder class for creating test data.

    Provides a fluent interface for constructing test scenarios
    with window events, AFK events, browser events, etc.

    Example:
        >>> data = (FixtureDataBuilder()
        ...     .add_window_event("vscode", "main.py", duration=600)
        ...     .add_afk_event("not-afk", duration=600)
        ...     .build())
    """

    def __init__(self, start_time: datetime | None = None):
        """
        Initialize the test data builder.

        Args:
            start_time: Starting time for events (defaults to a fixed test time)
        """
        self.start_time = start_time or datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
        self.current_time = self.start_time
        self.last_window_event_start = (
            self.start_time
        )  # Track last window event start for AFK event overlap
        self.buckets = {}
        self.events = {}
        self._init_buckets()

    def _init_buckets(self):
        """Initialize standard bucket definitions."""
        current_time_iso = self.current_time.isoformat()

        self.buckets = {
            "aw-watcher-window_test": {
                "id": "aw-watcher-window_test",
                "name": "aw-watcher-window_test",
                "type": "currentwindow",
                "client": "aw-watcher-window",
                "hostname": "test-host",
                "created": current_time_iso,
                "last_updated": current_time_iso,
            },
            "aw-watcher-afk_test": {
                "id": "aw-watcher-afk_test",
                "name": "aw-watcher-afk_test",
                "type": "afkstatus",
                "client": "aw-watcher-afk",
                "hostname": "test-host",
                "created": current_time_iso,
                "last_updated": current_time_iso,
            },
            "aw-watcher-web-chrome_test": {
                "id": "aw-watcher-web-chrome_test",
                "name": "aw-watcher-web-chrome_test",
                "type": "web.tab.current",
                "client": "aw-watcher-web-chrome",
                "hostname": "test-host",
                "created": current_time_iso,
                "last_updated": current_time_iso,
            },
            "aw-watcher-emacs_test": {
                "id": "aw-watcher-emacs_test",
                "name": "aw-watcher-emacs_test",
                "type": "app.editor.activity",
                "client": "aw-watcher-emacs",
                "hostname": "test-host",
                "created": current_time_iso,
                "last_updated": current_time_iso,
            },
            "aw-watcher-lid_test": {
                "id": "aw-watcher-lid_test",
                "name": "aw-watcher-lid_test",
                "type": "systemafkstatus",
                "client": "aw-watcher-lid",
                "hostname": "test-host",
                "created": current_time_iso,
                "last_updated": current_time_iso,
            },
            # AFK prompt bucket (using legacy name for backward compatibility in tests)
            # The new name is aw-watcher-afk-prompt, but tests use the legacy name
            # to maintain backward compatibility with existing test data.
            # See test_event_fetcher.py::TestAfkPromptBucketDetection for bucket name tests.
            "aw-watcher-ask-away_test": {
                "id": "aw-watcher-ask-away_test",
                "name": "aw-watcher-ask-away_test",
                "type": "afktask",
                "client": "aw-watcher-ask-away",
                "hostname": "test-host",
                "created": current_time_iso,
                "last_updated": current_time_iso,
            },
        }

        # Initialize empty event lists for each bucket
        for bucket_id in self.buckets:
            self.events[bucket_id] = []

    def add_window_event(
        self, app: str, title: str, duration: int | timedelta, timestamp: datetime | None = None
    ) -> "FixtureDataBuilder":
        """
        Add a window event.

        Args:
            app: Application name
            title: Window title
            duration: Duration in seconds or timedelta
            timestamp: Event timestamp (uses current_time if not specified)

        Returns:
            Self for chaining
        """
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)

        event_time = timestamp or self.current_time

        event = {
            "id": len(self.events["aw-watcher-window_test"]) + 1,
            "timestamp": event_time.isoformat(),
            "duration": duration.total_seconds(),
            "data": {"app": app, "title": title},
        }

        self.events["aw-watcher-window_test"].append(event)
        self.last_window_event_start = event_time  # Save for AFK event overlap
        self.current_time = event_time + duration

        return self

    def add_afk_event(
        self, status: str, duration: int | timedelta, timestamp: datetime | None = None
    ) -> "FixtureDataBuilder":
        """
        Add an AFK status event.

        Args:
            status: "afk" or "not-afk"
            duration: Duration in seconds or timedelta
            timestamp: Event timestamp (uses last_window_event_start if not specified, for overlap)

        Returns:
            Self for chaining
        """
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)

        # Default to last_window_event_start for overlap with window events
        event_time = timestamp or self.last_window_event_start

        event = {
            "id": len(self.events["aw-watcher-afk_test"]) + 1,
            "timestamp": event_time.isoformat(),
            "duration": duration.total_seconds(),
            "data": {"status": status},
        }

        self.events["aw-watcher-afk_test"].append(event)

        return self

    def add_lid_event(
        self,
        lid_state: str,
        duration: int | timedelta,
        timestamp: datetime | None = None,
        suspend_state: str | None = None,
        boot_gap: bool = False,
    ) -> "FixtureDataBuilder":
        """
        Add a lid event.

        Args:
            lid_state: "closed" or "open"
            duration: Duration in seconds or timedelta
            timestamp: Event timestamp (uses current_time if not specified)
            suspend_state: Optional "suspended" or "resumed" state

        Returns:
            Self for chaining
        """
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)

        event_time = timestamp or self.current_time

        # Determine status based on lid state
        status = "system-afk" if lid_state == "closed" else "not-afk"

        event = {
            "id": len(self.events["aw-watcher-lid_test"]) + 1,
            "timestamp": event_time.isoformat(),
            "duration": duration.total_seconds(),
            "data": {
                "status": status,
                "lid_state": lid_state,
                "suspend_state": suspend_state,
                "boot_gap": boot_gap,
                "event_source": "lid",
            },
        }

        self.events["aw-watcher-lid_test"].append(event)
        self.current_time = event_time + duration

        return self

    def add_ask_away_event(
        self, message: str, duration: int | timedelta, timestamp: datetime | None = None
    ) -> "FixtureDataBuilder":
        """
        Add an ask-away event with a user message.

        Args:
            message: User-entered message (e.g., "housework", "lunch break")
            duration: Duration in seconds or timedelta
            timestamp: Event timestamp (uses current_time if not specified)

        Returns:
            Self for chaining
        """
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)

        event_time = timestamp or self.current_time

        event = {
            "id": len(self.events["aw-watcher-ask-away_test"]) + 1,
            "timestamp": event_time.isoformat(),
            "duration": duration.total_seconds(),
            "data": {
                "message": message,
            },
        }

        self.events["aw-watcher-ask-away_test"].append(event)
        self.current_time = event_time + duration

        return self

    def add_split_ask_away_events(
        self,
        activities: list[tuple[str, int | timedelta]],
        timestamp: datetime | None = None,
    ) -> "FixtureDataBuilder":
        """
        Add multiple ask-away events from split mode with split metadata.

        Args:
            activities: List of (message, duration) tuples for each activity
            timestamp: Start timestamp for first activity (uses current_time if not specified)

        Returns:
            Self for chaining
        """
        event_time = timestamp or self.current_time
        split_id = str(event_time.timestamp())
        split_count = len(activities)

        current_start = event_time
        for i, (message, duration) in enumerate(activities):
            if isinstance(duration, int):
                duration = timedelta(seconds=duration)

            event = {
                "id": len(self.events["aw-watcher-ask-away_test"]) + 1,
                "timestamp": current_start.isoformat(),
                "duration": duration.total_seconds(),
                "data": {
                    "message": message,
                    "split": True,
                    "split_count": split_count,
                    "split_index": i,
                    "split_id": split_id,
                },
            }

            self.events["aw-watcher-ask-away_test"].append(event)
            current_start += duration

        self.current_time = current_start
        return self

    def add_suspend_event(
        self, suspend_state: str, duration: int | timedelta, timestamp: datetime | None = None
    ) -> "FixtureDataBuilder":
        """
        Add a suspend/resume event.

        Args:
            suspend_state: "suspended" or "resumed"
            duration: Duration in seconds or timedelta
            timestamp: Event timestamp (uses current_time if not specified)

        Returns:
            Self for chaining
        """
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)

        event_time = timestamp or self.current_time

        # Suspended = AFK, resumed = not-afk
        status = "system-afk" if suspend_state == "suspended" else "not-afk"

        event = {
            "id": len(self.events["aw-watcher-lid_test"]) + 1,
            "timestamp": event_time.isoformat(),
            "duration": duration.total_seconds(),
            "data": {
                "status": status,
                "lid_state": None,
                "suspend_state": suspend_state,
                "boot_gap": False,
                "event_source": "suspend",
            },
        }

        self.events["aw-watcher-lid_test"].append(event)
        self.current_time = event_time + duration

        return self

    def add_boot_gap_event(
        self, duration: int | timedelta, timestamp: datetime | None = None
    ) -> "FixtureDataBuilder":
        """
        Add a boot gap event (system downtime).

        Args:
            duration: Duration in seconds or timedelta
            timestamp: Event timestamp (uses current_time if not specified)

        Returns:
            Self for chaining
        """
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)

        event_time = timestamp or self.current_time

        event = {
            "id": len(self.events["aw-watcher-lid_test"]) + 1,
            "timestamp": event_time.isoformat(),
            "duration": duration.total_seconds(),
            "data": {
                "status": "system-afk",
                "lid_state": None,
                "suspend_state": None,
                "boot_gap": True,
                "event_source": "boot",
            },
        }

        self.events["aw-watcher-lid_test"].append(event)
        self.current_time = event_time + duration

        return self

    def add_browser_event(
        self, url: str, title: str, duration: int | timedelta, timestamp: datetime | None = None
    ) -> "FixtureDataBuilder":
        """
        Add a browser event.

        Args:
            url: URL being viewed
            title: Page title
            duration: Duration in seconds or timedelta
            timestamp: Event timestamp (uses current_time if not specified)

        Returns:
            Self for chaining
        """
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)

        event_time = timestamp or self.current_time

        event = {
            "id": len(self.events["aw-watcher-web-chrome_test"]) + 1,
            "timestamp": event_time.isoformat(),
            "duration": duration.total_seconds(),
            "data": {"url": url, "title": title},
        }

        self.events["aw-watcher-web-chrome_test"].append(event)

        return self

    def add_editor_event(
        self,
        file_path: str,
        project: str,
        language: str = "python",
        duration: int | timedelta = 0,
        timestamp: datetime | None = None,
    ) -> "FixtureDataBuilder":
        """
        Add an editor event.

        Args:
            file_path: File being edited
            project: Project name
            language: Programming language
            duration: Duration in seconds or timedelta
            timestamp: Event timestamp (uses current_time if not specified)

        Returns:
            Self for chaining
        """
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)

        event_time = timestamp or self.current_time

        event = {
            "id": len(self.events["aw-watcher-emacs_test"]) + 1,
            "timestamp": event_time.isoformat(),
            "duration": duration.total_seconds(),
            "data": {"file": file_path, "project": project, "language": language},
        }

        self.events["aw-watcher-emacs_test"].append(event)

        return self

    def set_time(self, new_time: datetime) -> "FixtureDataBuilder":
        """
        Set the current time for subsequent events.

        Args:
            new_time: New current time

        Returns:
            Self for chaining
        """
        self.current_time = new_time
        return self

    def advance_time(self, delta: int | timedelta) -> "FixtureDataBuilder":
        """
        Advance the current time by a delta.

        Args:
            delta: Time delta in seconds or timedelta

        Returns:
            Self for chaining
        """
        if isinstance(delta, int):
            delta = timedelta(seconds=delta)

        self.current_time += delta
        return self

    def build(self) -> dict[str, Any]:
        """
        Build and return the test data dictionary.

        Returns:
            Dictionary with buckets and events suitable for loading
        """
        return {
            "metadata": {
                "export_time": datetime.now(UTC).isoformat(),
                "start_time": self.start_time.isoformat(),
                "end_time": self.current_time.isoformat(),
                "duration_seconds": (self.current_time - self.start_time).total_seconds(),
                "anonymized": False,
                "test_data": True,
            },
            "buckets": self.buckets,
            "events": self.events,
        }


def create_simple_work_session():
    """
    Create a simple work session fixture.

    Returns:
        Test data for a typical work session
    """
    return (
        FixtureDataBuilder()
        .add_afk_event("not-afk", 600)
        .add_window_event("vscode", "main.py - Visual Studio Code", 600)
        .add_editor_event("/home/user/project/main.py", "project", "python", 600)
        .add_browser_event(
            "https://docs.python.org/3/library/datetime.html",
            "datetime — Python Documentation",
            300,
        )
        .add_window_event("chrome", "datetime — Python Documentation", 300)
        .build()
    )


def create_afk_transition_fixture():
    """
    Create a fixture with AFK transition in the middle of an event.

    Returns:
        Test data for AFK transition scenario
    """
    return (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 300)  # 5 min work
        .add_afk_event("not-afk", 300)
        .advance_time(0)  # Reset to same time for AFK event
        .add_afk_event("afk", 300)  # Goes AFK after 5 min
        .build()
    )


# =============================================================================
# Shared fixtures for report tests
# =============================================================================


@pytest.fixture
def report_test_data_path() -> Path:
    """Path to the anonymized report test data file."""
    return Path(__file__).parent / "fixtures" / "report_test_data.json"


@pytest.fixture
def exporter_with_report_data(report_test_data_path: Path):
    """Create an Exporter instance with report test data loaded."""
    from src.aw_export_timewarrior.export import load_test_data
    from src.aw_export_timewarrior.main import Exporter

    test_data = load_test_data(report_test_data_path)
    exporter = Exporter(dry_run=True, test_data=test_data)
    return exporter
