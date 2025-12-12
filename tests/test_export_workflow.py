"""Integration tests for the export workflow and timewarrior interaction."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch, call
import subprocess
import logging

import pytest

from aw_export_timewarrior.main import (
    Exporter,
    get_timew_info,
    timew_run,
    timew_retag,
)
from aw_export_timewarrior.state import AfkState


def create_aw_event(timestamp, duration, data):
    """Create a mock ActivityWatch event object with proper attributes and dict access."""
    event = Mock()
    event.timestamp = timestamp
    event.duration = duration
    event.data = data
    # Support both attribute and dictionary access
    event.__getitem__ = lambda self, key: getattr(self, key)
    return event


@pytest.fixture
def mock_aw_client():
    """Fixture for mocked ActivityWatch client."""
    with patch('aw_export_timewarrior.main.aw_client') as mock_aw:
        mock_client = Mock()

        # Get current time for last_updated
        current_time = datetime.now(timezone.utc).isoformat()

        mock_client.get_buckets.return_value = {
            'aw-watcher-window_test': {
                'id': 'aw-watcher-window_test',
                'client': 'aw-watcher-window',
                'last_updated': current_time
            },
            'aw-watcher-afk_test': {
                'id': 'aw-watcher-afk_test',
                'client': 'aw-watcher-afk',
                'last_updated': current_time
            }
        }
        mock_aw.ActivityWatchClient.return_value = mock_client
        yield mock_client


class TestGetTimewInfo:
    """Tests for get_timew_info function."""

    @patch('subprocess.check_output')
    def test_get_timew_info_parses_json(self, mock_subprocess: Mock) -> None:
        """Test that get_timew_info parses timewarrior JSON correctly."""
        mock_subprocess.return_value = b'''{
            "id": 1,
            "start": "20250528T140000Z",
            "tags": ["4work", "programming", "python"]
        }'''

        result = get_timew_info()

        assert result['id'] == 1
        assert result['start'] == "20250528T140000Z"
        assert result['tags'] == {'4work', 'programming', 'python'}
        assert 'start_dt' in result
        assert isinstance(result['start_dt'], datetime)
        assert result['start_dt'].tzinfo == timezone.utc

    @patch('subprocess.check_output')
    def test_get_timew_info_command(self, mock_subprocess: Mock) -> None:
        """Test that correct timewarrior command is called."""
        import subprocess
        mock_subprocess.return_value = b'{"id": 1, "start": "20250528T140000Z", "tags": []}'

        get_timew_info()

        mock_subprocess.assert_called_once_with(["timew", "get", "dom.active.json"], stderr=subprocess.DEVNULL)

    @patch('subprocess.check_output')
    def test_get_timew_info_no_active_tracking(self, mock_subprocess: Mock) -> None:
        """Test that get_timew_info returns None when there's no active tracking."""
        import subprocess
        mock_subprocess.side_effect = subprocess.CalledProcessError(255, ['timew', 'get', 'dom.active.json'])

        result = get_timew_info()

        assert result is None

    @patch('subprocess.check_output')
    def test_get_timew_info_invalid_json(self, mock_subprocess: Mock) -> None:
        """Test that get_timew_info returns None when timew returns invalid JSON."""
        import subprocess
        mock_subprocess.return_value = b'invalid json'

        result = get_timew_info()

        assert result is None


class TestTimewRun:
    """Tests for timew_run function."""

    @patch('subprocess.run')
    @patch('aw_export_timewarrior.main.sleep')
    @patch('aw_export_timewarrior.main.GRACE_TIME', 0.1)
    def test_timew_run_executes_command(self, mock_sleep: Mock, mock_subprocess: Mock) -> None:
        """Test that timew_run executes the correct command."""
        timew_run(['start', '4work', 'programming'])

        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args[0][0]
        assert call_args == ['timew', 'start', '4work', 'programming']

    @patch('subprocess.run')
    @patch('aw_export_timewarrior.main.sleep')
    @patch('aw_export_timewarrior.main.GRACE_TIME', 0.1)
    def test_timew_run_waits_grace_time(self, mock_sleep: Mock, mock_subprocess: Mock) -> None:
        """Test that timew_run waits the grace period."""
        timew_run(['stop'])

        mock_sleep.assert_called_once_with(0.1)


