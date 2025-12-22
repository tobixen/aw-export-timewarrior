"""Comprehensive unit tests for aw-export-timewarrior."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.main import (
    EventMatchResult,
    Exporter,
    TagResult,
    retag_by_rules,
)
from aw_export_timewarrior.state import AfkState
from aw_export_timewarrior.tag_extractor import TagExtractor
from aw_export_timewarrior.utils import ts2str, ts2strtime


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
    with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
        mock_client = Mock()

        # Get current time for last_updated
        current_time = datetime.now(UTC).isoformat()

        mock_client.get_buckets.return_value = {
            "aw-watcher-window_test": {
                "id": "aw-watcher-window_test",
                "client": "aw-watcher-window",
                "last_updated": current_time,
            },
            "aw-watcher-afk_test": {
                "id": "aw-watcher-afk_test",
                "client": "aw-watcher-afk",
                "last_updated": current_time,
            },
        }
        # Set up mock to return our mock_client
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
        assert result == "XX:XX:XX"


class TestExclusiveOverlapping:
    """Tests for exclusive tag checking."""

    def test_no_overlap(self) -> None:
        """Test tags with no exclusive overlap."""
        config = {
            "exclusive": {
                "main_category": {"tags": ["4work", "4break", "4chores"]},
                "customer": {"tags": ["acme", "emca", "initech"]},
            }
        }
        extractor = TagExtractor(config=config, event_fetcher=None)
        tags = {"4work", "programming", "python"}
        assert not extractor.check_exclusive_groups(tags)

    def test_overlap_in_main_category(self) -> None:
        """Test tags that overlap in exclusive main category."""
        config = {"exclusive": {"main_category": {"tags": ["4work", "4break", "4chores"]}}}
        extractor = TagExtractor(config=config, event_fetcher=None)
        tags = {"4work", "4break", "programming"}
        assert extractor.check_exclusive_groups(tags)

    def test_overlap_in_customer(self) -> None:
        """Test tags that overlap in exclusive customer category."""
        config = {"exclusive": {"customer": {"tags": ["acme", "emca"]}}}
        extractor = TagExtractor(config=config, event_fetcher=None)
        tags = {"acme", "emca", "programming"}
        assert extractor.check_exclusive_groups(tags)

    def test_no_exclusive_groups(self) -> None:
        """Test with no exclusive groups configured."""
        config = {"exclusive": {}}
        extractor = TagExtractor(config=config, event_fetcher=None)
        tags = {"any", "tags", "should", "work"}
        assert not extractor.check_exclusive_groups(tags)


class TestRetagByRules:
    """Tests for retag_by_rules function."""

    @patch(
        "aw_export_timewarrior.main.config",
        {
            "exclusive": {},
            "tags": {"tea_break": {"source_tags": ["tea"], "add": ["4break", "afk"]}},
        },
    )
    def test_simple_retag_adds_tags(self) -> None:
        """Test that retag adds configured tags."""
        source_tags = {"tea"}
        result = retag_by_rules(source_tags)
        assert "4break" in result
        assert "afk" in result
        assert "tea" in result

    @patch("aw_export_timewarrior.main.config", {"exclusive": {}, "tags": {}})
    def test_retag_with_no_rules(self) -> None:
        """Test retag when no rules match."""
        source_tags = {"random", "tags"}
        result = retag_by_rules(source_tags)
        assert result == source_tags

    @patch(
        "aw_export_timewarrior.main.config",
        {
            "exclusive": {},
            "tags": {
                "work_tags": {
                    "source_tags": ["programming", "coding"],
                    "add": ["4work", "computer"],
                }
            },
        },
    )
    def test_retag_partial_match(self) -> None:
        """Test retag with partial source_tags match."""
        source_tags = {"programming", "python"}
        result = retag_by_rules(source_tags)
        assert "4work" in result
        assert "computer" in result
        assert "programming" in result
        assert "python" in result

    @patch(
        "aw_export_timewarrior.main.config",
        {
            "exclusive": {"main": {"tags": ["4work", "4break"]}},
            "tags": {
                "break_rule": {
                    "source_tags": ["tea"],
                    "add": ["4work"],  # Would conflict with break
                }
            },
        },
    )
    def test_retag_respects_exclusive_rules(self) -> None:
        """Test that retag respects exclusive tag rules."""
        source_tags = {"tea", "4break"}
        # Should not add 4work because it conflicts with 4break
        with patch("aw_export_timewarrior.main.logging") as _mock_logging:
            result = retag_by_rules(source_tags)
            # The rule should be excluded due to conflict
            assert "4work" not in result or "4break" not in result

    @patch(
        "aw_export_timewarrior.main.config",
        {
            "exclusive": {},
            "tags": {
                "expand_source": {
                    "source_tags": ["github"],
                    "add": ["$source_tag-work", "programming"],
                }
            },
        },
    )
    def test_retag_with_source_tag_placeholder(self) -> None:
        """Test retag with $source_tag placeholder expansion."""
        source_tags = {"github"}
        result = retag_by_rules(source_tags)
        assert "github-work" in result
        assert "programming" in result

    @patch(
        "aw_export_timewarrior.main.config",
        {
            "exclusive": {},
            "tags": {
                "remove_unwanted": {
                    "source_tags": ["work"],
                    "remove": ["debug", "temp"],
                }
            },
        },
    )
    def test_retag_remove_tags(self) -> None:
        """Test that remove operation removes specified tags."""
        source_tags = {"work", "debug", "temp", "important"}
        result = retag_by_rules(source_tags)
        assert "work" in result
        assert "important" in result
        assert "debug" not in result
        assert "temp" not in result

    @patch(
        "aw_export_timewarrior.main.config",
        {
            "exclusive": {},
            "tags": {
                "remove_with_placeholder": {
                    "source_tags": ["old-tag"],
                    "remove": ["$source_tag"],
                }
            },
        },
    )
    def test_retag_remove_with_source_tag_placeholder(self) -> None:
        """Test that remove with $source_tag removes the matched source tag."""
        source_tags = {"old-tag", "keep-this"}
        result = retag_by_rules(source_tags)
        assert "old-tag" not in result
        assert "keep-this" in result

    @patch(
        "aw_export_timewarrior.main.config",
        {
            "exclusive": {},
            "tags": {
                "replace_old": {
                    "source_tags": ["old-project"],
                    "replace": ["new-project", "migrated"],
                }
            },
        },
    )
    def test_retag_replace_tags(self) -> None:
        """Test that replace operation replaces source tags with new tags."""
        source_tags = {"old-project", "work"}
        result = retag_by_rules(source_tags)
        assert "old-project" not in result
        assert "new-project" in result
        assert "migrated" in result
        assert "work" in result  # Non-source tags are preserved

    @patch(
        "aw_export_timewarrior.main.config",
        {
            "exclusive": {},
            "tags": {
                "replace_with_placeholder": {
                    "source_tags": ["v1", "v2"],
                    "replace": ["$source_tag-archived"],
                }
            },
        },
    )
    def test_retag_replace_with_source_tag_placeholder(self) -> None:
        """Test that replace with $source_tag expands to matched tags."""
        source_tags = {"v1", "active"}
        result = retag_by_rules(source_tags)
        assert "v1" not in result
        assert "v1-archived" in result
        assert "active" in result

    @patch(
        "aw_export_timewarrior.main.config",
        {
            "exclusive": {},
            "tags": {
                "combined_ops": {
                    "source_tags": ["trigger"],
                    "remove": ["unwanted"],
                    "replace": ["replaced"],
                    "add": ["extra"],
                }
            },
        },
    )
    def test_retag_combined_operations(self) -> None:
        """Test that remove, replace, and add can be combined in one rule."""
        source_tags = {"trigger", "unwanted", "keep"}
        result = retag_by_rules(source_tags)
        # remove should remove "unwanted"
        assert "unwanted" not in result
        # replace should remove "trigger" and add "replaced"
        assert "trigger" not in result
        assert "replaced" in result
        # add should add "extra"
        assert "extra" in result
        # unrelated tags should be preserved
        assert "keep" in result


class TestExporterInitialization:
    """Tests for Exporter class initialization."""

    def test_exporter_init_creates_client(self, mock_aw_client: Mock) -> None:
        """Test that Exporter initializes ActivityWatch client."""
        exporter = Exporter()

        assert exporter.aw is mock_aw_client

    def test_exporter_init_processes_buckets(self, mock_aw_client: Mock) -> None:
        """Test that Exporter processes buckets correctly."""
        exporter = Exporter()

        assert "aw-watcher-window" in exporter.bucket_by_client
        assert "aw-watcher-afk" in exporter.bucket_by_client
        assert "aw-watcher-window" in exporter.bucket_short


class TestExporterSetKnownTickStats:
    """Tests for set_known_tick_stats method."""

    def test_set_known_tick_with_event(self, mock_aw_client: Mock) -> None:
        """Test set_known_tick_stats with an event."""

        exporter = Exporter()

        event = {
            "timestamp": datetime(2025, 5, 28, 10, 0, 0, tzinfo=UTC),
            "duration": timedelta(minutes=5),
        }

        exporter.set_known_tick_stats(event=event)

        assert exporter.state.last_known_tick == datetime(2025, 5, 28, 10, 5, 0, tzinfo=UTC)
        assert exporter.state.last_start_time == datetime(2025, 5, 28, 10, 0, 0, tzinfo=UTC)

    def test_set_known_tick_resets_accumulator(self, mock_aw_client: Mock) -> None:
        """Test that reset_accumulator clears accumulated times."""

        exporter = Exporter()

        # Add some accumulated time
        exporter.state.stats.tags_accumulated_time["work"] = timedelta(minutes=10)
        exporter.state.stats.tags_accumulated_time["coding"] = timedelta(minutes=5)

        exporter.set_known_tick_stats(
            start=datetime.now(UTC),
            reset_accumulator=True,
            retain_accumulator=False,  # Don't retain to avoid needing tags parameter
        )

        assert len(exporter.state.stats.tags_accumulated_time) == 0

    def test_set_known_tick_retains_accumulator(self, mock_aw_client: Mock) -> None:
        """Test that retain_accumulator keeps tags with sticky factor."""

        exporter = Exporter()
        exporter.stickyness_factor = 0.2
        exporter.min_recording_interval = 60

        tags = ["work", "coding"]
        exporter.set_known_tick_stats(
            start=datetime.now(UTC), reset_accumulator=True, retain_accumulator=True, tags=tags
        )

        # Should have retained tags with stickyness_factor * min_recording_interval
        assert "work" in exporter.state.stats.tags_accumulated_time
        assert "coding" in exporter.state.stats.tags_accumulated_time
        expected_duration = timedelta(
            seconds=0.2 * 60
        )  # stickyness_factor * min_recording_interval
        assert exporter.state.stats.tags_accumulated_time["work"] == expected_duration
        assert exporter.state.stats.tags_accumulated_time["coding"] == expected_duration


class TestExporterFindTagsFromEvent:
    """Tests for find_tags_from_event method."""

    def test_short_event_returns_ignored(self, mock_aw_client: Mock) -> None:
        """Test that events shorter than ignore_interval return IGNORED result."""

        exporter = Exporter()
        exporter.ignore_interval = 3

        event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(seconds=2),  # Less than ignore_interval
            "data": {"app": "TestApp"},
        }

        result = exporter.find_tags_from_event(event)
        assert isinstance(result, TagResult)
        assert result.result == EventMatchResult.IGNORED
        assert result.tags == set()
        assert not result  # Should be falsy

    def test_afk_event_returns_afk_tag(self, mock_aw_client: Mock) -> None:
        """Test that AFK events return MATCHED result with afk tag."""

        exporter = Exporter()
        exporter.ignore_interval = 3

        event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"status": "afk"},
        }

        result = exporter.find_tags_from_event(event)
        assert isinstance(result, TagResult)
        assert result.result == EventMatchResult.MATCHED
        assert result.tags == {"afk"}
        assert result  # Should be truthy


class TestExporterCheckAndHandleAfkStateChange:
    """Tests for check_and_handle_afk_state_change method."""

    def test_initial_afk_state_from_tags(self, mock_aw_client: Mock) -> None:
        """Test initial AFK state is set from tags."""

        exporter = Exporter()
        exporter.state.afk_state = AfkState.UNKNOWN  # Initial state

        tags = {"afk"}
        event = {"timestamp": datetime.now(UTC), "duration": timedelta(minutes=5)}

        result = exporter.check_and_handle_afk_state_change(tags, event)

        assert exporter.state.is_afk() is True
        assert result is True  # Handled completely

    def test_initial_not_afk_state_from_tags(self, mock_aw_client: Mock) -> None:
        """Test initial not-AFK state is set from tags."""

        exporter = Exporter()
        exporter.state.afk_state = AfkState.UNKNOWN

        tags = {"not-afk"}
        event = {"timestamp": datetime.now(UTC), "duration": timedelta(seconds=1)}

        result = exporter.check_and_handle_afk_state_change(tags, event)

        assert exporter.state.is_afk() is False
        assert result is True

    def test_return_from_afk_resets_accumulator(self, mock_aw_client: Mock) -> None:
        """Test returning from AFK resets accumulator."""

        exporter = Exporter()
        exporter.state.set_afk_state(AfkState.AFK)
        exporter.timew_info = {"tags": {"afk"}}
        exporter.state.last_start_time = datetime.now(UTC) - timedelta(minutes=10)

        # Add some accumulated time
        exporter.state.stats.tags_accumulated_time["work"] = timedelta(minutes=5)

        tags = {"not-afk"}
        event = {"timestamp": datetime.now(UTC), "duration": timedelta(seconds=1)}

        exporter.check_and_handle_afk_state_change(tags, event)

        # Accumulator should be reset
        assert len(exporter.state.stats.tags_accumulated_time) == 0


class TestExporterPrettyAccumulatorString:
    """Tests for pretty_accumulator_string method."""

    def test_pretty_accumulator_string_formatting(self, mock_aw_client: Mock) -> None:
        """Test accumulator string formatting."""

        exporter = Exporter()
        exporter.min_tag_recording_interval = 30

        exporter.state.stats.tags_accumulated_time["work"] = timedelta(seconds=120)
        exporter.state.stats.tags_accumulated_time["coding"] = timedelta(seconds=60)
        exporter.state.stats.tags_accumulated_time["python"] = timedelta(seconds=45)
        exporter.state.stats.tags_accumulated_time["short"] = timedelta(
            seconds=10
        )  # Below threshold

        result = exporter.pretty_accumulator_string()

        # Should include tags above min_tag_recording_interval
        assert "work" in result
        assert "coding" in result
        assert "python" in result
        # Should not include tags below threshold
        assert "short" not in result
        # Should be sorted by duration (descending)
        lines = result.split("\n")
        assert "work" in lines[0]  # Highest duration first


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
