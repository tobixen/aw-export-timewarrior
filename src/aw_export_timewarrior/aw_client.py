"""ActivityWatch event fetching and bucket management.

This module isolates all ActivityWatch data access into a single component,
making it easy to test and maintain. Part of the Exporter refactoring plan.
"""

import bisect
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from time import time
from typing import Any

from .utils import normalize_duration, normalize_timestamp

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

# How far back get_corresponding_event's fallback_to_recent lookup searches for
# a nearby sub-event (e.g. tmux, where state persists between recorded
# events). main.py's cache-range buffer is sized off this constant, since a
# cache window shorter than this lookback would make the fallback a no-op.
FALLBACK_TO_RECENT_LOOKBACK = timedelta(minutes=10)

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
        cache_range: tuple[datetime, datetime] | None = None,
    ) -> None:
        """Initialize event fetcher.

        Args:
            test_data: Optional test data dict (avoids AW connection)
            client_name: ActivityWatch client name
            log_callback: Optional callback for logging (signature: log(msg, event=None))
            cache_range: If set, events for each bucket are fetched once from AW for this
                full time range and cached in memory. Subsequent get_events() calls within
                this range are served from the cache, avoiding repeated HTTP requests.
                Use this for batch/historical processing when start and end times are fixed.
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

        # Event cache for batch processing: bucket_id -> (prepared, prefix_max_end)
        # from _prepare_cached_events(). Populated lazily on first get_events()
        # call per bucket.
        self._cache_range = cache_range
        self._events_cache: dict[str, tuple[list[tuple], list[datetime]]] = (
            {} if cache_range else {}
        )

        self._init_bucket_mappings()

    def reset_cache(self, new_range: tuple[datetime, datetime] | None = None) -> None:
        """Clear the event cache and optionally set a new cache range.

        Use this to invalidate cached data (e.g. after a sleep cycle in rolling
        sync mode) and optionally activate a fresh cache window.  After calling
        with ``new_range=None`` the fetcher behaves as if ``cache_range`` was
        never supplied: every ``get_events()`` call goes directly to AW.

        Args:
            new_range: Optional new (start, end) cache window.  If None, caching
                is disabled until ``reset_cache`` is called again with a range.
        """
        self._events_cache.clear()
        self._cache_range = new_range

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
            if self._cache_range is not None:
                cache_start, cache_end = self._cache_range
                if bucket_id not in self._events_cache:
                    # Fetch the full cache range once and store
                    logger.debug(
                        "Cache miss for bucket %s, fetching [%s, %s]",
                        bucket_id,
                        cache_start,
                        cache_end,
                    )
                    raw_events = self.aw.get_events(bucket_id, start=cache_start, end=cache_end)
                    self._events_cache[bucket_id] = self._prepare_cached_events(raw_events)
                return self._filter_events_in_range(self._events_cache[bucket_id], start, end)
            return self.aw.get_events(bucket_id, start=start, end=end)
        else:
            # Test data path
            return self._get_events_from_test_data(bucket_id, start, end)

    def _prepare_cached_events(self, events: list) -> tuple[list[tuple], list[datetime]]:
        """Normalize timestamps once and sort by start, for efficient repeated filtering.

        A cached bucket is filtered once per get_events() call within its range
        (potentially O(N events) times over a batch run). Precomputing (start,
        end) here instead of re-parsing ISO timestamps on every
        _filter_events_in_range call, and sorting so that call can bisect
        straight to the relevant slice, turns each filter from an O(bucket
        size) rescan into O(log bucket size + matches).

        Also builds a running maximum of `end` in start-sorted order. Since
        events are sorted by start (not end), a lower bound can't just bisect
        on start - an early event can have a long duration and still overlap
        a much later window. But the prefix-max IS monotonic: if the maximum
        end seen up to index i is still before `start`, then every event up
        to i has ended before `start` too, giving a valid bisectable lower
        bound (see _filter_events_in_range).
        """
        prepared = []
        prefix_max_end = []
        running_max_end = None
        for event in events:
            event_start = normalize_timestamp(event["timestamp"])
            event_end = event_start + normalize_duration(event["duration"])
            prepared.append((event_start, event_end, event))

        prepared.sort(key=lambda item: item[0])

        for _event_start, event_end, _event in prepared:
            running_max_end = (
                event_end if running_max_end is None else max(running_max_end, event_end)
            )
            prefix_max_end.append(running_max_end)

        return prepared, prefix_max_end

    def _filter_events_in_range(
        self,
        cached_bucket: tuple[list[tuple], list[datetime]],
        start: datetime | None,
        end: datetime | None,
    ) -> list:
        """Filter cache-prepared (start, end, event) tuples to those overlapping [start, end].

        Matches the semantics of _get_events_from_test_data(): includes events where
        event_end >= start AND event_start <= end (i.e. any overlap with the window).

        cached_bucket is the (prepared, prefix_max_end) pair from
        _prepare_cached_events. `prepared` is sorted by start, so bisecting to
        the last entry whose start <= end bounds the upper end of the scan.
        `prefix_max_end` is non-decreasing, so bisecting it for the first
        entry >= start bounds the lower end - narrowing the scan to a genuine
        [lo, hi) slice instead of walking from the start of the bucket.
        """
        prepared_events, prefix_max_end = cached_bucket

        if end is not None:
            hi = bisect.bisect_right(prepared_events, end, key=lambda item: item[0])
        else:
            hi = len(prepared_events)

        lo = bisect.bisect_left(prefix_max_end, start) if start is not None else 0

        result = []
        for i in range(lo, hi):
            _event_start, event_end, event = prepared_events[i]
            if start and event_end < start:
                continue
            result.append(event)
        return result

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
        lookahead_buffer_seconds: float | None = None,
        candidate_filter: Callable[[dict], bool] | None = None,
        candidate_reach: timedelta | None = None,
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
            lookahead_buffer_seconds: Override the end-bound widening used by the
                "wider window" fallback below (default EVENT_MATCHING_BUFFER_SECONDS
                when None). Some watchers (e.g. emacs, which pulses on a timer
                instead of on buffer switch) can start their event well after the
                window event they belong to.
            candidate_filter: Predicate deciding whether a sub-event may be
                adopted. Applied to the speculative matches only -- the widened
                window, the fallback and the bracketing search below -- never to
                a sub-event that genuinely overlaps the window event. Those match
                that are merely near in time, so without a content check (for
                emacs: the sub-event's file basename against the buffer named in
                the window title) they readily adopt a same-named file from
                another project.
            candidate_reach: With candidate_filter, how far before and after the
                window event to look for a bracketing sub-event when the widened
                window found nothing. Only the events immediately bracketing the
                window event are eligible, so this can reach much further than
                the widened window without guessing wildly: it answers "the
                watcher last reported this file and then went silent", which is
                what a watcher pulsing on activity does while a buffer is only
                being read.

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
                # Evict this bucket from the cache before retrying: with cache_range
                # active, get_events() would otherwise keep serving the same stale
                # snapshot taken before this event's data reached AW, making the
                # sleep-and-retry above a no-op.
                if self._cache_range is not None:
                    self._events_cache.pop(bucket_id, None)
                return self.get_corresponding_event(
                    window_event,
                    bucket_id,
                    ignorable=ignorable,
                    retry=retry,
                    fallback_to_recent=fallback_to_recent,
                    lookahead_buffer_seconds=lookahead_buffer_seconds,
                    candidate_filter=candidate_filter,
                    candidate_reach=candidate_reach,
                )

        # If still nothing found, try a wider window to account for timing differences
        if not ret and not ignorable:
            end_buffer = (
                EVENT_MATCHING_BUFFER_SECONDS
                if lookahead_buffer_seconds is None
                else lookahead_buffer_seconds
            )
            ret = self.get_events(
                bucket_id,
                start=window_event["timestamp"] - timedelta(seconds=EVENT_MATCHING_BUFFER_SECONDS),
                end=window_event["timestamp"]
                + window_event["duration"]
                + timedelta(seconds=end_buffer),
            )
            if candidate_filter is not None:
                ret = [event for event in ret if candidate_filter(event)]

        # Fallback: find nearest event around the window event
        # Useful for tmux where state persists between recorded events,
        # and where the tmux event may start slightly after the window event
        # (e.g., 0-second window events just before tmux activity begins)
        if not ret and fallback_to_recent:
            lookback = FALLBACK_TO_RECENT_LOOKBACK
            lookahead = timedelta(seconds=EVENT_MATCHING_BUFFER_SECONDS)
            nearby_events = self.get_events(
                bucket_id,
                start=window_event["timestamp"] - lookback,
                end=window_event["timestamp"] + lookahead,
            )
            if candidate_filter is not None:
                nearby_events = [event for event in nearby_events if candidate_filter(event)]
            if nearby_events:
                # Prefer the nearest event by timestamp proximity
                nearby_events.sort(
                    key=lambda x: abs((x["timestamp"] - window_event["timestamp"]).total_seconds())
                )
                ret = [nearby_events[0]]

        # Guarded fallback: the sub-event watcher may stay silent for minutes
        # at a time (activity-watch-mode pulses on activity, so reading a
        # buffer produces nothing). Reach further out, but only for the events
        # immediately bracketing the window event and only if candidate_filter
        # vouches for them -- an intervening event for another file means the
        # editor did switch buffers, so a match beyond it is no evidence.
        if not ret and candidate_filter is not None and candidate_reach is not None:
            window_end = window_event["timestamp"] + window_event["duration"]
            nearby_events = sorted(
                self.get_events(
                    bucket_id,
                    start=window_event["timestamp"] - candidate_reach,
                    end=window_end + candidate_reach,
                ),
                key=lambda x: x["timestamp"],
            )
            before = [x for x in nearby_events if x["timestamp"] <= window_event["timestamp"]]
            after = [x for x in nearby_events if x["timestamp"] >= window_end]
            bracketing = ([before[-1]] if before else []) + ([after[0]] if after else [])
            bracketing = [x for x in bracketing if candidate_filter(x)]
            if bracketing:
                bracketing.sort(
                    key=lambda x: abs((x["timestamp"] - window_event["timestamp"]).total_seconds())
                )
                ret = [bracketing[0]]

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

    def get_afk_prompt_bucket(self) -> str | None:
        """Get AFK prompt watcher bucket ID.

        Checks for the new aw-watcher-afk-prompt first, then falls back to
        the legacy aw-watcher-ask-away for backward compatibility.

        Returns:
            Bucket ID for aw-watcher-afk-prompt or aw-watcher-ask-away,
            or None if neither is available
        """
        # Check for new bucket name first (aw-watcher-afk-prompt)
        if self.has_bucket_client("aw-watcher-afk-prompt"):
            return self.bucket_by_client["aw-watcher-afk-prompt"][0]
        # Fall back to legacy bucket name (aw-watcher-ask-away)
        if self.has_bucket_client("aw-watcher-ask-away"):
            return self.bucket_by_client["aw-watcher-ask-away"][0]
        return None

    # Legacy alias for backward compatibility
    get_ask_away_bucket = get_afk_prompt_bucket

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