class TestTimewRetag:
    """Tests for timew_retag function."""

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {},
        'tags': {
            'work_tags': {
                'source_tags': ['programming'],
                'add': ['4work']
            }
        }
    })
    @patch('aw_export_timewarrior.main.timew_run')
    @patch('aw_export_timewarrior.main.get_timew_info')
    def test_timew_retag_applies_rules(
        self,
        mock_get_info: Mock,
        mock_timew_run: Mock
    ) -> None:
        """Test that timew_retag applies retagging rules."""
        initial_info = {
            'id': 1,
            'start': '20250528T140000Z',
            'start_dt': datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc),
            'tags': {'programming'}
        }

        retagged_info = {
            'id': 1,
            'start': '20250528T140000Z',
            'start_dt': datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc),
            'tags': {'programming', '4work'}
        }

        mock_get_info.return_value = retagged_info

        result = timew_retag(initial_info)

        # Should have called timew retag command
        mock_timew_run.assert_called_once()
        call_args = mock_timew_run.call_args[0][0]
        assert call_args[0] == 'retag'
        assert '4work' in call_args
        assert 'programming' in call_args

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {},
        'tags': {}
    })
    @patch('aw_export_timewarrior.main.timew_run')
    def test_timew_retag_no_changes_needed(self, mock_timew_run: Mock) -> None:
        """Test that timew_retag doesn't call timew if no changes needed."""
        timew_info = {
            'id': 1,
            'start': '20250528T140000Z',
            'start_dt': datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc),
            'tags': {'4work', 'programming'}
        }

        result = timew_retag(timew_info)

        # Should not have called timew_run
        mock_timew_run.assert_not_called()
        assert result == timew_info


class TestEnsureTagExported:
    """Tests for ensure_tag_exported method."""

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {},
        'tags': {}
    })
    @patch('aw_export_timewarrior.main.timew_run')
    @patch('aw_export_timewarrior.main.get_timew_info')
    @patch('aw_export_timewarrior.main.timew_retag')
    def test_ensure_tag_exported_starts_new_tracking(
        self,
        mock_retag: Mock,
        mock_get_info: Mock,
        mock_timew_run: Mock,
        mock_aw_client: Mock
    ) -> None:
        """Test that ensure_tag_exported starts new timewarrior tracking."""
        exporter = Exporter()
        exporter.state.last_known_tick = datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc)
        exporter.state.last_start_time = datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc)
        exporter.state.set_afk_state(AfkState.ACTIVE)
        exporter.state.manual_tracking = False

        mock_timew_info = {
            'id': 1,
            'start': '20250528T140000Z',
            'start_dt': datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc),
            'tags': {'old', 'tags'}
        }
        mock_retag.return_value = mock_timew_info
        mock_get_info.return_value = mock_timew_info

        event = {
            'timestamp': datetime(2025, 5, 28, 14, 2, 0, tzinfo=timezone.utc),
            'duration': timedelta(minutes=5)
        }

        tags = {'4work', 'programming'}
        exporter.ensure_tag_exported(tags, event)

        # Should have called timew start with new tags
        mock_timew_run.assert_called_once()
        call_args = mock_timew_run.call_args[0][0]
        assert call_args[0] == 'start'
        assert '4work' in call_args
        assert 'programming' in call_args

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {},
        'tags': {}
    })
    @patch('aw_export_timewarrior.main.timew_run')
    @patch('aw_export_timewarrior.main.get_timew_info')
    @patch('aw_export_timewarrior.main.timew_retag')
    def test_ensure_tag_exported_skips_if_override(
        self,
        mock_retag: Mock,
        mock_get_info: Mock,
        mock_timew_run: Mock,
        mock_aw_client: Mock
    ) -> None:
        """Test that ensure_tag_exported skips when 'override' tag is present."""
        exporter = Exporter()
        exporter.state.last_known_tick = datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc)
        exporter.state.last_start_time = datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc)
        exporter.state.set_afk_state(AfkState.ACTIVE)

        mock_timew_info = {
            'id': 1,
            'start': '20250528T140000Z',
            'start_dt': datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc),
            'tags': {'4work', 'override'}  # Has override tag
        }
        mock_retag.return_value = mock_timew_info

        event = {
            'timestamp': datetime(2025, 5, 28, 14, 2, 0, tzinfo=timezone.utc),
            'duration': timedelta(minutes=5)
        }

        tags = {'4break', 'tea'}
        exporter.ensure_tag_exported(tags, event)

        # Should not have called timew_run because of override
        mock_timew_run.assert_not_called()

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {},
        'tags': {}
    })
    @patch('aw_export_timewarrior.main.timew_run')
    @patch('aw_export_timewarrior.main.get_timew_info')
    @patch('aw_export_timewarrior.main.timew_retag')
    def test_ensure_tag_exported_skips_if_tags_subset(
        self,
        mock_retag: Mock,
        mock_get_info: Mock,
        mock_timew_run: Mock,
        mock_aw_client: Mock
    ) -> None:
        """Test that ensure_tag_exported skips when tags are already tracked."""
        exporter = Exporter()
        exporter.state.last_known_tick = datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc)
        exporter.state.last_start_time = datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc)
        exporter.state.set_afk_state(AfkState.ACTIVE)

        mock_timew_info = {
            'id': 1,
            'start': '20250528T140000Z',
            'start_dt': datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc),
            'tags': {'4work', 'programming', 'python'}
        }
        mock_retag.return_value = mock_timew_info

        event = {
            'timestamp': datetime(2025, 5, 28, 14, 2, 0, tzinfo=timezone.utc),
            'duration': timedelta(minutes=5)
        }

        # Tags are subset of current tracking
        tags = {'4work', 'programming'}
        exporter.ensure_tag_exported(tags, event)

        # Should not have called timew_run because tags are already tracked
        mock_timew_run.assert_not_called()


