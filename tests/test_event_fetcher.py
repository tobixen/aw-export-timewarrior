"""Tests for EventFetcher component (aw_client.py).

This test suite covers the EventFetcher class which isolates all ActivityWatch
data access. Part of the Exporter refactoring plan (EXPORTER_REFACTORING_PLAN.md).
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.aw_client import EventFetcher


def create_test_bucket(bucket_id: str, client: str, last_updated: str | None = None) -> dict:
    """Create a test bucket dictionary."""
    return {
        "id": bucket_id,
        "client": client,
        "last_updated": last_updated or datetime.now(UTC).isoformat(),
    }


def create_test_event(timestamp: datetime, duration_seconds: float, data: dict) -> dict:
    """Create a test event dictionary."""
    return {"timestamp": timestamp.isoformat(), "duration": duration_seconds, "data": data}


class TestEventFetcherInit:
    """Tests for EventFetcher initialization."""

    def test_init_with_test_data(self) -> None:
        """Test initialization with test data (no AW connection)."""
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                )
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        assert fetcher.aw is None
        assert fetcher.test_data == test_data
        assert len(fetcher.buckets) == 1
        assert "aw-watcher-window_test" in fetcher.buckets

    def test_init_with_aw_client(self) -> None:
        """Test initialization with real AW client."""
        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                )
            }
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher()

            assert fetcher.aw == mock_client
            assert fetcher.test_data is None
            mock_aw_class.assert_called_once_with(client_name="aw-export")
            mock_client.get_buckets.assert_called_once()

    def test_custom_client_name(self) -> None:
        """Test initialization with custom client name."""
        test_data = {"buckets": {}}
        fetcher = EventFetcher(test_data=test_data, client_name="custom-client")
        # Should work with test data (client_name ignored)
        assert fetcher.aw is None


class TestBucketMappings:
    """Tests for bucket mapping initialization."""

    def test_bucket_by_client_mapping(self) -> None:
        """Test that buckets are indexed by client type."""
        test_data = {
            "buckets": {
                "aw-watcher-window_host1": create_test_bucket(
                    "aw-watcher-window_host1", "aw-watcher-window"
                ),
                "aw-watcher-window_host2": create_test_bucket(
                    "aw-watcher-window_host2", "aw-watcher-window"
                ),
                "aw-watcher-afk_host1": create_test_bucket(
                    "aw-watcher-afk_host1", "aw-watcher-afk"
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        assert "aw-watcher-window" in fetcher.bucket_by_client
        assert len(fetcher.bucket_by_client["aw-watcher-window"]) == 2
        assert "aw-watcher-window_host1" in fetcher.bucket_by_client["aw-watcher-window"]
        assert "aw-watcher-window_host2" in fetcher.bucket_by_client["aw-watcher-window"]

        assert "aw-watcher-afk" in fetcher.bucket_by_client
        assert len(fetcher.bucket_by_client["aw-watcher-afk"]) == 1

    def test_bucket_short_mapping(self) -> None:
        """Test that buckets can be accessed by short name."""
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                ),
                "aw-watcher-afk_test": create_test_bucket("aw-watcher-afk_test", "aw-watcher-afk"),
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        assert "aw-watcher-window" in fetcher.bucket_short
        assert fetcher.bucket_short["aw-watcher-window"]["client"] == "aw-watcher-window"
        assert fetcher.bucket_short["aw-watcher-window"]["id"] == "aw-watcher-window_test"

        assert "aw-watcher-afk" in fetcher.bucket_short
        assert fetcher.bucket_short["aw-watcher-afk"]["id"] == "aw-watcher-afk_test"

    def test_last_updated_parsing(self) -> None:
        """Test that last_updated timestamps are parsed."""
        timestamp = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test",
                    "aw-watcher-window",
                    last_updated=timestamp.isoformat(),
                )
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        bucket = fetcher.buckets["aw-watcher-window_test"]
        assert "last_updated_dt" in bucket
        assert bucket["last_updated_dt"] == timestamp

    def test_missing_last_updated(self) -> None:
        """Test handling of missing last_updated field."""
        test_data = {
            "buckets": {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "client": "aw-watcher-window",
                    # No last_updated field
                }
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        bucket = fetcher.buckets["aw-watcher-window_test"]
        assert bucket.get("last_updated_dt") is None


class TestGetEvents:
    """Tests for get_events method."""

    def test_get_events_from_test_data(self) -> None:
        """Test fetching events from test data."""
        start_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                )
            },
            "events": {
                "aw-watcher-window_test": [
                    create_test_event(start_time, 60, {"title": "Event 1"}),
                    create_test_event(start_time + timedelta(minutes=5), 120, {"title": "Event 2"}),
                ]
            },
        }

        fetcher = EventFetcher(test_data=test_data)
        events = fetcher.get_events("aw-watcher-window_test")

        assert len(events) == 2
        assert events[0]["data"]["title"] == "Event 1"
        assert events[1]["data"]["title"] == "Event 2"

    def test_get_events_with_time_filter(self) -> None:
        """Test fetching events with start/end time filtering."""
        base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                )
            },
            "events": {
                "aw-watcher-window_test": [
                    create_test_event(base_time, 60, {"title": "Event 1"}),  # 10:00 - 10:01
                    create_test_event(
                        base_time + timedelta(minutes=5), 60, {"title": "Event 2"}
                    ),  # 10:05 - 10:06
                    create_test_event(
                        base_time + timedelta(minutes=10), 60, {"title": "Event 3"}
                    ),  # 10:10 - 10:11
                ]
            },
        }

        fetcher = EventFetcher(test_data=test_data)

        # Filter to get only middle event
        events = fetcher.get_events(
            "aw-watcher-window_test",
            start=base_time + timedelta(minutes=4),
            end=base_time + timedelta(minutes=7),
        )

        assert len(events) == 1
        assert events[0]["data"]["title"] == "Event 2"

    def test_get_events_timestamp_conversion(self) -> None:
        """Test that timestamp strings are converted to datetime objects."""
        start_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                )
            },
            "events": {
                "aw-watcher-window_test": [
                    create_test_event(start_time, 60, {"title": "Event 1"}),
                ]
            },
        }

        fetcher = EventFetcher(test_data=test_data)
        events = fetcher.get_events("aw-watcher-window_test")

        # Timestamp should be converted to datetime
        assert isinstance(events[0]["timestamp"], datetime)
        assert events[0]["timestamp"] == start_time

    def test_get_events_duration_conversion(self) -> None:
        """Test that duration numbers are converted to timedelta objects."""
        start_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                )
            },
            "events": {
                "aw-watcher-window_test": [
                    create_test_event(start_time, 120, {"title": "Event 1"}),
                ]
            },
        }

        fetcher = EventFetcher(test_data=test_data)
        events = fetcher.get_events("aw-watcher-window_test")

        # Duration should be converted to timedelta
        assert isinstance(events[0]["duration"], timedelta)
        assert events[0]["duration"] == timedelta(seconds=120)

    def test_get_events_attribute_and_dict_access(self) -> None:
        """Test that events support both dict and attribute access."""
        start_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                )
            },
            "events": {
                "aw-watcher-window_test": [
                    create_test_event(start_time, 60, {"title": "Event 1"}),
                ]
            },
        }

        fetcher = EventFetcher(test_data=test_data)
        events = fetcher.get_events("aw-watcher-window_test")

        event = events[0]

        # Both dict and attribute access should work
        assert event["timestamp"] == event.timestamp
        assert event["duration"] == event.duration
        assert event["data"] == event.data

    def test_get_events_from_aw_client(self) -> None:
        """Test fetching events from real AW client."""
        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = [
                {"timestamp": datetime.now(UTC), "duration": timedelta(seconds=60), "data": {}}
            ]
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher()

            start = datetime.now(UTC)
            end = start + timedelta(hours=1)
            events = fetcher.get_events("test-bucket", start=start, end=end)

            mock_client.get_events.assert_called_once_with("test-bucket", start=start, end=end)
            assert len(events) == 1


class TestGetCorrespondingEvent:
    """Tests for get_corresponding_event method."""

    def test_find_corresponding_event_simple(self) -> None:
        """Test finding a corresponding event in normal case."""
        window_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        browser_time = window_time + timedelta(seconds=0.5)

        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                ),
                "aw-watcher-web-chrome_test": create_test_bucket(
                    "aw-watcher-web-chrome_test", "aw-watcher-web-chrome"
                ),
            },
            "events": {
                "aw-watcher-web-chrome_test": [
                    create_test_event(browser_time, 120, {"url": "https://github.com"})
                ]
            },
        }

        fetcher = EventFetcher(test_data=test_data)

        window_event = {
            "timestamp": window_time,
            "duration": timedelta(seconds=60),
            "data": {"title": "GitHub"},
        }

        result = fetcher.get_corresponding_event(
            window_event, "aw-watcher-web-chrome_test", ignorable=True
        )

        assert result is not None
        assert result["data"]["url"] == "https://github.com"

    def test_no_corresponding_event_found(self) -> None:
        """Test when no corresponding event exists."""
        window_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                ),
                "aw-watcher-web-chrome_test": create_test_bucket(
                    "aw-watcher-web-chrome_test", "aw-watcher-web-chrome"
                ),
            },
            "events": {
                "aw-watcher-web-chrome_test": []  # No events
            },
        }

        fetcher = EventFetcher(test_data=test_data)

        window_event = {
            "timestamp": window_time,
            "duration": timedelta(seconds=60),
            "data": {"title": "GitHub"},
        }

        result = fetcher.get_corresponding_event(
            window_event, "aw-watcher-web-chrome_test", ignorable=True
        )

        assert result is None

    def test_multiple_events_picks_longest(self) -> None:
        """Test that when multiple events found, longest is returned."""
        window_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

        test_data = {
            "buckets": {
                "aw-watcher-web-chrome_test": create_test_bucket(
                    "aw-watcher-web-chrome_test", "aw-watcher-web-chrome"
                ),
            },
            "events": {
                "aw-watcher-web-chrome_test": [
                    create_test_event(window_time, 10, {"url": "https://short.com"}),
                    create_test_event(window_time, 120, {"url": "https://longest.com"}),
                    create_test_event(window_time, 30, {"url": "https://medium.com"}),
                ]
            },
        }

        fetcher = EventFetcher(test_data=test_data)

        window_event = {
            "timestamp": window_time,
            "duration": timedelta(seconds=60),
            "data": {"title": "Browser"},
        }

        result = fetcher.get_corresponding_event(
            window_event, "aw-watcher-web-chrome_test", ignorable=True
        )

        assert result is not None
        assert result["data"]["url"] == "https://longest.com"

    def test_filters_out_very_short_events(self) -> None:
        """Test that very short events are filtered when multiple exist."""
        window_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

        test_data = {
            "buckets": {
                "aw-watcher-web-chrome_test": create_test_bucket(
                    "aw-watcher-web-chrome_test", "aw-watcher-web-chrome"
                ),
            },
            "events": {
                "aw-watcher-web-chrome_test": [
                    create_test_event(
                        window_time, 1, {"url": "https://too-short.com"}
                    ),  # Very short
                    create_test_event(window_time, 10, {"url": "https://valid.com"}),  # Long enough
                ]
            },
        }

        fetcher = EventFetcher(test_data=test_data)

        window_event = {
            "timestamp": window_time,
            "duration": timedelta(seconds=60),
            "data": {"title": "Browser"},
        }

        result = fetcher.get_corresponding_event(
            window_event, "aw-watcher-web-chrome_test", ignorable=True
        )

        assert result is not None
        assert result["data"]["url"] == "https://valid.com"

    def test_log_callback_on_missing_event(self) -> None:
        """Test that log callback is called when event not found."""
        window_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

        test_data = {"buckets": {}, "events": {}}

        log_calls = []

        def log_callback(msg: str, **kwargs: Any) -> None:
            log_calls.append((msg, kwargs))

        fetcher = EventFetcher(test_data=test_data, log_callback=log_callback)

        window_event = {
            "timestamp": window_time,
            "duration": timedelta(seconds=60),
            "data": {"title": "GitHub"},
        }

        # Not ignorable and long enough to trigger logging
        result = fetcher.get_corresponding_event(
            window_event,
            "aw-watcher-web-chrome_test",
            ignorable=False,
            retry=0,  # Disable retry for this test
        )

        assert result is None
        assert len(log_calls) > 0
        assert "No corresponding" in log_calls[0][0]


class TestBucketHelpers:
    """Tests for bucket helper methods."""

    def test_get_window_bucket(self) -> None:
        """Test getting window bucket ID."""
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)
        bucket_id = fetcher.get_window_bucket()

        assert bucket_id == "aw-watcher-window_test"

    def test_get_afk_bucket(self) -> None:
        """Test getting AFK bucket ID."""
        test_data = {
            "buckets": {
                "aw-watcher-afk_test": create_test_bucket("aw-watcher-afk_test", "aw-watcher-afk"),
            }
        }

        fetcher = EventFetcher(test_data=test_data)
        bucket_id = fetcher.get_afk_bucket()

        assert bucket_id == "aw-watcher-afk_test"

    def test_has_bucket_client_true(self) -> None:
        """Test has_bucket_client returns True when bucket exists."""
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        assert fetcher.has_bucket_client("aw-watcher-window") is True

    def test_has_bucket_client_false(self) -> None:
        """Test has_bucket_client returns False when bucket doesn't exist."""
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        assert fetcher.has_bucket_client("aw-watcher-web-chrome") is False


