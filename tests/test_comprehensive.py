"""Comprehensive unit tests for aw-export-timewarrior."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.main import (
    Exporter,
    check_bucket_updated,
    exclusive_overlapping,
    retag_by_rules,
    ts2str,
    ts2strtime,
)
from aw_export_timewarrior.state import AfkState


def create_aw_event(timestamp, duration, data):
    """Create a mock ActivityWatch event object with proper attributes."""
    event = Mock()
    event.timestamp = timestamp
    event.duration = duration
    event.data = data
    return event


@pytest.fixture
def mock_aw_client():
    """Fixture for mocked ActivityWatch client with required buckets."""
    with patch('aw_export_timewarrior.main.aw_client') as mock_aw, \
         patch('aw_export_timewarrior.aw_client.ActivityWatchClient') as mock_aw_class:
        mock_client = Mock()

        # Get current time for last_updated
        current_time = datetime.now(UTC).isoformat()

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
        # Set up both patches to return the same mock
        mock_aw.ActivityWatchClient.return_value = mock_client
        mock_aw_class.return_value = mock_client
        yield mock_client


class TestTimestampFormatting:
    """Tests for timestamp formatting functions."""

    def test_ts2str_default_format(self) -> None:
        """Test ts2str with default format."""
        dt = datetime(2025, 5, 28, 14, 30, 45, tzinfo=UTC)
        result = ts2str(dt)
        assert "2025-05-28" in result
        assert ":30:45" in result  # Check time portion exists (timezone-independent)

    def test_ts2str_custom_format(self) -> None:
        """Test ts2str with custom format."""
        dt = datetime(2025, 5, 28, 14, 30, 45, tzinfo=UTC)
        result = ts2str(dt, format="%Y/%m/%d")
        assert "2025/05/28" in result

    def test_ts2strtime_with_timestamp(self) -> None:
        """Test ts2strtime with valid timestamp."""
        dt = datetime(2025, 5, 28, 14, 30, 45, tzinfo=UTC)
        result = ts2strtime(dt)
        # Should return time only
        assert ":" in result
        assert len(result) == 8  # HH:MM:SS

    def test_ts2strtime_with_none(self) -> None:
        """Test ts2strtime with None input."""
        result = ts2strtime(None)
        assert result == "XX:XX:XX:"


class TestExclusiveOverlapping:
    """Tests for exclusive tag checking."""

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {
            'main_category': {'tags': ['4work', '4break', '4chores']},
            'customer': {'tags': ['acme', 'emca', 'initech']}
        }
    })
    def test_no_overlap(self) -> None:
        """Test tags with no exclusive overlap."""
        tags = {'4work', 'programming', 'python'}
        assert not exclusive_overlapping(tags)

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {
            'main_category': {'tags': ['4work', '4break', '4chores']}
        }
    })
    def test_overlap_in_main_category(self) -> None:
        """Test tags that overlap in exclusive main category."""
        tags = {'4work', '4break', 'programming'}
        assert exclusive_overlapping(tags)

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {
            'customer': {'tags': ['acme', 'emca']}
        }
    })
    def test_overlap_in_customer(self) -> None:
        """Test tags that overlap in exclusive customer category."""
        tags = {'acme', 'emca', 'programming'}
        assert exclusive_overlapping(tags)

    @patch('aw_export_timewarrior.main.config', {'exclusive': {}})
    def test_no_exclusive_groups(self) -> None:
        """Test with no exclusive groups configured."""
        tags = {'any', 'tags', 'should', 'work'}
        assert not exclusive_overlapping(tags)


class TestRetagByRules:
    """Tests for retag_by_rules function."""

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {},
        'tags': {
            'tea_break': {
                'source_tags': ['tea'],
                'add': ['4break', 'afk']
            }
        }
    })
    def test_simple_retag_adds_tags(self) -> None:
        """Test that retag adds configured tags."""
        source_tags = {'tea'}
        result = retag_by_rules(source_tags)
        assert '4break' in result
        assert 'afk' in result
        assert 'tea' in result

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {},
        'tags': {}
    })
    def test_retag_with_no_rules(self) -> None:
        """Test retag when no rules match."""
        source_tags = {'random', 'tags'}
        result = retag_by_rules(source_tags)
        assert result == source_tags

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {},
        'tags': {
            'work_tags': {
                'source_tags': ['programming', 'coding'],
                'add': ['4work', 'computer']
            }
        }
    })
    def test_retag_partial_match(self) -> None:
        """Test retag with partial source_tags match."""
        source_tags = {'programming', 'python'}
        result = retag_by_rules(source_tags)
        assert '4work' in result
        assert 'computer' in result
        assert 'programming' in result
        assert 'python' in result

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {'main': {'tags': ['4work', '4break']}},
        'tags': {
            'break_rule': {
                'source_tags': ['tea'],
                'add': ['4work']  # Would conflict with break
            }
        }
    })
    def test_retag_respects_exclusive_rules(self) -> None:
        """Test that retag respects exclusive tag rules."""
        source_tags = {'tea', '4break'}
        # Should not add 4work because it conflicts with 4break
        with patch('aw_export_timewarrior.main.logging') as _mock_logging:
            result = retag_by_rules(source_tags)
            # The rule should be excluded due to conflict
            assert '4work' not in result or '4break' not in result

    @patch('aw_export_timewarrior.main.config', {
        'exclusive': {},
        'tags': {
            'expand_source': {
                'source_tags': ['github'],
                'add': ['$source_tag-work', 'programming']
            }
        }
    })
    def test_retag_with_source_tag_placeholder(self) -> None:
        """Test retag with $source_tag placeholder expansion."""
        source_tags = {'github'}
        result = retag_by_rules(source_tags)
        assert 'github-work' in result
        assert 'programming' in result


class TestBucketUpdated:
    """Tests for check_bucket_updated function."""

    @patch('aw_export_timewarrior.main.time')
    @patch('aw_export_timewarrior.main.logger')
    def test_recent_bucket_no_warning(self, mock_logger: Mock, mock_time: Mock) -> None:
        """Test that recent buckets don't trigger warnings."""
        mock_time.return_value = 1000.0
        bucket = {
            'id': 'test-bucket',
            'last_updated_dt': datetime.fromtimestamp(950.0, tz=UTC)
        }
        check_bucket_updated(bucket)
        mock_logger.warning.assert_not_called()

    @patch('aw_export_timewarrior.main.time')
    @patch('aw_export_timewarrior.main.logger')
    @patch('aw_export_timewarrior.main.AW_WARN_THRESHOLD', 300)
    def test_stale_bucket_triggers_warning(self, mock_logger: Mock, mock_time: Mock) -> None:
        """Test that stale buckets trigger warnings."""
        mock_time.return_value = 1000.0
        bucket = {
            'id': 'test-bucket',
            'last_updated_dt': datetime.fromtimestamp(500.0, tz=UTC)
        }
        check_bucket_updated(bucket)
        mock_logger.warning.assert_called_once()

    @patch('aw_export_timewarrior.main.logger')
    def test_null_last_updated_triggers_warning(self, mock_logger: Mock) -> None:
        """Test that buckets with no last_updated trigger warnings."""
        bucket = {
            'id': 'test-bucket',
            'last_updated_dt': None
        }
        check_bucket_updated(bucket)
        mock_logger.warning.assert_called_once()


