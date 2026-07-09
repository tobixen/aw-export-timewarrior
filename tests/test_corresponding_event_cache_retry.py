"""Regression test for CODE_REVIEW_2026-07.md #7.

get_corresponding_event()'s sleep-and-retry loop is meant to handle a sub-event
(browser URL, editor file) that hasn't reached ActivityWatch yet: it sleeps,
then re-queries. But with a `cache_range` active (batch/diff mode, and rolling
sync per main.py), get_events() serves a bucket from `_events_cache` once
populated and never refetches it - so every retry re-reads the same stale
snapshot taken before the sub-event arrived, silently defeating the retry.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from aw_core.models import Event

from aw_export_timewarrior.aw_client import EventFetcher


def test_retry_evicts_cache_and_sees_freshly_arrived_event() -> None:
    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    window_event = {
        "timestamp": t0,
        "duration": timedelta(seconds=5),
        "data": {"app": "firefox"},
    }
    browser_bucket = "aw-watcher-web_test"

    call_count = {"n": 0}

    def fake_get_events(bucket_id: str, start=None, end=None) -> list[Event]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First fetch: the browser sub-event hasn't reached AW yet.
            return []
        # Second fetch (after cache eviction on retry): the event has arrived.
        return [Event(timestamp=t0, duration=timedelta(seconds=5), data={"url": "example.com"})]

    mock_aw = MagicMock()
    mock_aw.get_buckets.return_value = {
        browser_bucket: {"client": "aw-watcher-web", "last_updated": None}
    }
    mock_aw.get_events.side_effect = fake_get_events

    with patch("aw_export_timewarrior.aw_client.ActivityWatchClient", return_value=mock_aw):
        fetcher = EventFetcher(
            test_data=None,
            cache_range=(t0 - timedelta(minutes=10), t0 + timedelta(minutes=10)),
        )

        with (
            patch("time.sleep"),
            patch("aw_export_timewarrior.aw_client.time", return_value=t0.timestamp()),
        ):
            result = fetcher.get_corresponding_event(window_event, browser_bucket, retry=2)

    assert call_count["n"] >= 2, "Expected the retry to trigger a second, non-cached fetch to AW"
    assert result is not None
    assert result["data"]["url"] == "example.com"