class TestExporterTick:
    """Tests for main tick method."""

    @patch('aw_export_timewarrior.main.get_timew_info')
    @patch('aw_export_timewarrior.main.timew_retag')
    @patch('aw_export_timewarrior.main.sleep')
    def test_tick_initializes_last_tick_from_timew(
        self,
        mock_sleep: Mock,
        mock_retag: Mock,
        mock_get_info: Mock,
        mock_aw_client: Mock
    ) -> None:
        """Test that first tick initializes from timewarrior info."""
        exporter = Exporter()
        exporter.state.last_tick = None  # Not initialized

        timew_info = {
            'id': 1,
            'start': '20250528T140000Z',
            'start_dt': datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc),
            'tags': {'4work'}
        }
        mock_retag.return_value = timew_info
        mock_get_info.return_value = timew_info

        # Mock find_next_activity to return False (no events)
        exporter.find_next_activity = Mock(return_value=False)

        exporter.tick()

        assert exporter.state.last_tick == timew_info['start_dt']
        assert exporter.state.last_known_tick == timew_info['start_dt']

    @patch('aw_export_timewarrior.main.get_timew_info')
    @patch('aw_export_timewarrior.main.timew_retag')
    @patch('aw_export_timewarrior.main.sleep')
    @patch('aw_export_timewarrior.main.SLEEP_INTERVAL', 0.1)
    def test_tick_sleeps_when_no_events(
        self,
        mock_sleep: Mock,
        mock_retag: Mock,
        mock_get_info: Mock,
        mock_aw_client: Mock
    ) -> None:
        """Test that tick sleeps when no events are found."""
        exporter = Exporter()
        exporter.state.last_tick = datetime.now(timezone.utc)

        timew_info = {
            'id': 1,
            'start': '20250528T140000Z',
            'start_dt': datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc),
            'tags': {'4work'}
        }
        mock_retag.return_value = timew_info
        mock_get_info.return_value = timew_info

        # Mock find_next_activity to return False (no events)
        exporter.find_next_activity = Mock(return_value=False)

        exporter.tick()

        mock_sleep.assert_called_once_with(0.1)


class TestExporterLog:
    """Tests for logging method."""

    @patch('aw_export_timewarrior.main.logger')
    def test_log_with_event(self, mock_logger: Mock, mock_aw_client: Mock) -> None:
        """Test logging with an event."""
        exporter = Exporter()
        exporter.state.last_tick = datetime(2025, 5, 28, 14, 0, 0, tzinfo=timezone.utc)

        event = {
            'timestamp': datetime(2025, 5, 28, 14, 5, 0, tzinfo=timezone.utc),
            'duration': timedelta(minutes=5)
        }

        exporter.log("Test message", event=event)

        mock_logger.log.assert_called_once()
        # Check the message and extra data
        call_args = mock_logger.log.call_args
        assert call_args[0][1] == "Test message"  # Second arg is the message
        extra = call_args[1]['extra']
        assert 'event_duration' in extra
        assert '300' in extra['event_duration'] or '300.0' in extra['event_duration']

    @patch('aw_export_timewarrior.main.logger')
    def test_log_with_level(self, mock_logger: Mock, mock_aw_client: Mock) -> None:
        """Test logging with different log levels."""
        exporter = Exporter()

        exporter.log("Important message", level=logging.WARNING)

        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.WARNING  # First arg is the level
        assert call_args[0][1] == "Important message"  # Second arg is the message


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