class TestExporterInitialization:
    """Tests for Exporter class initialization."""

    def test_exporter_init_creates_client(self, mock_aw_client: Mock) -> None:
        """Test that Exporter initializes ActivityWatch client."""
        exporter = Exporter()

        assert exporter.aw is mock_aw_client

    def test_exporter_init_processes_buckets(self, mock_aw_client: Mock) -> None:
        """Test that Exporter processes buckets correctly."""
        exporter = Exporter()

        assert 'aw-watcher-window' in exporter.bucket_by_client
        assert 'aw-watcher-afk' in exporter.bucket_by_client
        assert 'aw-watcher-window' in exporter.bucket_short


class TestExporterSetKnownTickStats:
    """Tests for set_known_tick_stats method."""


    def test_set_known_tick_with_event(self, mock_aw_client: Mock) -> None:
        """Test set_known_tick_stats with an event."""

        exporter = Exporter()

        event = {
            'timestamp': datetime(2025, 5, 28, 10, 0, 0, tzinfo=UTC),
            'duration': timedelta(minutes=5)
        }

        exporter.set_known_tick_stats(event=event)

        assert exporter.state.last_known_tick == datetime(2025, 5, 28, 10, 5, 0, tzinfo=UTC)
        assert exporter.state.last_start_time == datetime(2025, 5, 28, 10, 0, 0, tzinfo=UTC)


    def test_set_known_tick_resets_accumulator(self, mock_aw_client: Mock) -> None:
        """Test that reset_accumulator clears accumulated times."""

        exporter = Exporter()

        # Add some accumulated time
        exporter.state.stats.tags_accumulated_time['work'] = timedelta(minutes=10)
        exporter.state.stats.tags_accumulated_time['coding'] = timedelta(minutes=5)

        exporter.set_known_tick_stats(
            start=datetime.now(UTC),
            reset_accumulator=True,
            retain_accumulator=False  # Don't retain to avoid needing tags parameter
        )

        assert len(exporter.state.stats.tags_accumulated_time) == 0


    @patch('aw_export_timewarrior.main.STICKYNESS_FACTOR', 0.2)
    @patch('aw_export_timewarrior.main.MIN_RECORDING_INTERVAL', 60)
    def test_set_known_tick_retains_accumulator(self, mock_aw_client: Mock) -> None:
        """Test that retain_accumulator keeps tags with sticky factor."""

        exporter = Exporter()

        tags = ['work', 'coding']
        exporter.set_known_tick_stats(
            start=datetime.now(UTC),
            reset_accumulator=True,
            retain_accumulator=True,
            tags=tags
        )

        # Should have retained tags with STICKYNESS_FACTOR * MIN_RECORDING_INTERVAL
        assert 'work' in exporter.state.stats.tags_accumulated_time
        assert 'coding' in exporter.state.stats.tags_accumulated_time
        expected_duration = timedelta(seconds=0.2 * 60)  # STICKYNESS_FACTOR * MIN_RECORDING_INTERVAL
        assert exporter.state.stats.tags_accumulated_time['work'] == expected_duration
        assert exporter.state.stats.tags_accumulated_time['coding'] == expected_duration