class TestCheckBucketFreshness:
    """Tests for check_bucket_freshness method."""

    def test_fresh_bucket_no_warning(self) -> None:
        """Test that fresh buckets don't trigger warnings."""
        current_time = datetime.now(UTC)
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test",
                    "aw-watcher-window",
                    last_updated=current_time.isoformat(),
                ),
                "aw-watcher-afk_test": create_test_bucket(
                    "aw-watcher-afk_test", "aw-watcher-afk", last_updated=current_time.isoformat()
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        # Should not raise or log warnings
        with patch("aw_export_timewarrior.aw_client.logger") as mock_logger:
            fetcher.check_bucket_freshness(warn_threshold=300.0)
            mock_logger.warning.assert_not_called()

    def test_stale_bucket_triggers_warning(self) -> None:
        """Test that stale buckets trigger warnings."""
        # Bucket last updated 10 minutes ago
        stale_time = datetime.now(UTC) - timedelta(minutes=10)
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test",
                    "aw-watcher-window",
                    last_updated=stale_time.isoformat(),
                ),
                "aw-watcher-afk_test": create_test_bucket(
                    "aw-watcher-afk_test", "aw-watcher-afk", last_updated=stale_time.isoformat()
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        # Check with 300 second threshold (5 minutes) - should warn
        with patch("aw_export_timewarrior.aw_client.logger") as mock_logger:
            fetcher.check_bucket_freshness(warn_threshold=300.0)
            # Should warn about both buckets
            assert mock_logger.warning.call_count >= 2

    def test_missing_last_updated_triggers_warning(self) -> None:
        """Test that missing last_updated triggers warning."""
        test_data = {
            "buckets": {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "client": "aw-watcher-window",
                    # No last_updated
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "client": "aw-watcher-afk",
                    # No last_updated
                },
            }
        }

        # Need to manually set last_updated_dt since __init__ will parse it
        fetcher = EventFetcher(test_data=test_data)

        with patch("aw_export_timewarrior.aw_client.logger") as mock_logger:
            fetcher.check_bucket_freshness()
            # Should warn about both buckets
            assert mock_logger.warning.call_count >= 2


