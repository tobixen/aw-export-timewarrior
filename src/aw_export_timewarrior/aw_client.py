"""ActivityWatch event fetching and bucket management.

This module isolates all ActivityWatch data access into a single component,
making it easy to test and maintain. Part of the Exporter refactoring plan.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from time import time
from typing import Any

# Import at module level for easier mocking in tests
try:
    from aw_client import ActivityWatchClient
except ImportError:
    # Allow tests to run without aw_client installed
    ActivityWatchClient = None

logger = logging.getLogger(__name__)

# Constants from main.py - TODO: move to config
AW_WARN_THRESHOLD = 300.0  # Warn if bucket data older than this (seconds)
SLEEP_INTERVAL = 30.0  # Sleep between retries
IGNORE_INTERVAL = 3.0  # Ignore events shorter than this

# Event matching buffer: time window (in seconds) to expand search when looking
# for corresponding sub-events (browser, editor). Accounts for clock skew and
# timing differences between different watchers.
EVENT_MATCHING_BUFFER_SECONDS = 15

# Logging threshold: minimum event duration (as multiple of IGNORE_INTERVAL)
# before we log a warning about missing corresponding events.
# 4x IGNORE_INTERVAL = 12 seconds by default.
MIN_DURATION_FOR_MISSING_EVENT_WARNING = 4


class EventFetcher:
    """Fetches events from ActivityWatch (or test data).

    Responsible for:
    - Connecting to ActivityWatch
    - Managing buckets (window, AFK, browser, editor)
    - Fetching events with time ranges
    - Finding corresponding sub-events (browser URLs, editor files)
    - Test data loading and filtering
    """

    def __init__(
        self,
        test_data: dict[str, Any] | None = None,
        client_name: str = "aw-export",
        log_callback: Callable | None = None,
    ) -> None:
        """Initialize event fetcher.

        Args:
            test_data: Optional test data dict (avoids AW connection)
            client_name: ActivityWatch client name
            log_callback: Optional callback for logging (signature: log(msg, event=None))
        """
        self.log_callback = log_callback or (lambda msg, **kwargs: logger.info(msg))

        if test_data:
            self.buckets = test_data.get("buckets", {})
            self.test_data = test_data
            self.aw = None
        else:
            if ActivityWatchClient is None:
                raise ImportError("aw_client not installed - cannot create ActivityWatch client")
            self.aw = ActivityWatchClient(client_name=client_name)
            self.buckets = self.aw.get_buckets()
            self.test_data = None

        self._init_bucket_mappings()

    def _init_bucket_mappings(self) -> None:
        """Create lookup structures for bucket access."""
        self.bucket_by_client: dict[str, list[str]] = defaultdict(list)
        self.bucket_short: dict[str, dict] = {}

        for bucket_id, bucket in self.buckets.items():
            # Parse last_updated timestamp
            lu = bucket.get("last_updated")
            if lu:
                bucket["last_updated_dt"] = datetime.fromisoformat(lu)
            else:
                bucket["last_updated_dt"] = None

            # Index by client type
            client = bucket["client"]
            self.bucket_by_client[client].append(bucket_id)

            # Short name lookup (e.g., "aw-watcher-window" -> bucket)
            bucket_short = bucket_id[: bucket_id.find("_")] if "_" in bucket_id else bucket_id
            # Don't assert - just log warning if duplicate (allows flexibility)
            if bucket_short in self.bucket_short:
                logger.warning(f"Duplicate bucket short name: {bucket_short}")
            self.bucket_short[bucket_short] = bucket
            # Also store the full bucket_id for convenience
            self.bucket_short[bucket_short]["id"] = bucket_id

    def get_events(
        self, bucket_id: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[dict]:
        """Fetch events from a bucket.

        Args:
            bucket_id: Bucket identifier
            start: Start time (inclusive)
            end: End time (exclusive)

        Returns:
            List of events (dicts with timestamp, duration, data)
        """
        if self.aw:
            return self.aw.get_events(bucket_id, start=start, end=end)
        else:
            # Test data path
            return self._get_events_from_test_data(bucket_id, start, end)

    def _get_events_from_test_data(
        self, bucket_id: str, start: datetime | None, end: datetime | None
    ) -> list[dict]:
        """Get events from test data with time filtering.

        This is extracted from the original Exporter.get_events() method.
        """
        events = self.test_data.get("events", {}).get(bucket_id, [])

        # Convert dict events to Event objects supporting both dict and attribute access
        class Event(dict):
            def _convert_value(self, key: str, val: Any) -> Any:
                """Convert values for consistency between dict and attribute access."""
                # Convert timestamp strings to datetime
                if key == "timestamp" and isinstance(val, str):
                    return datetime.fromisoformat(val)
                # Convert duration to timedelta
                if key == "duration" and isinstance(val, int | float):
                    return timedelta(seconds=val)
                return val

            def __getitem__(self, key: str) -> Any:
                val = super().__getitem__(key)
                return self._convert_value(key, val)

            def __getattr__(self, key: str) -> Any:
                if key.startswith("_"):
                    raise AttributeError(f"Event has no attribute '{key}'")
                if key in self:
                    return self[key]  # Use __getitem__ for conversion
                raise AttributeError(f"Event has no attribute '{key}'")

        event_objs = [Event(e) for e in events]

        # Filter by time range if specified
        if start or end:
            filtered = []
            for event in event_objs:
                event_time = event.timestamp
                event_end = event_time + event.duration
                if start and event_end < start:
                    continue
                if end and event_time > end:
                    continue
                filtered.append(event)
            return filtered
        return event_objs

    def get_corresponding_event(
        self,
        window_event: dict,
        bucket_id: str,
        ignorable: bool = False,
        retry: int = 6,
        fallback_to_recent: bool = False,
    ) -> dict | None:
        """Find corresponding sub-event (browser URL, editor file, tmux).

        This matches specialized watcher events (browser, editor, tmux) to window events.
        Includes retry logic for events that may not have propagated to AW yet.

        Args:
            window_event: Main window event
            bucket_id: Sub-event bucket (browser/editor/tmux)
            ignorable: Whether to ignore timing mismatches and missing events
            retry: Number of retry attempts if event not found
            fallback_to_recent: If True and no overlapping event found, use the most
                recent event before the window event. Useful for tmux where state persists.

        Returns:
            Corresponding event or None
        """
        # Try to find events in a 1-second window around the window event
        ret = self.get_events(
            bucket_id,
            start=window_event["timestamp"] - timedelta(seconds=1),
            end=window_event["timestamp"] + window_event["duration"],
        )

        # If nothing found and this is a recent event, try waiting
        if not ret and not ignorable and retry:
            event_end = window_event["timestamp"] + window_event["duration"]
            # Only retry if event is recent (within SLEEP_INTERVAL*3 of current time)
            if time() - SLEEP_INTERVAL * 3 < event_end.timestamp():
                # Event might not have reached ActivityWatch yet
                self.log_callback(
                    f"Event details for {window_event} not in yet, attempting to sleep for a while",
                    event=window_event,
                )
                from time import sleep

                sleep(SLEEP_INTERVAL * 3 / retry + 0.2)
                retry -= 1
                return self.get_corresponding_event(window_event, bucket_id, ignorable, retry)

        # If still nothing found, try a wider window to account for timing differences
        if not ret and not ignorable:
            ret = self.get_events(
                bucket_id,
                start=window_event["timestamp"] - timedelta(seconds=EVENT_MATCHING_BUFFER_SECONDS),
                end=window_event["timestamp"]
                + window_event["duration"]
                + timedelta(seconds=EVENT_MATCHING_BUFFER_SECONDS),
            )

        # Fallback: use most recent event before the window event
        # Useful for tmux where state persists between recorded events
        if not ret and fallback_to_recent:
            # Look for events in a reasonable window before the window event
            # Use 10 minutes as the max lookback - state older than that is likely stale
            lookback = timedelta(minutes=10)
            recent_events = self.get_events(
                bucket_id,
                start=window_event["timestamp"] - lookback,
                end=window_event["timestamp"],
            )
            if recent_events:
                # Sort by timestamp (most recent first) and return the most recent
                recent_events.sort(key=lambda x: x["timestamp"], reverse=True)
                ret = [recent_events[0]]

        # Log if nothing found (unless ignorable or very short event)
        if not ret:
            if not ignorable and window_event["duration"] >= timedelta(
                seconds=IGNORE_INTERVAL * MIN_DURATION_FOR_MISSING_EVENT_WARNING
            ):
                self.log_callback(
                    f"No corresponding {bucket_id} found. Window title: {window_event['data']['title']}. "
                    f"If you see this often, you should verify that the relevant watchers are active and running.",
                    event=window_event,
                )
            return None

        # If multiple events found, filter out short ones and pick longest
        if len(ret) > 1:
            ret2 = [x for x in ret if x["duration"] > timedelta(seconds=IGNORE_INTERVAL)]
            if ret2:
                ret = ret2
            # Sort by duration (longest first)
            ret.sort(key=lambda x: -x["duration"])

        return ret[0]

    def check_bucket_freshness(self, warn_threshold: float = AW_WARN_THRESHOLD) -> None:
        """Check if buckets have recent data.

        Args:
            warn_threshold: Warn if bucket older than this (seconds)
        """
        for bucketclient in ("aw-watcher-window", "aw-watcher-afk"):
            if bucketclient not in self.bucket_by_client:
                logger.warning(f"Required bucket client not found: {bucketclient}")
                continue

            for bucket_id in self.bucket_by_client[bucketclient]:
                bucket = self.buckets[bucket_id]
                last_updated_dt = bucket.get("last_updated_dt")

                if not last_updated_dt or time() - last_updated_dt.timestamp() > warn_threshold:
                    logger.warning(f"Bucket {bucket['id']} seems not to have recent data!")

    def get_window_bucket(self) -> str:
        """Get window watcher bucket ID.

        Returns:
            Bucket ID for aw-watcher-window

        Raises:
            KeyError: If no window bucket found
        """
        return self.bucket_by_client["aw-watcher-window"][0]

    def get_afk_bucket(self) -> str:
        """Get AFK watcher bucket ID.

        Returns:
            Bucket ID for aw-watcher-afk

        Raises:
            KeyError: If no AFK bucket found
        """
        return self.bucket_by_client["aw-watcher-afk"][0]

    def get_lid_bucket(self) -> str | None:
        """Get lid watcher bucket ID.

        Returns:
            Bucket ID for aw-watcher-lid, or None if not available
        """
        if self.has_bucket_client("aw-watcher-lid"):
            return self.bucket_by_client["aw-watcher-lid"][0]
        return None

    def get_ask_away_bucket(self) -> str | None:
        """Get ask-away watcher bucket ID.

        Returns:
            Bucket ID for aw-watcher-ask-away, or None if not available
        """
        if self.has_bucket_client("aw-watcher-ask-away"):
            return self.bucket_by_client["aw-watcher-ask-away"][0]
        return None

    def get_tmux_bucket(self) -> str | None:
        """Get tmux watcher bucket ID.

        Returns:
            Bucket ID for aw-watcher-tmux, or None if not available
        """
        if self.has_bucket_client("aw-watcher-tmux"):
            return self.bucket_by_client["aw-watcher-tmux"][0]
        return None

    def has_bucket_client(self, client_type: str) -> bool:
        """Check if a bucket client type exists.

        Args:
            client_type: Client type (e.g., 'aw-watcher-window')

        Returns:
            True if bucket exists
        """
        return client_type in self.bucket_by_client and len(self.bucket_by_client[client_type]) > 0