class TestExporterFindTagsFromEvent:
    """Tests for find_tags_from_event method."""


    @patch('aw_export_timewarrior.main.IGNORE_INTERVAL', 3)
    def test_short_event_returns_none(self, mock_aw_client: Mock) -> None:
        """Test that events shorter than IGNORE_INTERVAL return None."""

        exporter = Exporter()

        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(seconds=2),  # Less than IGNORE_INTERVAL
            'data': {'app': 'TestApp'}
        }

        result = exporter.find_tags_from_event(event)
        assert result is None


    @patch('aw_export_timewarrior.main.IGNORE_INTERVAL', 3)
    def test_afk_event_returns_afk_tag(self, mock_aw_client: Mock) -> None:
        """Test that AFK events return afk tag."""

        exporter = Exporter()

        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {'status': 'afk'}
        }

        result = exporter.find_tags_from_event(event)
        assert result == {'afk'}


class TestExporterCheckAndHandleAfkStateChange:
    """Tests for check_and_handle_afk_state_change method."""


    def test_initial_afk_state_from_tags(self, mock_aw_client: Mock) -> None:
        """Test initial AFK state is set from tags."""

        exporter = Exporter()
        exporter.state.afk_state = AfkState.UNKNOWN  # Initial state

        tags = {'afk'}
        event = {'timestamp': datetime.now(UTC), 'duration': timedelta(minutes=5)}

        result = exporter.check_and_handle_afk_state_change(tags, event)

        assert exporter.state.is_afk() is True
        assert result is True  # Handled completely


    def test_initial_not_afk_state_from_tags(self, mock_aw_client: Mock) -> None:
        """Test initial not-AFK state is set from tags."""

        exporter = Exporter()
        exporter.state.afk_state = AfkState.UNKNOWN

        tags = {'not-afk'}
        event = {'timestamp': datetime.now(UTC), 'duration': timedelta(seconds=1)}

        result = exporter.check_and_handle_afk_state_change(tags, event)

        assert exporter.state.is_afk() is False
        assert result is True


    def test_return_from_afk_resets_accumulator(self, mock_aw_client: Mock) -> None:
        """Test returning from AFK resets accumulator."""

        exporter = Exporter()
        exporter.state.set_afk_state(AfkState.AFK)
        exporter.timew_info = {'tags': {'afk'}}
        exporter.state.last_start_time = datetime.now(UTC) - timedelta(minutes=10)

        # Add some accumulated time
        exporter.state.stats.tags_accumulated_time['work'] = timedelta(minutes=5)

        tags = {'not-afk'}
        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(seconds=1)
        }

        exporter.check_and_handle_afk_state_change(tags, event)

        # Accumulator should be reset
        assert len(exporter.state.stats.tags_accumulated_time) == 0


class TestExporterPrettyAccumulatorString:
    """Tests for pretty_accumulator_string method."""


    @patch('aw_export_timewarrior.main.MIN_TAG_RECORDING_INTERVAL', 30)
    def test_pretty_accumulator_string_formatting(self, mock_aw_client: Mock) -> None:
        """Test accumulator string formatting."""

        exporter = Exporter()

        exporter.state.stats.tags_accumulated_time['work'] = timedelta(seconds=120)
        exporter.state.stats.tags_accumulated_time['coding'] = timedelta(seconds=60)
        exporter.state.stats.tags_accumulated_time['python'] = timedelta(seconds=45)
        exporter.state.stats.tags_accumulated_time['short'] = timedelta(seconds=10)  # Below threshold

        result = exporter.pretty_accumulator_string()

        # Should include tags above MIN_TAG_RECORDING_INTERVAL
        assert 'work' in result
        assert 'coding' in result
        assert 'python' in result
        # Should not include tags below threshold
        assert 'short' not in result
        # Should be sorted by duration (descending)
        lines = result.split('\n')
        assert 'work' in lines[0]  # Highest duration first


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