class TestAfkPromptBucketDetection:
    """Tests for AFK prompt bucket detection (aw-watcher-afk-prompt / aw-watcher-ask-away)."""

    def test_new_bucket_name_detected(self) -> None:
        """Test that new bucket name aw-watcher-afk-prompt is detected."""
        test_data = {
            "buckets": {
                "aw-watcher-afk-prompt_test": create_test_bucket(
                    "aw-watcher-afk-prompt_test", "aw-watcher-afk-prompt"
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)
        bucket_id = fetcher.get_afk_prompt_bucket()

        assert bucket_id == "aw-watcher-afk-prompt_test"

    def test_legacy_bucket_name_fallback(self) -> None:
        """Test that legacy bucket name aw-watcher-ask-away is used as fallback."""
        test_data = {
            "buckets": {
                "aw-watcher-ask-away_test": create_test_bucket(
                    "aw-watcher-ask-away_test", "aw-watcher-ask-away"
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)
        bucket_id = fetcher.get_afk_prompt_bucket()

        assert bucket_id == "aw-watcher-ask-away_test"

    def test_new_bucket_preferred_over_legacy(self) -> None:
        """Test that new bucket name is preferred when both exist."""
        test_data = {
            "buckets": {
                "aw-watcher-afk-prompt_test": create_test_bucket(
                    "aw-watcher-afk-prompt_test", "aw-watcher-afk-prompt"
                ),
                "aw-watcher-ask-away_test": create_test_bucket(
                    "aw-watcher-ask-away_test", "aw-watcher-ask-away"
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)
        bucket_id = fetcher.get_afk_prompt_bucket()

        # Should prefer the new name
        assert bucket_id == "aw-watcher-afk-prompt_test"

    def test_no_bucket_returns_none(self) -> None:
        """Test that None is returned when neither bucket exists."""
        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)
        bucket_id = fetcher.get_afk_prompt_bucket()

        assert bucket_id is None

    def test_legacy_alias_works(self) -> None:
        """Test that legacy method name get_ask_away_bucket still works."""
        test_data = {
            "buckets": {
                "aw-watcher-afk-prompt_test": create_test_bucket(
                    "aw-watcher-afk-prompt_test", "aw-watcher-afk-prompt"
                ),
            }
        }

        fetcher = EventFetcher(test_data=test_data)

        # Legacy alias should return same result
        assert fetcher.get_ask_away_bucket() == fetcher.get_afk_prompt_bucket()
        assert fetcher.get_ask_away_bucket() == "aw-watcher-afk-prompt_test"


class TestEventCache:
    """Tests for event caching in batch processing mode."""

    def _make_fetcher_with_aw(
        self,
        events: list,
        cache_range: tuple[datetime, datetime] | None = None,
    ) -> tuple["EventFetcher", Mock]:
        """Create an EventFetcher backed by a mock AW client."""
        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = events
            mock_aw_class.return_value = mock_client
            fetcher = EventFetcher(cache_range=cache_range)
            # Store the mock so callers can inspect it
            fetcher._mock_aw = mock_client
            return fetcher, mock_client

    def test_no_cache_by_default(self) -> None:
        """Without cache_range, every get_events call goes to AW."""
        base = datetime(2026, 2, 9, 11, 0, 0, tzinfo=UTC)
        event = {"timestamp": base, "duration": timedelta(seconds=60), "data": {}}

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = [event]
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher()

            start = base
            end = base + timedelta(hours=3)
            fetcher.get_events("bucket-a", start=start, end=end)
            fetcher.get_events("bucket-a", start=start, end=end)

            # Both calls should hit AW (no caching)
            assert mock_client.get_events.call_count == 2

    def test_cache_enabled_fetches_once_per_bucket(self) -> None:
        """With cache_range, each bucket is fetched from AW exactly once."""
        base = datetime(2026, 2, 9, 11, 0, 0, tzinfo=UTC)
        cache_start = base
        cache_end = base + timedelta(hours=3)
        event = {
            "timestamp": base + timedelta(minutes=30),
            "duration": timedelta(seconds=60),
            "data": {},
        }

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = [event]
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=(cache_start, cache_end))

            # First call fetches from AW and caches
            fetcher.get_events("bucket-a", start=cache_start, end=cache_end)
            assert mock_client.get_events.call_count == 1

            # Second call with same range is served from cache
            fetcher.get_events("bucket-a", start=cache_start, end=cache_end)
            assert mock_client.get_events.call_count == 1

            # Third call with a sub-range is also served from cache
            fetcher.get_events("bucket-a", start=base + timedelta(hours=1), end=cache_end)
            assert mock_client.get_events.call_count == 1

    def test_cache_fetches_full_range_not_sub_range(self) -> None:
        """The first fetch uses the full cache_range, not the requested sub-range."""
        base = datetime(2026, 2, 9, 11, 0, 0, tzinfo=UTC)
        cache_start = base
        cache_end = base + timedelta(hours=3)

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = []
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=(cache_start, cache_end))

            # Request only middle 1 hour
            fetcher.get_events(
                "bucket-a", start=base + timedelta(hours=1), end=base + timedelta(hours=2)
            )

            # AW should have been called with the FULL cache range
            mock_client.get_events.assert_called_once_with(
                "bucket-a", start=cache_start, end=cache_end
            )

    def test_cache_filters_events_by_requested_range(self) -> None:
        """Cached events are correctly filtered by the requested time range."""
        base = datetime(2026, 2, 9, 11, 0, 0, tzinfo=UTC)
        cache_start = base
        cache_end = base + timedelta(hours=3)

        events = [
            {
                "timestamp": base + timedelta(minutes=10),
                "duration": timedelta(seconds=60),
                "data": {"n": 1},
            },
            {
                "timestamp": base + timedelta(minutes=90),
                "duration": timedelta(seconds=60),
                "data": {"n": 2},
            },
            {
                "timestamp": base + timedelta(minutes=150),
                "duration": timedelta(seconds=60),
                "data": {"n": 3},
            },
        ]

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = events
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=(cache_start, cache_end))

            # Request only the middle portion
            result = fetcher.get_events(
                "bucket-a",
                start=base + timedelta(minutes=60),
                end=base + timedelta(minutes=120),
            )

            assert len(result) == 1
            assert result[0]["data"]["n"] == 2

    def test_cache_each_bucket_fetched_independently(self) -> None:
        """Each bucket has its own cache entry; different buckets are fetched independently."""
        base = datetime(2026, 2, 9, 11, 0, 0, tzinfo=UTC)
        cache_start = base
        cache_end = base + timedelta(hours=3)

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = []
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=(cache_start, cache_end))

            fetcher.get_events("bucket-a", start=cache_start, end=cache_end)
            fetcher.get_events("bucket-b", start=cache_start, end=cache_end)
            fetcher.get_events("bucket-a", start=cache_start, end=cache_end)  # cached
            fetcher.get_events("bucket-b", start=cache_start, end=cache_end)  # cached

            # Each bucket fetched once from AW
            assert mock_client.get_events.call_count == 2

    def test_cache_disabled_for_test_data(self) -> None:
        """Test data path is unaffected by cache_range (always reads from test_data dict)."""
        base = datetime(2026, 2, 9, 11, 0, 0, tzinfo=UTC)
        cache_start = base
        cache_end = base + timedelta(hours=3)

        test_data = {
            "buckets": {
                "aw-watcher-window_test": create_test_bucket(
                    "aw-watcher-window_test", "aw-watcher-window"
                )
            },
            "events": {
                "aw-watcher-window_test": [
                    create_test_event(base + timedelta(minutes=30), 60, {"title": "Test"})
                ]
            },
        }

        # cache_range should have no negative effect on test data path
        fetcher = EventFetcher(test_data=test_data, cache_range=(cache_start, cache_end))
        events = fetcher.get_events("aw-watcher-window_test")
        assert len(events) == 1

    def test_prepare_cached_events_normalizes_timestamp_once_per_event(self) -> None:
        """Regression test for CODE_REVIEW_2026-07-12.md #9: `_prepare_cached_events`
        called `normalize_timestamp(event["timestamp"])` twice per event (once for
        the start, once again to derive the end) - the exact re-parsing this
        cache exists to amortize away.
        """
        base = datetime(2026, 2, 9, 11, 0, 0, tzinfo=UTC)
        events = [
            {
                "timestamp": base + timedelta(minutes=i),
                "duration": timedelta(seconds=60),
                "data": {},
            }
            for i in range(5)
        ]

        with (
            patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class,
            patch(
                "aw_export_timewarrior.aw_client.normalize_timestamp",
                side_effect=lambda ts: ts,
            ) as mock_normalize,
        ):
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = events
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=(base, base + timedelta(hours=1)))
            fetcher.get_events("bucket-a", start=base, end=base + timedelta(hours=1))

        assert mock_normalize.call_count == len(events), (
            f"Expected normalize_timestamp called once per event ({len(events)}), "
            f"got {mock_normalize.call_count}"
        )

    def test_cache_filters_long_early_event_overlapping_later_window(self) -> None:
        """A long-duration event starting well before the requested window, but
        still overlapping it, must not be dropped by the cache's lower-bound
        search (events are sorted by start, not end, so a naive bisect on
        start alone would incorrectly exclude it).
        """
        base = datetime(2026, 2, 9, 11, 0, 0, tzinfo=UTC)
        cache_start = base
        cache_end = base + timedelta(hours=3)

        events = [
            # Starts right at cache_start but runs for 2 hours - overlaps a
            # request window that starts well after it.
            {
                "timestamp": base,
                "duration": timedelta(hours=2),
                "data": {"n": "long"},
            },
            {
                "timestamp": base + timedelta(minutes=10),
                "duration": timedelta(seconds=60),
                "data": {"n": "short-early"},
            },
        ]

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = events
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=(cache_start, cache_end))

            result = fetcher.get_events(
                "bucket-a",
                start=base + timedelta(minutes=90),
                end=base + timedelta(minutes=100),
            )

        names = {event["data"]["n"] for event in result}
        assert "long" in names, f"Long early event should overlap the later window, got: {names}"
        assert "short-early" not in names


