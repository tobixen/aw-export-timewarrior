"""Event pipeline for processing ActivityWatch events.

This module handles the fetching, filtering, merging, and preparation
of events from ActivityWatch before they are processed for tag extraction.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .utils import get_event_range, normalize_duration, normalize_timestamp

logger = logging.getLogger(__name__)


@dataclass
class EventPipelineConfig:
    """Configuration for the event pipeline.

    Attributes:
        enable_afk_gap_workaround: Fill gaps between AFK events with synthetic AFK
        enable_lid_events: Process lid events from aw-watcher-lid
        min_lid_duration: Minimum lid event duration to process (seconds)
        min_recording_interval: Minimum interval for synthetic AFK events (seconds)
        max_mixed_interval: Filter out short AFK events below this duration (seconds)
    """

    enable_afk_gap_workaround: bool = True
    enable_lid_events: bool = True
    min_lid_duration: float = 10.0
    min_recording_interval: float = 90.0
    max_mixed_interval: float = 240.0

    @classmethod
    def from_config(cls, config: dict) -> "EventPipelineConfig":
        """Create pipeline config from application config dict."""
        return cls(
            enable_afk_gap_workaround=config.get("enable_afk_gap_workaround", True),
            enable_lid_events=config.get("enable_lid_events", True),
            min_lid_duration=config.get("min_lid_duration", 10.0),
            min_recording_interval=config.get("tuning", {}).get("min_recording_interval", 90.0),
            max_mixed_interval=config.get("tuning", {}).get("max_mixed_interval", 240.0),
        )


@dataclass
class EventPipeline:
    """Processes events from ActivityWatch through various pipeline stages.

    The pipeline handles:
    - Fetching events from AFK, window, and lid watchers
    - Applying AFK gap workaround for Wayland issues
    - Merging lid events with AFK events
    - Splitting window events at AFK boundaries
    - Filtering and sorting events

    Attributes:
        event_fetcher: EventFetcher instance for accessing ActivityWatch data
        pipeline_config: Configuration for pipeline behavior
        last_tick: Start time for event queries (usually last processed time)
        end_time: End time for event queries (None for live monitoring)
        start_time: Start time for batch processing (None for live monitoring)
    """

    event_fetcher: object  # EventFetcher
    pipeline_config: EventPipelineConfig
    last_tick: datetime | None = None
    end_time: datetime | None = None
    start_time: datetime | None = None

    # Internal state
    _ask_away_events: list = field(default_factory=list, init=False, repr=False)

    def fetch_and_prepare_events(self) -> tuple[list, dict | None]:
        """Fetch, filter, merge, and sort events from ActivityWatch.

        Returns:
            Tuple of (completed_events, current_event):
            - completed_events: List of finished events to process
            - current_event: The ongoing event (or None)
        """
        afk_id = self.event_fetcher.bucket_by_client["aw-watcher-afk"][0]
        window_id = self.event_fetcher.bucket_by_client["aw-watcher-window"][0]

        # Fetch AFK events
        afk_events = self.event_fetcher.get_events(afk_id, start=self.last_tick, end=self.end_time)

        # Apply workaround if enabled
        if self.pipeline_config.enable_afk_gap_workaround:
            afk_events = self._apply_afk_gap_workaround(afk_events)

        # Filter out short AFK events
        afk_events = [
            x
            for x in afk_events
            if x["duration"] > timedelta(seconds=self.pipeline_config.max_mixed_interval)
        ]

        # Fetch lid events if available and enabled
        lid_events = []
        if self.pipeline_config.enable_lid_events:
            lid_bucket = self.event_fetcher.get_lid_bucket()
            if lid_bucket:
                lid_events = self.event_fetcher.get_events(
                    lid_bucket, start=self.last_tick, end=self.end_time
                )

                # Filter out short lid cycles (except boot gaps)
                lid_events = [
                    e
                    for e in lid_events
                    if e["duration"] > timedelta(seconds=self.pipeline_config.min_lid_duration)
                    or e["data"].get("boot_gap", False)
                ]

                if lid_events:
                    logger.info(f"Fetched {len(lid_events)} lid events (after filtering)")

        # Merge lid events with AFK events
        merged_afk_events = self._merge_afk_and_lid_events(afk_events, lid_events)

        # Fetch ask-away events if available
        ask_away_bucket = self.event_fetcher.get_ask_away_bucket()
        if ask_away_bucket:
            ask_away_events = self.event_fetcher.get_events(
                ask_away_bucket, start=self.last_tick, end=self.end_time
            )
            if ask_away_events:
                logger.info(f"Fetched {len(ask_away_events)} ask-away events")
                self._ask_away_events = ask_away_events
            else:
                self._ask_away_events = []
        else:
            self._ask_away_events = []

        # Fetch window events and merge with AFK events
        afk_window_events = (
            self.event_fetcher.get_events(window_id, start=self.last_tick, end=self.end_time)
            + merged_afk_events
        )

        # Sort by timestamp
        afk_window_events.sort(key=lambda e: normalize_timestamp(e["timestamp"]))

        # Split window events that overlap with AFK periods
        afk_window_events = self._split_window_events_by_afk(afk_window_events, merged_afk_events)

        # Filter out events that end before or at last_tick
        if self.last_tick:
            afk_window_events = [
                e for e in afk_window_events if get_event_range(e)[1] > self.last_tick
            ]

        if len(afk_window_events) == 0:
            return [], None

        # Historical mode vs live monitoring
        if self.end_time:
            return afk_window_events, None
        else:
            current_event = afk_window_events[-1] if len(afk_window_events) > 0 else None
            completed_events = afk_window_events[:-1] if len(afk_window_events) > 1 else []
            return completed_events, current_event

    def get_ask_away_events(self) -> list:
        """Get the ask-away events fetched during the last pipeline run."""
        return self._ask_away_events

    def _apply_afk_gap_workaround(self, afk_events: list) -> list:
        """Apply workaround for aw-watcher-window-wayland issue #41.

        Issue: https://github.com/ActivityWatch/aw-watcher-window-wayland/issues/41
        Problem: AFK watcher on Wayland may not report AFK events, leaving gaps
                 between "not-afk" events that should be treated as AFK periods.

        Args:
            afk_events: List of AFK events from ActivityWatch

        Returns:
            Modified list of AFK events with synthetic gaps filled in
        """
        if len(afk_events) <= 1:
            return afk_events

        # Sort events by timestamp to find gaps
        sorted_events = sorted(afk_events, key=lambda x: x["timestamp"])

        # Find gaps between consecutive events and fill with synthetic AFK events
        synthetic_afk_events = []
        for i in range(1, len(sorted_events)):
            prev_event = sorted_events[i - 1]
            curr_event = sorted_events[i]

            # Calculate gap between end of previous event and start of current
            gap_start = prev_event["timestamp"] + prev_event["duration"]
            gap_end = curr_event["timestamp"]
            gap_duration = gap_end - gap_start

            # Only create synthetic AFK event if gap is significant
            if gap_duration.total_seconds() >= self.pipeline_config.min_recording_interval:
                synthetic_afk_events.append(
                    {"data": {"status": "afk"}, "timestamp": gap_start, "duration": gap_duration}
                )

        # Combine original and synthetic events
        return afk_events + synthetic_afk_events

    def _merge_afk_and_lid_events(self, afk_events: list, lid_events: list) -> list:
        """Merge lid events with AFK events, giving lid events priority.

        Strategy:
        - Lid closed -> ALWAYS system-afk (overrides user activity detection)
        - Lid open during AFK -> keep AFK state from aw-watcher-afk
        - Lid events are converted to AFK-compatible format

        Args:
            afk_events: Events from aw-watcher-afk
            lid_events: Events from aw-watcher-lid

        Returns:
            Merged list of AFK events (lid events converted to AFK format)
        """
        if not lid_events:
            return afk_events

        # Convert lid events to AFK-compatible format
        converted_lid_events = []
        for event in lid_events:
            data = event["data"]

            # Determine AFK status based on lid/suspend/boot state
            if (
                data.get("lid_state") == "closed"
                or data.get("suspend_state") == "suspended"
                or data.get("boot_gap", False)
            ):
                status = "afk"
            else:
                status = "not-afk"

            converted_event = {
                "timestamp": event["timestamp"],
                "duration": event["duration"],
                "data": {
                    "status": status,
                    "source": "lid",
                    "original_data": data,
                },
            }
            converted_lid_events.append(converted_event)

        # Resolve conflicts: lid events override conflicting AFK events
        resolved_afk_events = self._resolve_event_conflicts(afk_events, converted_lid_events)

        # Merge and sort
        merged = resolved_afk_events + converted_lid_events
        merged.sort(key=lambda e: normalize_timestamp(e["timestamp"]))

        return merged

    def _resolve_event_conflicts(self, afk_events: list, priority_events: list) -> list:
        """Remove or trim AFK events that conflict with higher-priority lid events.

        Only removes/trims AFK events when the lid event indicates AFK (closed/suspended)
        and the AFK event indicates activity (not-afk).

        Args:
            afk_events: Events from aw-watcher-afk
            priority_events: Events from lid watcher (in AFK format)

        Returns:
            List of AFK events with conflicts resolved
        """
        if not priority_events:
            return afk_events

        def events_overlap(
            e1_start: datetime, e1_end: datetime, e2_start: datetime, e2_end: datetime
        ) -> bool:
            """Check if two time ranges overlap."""
            return e1_start < e2_end and e2_start < e1_end

        def events_conflict(afk_event: dict, priority_event: dict) -> bool:
            """Check if two events conflict (overlap and different status).

            Only consider it a conflict when:
            1. They have different status, AND
            2. The priority event indicates AFK (lid closed/suspended)
            """
            afk_status = afk_event["data"]["status"]
            priority_status = priority_event["data"]["status"]

            # Only conflict if priority event indicates AFK
            if priority_status != "afk":
                return False

            return afk_status != priority_status

        result = []
        for afk_event in afk_events:
            afk_start = normalize_timestamp(afk_event["timestamp"])
            afk_end = afk_start + normalize_duration(afk_event["duration"])

            conflicting = False
            for priority_event in priority_events:
                priority_start = normalize_timestamp(priority_event["timestamp"])
                priority_end = priority_start + normalize_duration(priority_event["duration"])

                if events_overlap(
                    afk_start, afk_end, priority_start, priority_end
                ) and events_conflict(afk_event, priority_event):
                    conflicting = True
                    break

            if not conflicting:
                result.append(afk_event)

        return result

    def _split_window_events_by_afk(self, events: list[dict], afk_events: list[dict]) -> list[dict]:
        """Split window events when they overlap with AFK periods.

        When a window event spans across an AFK period, split it into:
        1. Part before AFK (original tags)
        2. AFK period (afk tag)
        3. Part after AFK (original tags)

        Args:
            events: Combined list of window and AFK events
            afk_events: List of AFK events to check for overlaps

        Returns:
            List of events with window events split at AFK boundaries
        """
        if not afk_events:
            return events

        # Separate window and AFK events
        window_events = [e for e in events if "status" not in e["data"]]
        status_events = [e for e in events if "status" in e["data"]]

        result = []

        for window_event in window_events:
            window_start = normalize_timestamp(window_event["timestamp"])
            window_end = window_start + normalize_duration(window_event["duration"])

            # Find overlapping AFK events
            overlapping_afk = [
                afk
                for afk in afk_events
                if afk["data"].get("status") == "afk"
                and normalize_timestamp(afk["timestamp"]) < window_end
                and (normalize_timestamp(afk["timestamp"]) + normalize_duration(afk["duration"]))
                > window_start
            ]

            if not overlapping_afk:
                result.append(window_event)
                continue

            # Sort AFK events by timestamp
            overlapping_afk.sort(key=lambda x: normalize_timestamp(x["timestamp"]))

            # Split window event at AFK boundaries
            current_time = window_start
            for afk_event in overlapping_afk:
                afk_start = normalize_timestamp(afk_event["timestamp"])
                afk_end = afk_start + normalize_duration(afk_event["duration"])

                # Add window portion before AFK (if any)
                if current_time < afk_start < window_end:
                    duration_td = afk_start - current_time
                    result.append(
                        {
                            **window_event,
                            "timestamp": current_time,
                            "duration": duration_td,
                        }
                    )

                # Move current_time to after this AFK period
                current_time = max(current_time, afk_end)

            # Add remaining window portion after all AFK periods
            if current_time < window_end:
                duration_td = window_end - current_time
                result.append(
                    {
                        **window_event,
                        "timestamp": current_time,
                        "duration": duration_td,
                    }
                )

        # Add all status events back and re-sort
        result.extend(status_events)
        result.sort(key=lambda x: normalize_timestamp(x["timestamp"]))

        return result
