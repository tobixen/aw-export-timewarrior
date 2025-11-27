"""
Helper utilities for creating test fixtures and test data.

This module provides a builder pattern for creating test scenarios
and fixtures for aw-export-timewarrior.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union


class TestDataBuilder:
    """
    Builder class for creating test data.

    Provides a fluent interface for constructing test scenarios
    with window events, AFK events, browser events, etc.

    Example:
        >>> data = (TestDataBuilder()
        ...     .add_window_event("vscode", "main.py", duration=600)
        ...     .add_afk_event("not-afk", duration=600)
        ...     .build())
    """

    def __init__(self, start_time: Optional[datetime] = None):
        """
        Initialize the test data builder.

        Args:
            start_time: Starting time for events (defaults to a fixed test time)
        """
        self.start_time = start_time or datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        self.current_time = self.start_time
        self.buckets = {}
        self.events = {}
        self._init_buckets()

    def _init_buckets(self):
        """Initialize standard bucket definitions."""
        current_time_iso = self.current_time.isoformat()

        self.buckets = {
            'aw-watcher-window_test': {
                'id': 'aw-watcher-window_test',
                'name': 'aw-watcher-window_test',
                'type': 'currentwindow',
                'client': 'aw-watcher-window',
                'hostname': 'test-host',
                'created': current_time_iso,
                'last_updated': current_time_iso
            },
            'aw-watcher-afk_test': {
                'id': 'aw-watcher-afk_test',
                'name': 'aw-watcher-afk_test',
                'type': 'afkstatus',
                'client': 'aw-watcher-afk',
                'hostname': 'test-host',
                'created': current_time_iso,
                'last_updated': current_time_iso
            },
            'aw-watcher-web-chrome_test': {
                'id': 'aw-watcher-web-chrome_test',
                'name': 'aw-watcher-web-chrome_test',
                'type': 'web.tab.current',
                'client': 'aw-watcher-web-chrome',
                'hostname': 'test-host',
                'created': current_time_iso,
                'last_updated': current_time_iso
            },
            'aw-watcher-emacs_test': {
                'id': 'aw-watcher-emacs_test',
                'name': 'aw-watcher-emacs_test',
                'type': 'app.editor.activity',
                'client': 'aw-watcher-emacs',
                'hostname': 'test-host',
                'created': current_time_iso,
                'last_updated': current_time_iso
            }
        }

        # Initialize empty event lists for each bucket
        for bucket_id in self.buckets:
            self.events[bucket_id] = []

    def add_window_event(
        self,
        app: str,
        title: str,
        duration: Union[int, timedelta],
        timestamp: Optional[datetime] = None
    ) -> 'TestDataBuilder':
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
            'id': len(self.events['aw-watcher-window_test']) + 1,
            'timestamp': event_time.isoformat(),
            'duration': duration.total_seconds(),
            'data': {
                'app': app,
                'title': title
            }
        }

        self.events['aw-watcher-window_test'].append(event)
        self.current_time = event_time + duration

        return self

    def add_afk_event(
        self,
        status: str,
        duration: Union[int, timedelta],
        timestamp: Optional[datetime] = None
    ) -> 'TestDataBuilder':
        """
        Add an AFK status event.

        Args:
            status: "afk" or "not-afk"
            duration: Duration in seconds or timedelta
            timestamp: Event timestamp (uses current_time if not specified)

        Returns:
            Self for chaining
        """
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)

        event_time = timestamp or self.current_time

        event = {
            'id': len(self.events['aw-watcher-afk_test']) + 1,
            'timestamp': event_time.isoformat(),
            'duration': duration.total_seconds(),
            'data': {
                'status': status
            }
        }

        self.events['aw-watcher-afk_test'].append(event)

        return self

    def add_browser_event(
        self,
        url: str,
        title: str,
        duration: Union[int, timedelta],
        timestamp: Optional[datetime] = None
    ) -> 'TestDataBuilder':
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
            'id': len(self.events['aw-watcher-web-chrome_test']) + 1,
            'timestamp': event_time.isoformat(),
            'duration': duration.total_seconds(),
            'data': {
                'url': url,
                'title': title
            }
        }

        self.events['aw-watcher-web-chrome_test'].append(event)

        return self

    def add_editor_event(
        self,
        file_path: str,
        project: str,
        language: str = 'python',
        duration: Union[int, timedelta] = 0,
        timestamp: Optional[datetime] = None
    ) -> 'TestDataBuilder':
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
            'id': len(self.events['aw-watcher-emacs_test']) + 1,
            'timestamp': event_time.isoformat(),
            'duration': duration.total_seconds(),
            'data': {
                'file': file_path,
                'project': project,
                'language': language
            }
        }

        self.events['aw-watcher-emacs_test'].append(event)

        return self

    def set_time(self, new_time: datetime) -> 'TestDataBuilder':
        """
        Set the current time for subsequent events.

        Args:
            new_time: New current time

        Returns:
            Self for chaining
        """
        self.current_time = new_time
        return self

    def advance_time(self, delta: Union[int, timedelta]) -> 'TestDataBuilder':
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

    def build(self) -> Dict[str, Any]:
        """
        Build and return the test data dictionary.

        Returns:
            Dictionary with buckets and events suitable for loading
        """
        return {
            'metadata': {
                'export_time': datetime.now(timezone.utc).isoformat(),
                'start_time': self.start_time.isoformat(),
                'end_time': self.current_time.isoformat(),
                'duration_seconds': (self.current_time - self.start_time).total_seconds(),
                'anonymized': False,
                'test_data': True
            },
            'buckets': self.buckets,
            'events': self.events
        }


def create_simple_work_session():
    """
    Create a simple work session fixture.

    Returns:
        Test data for a typical work session
    """
    return (TestDataBuilder()
        .add_afk_event('not-afk', 600)
        .add_window_event('vscode', 'main.py - Visual Studio Code', 600)
        .add_editor_event('/home/user/project/main.py', 'project', 'python', 600)
        .add_browser_event('https://docs.python.org/3/library/datetime.html',
                          'datetime — Python Documentation', 300)
        .add_window_event('chrome', 'datetime — Python Documentation', 300)
        .build())


def create_afk_transition_fixture():
    """
    Create a fixture with AFK transition in the middle of an event.

    Returns:
        Test data for AFK transition scenario
    """
    return (TestDataBuilder()
        .add_window_event('vscode', 'main.py', 300)  # 5 min work
        .add_afk_event('not-afk', 300)
        .advance_time(0)  # Reset to same time for AFK event
        .add_afk_event('afk', 300)  # Goes AFK after 5 min
        .build())