class TestResetCache:
    """Tests for reset_cache method (rolling cache support for sync mode)."""

    def test_reset_cache_clears_entries_and_disables_range(self) -> None:
        """reset_cache() with no args clears cached data and sets _cache_range to None."""
        base = datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC)
        cache_range = (base, base + timedelta(hours=3))

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = []
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=cache_range)
            fetcher.get_events("bucket-a")  # populate cache
            assert "bucket-a" in fetcher._events_cache
            assert fetcher._cache_range is not None

            fetcher.reset_cache()

            assert fetcher._cache_range is None
            assert fetcher._events_cache == {}

    def test_reset_cache_with_new_range_sets_range(self) -> None:
        """reset_cache(new_range) clears cached data and activates the new window."""
        base = datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC)
        old_range = (base, base + timedelta(hours=1))
        new_range = (base + timedelta(hours=1), base + timedelta(hours=2))

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = []
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=old_range)
            fetcher.get_events("bucket-a")  # populate cache

            fetcher.reset_cache(new_range=new_range)

            assert fetcher._cache_range == new_range
            assert fetcher._events_cache == {}

    def test_reset_cache_causes_refetch(self) -> None:
        """After reset_cache(new_range), the next get_events hits AW again."""
        base = datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC)
        cache_range = (base, base + timedelta(hours=3))

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = []
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=cache_range)
            fetcher.get_events("bucket-a")  # cache miss → fetch #1
            assert mock_client.get_events.call_count == 1

            fetcher.get_events("bucket-a")  # cache hit → no new fetch
            assert mock_client.get_events.call_count == 1

            new_range = (base + timedelta(hours=3), base + timedelta(hours=6))
            fetcher.reset_cache(new_range=new_range)

            fetcher.get_events("bucket-a")  # cache miss after reset → fetch #2
            assert mock_client.get_events.call_count == 2

    def test_reset_cache_no_range_causes_direct_fetches(self) -> None:
        """After reset_cache() with no range, get_events bypasses cache entirely."""
        base = datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC)
        cache_range = (base, base + timedelta(hours=3))

        with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as mock_aw_class:
            mock_client = Mock()
            mock_client.get_buckets.return_value = {}
            mock_client.get_events.return_value = []
            mock_aw_class.return_value = mock_client

            fetcher = EventFetcher(cache_range=cache_range)
            fetcher.get_events("bucket-a")  # fetch #1 (with cache)
            assert mock_client.get_events.call_count == 1

            fetcher.reset_cache()  # disable cache

            fetcher.get_events("bucket-a")  # fetch #2 (no cache)
            fetcher.get_events("bucket-a")  # fetch #3 (no cache)
            assert mock_client.get_events.call_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
