"""
Functional tests using a real TimeWarrior database.

These tests set up a temporary TimeWarrior database and test the actual
integration with the timew command-line tool.
"""

import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import pytest

from aw_export_timewarrior.main import Exporter
from aw_export_timewarrior.compare import fetch_timew_intervals, SuggestedInterval


class TimewTestDatabase:
    """Context manager for a temporary TimeWarrior database."""

    def __init__(self):
        self.temp_dir = None
        self.data_dir = None
        self.old_xdg_data_home = None

    def __enter__(self):
        """Set up temporary TimeWarrior database."""
        # Create temp directory
        self.temp_dir = tempfile.mkdtemp(prefix='timew_test_')
        self.data_dir = Path(self.temp_dir) / 'timewarrior' / 'data'
        self.data_dir.mkdir(parents=True)

        # Create empty tags.data file (empty JSON dict)
        tags_file = self.data_dir / 'tags.data'
        with open(tags_file, 'w') as f:
            json.dump({}, f)

        # Set XDG_DATA_HOME to point to our temp directory
        self.old_xdg_data_home = os.environ.get('XDG_DATA_HOME')
        os.environ['XDG_DATA_HOME'] = self.temp_dir

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up temporary TimeWarrior database."""
        # Restore original XDG_DATA_HOME
        if self.old_xdg_data_home is None:
            os.environ.pop('XDG_DATA_HOME', None)
        else:
            os.environ['XDG_DATA_HOME'] = self.old_xdg_data_home

        # Clean up temp directory
        if self.temp_dir:
            import shutil
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run_timew(self, *args) -> subprocess.CompletedProcess:
        """Run a timew command in the test database."""
        return subprocess.run(
            ['timew'] + list(args),
            capture_output=True,
            text=True,
            check=False
        )

    def add_interval(self, start: datetime, end: datetime, tags: List[str]) -> None:
        """Add an interval to the test database using timew track."""
        start_str = start.astimezone().strftime('%Y-%m-%dT%H:%M:%S')
        end_str = end.astimezone().strftime('%Y-%m-%dT%H:%M:%S')

        # Pass each tag as a separate argument
        result = self.run_timew('track', start_str, '-', end_str, *tags)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to add interval: {result.stderr}")

    def get_intervals(self, start: datetime, end: datetime) -> List[Dict]:
        """Get intervals from the database using timew export."""
        start_str = start.astimezone().strftime('%Y-%m-%dT%H:%M:%S')
        end_str = end.astimezone().strftime('%Y-%m-%dT%H:%M:%S')

        result = self.run_timew('export', start_str, '-', end_str)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to export: {result.stderr}")

        if not result.stdout.strip():
            return []

        return json.loads(result.stdout)


@pytest.fixture
def timew_db():
    """Pytest fixture for a temporary TimeWarrior database."""
    with TimewTestDatabase() as db:
        yield db


class TestTimewDatabaseSetup:
    """Test that the TimewTestDatabase fixture works correctly."""

    def test_empty_database(self, timew_db: TimewTestDatabase) -> None:
        """Test that we can create an empty database."""
        # Check that tags.data exists
        tags_file = timew_db.data_dir / 'tags.data'
        assert tags_file.exists()

        # Check that it contains an empty dict
        with open(tags_file) as f:
            data = json.load(f)
        assert data == {}

        # Check that timew can run
        result = timew_db.run_timew('--version')
        assert result.returncode == 0

    def test_add_interval(self, timew_db: TimewTestDatabase) -> None:
        """Test that we can add an interval to the database."""
        start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)

        timew_db.add_interval(start, end, ['test-tag', 'another-tag'])

        # Verify it was added
        intervals = timew_db.get_intervals(start, end)
        assert len(intervals) == 1
        assert set(intervals[0]['tags']) == {'test-tag', 'another-tag'}

    def test_multiple_intervals(self, timew_db: TimewTestDatabase) -> None:
        """Test that we can add multiple intervals."""
        base = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)

        # Add three intervals
        for i in range(3):
            start = base + timedelta(hours=i)
            end = start + timedelta(minutes=30)
            timew_db.add_interval(start, end, [f'tag-{i}'])

        # Verify all were added
        intervals = timew_db.get_intervals(base, base + timedelta(hours=3))
        assert len(intervals) == 3


class TestFetchTimewIntervals:
    """Test fetching intervals from a real TimeWarrior database."""

    def test_fetch_empty_database(self, timew_db: TimewTestDatabase) -> None:
        """Test fetching from an empty database."""
        start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)

        intervals = fetch_timew_intervals(start, end)
        assert len(intervals) == 0

    def test_fetch_with_intervals(self, timew_db: TimewTestDatabase) -> None:
        """Test fetching intervals that exist."""
        start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)

        # Add an interval
        timew_db.add_interval(start, end, ['work', 'python'])

        # Fetch it
        intervals = fetch_timew_intervals(start, end)
        assert len(intervals) == 1
        assert intervals[0].tags == {'work', 'python'}
        assert intervals[0].start == start
        assert intervals[0].end == end

    def test_fetch_partial_overlap(self, timew_db: TimewTestDatabase) -> None:
        """Test fetching intervals that partially overlap the time range."""
        # Add interval from 10:00-12:00
        interval_start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        interval_end = datetime(2025, 12, 10, 12, 0, 0, tzinfo=timezone.utc)
        timew_db.add_interval(interval_start, interval_end, ['work'])

        # Query from 11:00-13:00 (partial overlap)
        query_start = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)
        query_end = datetime(2025, 12, 10, 13, 0, 0, tzinfo=timezone.utc)

        intervals = fetch_timew_intervals(query_start, query_end)
        # Should still fetch the interval since timew export includes overlapping intervals
        assert len(intervals) == 1


class TestDiffWithRealTimew:
    """Test diff functionality with a real TimeWarrior database."""

    def test_diff_missing_interval(self, timew_db: TimewTestDatabase) -> None:
        """Test detecting a missing interval."""
        start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)

        # TimeWarrior is empty
        timew_intervals = fetch_timew_intervals(start, end)
        assert len(timew_intervals) == 0

        # But we suggest an interval
        suggested = [SuggestedInterval(start, end, {'work', 'python'})]

        from aw_export_timewarrior.compare import compare_intervals
        comparison = compare_intervals(timew_intervals, suggested)

        assert len(comparison['missing']) == 1
        assert len(comparison['extra']) == 0
        assert len(comparison['matching']) == 0
        assert len(comparison['different_tags']) == 0

    def test_diff_extra_interval(self, timew_db: TimewTestDatabase) -> None:
        """Test detecting an extra interval in TimeWarrior."""
        start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)

        # Add interval to TimeWarrior
        timew_db.add_interval(start, end, ['manual-entry'])

        # Fetch it
        timew_intervals = fetch_timew_intervals(start, end)
        assert len(timew_intervals) == 1

        # But we don't suggest anything
        suggested = []

        from aw_export_timewarrior.compare import compare_intervals
        comparison = compare_intervals(timew_intervals, suggested)

        assert len(comparison['missing']) == 0
        assert len(comparison['extra']) == 1
        assert len(comparison['matching']) == 0
        assert len(comparison['different_tags']) == 0

    def test_diff_different_tags(self, timew_db: TimewTestDatabase) -> None:
        """Test detecting an interval with different tags."""
        start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)

        # Add interval to TimeWarrior with wrong tags
        timew_db.add_interval(start, end, ['old-tag'])

        # Fetch it
        timew_intervals = fetch_timew_intervals(start, end)
        assert len(timew_intervals) == 1

        # Suggest the same interval with different tags
        suggested = [SuggestedInterval(start, end, {'new-tag', 'work'})]

        from aw_export_timewarrior.compare import compare_intervals
        comparison = compare_intervals(timew_intervals, suggested)

        assert len(comparison['missing']) == 0
        assert len(comparison['extra']) == 0
        assert len(comparison['matching']) == 0
        assert len(comparison['different_tags']) == 1

    def test_diff_matching_interval(self, timew_db: TimewTestDatabase) -> None:
        """Test detecting a matching interval."""
        start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)

        # Add interval to TimeWarrior
        timew_db.add_interval(start, end, ['work', 'python'])

        # Fetch it
        timew_intervals = fetch_timew_intervals(start, end)
        assert len(timew_intervals) == 1

        # Suggest the same interval
        suggested = [SuggestedInterval(start, end, {'work', 'python'})]

        from aw_export_timewarrior.compare import compare_intervals
        comparison = compare_intervals(timew_intervals, suggested)

        assert len(comparison['missing']) == 0
        assert len(comparison['extra']) == 0
        assert len(comparison['matching']) == 1
        assert len(comparison['different_tags']) == 0


class TestApplyFix:
    """Test applying fix commands to a real TimeWarrior database."""

    def test_apply_missing_interval(self, timew_db: TimewTestDatabase) -> None:
        """Test adding a missing interval using generated commands."""
        start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)

        # TimeWarrior is empty
        timew_intervals = fetch_timew_intervals(start, end)
        assert len(timew_intervals) == 0

        # Suggest an interval
        suggested = [SuggestedInterval(start, end, {'work', 'python'})]

        from aw_export_timewarrior.compare import compare_intervals, generate_fix_commands
        comparison = compare_intervals(timew_intervals, suggested)
        commands = generate_fix_commands(comparison)

        # Should generate one track command
        assert len(commands) == 1
        assert commands[0].startswith('timew track')
        assert 'work' in commands[0]
        assert 'python' in commands[0]
        assert ':adjust' in commands[0]

        # Execute the command (parse it first)
        # timew track 2025-12-10T10:00:00 - 2025-12-10T11:00:00 python work :adjust
        parts = commands[0].split()
        assert parts[0] == 'timew'
        assert parts[1] == 'track'
        # parts[2] is start time, parts[3] is '-', parts[4] is end time, rest are tags

        result = timew_db.run_timew(*parts[1:])
        assert result.returncode == 0

        # Verify the interval was added
        new_intervals = fetch_timew_intervals(start, end)
        assert len(new_intervals) == 1
        assert new_intervals[0].tags == {'work', 'python'}

    def test_apply_retag(self, timew_db: TimewTestDatabase) -> None:
        """Test retagging an interval using generated commands."""
        start = datetime(2025, 12, 10, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 12, 10, 11, 0, 0, tzinfo=timezone.utc)

        # Add interval with old tags
        timew_db.add_interval(start, end, ['old-tag'])

        # Fetch it
        timew_intervals = fetch_timew_intervals(start, end)
        assert len(timew_intervals) == 1
        original_id = timew_intervals[0].id

        # Suggest new tags
        suggested = [SuggestedInterval(start, end, {'new-tag', 'work'})]

        from aw_export_timewarrior.compare import compare_intervals, generate_fix_commands
        comparison = compare_intervals(timew_intervals, suggested)
        commands = generate_fix_commands(comparison)

        # Should generate one retag command
        assert len(commands) == 1
        assert commands[0].startswith('timew retag')
        assert f'@{original_id}' in commands[0]
        assert 'new-tag' in commands[0]
        assert 'work' in commands[0]

        # Execute the command
        parts = commands[0].split()
        result = timew_db.run_timew(*parts[1:])
        assert result.returncode == 0

        # Verify the tags were changed
        new_intervals = fetch_timew_intervals(start, end)
        assert len(new_intervals) == 1
        assert new_intervals[0].tags == {'new-tag', 'work'}
        assert new_intervals[0].id == original_id  # Same interval
