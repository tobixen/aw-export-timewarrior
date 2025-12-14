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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
