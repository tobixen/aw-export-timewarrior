import json
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from time import sleep

from .aw_client import EventFetcher
from .config import config
from .output import user_output
from .state import AfkState, StateManager
from .tag_extractor import ExclusiveGroupError, TagExtractor
from .timew_tracker import TimewTracker
from .utils import get_event_range, normalize_duration, normalize_timestamp, ts2strtime

# Configure structured logging
logger = logging.getLogger(__name__)

# Magic number constants with explanations
# Minimum ratio of known events to total tracked time.
# If less than this ratio is accounted for, tag the interval as UNKNOWN.
# For example, 0.3 means at least 30% of tracked time should be known events.
MIN_KNOWN_ACTIVITY_RATIO = 0.3

# Debug threshold: trigger breakpoint if skipping an event longer than this duration.
# This helps catch unexpected behavior where significant events are being skipped.
DEBUG_SKIP_THRESHOLD_SECONDS = 30


def parse_message_tags(message: str) -> set[str]:
    """Parse a message string into tags, respecting quoted strings.

    Space-delimited words become separate tags, but quoted strings
    are treated as single tags. Preserves original casing.

    Examples:
        "food 4FAMILY" -> {"food", "4FAMILY"}
        '"my project" coding' -> {"my project", "coding"}
        "4BREAK 'long tag'" -> {"4BREAK", "long tag"}

    Args:
        message: The message string to parse

    Returns:
        Set of tags extracted from the message
    """
    try:
        # shlex.split handles both single and double quotes
        words = shlex.split(message.strip())
        return {word for word in words if word}
    except ValueError:
        # If shlex fails (unmatched quotes), fall back to simple split
        return {word for word in message.strip().split() if word}


class EventMatchResult(Enum):
    """Result of matching an event to tags."""

    IGNORED = auto()  # Event too short to process
    NO_MATCH = auto()  # Event processed but no tags found
    MATCHED = auto()  # Tags found


@dataclass
class TagResult:
    """Result of tag extraction from an event.

    Attributes:
        result: The match result (IGNORED, NO_MATCH, or MATCHED)
        tags: Set of extracted tags (empty if no match)
        reason: Optional explanation (useful for debugging/logging)
    """

    result: EventMatchResult
    tags: set[str] = field(default_factory=set)
    reason: str = ""

    def __bool__(self) -> bool:
        """Allow boolean checks: if tag_result: ..."""
        return self.result == EventMatchResult.MATCHED


def get_tuning_param(config: dict, param_name: str, env_var: str, default: float) -> float:
    """Get a tuning parameter from config or environment variable.

    Priority order (highest to lowest):
    1. Environment variable (allows temporary override)
    2. config['tuning'][param_name] (persistent configuration)
    3. default value

    This allows users to temporarily override via env vars (e.g., for testing)
    while having persistent defaults in config.

    Args:
        config: Configuration dictionary
        param_name: Name in config['tuning'] section
        env_var: Environment variable name (e.g., 'AW2TW_SLEEP_INTERVAL')
        default: Default value if neither config nor env var is set

    Returns:
        The parameter value as float
    """
    # Environment variable takes highest priority for temporary overrides
    env_value = os.environ.get(env_var)
    if env_value:
        return float(env_value)

    # Then check config file
    if "tuning" in config and param_name in config["tuning"]:
        return float(config["tuning"][param_name])

    # Fall back to default
    return default


# Special tags that have specific meanings
SPECIAL_TAGS = {"manual", "override", "not-afk"}


def load_config(config_path):
    # Load custom config if provided
    from . import config as config_module

    if config_path:
        config_module.load_custom_config(config_path)
    return config_module.config


## We keep quite some statistics here, all the counters should be documented
## TODO: Resetting counters should be done through explicit methods in this class and
## not through arbitrary assignments in unrelated methods
@dataclass
class Exporter:
    ## State Manager - centralized state management
    _state: StateManager = field(default_factory=StateManager, init=False, repr=False)

    ## Information from timew about the current tagging (not part of StateManager)
    timew_info: dict = None

    ## Testing and debugging options
    dry_run: bool = False  # If True, don't actually modify timewarrior
    verbose: bool = False  # If True, show detailed reasoning
    show_diff: bool = False  # If True, show diffs in dry-run mode
    show_fix_commands: bool = False  # If True, show timew track commands to fix differences
    apply_fix: bool = False  # If True, execute timew track commands to fix differences
    hide_diff_report: bool = False  # If True, hide the detailed comparison report
    hide_processing_output: bool = False  # If True, hide "would execute" messages
    show_unmatched: bool = False  # If True, show events that didn't match any rules
    show_timeline: bool = False  # If True, show side-by-side timeline view in diff mode
    enable_pdb: bool = False  # If True, drop into debugger on unexpected states
    enable_assert: bool = True  # If True, assert on unexpected states
    config: dict = None  # Configuration
    config_path: str = None  # Configuration file name
    test_data: dict = None  # Optional test data instead of querying AW
    start_time: datetime = None  # Optional start time for processing window
    end_time: datetime = None  # Optional end time for processing window
    captured_commands: list | None = (
        None  # Captures timew commands when set to a list (for testing)
    )
    unmatched_events: list = field(
        default_factory=list
    )  # Tracks events that didn't match any rules
    _ask_away_messages: dict = field(
        default_factory=dict, init=False, repr=False
    )  # Maps (timestamp, duration) to ask-away messages

    # Short event accumulation tracking - prevents ignoring rapid activity in same app/rule
    # Example: flipping through photos in feh creates many <3s events, but total time is significant
    _short_event_context: tuple | None = field(
        default=None, init=False, repr=False
    )  # (app, frozenset(tags) or None)
    _short_event_first_time: datetime | None = field(
        default=None, init=False, repr=False
    )  # Timestamp of first short event in current sequence
    _short_event_accumulated: timedelta = field(
        default_factory=timedelta, init=False, repr=False
    )  # Accumulated duration of short events in current sequence

    def __post_init__(self):
        if not self.config:
            self.config = load_config(self.config_path)
        # Convert terminal_apps list to lowercase set for efficient lookups
        self.terminal_apps = {app.lower() for app in self.config.get("terminal_apps", [])}

        # When using test data, automatically set start_time and end_time from metadata if not already set
        if self.test_data:
            metadata = self.test_data.get("metadata", {})
            if not self.start_time and "start_time" in metadata:
                start_time_str = metadata["start_time"]
                self.start_time = datetime.fromisoformat(start_time_str)
            if not self.end_time and "end_time" in metadata:
                end_time_str = metadata["end_time"]
                self.end_time = datetime.fromisoformat(end_time_str)

        ## Initialize EventFetcher for all ActivityWatch data access
        client_name = "timewarrior_test_export" if self.dry_run else "timewarrior_export"
        self.event_fetcher = EventFetcher(
            test_data=self.test_data, client_name=client_name, log_callback=self.log
        )

        # Initialize TagExtractor for all tag matching logic
        # Pass lambda to support tests that change config after initialization
        # In dry_run mode, use default_retry=0 to avoid sleeping on recent events
        self.tag_extractor = TagExtractor(
            config=lambda: self.config,
            event_fetcher=self.event_fetcher,
            terminal_apps=self.terminal_apps,
            log_callback=self.log,
            default_retry=0 if self.dry_run else 6,
        )

        # Initialize TimeTracker for time tracking backend
        # Use DryRunTracker in dry-run mode to prevent actual command execution
        # DryRunTracker will still capture commands for testing
        if self.dry_run:
            from .time_tracker import DryRunTracker

            # Initialize captured_commands list for dry-run mode if not already set
            if self.captured_commands is None:
                self.captured_commands = []

            self.tracker = DryRunTracker(
                capture_commands=self.captured_commands, hide_output=self.hide_processing_output
            )
        else:
            # Pass captured_commands (None in normal operation, list in tests)
            # When None, timew output goes to terminal; when list, output is captured
            self.tracker = TimewTracker(
                grace_time=None,
                capture_commands=self.captured_commands,
                hide_output=self.hide_processing_output,
            )

        # Initialize tuning parameters from config (with env var override support)
        self.aw_warn_threshold = get_tuning_param(
            self.config, "aw_warn_threshold", "AW2TW_AW_WARN_THRESHOLD", 300.0
        )
        self.sleep_interval = get_tuning_param(
            self.config, "sleep_interval", "AW2TW_SLEEP_INTERVAL", 30.0
        )
        self.ignore_interval = get_tuning_param(
            self.config, "ignore_interval", "AW2TW_IGNORE_INTERVAL", 3.0
        )
        self.min_recording_interval = get_tuning_param(
            self.config, "min_recording_interval", "AW2TW_MIN_RECORDING_INTERVAL", 90.0
        )
        self.min_tag_recording_interval = get_tuning_param(
            self.config, "min_tag_recording_interval", "AW2TW_MIN_TAG_RECORDING_INTERVAL", 50.0
        )
        self.stickyness_factor = get_tuning_param(
            self.config, "stickyness_factor", "AW2TW_STICKYNESS_FACTOR", 0.1
        )
        self.max_mixed_interval = get_tuning_param(
            self.config, "max_mixed_interval", "AW2TW_MAX_MIXED_INTERVAL", 240.0
        )

        # Derived values
        self.min_recording_interval_adj = self.min_recording_interval * (1 + self.stickyness_factor)
        self.min_tag_recording_interval_adj = self.min_tag_recording_interval * (
            1 + self.stickyness_factor
        )

        # Only check bucket freshness when using real ActivityWatch data
        if not self.test_data:
            for bucketclient in ("aw-watcher-window", "aw-watcher-afk"):
                assert bucketclient in self.event_fetcher.bucket_by_client
            self.event_fetcher.check_bucket_freshness()

    ## TODO: perhaps better to have an _assert method
    def breakpoint(self, reason: str = "Unexpected condition"):
        self.log(f"ASSERTION FAILED: {reason}", level=logging.ERROR)
        if self.enable_pdb:
            breakpoint()
        elif self.enable_assert:
            raise AssertionError(reason)

    def apply_retag_rules(self, source_tags: set[str]) -> set[str]:
        """Apply retag rules with proper error handling for exclusive group violations.

        Wraps TagExtractor.apply_retag_rules to handle ExclusiveGroupError
        and respect enable_pdb/enable_assert settings.

        Args:
            source_tags: Set of tags to transform

        Returns:
            Transformed set of tags, or original tags if violation occurs and pdb is enabled
        """
        try:
            return self.tag_extractor.apply_retag_rules(source_tags)
        except ExclusiveGroupError as e:
            self.log(str(e), level=logging.ERROR)
            if self.enable_pdb:
                # Make exception info available for debugging
                exc = e  # noqa: F841 - available in debugger
                breakpoint()
                # After debugging, return original tags to continue
                return source_tags
            elif self.enable_assert:
                raise
            else:
                # In normal mode, re-raise to stop execution
                raise

    @property
    def state(self) -> StateManager:
        """Access to the StateManager instance."""
        return self._state

    def load_test_data(self, file_path):
        """Load test data from a JSON/YAML file."""
        from .export import load_test_data as load_file

        self.test_data = load_file(file_path)
        # Reinitialize with test data
        self.__post_init__()

    def get_captured_commands(self) -> list:
        """
        Get the list of captured timew commands.

        Returns:
            List of command lists, e.g. [['timew', 'start', 'tag1', 'tag2', '2025-01-01T10:00:00'], ...]
        """
        return self.captured_commands if self.captured_commands is not None else []

    def clear_captured_commands(self) -> None:
        """Clear the captured commands list."""
        if self.captured_commands is not None:
            self.captured_commands.clear()

    def get_suggested_intervals(self):
        """
        Extract suggested intervals from captured timew commands.

        Returns:
            List of SuggestedInterval objects
        """
        from .compare import SuggestedInterval

        if self.captured_commands is None:
            return []

        intervals = []
        current_start = None
        current_tags = set()

        for cmd in self.captured_commands:
            if len(cmd) < 2:
                continue

            command = cmd[1]  # 'start', 'stop', etc.

            if command == "start":
                # Extract tags and timestamp
                # Format: ['timew', 'start', 'tag1', 'tag2', ..., '2025-01-01T10:00:00']
                tags = set(cmd[2:-1])  # All elements between 'start' and timestamp
                timestamp_str = cmd[-1]

                # Parse timestamp - timestamps in commands are in local timezone
                # (because they're generated with since.astimezone().strftime())
                start = datetime.fromisoformat(timestamp_str.replace("T", " ", 1).rstrip("Z"))
                if start.tzinfo is None:
                    # Assume local timezone, then convert to UTC
                    start = start.astimezone(UTC)

                # If there was a previous interval, close it
                if current_start:
                    intervals.append(
                        SuggestedInterval(start=current_start, end=start, tags=current_tags)
                    )

                # Start new interval
                current_start = start
                current_tags = tags

            elif command == "stop" and current_start:
                # Close current interval
                # May have timestamp as last arg
                if len(cmd) > 2 and cmd[-1].count("T") == 1:
                    end = datetime.fromisoformat(cmd[-1].replace("T", " ", 1).rstrip("Z"))
                    if end.tzinfo is None:
                        # Assume local timezone, then convert to UTC
                        end = end.astimezone(UTC)
                else:
                    end = datetime.now(UTC)

                intervals.append(SuggestedInterval(start=current_start, end=end, tags=current_tags))

                current_start = None
                current_tags = set()

        return intervals

    def run_comparison(self) -> dict:
        """
        Run comparison between TimeWarrior database and ActivityWatch suggestions.

        Requires show_diff=True and will use start_time/end_time for the comparison window.

        Returns:
            Comparison dictionary with keys: 'matching', 'different_tags', 'missing', 'extra'
        """
        from .compare import (
            compare_intervals,
            fetch_timew_intervals,
            format_diff_output,
            format_timeline,
            generate_fix_commands,
        )

        if not self.show_diff:
            return {}

        # Fetch what's in TimeWarrior
        timew_intervals = fetch_timew_intervals(self.start_time, self.end_time)

        # Get what we suggested
        suggested_intervals = self.get_suggested_intervals()

        # Compare
        comparison = compare_intervals(timew_intervals, suggested_intervals)

        # Display timeline view if requested
        if self.show_timeline:
            timeline_output = format_timeline(
                timew_intervals, suggested_intervals, self.start_time, self.end_time
            )
            print(timeline_output)

        # Display comparison report (unless hidden or showing timeline)
        if not self.hide_diff_report and not self.show_timeline:
            output = format_diff_output(comparison, verbose=self.verbose)
            print(output)

        # Generate and display/execute fix commands
        if self.show_fix_commands or self.apply_fix:
            fix_commands = generate_fix_commands(comparison)

            if fix_commands:
                if self.apply_fix:
                    print("\n" + "=" * 80)
                    print("Applying fixes to TimeWarrior database...")
                    print("=" * 80 + "\n")

                    for cmd in fix_commands:
                        # Skip empty lines and commented-out commands
                        if not cmd.strip() or cmd.startswith("#"):
                            if cmd.startswith("#"):
                                print(f"Skipping (manual entry): {cmd}")
                            continue

                        print(f"Executing: {cmd}")
                        # Parse and execute the command (strip comment part)
                        import subprocess

                        try:
                            # Remove comment part if present (e.g., "  # 2025-12-10 - old tags: ...")
                            command_part = cmd.split("  #")[0].strip()
                            result = subprocess.run(
                                command_part.split(), capture_output=True, text=True, check=True
                            )
                            print("  ✓ Success")
                            if result.stdout:
                                print(f"    Output: {result.stdout.strip()}")
                        except subprocess.CalledProcessError as e:
                            print(f"  ✗ Failed (exit code {e.returncode})")
                            if e.stderr:
                                print(f"    stderr: {e.stderr.strip()}")
                            if e.stdout:
                                print(f"    stdout: {e.stdout.strip()}")
                            print(f"    Command: {command_part}")

                    print("\n" + "=" * 80 + "\n")
                else:
                    # Just show the commands
                    print("\n" + "=" * 80)
                    print("Commands to fix differences:")
                    print("=" * 80 + "\n")

                    for cmd in fix_commands:
                        print(cmd)

                    print("\n" + "=" * 80 + "\n")
            else:
                if self.hide_diff_report:
                    print("No differences found - TimeWarrior matches ActivityWatch suggestions.")

        return comparison

    def show_unmatched_events_report(self, limit: int = 10, verbose: bool = False) -> None:
        """Display a report of events that didn't match any rules.

        Args:
            limit: Maximum number of output lines to show (default: 10)
            verbose: If True, show additional context (URLs, paths, tmux info)
        """
        from .report import show_unmatched_events_report as _show_report

        _show_report(self.unmatched_events, limit=limit, verbose=verbose, exporter=self)

    def set_known_tick_stats(
        self,
        event=None,
        start=None,
        end=None,
        manual=False,
        tags=None,
        reset_accumulator=False,
        retain_accumulator=True,
        record_export=False,
        decision_timestamp=None,
        accumulator_before=None,
    ):
        """
        Set statistics after exporting tags.

        Args:
            event: Event dictionary with timestamp and duration
            start: Start time (overrides event timestamp)
            end: End time (overrides event timestamp + duration)
            manual: Whether this is manual tracking
            tags: Tags being exported
            reset_accumulator: Whether to reset tag accumulator
            retain_accumulator: Whether to retain current tags with stickyness
            record_export: Whether to record this as an export for reporting
            decision_timestamp: When the export decision was triggered
            accumulator_before: Pre-stickyness accumulator state for accurate reporting
        """
        # Extract timestamps
        if event and not start:
            start = event["timestamp"]
        if event and not end:
            end = event["timestamp"] + event["duration"]
        if start and not end:
            end = start

        # Decision timestamp defaults to event timestamp if not provided
        if decision_timestamp is None and event:
            decision_timestamp = event["timestamp"]

        # Prepare tags for retention
        if tags is None:
            tags = set()
        elif isinstance(tags, str):
            tags = {tags}
        else:
            tags = set(tags)  # Ensure it's a set

        # Delegate to StateManager
        self.state.record_export(
            start=start,
            end=end,
            tags=tags,
            manual=manual,
            reset_stats=reset_accumulator,
            retain_tags=tags if (reset_accumulator and retain_accumulator) else None,
            stickyness_factor=self.stickyness_factor
            if (reset_accumulator and retain_accumulator)
            else 0.0,
            record_export_history=record_export,
            decision_timestamp=decision_timestamp,
            accumulator_before=accumulator_before,
        )

        # Handle the special case where retain_accumulator adds initial time to tags
        # This matches the old behavior: self.tags_accumulated_time[tag] = self.stickyness_factor*self.min_recording_interval
        if reset_accumulator and retain_accumulator and tags:
            for tag in tags:
                # If tag wasn't in accumulator before (so it has 0 time after reset),
                # initialize it with self.stickyness_factor * self.min_recording_interval
                if self.state.stats.tags_accumulated_time[tag] == timedelta(0):
                    self.state.stats.tags_accumulated_time[tag] = timedelta(
                        seconds=self.stickyness_factor * self.min_recording_interval
                    )

    ## TODO: move all dealings with statistics to explicit statistics-handling methods
    def ensure_tag_exported(self, tags, event, since=None, accumulator_before=None):
        if since is None:
            since = event["timestamp"]

        if isinstance(tags, str):
            tags = {tags}

        # Only perform validation checks if state has been initialized
        if self.state.last_start_time is not None and self.state.last_known_tick is not None:
            ## Now, the previously tagged thing has been running (at least) since self.last_known_tick,
            ## no matter if we have activity supporting it or not since self.last_known_tick.
            last_activity_run_time = since - self.state.last_start_time

            ## We'd like to compare with self.total_time_known_event, but it's counted from the end of the previous event to the end of the current event
            tracked_gap = event["timestamp"] + event["duration"] - self.state.last_known_tick

            ## if the time tracked is significantly less than the minimum
            ## time we're supposed to track, something is also probably
            ## wrong and should be investigated
            if (
                tags != {"afk"}
                and not self.state.is_afk()
                and not self.state.manual_tracking
                and last_activity_run_time.total_seconds() < self.min_recording_interval - 3
            ):
                if self.start_time and self.end_time:
                    # Batch/diff mode - log and continue
                    self.log(
                        f"last_activity_run_time ({last_activity_run_time.total_seconds()}s) < min_recording_interval-3 ({self.min_recording_interval - 3}s) - normal in batch/diff mode",
                        event=event,
                        level=logging.DEBUG,
                    )
                else:
                    # Sync mode - this indicates a real problem
                    self.breakpoint(
                        f"last_activity_run_time ({last_activity_run_time.total_seconds()}s) < self.min_recording_interval-3 ({self.min_recording_interval - 3}s), last_start_time={self.state.last_start_time}, since={since}"
                    )

            ## If the tracked time is less than the known events time we've counted
            ## then something is a little bit wrong.
            ## Use small tolerance (10ms) for floating point/timestamp rounding errors
            rounding_tolerance = timedelta(milliseconds=10)
            if (
                tags != {"afk"}
                and tracked_gap + rounding_tolerance < self.state.stats.known_events_time
            ):
                self.breakpoint(
                    f"tracked_gap ({tracked_gap.total_seconds()}s) < known_events_time ({self.state.stats.known_events_time.total_seconds()}s) for event {event['data']}, last_known_tick={self.state.last_known_tick}, event_start={event['timestamp']}, event_end={event['timestamp'] + event['duration']}"
                )

            ## If the time tracked is way longer than the known events time we've counted
            ## then we have too much unknown activity - tag it as UNKNOWN
            if (
                tags != {"afk"}
                and tracked_gap.total_seconds() > self.max_mixed_interval
                and self.state.stats.known_events_time / tracked_gap < MIN_KNOWN_ACTIVITY_RATIO
                and not self.state.manual_tracking
            ):
                self.log(
                    f"Large gap ({tracked_gap.total_seconds()}s) with low known activity ({(self.state.stats.known_events_time / tracked_gap):.1%}), tagging as UNKNOWN",
                    event=event,
                    level=logging.WARNING,
                )
                tags = {"UNKNOWN", "not-afk"}

        if "afk" in tags:
            self.state.set_afk_state(AfkState.AFK)

        # For AFK events, only advance last_known_tick to the START of the interval,
        # not the END. This prevents skipping window events that occurred during AFK.
        # AFK events overlap with window events (user AFK while window active).
        # NOTE: For AFK events, export recording is deferred until after ask-away tags
        # are computed (see below) to include the full tags and proper duration.
        if "afk" in tags:
            self.set_known_tick_stats(
                start=since,
                end=since,
                tags=tags,
                reset_accumulator=True,
                record_export=False,  # Deferred - will record after ask-away tags computed
            )
        else:
            self.set_known_tick_stats(
                event=event,
                start=since,
                tags=tags,
                reset_accumulator=True,
                record_export=True,
                accumulator_before=accumulator_before,
            )

        # Reset statistics counters at the start of new tracking cycle
        # This ensures known_events_time only tracks events since the last export
        # and makes the validation assertions meaningful
        self.state.stats.reset(retain_tags=tags)

        # Update timew_info (either from actual timew or maintain simulated state in dry-run)
        if not self.dry_run:
            self.set_timew_info(self.retag_current_interval())

        ## Special logic with 'override', 'manual' and 'unknown' should be documented or removed!
        if self.timew_info is not None:
            if "override" in self.timew_info["tags"]:
                return
            if "manual" in self.timew_info["tags"] and "unknown" in tags:
                return
            # Don't skip early if this is an AFK event that might have ask-away overlap
            # We need to check for ask-away tags first
            if set(tags).issubset(self.timew_info["tags"]) and "afk" not in tags:
                return
        tags = self.apply_retag_rules(tags)
        assert not self.tag_extractor.check_exclusive_groups(tags)

        # Look up ask-away message for this event and extract tags from it
        # This must happen BEFORE the final_tags comparison below, so that
        # ask-away tags are included in the comparison
        ask_away_tags = set()
        if "afk" in tags and hasattr(self, "_ask_away_events") and self._ask_away_events:
            event_start = event["timestamp"]
            event_end = event_start + event["duration"]
            overlapping_events = []

            for ask_event in self._ask_away_events:
                ask_start = ask_event["timestamp"]
                ask_end = ask_start + ask_event["duration"]
                if ask_start < event_end and ask_end > event_start:
                    overlapping_events.append(ask_event)

            if overlapping_events:
                # Check if first event has split metadata
                first_event = overlapping_events[0]
                is_split = first_event["data"].get("split", False)

                if is_split:
                    # Split events are handled separately below
                    pass
                else:
                    # Non-split: extract tags from the first overlapping event
                    ask_event = overlapping_events[0]
                    message = ask_event["data"].get("message", "")
                    if message:
                        synthetic_event = {
                            "timestamp": event["timestamp"],
                            "duration": event["duration"],
                            "data": {"app": "ask-away", "title": message},
                        }
                        message_tags = self.tag_extractor.get_app_tags(synthetic_event)
                        if not message_tags or message_tags is False:
                            message_tags = parse_message_tags(message)
                        if message_tags:
                            if isinstance(message_tags, set):
                                ask_away_tags = message_tags
                            else:
                                ask_away_tags = set(message_tags)

        # Check if tags are exactly the same as current tags (after rule application)
        # This prevents redundant timew start commands when tags haven't changed
        final_tags = tags | {"~aw"} | ask_away_tags  # Add ~aw tag and ask-away tags

        # Record the deferred AFK export now that we have final_tags computed
        # For AFK events, use the proper end time (event end, not just since)
        if "afk" in tags:
            afk_end = event["timestamp"] + event["duration"]
            self.state.record_export(
                start=since,
                end=afk_end,
                tags=final_tags,
                reset_stats=False,  # Already reset above
                record_export_history=True,
            )

        if self.timew_info is not None and final_tags == self.timew_info["tags"]:
            return

        # Handle split ask-away events (these need special processing with multiple intervals)
        # Non-split ask-away events are already handled above via ask_away_tags
        if "afk" in tags and hasattr(self, "_ask_away_events") and self._ask_away_events:
            event_start = event["timestamp"]
            event_end = event_start + event["duration"]
            overlapping_events = []

            for ask_event in self._ask_away_events:
                ask_start = ask_event["timestamp"]
                ask_end = ask_start + ask_event["duration"]
                if ask_start < event_end and ask_end > event_start:
                    overlapping_events.append(ask_event)

            if overlapping_events:
                first_event = overlapping_events[0]
                is_split = first_event["data"].get("split", False)

                if is_split:
                    # This AFK period was split by the user
                    # Sort split events by split_index to ensure correct order
                    split_events = sorted(
                        overlapping_events, key=lambda e: e["data"].get("split_index", 0)
                    )

                    logger.info(f"Found {len(split_events)} split activities for AFK period")

                    # For each split event, create a separate tracking entry
                    for i, split_event in enumerate(split_events):
                        message = split_event["data"].get("message", "")
                        if not message:
                            continue

                        # Extract tags for this specific split activity
                        synthetic_event = {
                            "timestamp": split_event["timestamp"],
                            "duration": split_event["duration"],
                            "data": {"app": "ask-away", "title": message},
                        }
                        message_tags = self.tag_extractor.get_app_tags(synthetic_event)

                        # If no rules matched, use the message text directly as tags
                        if not message_tags or message_tags is False:
                            message_tags = parse_message_tags(message)

                        # Combine with base tags
                        split_tags = tags | {"~aw"}
                        if message_tags:
                            if isinstance(message_tags, set):
                                split_tags = split_tags | message_tags
                            else:
                                split_tags = split_tags | set(message_tags)

                        # Start tracking for this split activity with its specific timestamp
                        split_since = split_event["timestamp"]
                        logger.info(
                            f"  Split {i + 1}/{len(split_events)}: '{message}' "
                            f"at {split_since} ({split_event['duration']})"
                        )
                        self.tracker.start_tracking(split_tags, split_since)

                        # Update state after each split (simulate sequential tracking)
                        if not self.dry_run:
                            self.set_timew_info(self.retag_current_interval())
                        else:
                            self.set_timew_info(
                                {
                                    "start": split_since.strftime("%Y%m%dT%H%M%SZ"),
                                    "start_dt": split_since,
                                    "tags": split_tags,
                                }
                            )

                    # Split events handled - return early, don't call start_tracking again
                    return
                # Non-split events already handled via ask_away_tags above

        # Start tracking with the final tags
        self.tracker.start_tracking(final_tags, since)

        # Update timew_info after command
        if not self.dry_run:
            self.set_timew_info(self.retag_current_interval())
        else:
            # In dry-run mode, simulate the timew_info state as if the command was executed
            self.set_timew_info(
                {"start": since.strftime("%Y%m%dT%H%M%SZ"), "start_dt": since, "tags": final_tags}
            )

    def pretty_accumulator_string(self) -> str:
        a = self.state.stats.tags_accumulated_time
        tags = [x for x in a if a[x].total_seconds() > self.min_tag_recording_interval]
        tags.sort(key=lambda x: -a[x])
        return "\n".join([f"{x}: {a[x].total_seconds():5.1f}s" for x in tags])

    def log(
        self, msg: str, tags=None, event=None, ts=None, level: int = logging.INFO, extra=None
    ) -> None:
        """
        Log a message with context about the current event and state.

        Args:
            msg: The log message
            tags: Optional tags being processed
            event: Optional event being processed
            ts: Optional timestamp (defaults to event timestamp if not provided)
            level: Logging level (default: INFO, use logging.WARNING for bold, logging.ERROR for critical)
        """
        if not extra:
            extra = {}

        # Build extra context for structured logging
        extra.update(
            {
                "last_tick": ts2strtime(self.state.last_tick)
                if self.state.last_tick
                else "XX:XX:XX",
            }
        )

        if ts:
            extra["ts"] = ts2strtime(ts)

        if event:
            extra["event_start"] = event["timestamp"]
            extra["event_stop"] = event["timestamp"] + event["duration"]
            extra["event_duration"] = f"+ {event['duration'].total_seconds():6.1f}s"
            if event.get("data"):
                extra["event_data"] = event["data"]

        if tags:
            extra["tags"] = tags

        # Log with appropriate level
        logger.log(level, msg, extra=extra)

    def retag_current_interval(self) -> dict | None:
        """Get current tracking and apply retag rules if needed.

        Returns:
            Updated tracking info, or None if no active tracking
        """
        # Get current tracking
        timew_info = self.tracker.get_current_tracking()

        if timew_info is None:
            return None

        # Apply retag rules
        source_tags = set(timew_info["tags"])
        new_tags = self.apply_retag_rules(source_tags)

        # Retag if tags changed
        if new_tags != source_tags:
            self.tracker.retag(new_tags)
            # Get updated info
            if not self.dry_run:
                timew_info = self.tracker.get_current_tracking()
                if timew_info:  # Check if still active
                    assert set(timew_info["tags"]) == new_tags, (
                        f"Expected {new_tags}, got {timew_info['tags']}"
                    )

        return timew_info

    def _afk_change_stats(self, afk, tags, event):
        """
        Internal method used from check_and_handle_afk_state_change.
        Reset statistics counters when coming/going afk.
        """
        # Determine new AFK state
        if afk == "afk":
            new_state = AfkState.AFK
        elif afk == "not-afk":
            new_state = AfkState.ACTIVE
        else:
            # Handle unexpected states - default to UNKNOWN->ACTIVE transition
            logger.warning(f"Unexpected afk value: {afk}, treating as 'not-afk'")
            new_state = AfkState.ACTIVE

        # Calculate event end time
        event_end = event["timestamp"] + event["duration"]

        # Delegate to StateManager
        self.state.handle_afk_transition(
            new_state=new_state,
            current_time=event_end if tags == {"afk"} else event["timestamp"],
            reason=f"AFK change: {afk}, tags: {tags}",
        )

    def check_and_handle_afk_state_change(self, tags, event=None):
        """
        * Checks if I've gone afk or returned to keyboard
        * Resets the statistics that should be reset if I'm coming or leaving
        * Exports the tracking, if applicable
        * Returns False if the event/tags needs further handling
        * Returns True if all logic has been handled in this function, meaning that the event/tags does not need further handling
        """
        if not tags:  ## Not much to do here.  Except, we could verify that the event is compatible with the afk setting
            return False
        if "afk" in tags and "not-afk" in tags:
            ## Those are exclusive, should not happen!
            self.breakpoint()
        if self.state.afk_state == AfkState.UNKNOWN:
            ## Program has just been started, and we don't know if we're afk or not
            if "afk" in tags:
                self.state.set_afk_state(AfkState.AFK)
            if "not-afk" in tags:
                self.state.set_afk_state(AfkState.ACTIVE)
            ## unless tags are { 'afk' } or { 'non-afk' } we'll return False
            ## to indicate that we haven't handled any state change, and that
            ## the tags still needs handling
            return self.state.afk_state != AfkState.UNKNOWN and len(tags) == 1
        if self.state.is_afk():
            if tags == {"afk"}:
                ## We're already afk, but got another afk event.
                ## This can happen with overlapping AFK periods or out-of-order events.
                ## In batch/diff mode this is normal - just update the stats.
                self.log(
                    "Received AFK event while already in AFK state - likely overlapping AFK periods",
                    event=event,
                    level=logging.DEBUG,
                )
                self._afk_change_stats("afk", tags, event)
                return True
            if "afk" not in self.timew_info["tags"]:
                ## I'm apparently afk, but we're not tracking it in timew?
                ## In batch/diff mode with historical data, this can happen when:
                ## - Processing events from the past and building up state
                ## - TimeWarrior's current state doesn't match the historical timestamp
                ## - In dry-run mode where we haven't applied changes yet
                if self.start_time and self.end_time:
                    # Batch/diff mode - log and continue
                    self.log(
                        "Internal state shows AFK but TimeWarrior not tracking afk tag - normal in batch/diff mode",
                        event=event,
                        level=logging.DEBUG,
                    )
                else:
                    # Sync mode - this indicates a real problem
                    self.breakpoint()
            if "not-afk" in tags:
                self._afk_change_stats("not-afk", tags, event)
                self.log(
                    f"You have returned to the keyboard after {(event['timestamp'] - self.state.last_start_time).total_seconds()}s absence",
                    event=event,
                )
                ## Some possibilities when tags != {'not-afk'}:
                ## 1) We have returned from the keyboard without the 'not-afk' special event triggered?
                ## 2) We're catching up some "ghost tracking" of window events while we're afk?
                ## 3) The 'not-afk' special event is not in the right order in the event queue?
                ## 4) The data from the afk/not-afk watcher is unreliable
                ## I think I found out that 3 is normal, but we may want to investigate TODO
                return tags == {"not-afk"}
        else:  ## We're not afk
            if tags == {"not-afk"}:
                ## Check this up manually.  Possibilities:
                ## 1) We're wrongly marked as 'not-afk' while we've actually been afk
                ## 2) The 'not-afk' special event is not in the right order in the event queue?
                ## 3) The data from the afk/not-afk watcher is unreliable
                ## I think I found 2 is normal, but we may want to investigate TODO
                return True
            elif tags == {"afk"}:
                ## Meaning we've just gone afk.
                self.ensure_tag_exported(tags, event)
                self._afk_change_stats("afk", tags, event)
                self.log(f"You're going to be afk for at least {event['duration']}s", event=event)
                return True
            elif "afk" in tags:
                ## We've gone afk ... in some weird way?
                self._afk_change_stats("afk", tags, event)
                self.breakpoint()
                return False
            else:
                ## We're not afk and we've not gone afk
                return False

        return False

    def find_tags_from_event(self, event) -> TagResult:
        """Extract tags from an event.

        Returns:
            TagResult with:
            - IGNORED if event too short (unless accumulated time in same context is significant)
            - NO_MATCH if event processed but no tags found
            - MATCHED if tags were extracted

        Short event handling:
            Brief window switches while searching for the right window are ignored.
            However, staying in one app with rapid title changes (e.g., flipping through
            photos in feh) should NOT be ignored - that's legitimate activity.

            We track consecutive short events by (app, tags) context. If the wall-clock
            time span of these events exceeds ignore_interval, we treat them as significant.
        """
        # First, always determine what tags the event would have
        # (we need this before deciding whether to ignore)
        # Use tag_extractor.get_tags() to ensure single source of truth for tag extraction
        tags = self.tag_extractor.get_tags(event)

        is_short = event["duration"].total_seconds() < self.ignore_interval

        if is_short:
            # Build context key: (app, frozenset of tags or None if unmatched)
            app = event["data"].get("app", "unknown")
            tags_key = frozenset(tags) if tags and tags is not False else None
            current_context = (app, tags_key)
            event_time = event["timestamp"]
            event_end = event_time + event["duration"]

            if current_context == self._short_event_context:
                # Continue in same context - accumulate
                self._short_event_accumulated += event["duration"]
            else:
                # New context - reset tracking
                self._short_event_context = current_context
                self._short_event_first_time = event_time
                self._short_event_accumulated = event["duration"]

            # Check wall-clock time: from first short event to this event's end
            wall_clock_elapsed = (event_end - self._short_event_first_time).total_seconds()

            if wall_clock_elapsed >= self.ignore_interval:
                # Significant wall-clock time in same context - don't ignore
                # Reset tracking after recognizing significant activity
                self._short_event_context = None
                self._short_event_first_time = None
                self._short_event_accumulated = timedelta(0)
                # Fall through to normal tag handling below
            else:
                return TagResult(
                    result=EventMatchResult.IGNORED, reason="Event duration below ignore_interval"
                )
        else:
            # Non-short event resets tracking
            self._short_event_context = None
            self._short_event_first_time = None
            self._short_event_accumulated = timedelta(0)

        # Normal tag result handling
        if tags is False:
            return TagResult(result=EventMatchResult.NO_MATCH, reason="No tag rules matched")

        # Ensure tags is a set (convert if needed for robustness)
        if not isinstance(tags, set):
            tags = set(tags) if tags else set()

        return TagResult(result=EventMatchResult.MATCHED, tags=tags)

    def _process_current_event_incrementally(self, event):
        """
        Process the current ongoing event in an idempotent way.

        Since the current event's duration increases on each loop,
        we track what we've already processed and only handle the delta.

        This ensures the program is "snappy" (processes current events immediately)
        while remaining idempotent (doesn't duplicate work when the same event
        comes back with increased duration).

        Args:
            event: The current ongoing event from ActivityWatch
        """
        event_start = event["timestamp"]
        current_duration = event["duration"]

        # Check if this is the same ongoing event as last time
        if self.state.current_event_timestamp == event_start:
            # Same event - calculate the incremental duration
            already_processed = self.state.current_event_processed_duration
            new_duration = current_duration - already_processed

            if new_duration <= timedelta(0):
                # No new duration to process
                return

            # Create a synthetic event with just the new duration
            # The timestamp is adjusted to start where we left off
            incremental_event = event.copy()
            incremental_event["duration"] = new_duration
            incremental_event["timestamp"] = event_start + already_processed

            # Process the incremental part
            tag_result = self.find_tags_from_event(incremental_event)

            if tag_result and not self.check_and_handle_afk_state_change(
                tag_result.tags, incremental_event
            ):
                # Add to known events time (only for non-AFK events to avoid double-counting)
                if "status" not in incremental_event["data"]:
                    self.state.stats.known_events_time += new_duration

                # Apply retagging rules
                tags = self.apply_retag_rules(tag_result.tags)

                # Accumulate tags from the incremental duration
                for tag in tags:
                    self.state.stats.tags_accumulated_time[tag] += new_duration

                self.log(
                    f"Processed incremental {new_duration.total_seconds()}s of current event with tags: {tags}"
                )

            # Update the processed duration
            self.state.current_event_processed_duration = current_duration

        else:
            # New ongoing event - the previous one must have ended
            if self.state.current_event_timestamp is not None:
                # The previous ongoing event has now completed
                # It was already processed incrementally, nothing more to do
                self.log(f"Previous ongoing event completed, starting new event at {event_start}")

            # Start tracking the new ongoing event
            self.state.current_event_timestamp = event_start
            self.state.current_event_processed_duration = timedelta(0)

            # Process the entire current event (first time seeing it)
            tag_result = self.find_tags_from_event(event)

            if tag_result and not self.check_and_handle_afk_state_change(tag_result.tags, event):
                # Add to known events time (only for non-AFK events to avoid double-counting)
                if "status" not in event["data"]:
                    self.state.stats.known_events_time += current_duration

                # Apply retagging rules
                tags = self.apply_retag_rules(tag_result.tags)

                for tag in tags:
                    self.state.stats.tags_accumulated_time[tag] += current_duration

                self.log(
                    f"Started tracking new current event ({current_duration.total_seconds()}s) with tags: {tags}"
                )

            # Record what we've processed
            self.state.current_event_processed_duration = current_duration

    def _apply_afk_gap_workaround(self, afk_events: list) -> list:
        """
        Apply workaround for aw-watcher-window-wayland issue #41.

        Issue: https://github.com/ActivityWatch/aw-watcher-window-wayland/issues/41
        Problem: AFK watcher on Wayland may not report AFK events, leaving gaps
                 between "not-afk" events that should be treated as AFK periods.

        This workaround fills gaps between consecutive AFK events with synthetic
        AFK events, assuming that any gap longer than self.min_recording_interval
        should be treated as an AFK period.

        Args:
            afk_events: List of AFK events from ActivityWatch

        Returns:
            Modified list of AFK events with synthetic gaps filled in

        Note:
            This workaround can be disabled by setting enable_afk_gap_workaround=false
            in the config file if the upstream issue is fixed or if it causes problems.
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
            if gap_duration.total_seconds() >= self.min_recording_interval:
                synthetic_afk_events.append(
                    {"data": {"status": "afk"}, "timestamp": gap_start, "duration": gap_duration}
                )

        # Combine original and synthetic events
        return afk_events + synthetic_afk_events

    def _merge_afk_and_lid_events(self, afk_events: list, lid_events: list) -> list:
        """
        Merge lid events with AFK events, giving lid events priority.

        Lid closure and suspend events represent system-level AFK state that
        should override user-level AFK detection from aw-watcher-afk.

        Strategy:
        - Lid closed -> ALWAYS system-afk (overrides user activity detection)
        - Lid open during AFK -> keep AFK state from aw-watcher-afk
        - Lid events are converted to AFK-compatible format for processing
        - Original lid data is preserved for debugging
        - When lid events overlap with AFK events, lid events take priority

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
            # Lid closed, suspended, or boot gap -> afk
            # Lid open or resumed -> not-afk
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
                    "source": "lid",  # Mark source for debugging
                    "original_data": data,  # Preserve original attributes
                },
            }
            converted_lid_events.append(converted_event)

        # Implement priority-based merge: lid events override conflicting AFK events
        # When a lid event indicates AFK (closed/suspended) and overlaps with a
        # non-AFK event from aw-watcher-afk, remove the conflicting portion
        resolved_afk_events = self._resolve_event_conflicts(afk_events, converted_lid_events)

        # Merge resolved AFK events with lid events
        merged = resolved_afk_events + converted_lid_events

        # Sort by timestamp
        merged.sort(key=lambda e: normalize_timestamp(e["timestamp"]))

        return merged

    def _resolve_event_conflicts(self, afk_events: list, priority_events: list) -> list:
        """
        Remove or trim AFK events that conflict with higher-priority lid events.

        Only removes/trims AFK events when the lid event indicates AFK (closed/suspended)
        and the AFK event indicates activity (not-afk). This implements the strategy:
        - Lid closed -> ALWAYS system-afk (overrides user activity detection)
        - Lid open during AFK -> keep AFK state from aw-watcher-afk

        Args:
            afk_events: Events from aw-watcher-afk
            priority_events: Events from lid watcher (already converted to AFK format)

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
            """Check if two events conflict (overlap and have different status).

            Only consider it a conflict when:
            1. They have different status, AND
            2. The priority event indicates AFK (lid closed/suspended)

            When lid is open (not-afk), we keep the user's AFK state from aw-watcher-afk,
            per the strategy: "Lid open during AFK -> keep AFK state from aw-watcher-afk"
            """
            afk_status = afk_event["data"]["status"]
            priority_status = priority_event["data"]["status"]

            # Only conflict if they have different status AND the priority event says afk
            # This means:
            # - Lid closed (afk) overrides user not-afk -> conflict, remove user event
            # - Lid open (not-afk) does NOT override user afk -> no conflict, keep user event
            return afk_status != priority_status and priority_status == "afk"

        resolved = []
        for afk_event in afk_events:
            afk_start, afk_end = get_event_range(afk_event)
            trimmed_segments = [(afk_start, afk_end)]

            # Check against each priority event
            for priority_event in priority_events:
                priority_start, priority_end = get_event_range(priority_event)

                # Check for overlap and conflict
                new_segments = []
                for seg_start, seg_end in trimmed_segments:
                    if events_overlap(seg_start, seg_end, priority_start, priority_end):
                        if events_conflict(afk_event, priority_event):
                            # Trim the conflicting portion
                            # Keep non-overlapping parts
                            if seg_start < priority_start:
                                # Keep portion before priority event
                                new_segments.append((seg_start, priority_start))
                            if seg_end > priority_end:
                                # Keep portion after priority event
                                new_segments.append((priority_end, seg_end))
                            # The overlapping portion is removed
                        else:
                            # Same status, no conflict - keep the segment
                            new_segments.append((seg_start, seg_end))
                    else:
                        # No overlap, keep as is
                        new_segments.append((seg_start, seg_end))

                trimmed_segments = new_segments

            # Create events from remaining segments
            for seg_start, seg_end in trimmed_segments:
                duration_td = seg_end - seg_start
                if duration_td.total_seconds() > 0:  # Only keep non-zero duration segments
                    resolved.append(
                        {
                            "timestamp": seg_start,  # Keep as datetime object
                            "duration": duration_td,  # Keep as timedelta object
                            "data": afk_event["data"].copy(),
                        }
                    )

        return resolved

    def _fetch_and_prepare_events(self) -> tuple[list, dict | None]:
        """Fetch, filter, merge, and sort events from ActivityWatch.

        Returns:
            Tuple of (completed_events, current_event):
            - completed_events: List of finished events to process
            - current_event: The ongoing event (or None)
        """
        afk_id = self.event_fetcher.bucket_by_client["aw-watcher-afk"][0]
        window_id = self.event_fetcher.bucket_by_client["aw-watcher-window"][0]

        # Fetch AFK events
        afk_events = self.event_fetcher.get_events(
            afk_id, start=self.state.last_tick, end=self.end_time
        )

        # Apply workaround if enabled in config
        if self.config.get("enable_afk_gap_workaround", True):
            afk_events = self._apply_afk_gap_workaround(afk_events)

        # The afk tracker is not reliable. Sometimes it shows me
        # being afk even when I've been sitting constantly by the
        # computer, working most of the time, perhaps spending a
        # minute reading something?
        # Filter out short AFK events
        afk_events = [
            x for x in afk_events if x["duration"] > timedelta(seconds=self.max_mixed_interval)
        ]

        # Fetch lid events if available and enabled
        lid_events = []
        if self.config.get("enable_lid_events", True):
            lid_bucket = self.event_fetcher.get_lid_bucket()
            if lid_bucket:
                lid_events = self.event_fetcher.get_events(
                    lid_bucket, start=self.state.last_tick, end=self.end_time
                )

                # Filter out short lid cycles (except boot gaps which should always be kept)
                min_lid_duration = self.config.get("min_lid_duration", 10.0)
                lid_events = [
                    e
                    for e in lid_events
                    if e["duration"] > timedelta(seconds=min_lid_duration)
                    or e["data"].get("boot_gap", False)
                ]

                if lid_events:
                    logger.info(f"Fetched {len(lid_events)} lid events (after filtering)")

        # Merge lid events with AFK events
        # Lid events take priority (system-level AFK overrides user AFK)
        merged_afk_events = self._merge_afk_and_lid_events(afk_events, lid_events)

        # Fetch ask-away events if available
        ask_away_bucket = self.event_fetcher.get_ask_away_bucket()
        if ask_away_bucket:
            ask_away_events = self.event_fetcher.get_events(
                ask_away_bucket, start=self.state.last_tick, end=self.end_time
            )
            if ask_away_events:
                logger.info(f"Fetched {len(ask_away_events)} ask-away events")
                # Store ask-away events for later annotation
                self._ask_away_events = ask_away_events
            else:
                self._ask_away_events = []
        else:
            self._ask_away_events = []

        # Fetch window events and merge with merged AFK events
        afk_window_events = (
            self.event_fetcher.get_events(window_id, start=self.state.last_tick, end=self.end_time)
            + merged_afk_events
        )

        # Sort by timestamp
        afk_window_events.sort(key=lambda e: normalize_timestamp(e["timestamp"]))

        # Split window events that overlap with AFK periods
        # This ensures window events are properly interrupted by AFK
        afk_window_events = self._split_window_events_by_afk(afk_window_events, merged_afk_events)

        # Filter out split events that end before or at last_tick to avoid reprocessing
        # This can happen when we fetch an event that overlaps with last_tick, split it,
        # and end up with segments that we've already processed
        if self.state.last_tick:
            afk_window_events = [
                e for e in afk_window_events if get_event_range(e)[1] > self.state.last_tick
            ]

        if len(afk_window_events) == 0:
            return [], None

        # When we have an end_time (test data or specific time range), treat ALL events as completed
        # Only in live monitoring (no end_time) should we treat the last event as "current/ongoing"
        if self.end_time:
            # Historical mode: all events are completed
            return afk_window_events, None
        else:
            # Live monitoring mode: separate the current ongoing event from completed events
            # The last event is the "current" event still in progress
            current_event = afk_window_events[-1] if len(afk_window_events) > 0 else None
            completed_events = afk_window_events[:-1] if len(afk_window_events) > 1 else []
            return completed_events, current_event

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
                # No overlap, keep window event as-is
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
                if current_time < afk_start and afk_start < window_end:
                    duration_td = afk_start - current_time
                    result.append(
                        {
                            **window_event,
                            "timestamp": current_time,  # Keep as datetime
                            "duration": duration_td,  # Keep as timedelta
                        }
                    )

                # Move current_time to after this AFK period
                current_time = max(current_time, afk_end)

            # Add remaining window portion after all AFK periods (if any)
            if current_time < window_end:
                duration_td = window_end - current_time
                result.append(
                    {
                        **window_event,
                        "timestamp": current_time,  # Keep as datetime
                        "duration": duration_td,  # Keep as timedelta
                    }
                )

        # Add all status events back and re-sort
        result.extend(status_events)
        result.sort(key=lambda x: normalize_timestamp(x["timestamp"]))

        return result

    def _should_skip_event(self, event: dict) -> bool:
        """Check if event should be skipped due to old timestamp.

        Args:
            event: The event to check

        Returns:
            True if event should be skipped, False otherwise
        """
        # In batch/diff mode with explicit time range, don't skip events based on state
        # Process all events within the requested range
        if self.start_time and self.end_time:
            return False

        # Skip events older than last_tick or last_known_tick
        if (self.state.last_tick and event["timestamp"] < self.state.last_tick) or (
            self.state.last_known_tick and event["timestamp"] < self.state.last_known_tick
        ):
            # Always skip not-afk status events with old timestamps
            if event["data"] == {"status": "not-afk"}:
                return True

            # For other events, check additional conditions
            if (
                event["data"] != {"status": "afk"}
                and self.state.last_start_time
                and event["timestamp"] > self.state.last_start_time
            ):
                if event["duration"] > timedelta(seconds=DEBUG_SKIP_THRESHOLD_SECONDS):
                    # Log warning for potentially unexpected long event skip
                    # Only breakpoint if PDB debugging is enabled
                    self.log(
                        f"Skipping long event ({event['duration'].total_seconds()}s) with old timestamp - {event}",
                        event=event,
                        level=logging.WARNING,
                    )
                    if self.enable_pdb:
                        self.breakpoint()
                else:
                    self.log(f"skipping event as the timestamp is too old - {event}", event=event)
                return True

        return False

    def _should_export_accumulator(
        self, interval_since_last_tick: timedelta, event: dict
    ) -> tuple[bool, set[str], datetime, dict[str, timedelta]]:
        """Decide if accumulator should be exported and get tags to export.

        Args:
            interval_since_last_tick: Time since last known tick
            event: Current event being processed

        Returns:
            Tuple of (should_export, tags_to_export, since_timestamp, accumulator_before):
            - should_export: True if accumulator should be exported
            - tags_to_export: Set of tags that should be exported
            - since_timestamp: Timestamp to use for export
            - accumulator_before: Accumulator state before stickyness applied (for reporting)
        """
        # Check if enough time has passed and we have significant tags
        if not (
            interval_since_last_tick.total_seconds() > self.min_recording_interval_adj
            and any(
                x
                for x in self.state.stats.tags_accumulated_time
                if x not in SPECIAL_TAGS
                and self.state.stats.tags_accumulated_time[x].total_seconds()
                > self.min_recording_interval_adj
            )
        ):
            return False, set(), self.state.last_known_tick, {}

        self.log("Emptying the accumulator!")

        # Build set of tags that meet the threshold
        tags = set()

        # TODO: This looks like a bug - we reset tags, and then assert that they are not overlapping?
        assert not self.tag_extractor.check_exclusive_groups(tags)

        # Find minimum threshold that avoids exclusive tag conflicts
        min_tag_recording_interval = self.min_tag_recording_interval
        while self.tag_extractor.check_exclusive_groups(
            {
                tag
                for tag in self.state.stats.tags_accumulated_time
                if self.state.stats.tags_accumulated_time[tag].total_seconds()
                > min_tag_recording_interval
            }
        ):
            min_tag_recording_interval += 1

        # Capture accumulator state BEFORE applying stickyness (for accurate reporting)
        accumulator_before = dict(self.state.stats.tags_accumulated_time)

        # Collect tags above threshold and apply stickyness
        for tag in self.state.stats.tags_accumulated_time:
            if (
                self.state.stats.tags_accumulated_time[tag].total_seconds()
                > min_tag_recording_interval
            ):
                tags.add(tag)
            self.state.stats.tags_accumulated_time[tag] *= self.stickyness_factor

        # If no tags to export (threshold was raised too high to avoid conflicts),
        # don't export but keep the decayed accumulator
        if not tags:
            self.log(
                "Threshold raised to avoid exclusive tag conflicts resulted in no tags to export",
                level=logging.DEBUG,
            )
            return False, set(), self.state.last_known_tick, {}

        # Determine since timestamp
        if self.state.manual_tracking:
            since = event["timestamp"] - self.state.stats.known_events_time + event["duration"]
        else:
            since = self.state.last_known_tick

        return True, tags, since, accumulator_before

    def _handle_tag_result(
        self,
        tag_result: TagResult,
        event: dict,
        num_skipped_events: int,
        total_time_skipped_events: timedelta,
    ) -> tuple[int, timedelta]:
        """Handle the tag extraction result and update counters.

        Args:
            tag_result: The tag extraction result
            event: The event being processed
            num_skipped_events: Current count of skipped events
            total_time_skipped_events: Total duration of skipped events

        Returns:
            Tuple of (num_skipped_events, total_time_skipped_events) after reset/update
        """
        # Handle different tag extraction results
        if tag_result.result == EventMatchResult.IGNORED:
            num_skipped_events += 1
            total_time_skipped_events += event["duration"]
            # Track ignored events for analyze reporting
            self.state.stats.ignored_events_count += 1
            self.state.stats.ignored_events_time += event["duration"]
            if total_time_skipped_events.total_seconds() > self.min_recording_interval:
                self.breakpoint()
            return num_skipped_events, total_time_skipped_events

        if tag_result.result == EventMatchResult.NO_MATCH:
            self.state.stats.unknown_events_time += event["duration"]
            # Track unmatched event if requested (for analyze command)
            # Note: We track ALL NO_MATCH events here, even ones that later get
            # exported as UNKNOWN tags, because they represent unmatched activity
            if self.show_unmatched:
                self.unmatched_events.append(event)
            if self.state.stats.unknown_events_time.total_seconds() > self.max_mixed_interval * 2:
                # Significant unknown activity - tag it as UNKNOWN
                self.log(
                    f"Significant unknown activity ({self.state.stats.unknown_events_time.total_seconds()}s), tagging as UNKNOWN",
                    event=event,
                )
                self.ensure_tag_exported({"UNKNOWN", "not-afk"}, event)
                self.state.stats.unknown_events_time = timedelta(0)
            else:
                self.log(
                    f"{self.state.stats.unknown_events_time.total_seconds()}s unknown events.  Data: {event['data']} - ({num_skipped_events} smaller events skipped, total duration {total_time_skipped_events.total_seconds()}s)",
                    event=event,
                )
        else:
            # EventMatchResult.MATCHED
            self.log(
                f"{event['data']} - tags found: {tag_result.tags} ({num_skipped_events} smaller events skipped, total duration {total_time_skipped_events.total_seconds()}s)"
            )

        # Reset counters after handling non-IGNORED events
        return 0, timedelta(0)

    def _update_tag_accumulator(self, tag_result: TagResult, event: dict) -> None:
        """Update the tag accumulator with tags from the event.

        Args:
            tag_result: The tag extraction result
            event: The event being processed
        """
        if tag_result:
            tags = self.apply_retag_rules(tag_result.tags)
            for tag in tags:
                self.state.stats.tags_accumulated_time[tag] += event["duration"]

    def find_next_activity(self):
        ## TODO: move all statistics from internal counters and up to the object

        ## Skipped events are events that takes so little time that we ignore it completely.
        ## The counter is nulled out when some non-skipped event comes in.
        ## Used only for debug logging.
        num_skipped_events = 0

        total_time_skipped_events = timedelta(0)

        # Initialize last_tick if None (first call with test data)
        if self.state.last_tick is None and self.start_time:
            self.state.last_tick = self.start_time

        # Fetch and prepare events
        completed_events, current_event = self._fetch_and_prepare_events()
        if not completed_events and not current_event:
            return False

        cnt = 0
        for event in completed_events:
            # CRITICAL: Always advance last_tick for every event, even if skipped/ignored
            # Otherwise we can get stuck in an infinite loop fetching the same events
            event_end = event["timestamp"] + event["duration"]

            # Skip events with old timestamps
            # Note: We do NOT advance last_tick here because these events are out of order
            # and advancing last_tick would cause time to jump forward incorrectly
            if self._should_skip_event(event):
                continue

            tag_result = self.find_tags_from_event(event)

            ## Handling afk/not-afk
            if self.check_and_handle_afk_state_change(tag_result.tags, event):
                ## TODO:
                ## Doh!  Some of the point of moving things to a separate
                ## function is to avoid the below logic here
                ## Returning after handling { 'not-afk' }
                ## and we'll come back and pick up the same event again!
                ## continue after handling { 'afk' } and
                ## we will pick up "ghost" events that should be
                ## ignored.  (we could add some logic to skip handled or skippable events)

                # CRITICAL: Advance last_tick to prevent infinite loop
                # Without this, the next call to find_next_activity() would
                # fetch the same events again from self.state.last_tick
                self.state.last_tick = (
                    event_end
                    if self.state.last_tick is None
                    else max(self.state.last_tick, event_end)
                )

                if self.state.is_afk():
                    return True
                continue

            # Only count duration for non-AFK events to avoid double-counting
            # (AFK events overlap with window/browser/editor events)
            if tag_result and "status" not in event["data"]:
                duration_to_add = event["duration"]
                # Avoid double-counting: if this event was partially processed as the
                # current/ongoing event, only add the remaining (unprocessed) duration.
                # This happens when an event transitions from current to completed.
                if self.state.current_event_timestamp == event["timestamp"]:
                    duration_to_add = (
                        event["duration"] - self.state.current_event_processed_duration
                    )
                    if duration_to_add < timedelta(0):
                        duration_to_add = timedelta(0)  # Safety check
                    # Clear the current event tracking since we've now fully processed it
                    self.state.current_event_timestamp = None
                    self.state.current_event_processed_duration = timedelta(0)
                if duration_to_add > timedelta(0):
                    self.state.stats.known_events_time += duration_to_add

            # Handle the tag result and update counters
            num_skipped_events, total_time_skipped_events = self._handle_tag_result(
                tag_result, event, num_skipped_events, total_time_skipped_events
            )

            # Continue to next event if this was IGNORED
            if tag_result.result == EventMatchResult.IGNORED:
                self.state.last_tick = (
                    event_end
                    if self.state.last_tick is None
                    else max(self.state.last_tick, event_end)
                )
                continue

            ## Ref README, if self.max_mixed_interval is met, ignore accumulated minor activity
            ## (the mixed time will be attributed to the previous work task)
            if tag_result and event["duration"].total_seconds() > self.max_mixed_interval:
                ## Theoretically, we may do lots of different things causing hundred of different independent tags to collect less than the minimum needed to record something.  In practice that doesn't happen.
                # print(f"We're tossing data: {self.tags_accumulated_time}")
                self.ensure_tag_exported(tag_result.tags, event)

            # Calculate interval since last known tick
            # If last_known_tick is None (first event), initialize it to event timestamp or start_time
            if self.state.last_known_tick is None:
                # Initialize last_known_tick to start_time or event timestamp
                self.state.last_known_tick = self.start_time or event["timestamp"]

            interval_since_last_known_tick = (
                event["timestamp"] + event["duration"] - self.state.last_known_tick
            )
            if interval_since_last_known_tick < timedelta(0):
                ## Something is very wrong here, it needs investigation.
                self.breakpoint()
            assert interval_since_last_known_tick >= timedelta(0)

            ## Track things in internal accumulator if the focus between windows changes often
            self._update_tag_accumulator(tag_result, event)

            ## Check - if `timew start` was run manually since last "known tick", then reset everything
            # Only update timew_info if not in dry-run mode
            if not self.dry_run:
                self.set_timew_info(self.retag_current_interval())

            # Check if we should export the accumulated tags
            should_export, tags_to_export, since, accumulator_before = (
                self._should_export_accumulator(interval_since_last_known_tick, event)
            )
            if should_export:
                self.log(f"Ensuring tags export, tags={tags_to_export}")
                self.ensure_tag_exported(
                    tags_to_export, event, since, accumulator_before=accumulator_before
                )

            self.state.last_tick = (
                event_end if self.state.last_tick is None else max(self.state.last_tick, event_end)
            )
            cnt += 1

        ## Process the current ongoing event incrementally (idempotent)
        if current_event:
            self._process_current_event_incrementally(current_event)

        # Return True if we processed any events (cnt > 0) or have a current event
        return cnt > 0 or current_event is not None

    def set_timew_info(self, timew_info):
        """Set the current TimeWarrior tracking info.

        Args:
            timew_info: Current interval info, or None if no active tracking
        """
        if timew_info is None:
            # No active tracking
            self.timew_info = None
            return

        if self.state.afk_state == AfkState.UNKNOWN and "afk" in timew_info["tags"]:
            self.state.set_afk_state(AfkState.AFK)
        if self.state.afk_state == AfkState.UNKNOWN and "not-afk" in timew_info["tags"]:
            self.state.set_afk_state(AfkState.ACTIVE)

        foo = self.timew_info
        self.timew_info = timew_info
        if foo != self.timew_info:  ## timew has been run since last
            self.log(
                f"tracking from {ts2strtime(self.timew_info['start_dt'])}: {self.timew_info['tags']}"
            )
            if (
                not self.state.last_known_tick
                or timew_info["start_dt"] > self.state.last_known_tick
            ):
                self.set_known_tick_stats(
                    start=timew_info["start_dt"], manual=True, tags=timew_info["tags"]
                )

    def tick(self, process_all: bool = False) -> bool:
        """
        Process one tick of events.

        Args:
            process_all: If True, keep processing until all events are consumed

        Returns:
            bool: True if processing should continue, False if we've reached the end
        """
        # In test mode or dry-run with start_time, skip getting real timew info
        if self.dry_run and self.start_time:
            # Create mock timew_info for test/dry-run mode
            if not self.timew_info:
                mock_start = self.start_time or datetime.now(UTC)
                self.timew_info = {
                    "start": mock_start.strftime("%Y%m%dT%H%M%SZ"),
                    "start_dt": mock_start,
                    "tags": set(),
                }
        elif not self.timew_info:
            # Normal mode or dry-run without start_time - get current timew tracking state
            try:
                self.set_timew_info(self.retag_current_interval())
            except Exception:
                # No active tracking - create mock info
                if self.dry_run:
                    mock_start = self.start_time or datetime.now(UTC)
                    self.timew_info = {
                        "start": mock_start.strftime("%Y%m%dT%H%M%SZ"),
                        "start_dt": mock_start,
                        "tags": set(),
                    }
                else:
                    raise

        if not self.state.last_tick:
            ## TODO: think more through this.  This is in practice program initialization
            # Use start_time if provided, otherwise use timew start
            if self.start_time:
                self.state.last_tick = self.start_time
            elif self.timew_info:
                self.state.last_tick = self.timew_info["start_dt"]
            else:
                # No active tracking and no start_time - query for last timew interval
                try:
                    intervals = self.tracker.get_intervals(
                        datetime.now(UTC) - timedelta(days=7), datetime.now(UTC)
                    )
                    if intervals:
                        # Find the last interval's end time
                        last_end = max((i["end"] for i in intervals if i["end"]), default=None)
                        if last_end:
                            self.state.last_tick = last_end
                        else:
                            # No completed intervals, use lookback period
                            self.state.last_tick = datetime.now(UTC) - timedelta(hours=1)
                    else:
                        # No intervals found, use lookback period
                        self.state.last_tick = datetime.now(UTC) - timedelta(hours=1)
                except Exception as e:
                    # Query failed, fall back to lookback period
                    self.log(f"Failed to query timew intervals: {e}", level=logging.WARNING)
                    self.state.last_tick = datetime.now(UTC) - timedelta(hours=1)
            self.state.last_known_tick = self.state.last_tick
            self.state.last_start_time = self.state.last_tick

        # If process_all is True, keep finding activity until there's none left
        if process_all:
            iterations = 0
            max_iterations = 10000  # Safety limit to prevent infinite loops
            while True:
                iterations += 1
                if iterations > max_iterations:
                    self.log(
                        f"ERROR: Reached maximum iteration limit ({max_iterations}). "
                        f"Possible infinite loop detected at last_tick={self.state.last_tick}",
                        level=logging.ERROR,
                    )
                    break

                found_activity = self.find_next_activity()
                if not found_activity:
                    # Check if we've reached end_time
                    if self.end_time and self.state.last_tick < self.end_time:
                        self.log(f"No more events before end_time, advancing to {self.end_time}")
                        self.state.last_tick = self.end_time
                        found_activity = self.find_next_activity()
                    if not found_activity:
                        break
            return False  # All done processing
        else:
            # Single tick processing
            found_activity = self.find_next_activity()

            # If we have an end_time and no new activity was found, check if we should stop
            if not found_activity and self.end_time:
                # Update last_tick to end_time if we've processed everything up to it
                if self.state.last_tick < self.end_time:
                    self.log(f"No more events before end_time, advancing to {self.end_time}")
                    self.state.last_tick = self.end_time
                    # Try one more time to find activity
                    found_activity = self.find_next_activity()

                # If still no activity, we've reached the end
                if not found_activity:
                    self.log(f"Reached end_time {self.end_time}, stopping")
                    return False

            if not found_activity:
                # In dry-run mode without end_time, we can't continue (would loop forever)
                if self.dry_run and not self.end_time:
                    self.breakpoint()
                    raise ValueError(
                        "dry-run mode without end_time would loop forever - this should be prevented by CLI validation"
                    )

                self.log("sleeping, because no events found")
                if not self.dry_run:  # Don't sleep in dry-run mode
                    sleep(self.sleep_interval)

            return True


## TODO: none of this has anything to do with ActivityWatch and can be moved to a separate module
def get_timew_info():
    """Get information about the currently active TimeWarrior interval.

    Returns:
        dict: Information about the active interval, or None if there's no active tracking
    """
    try:
        current_timew = json.loads(
            subprocess.check_output(["timew", "get", "dom.active.json"], stderr=subprocess.DEVNULL)
        )
        dt = datetime.strptime(current_timew["start"], "%Y%m%dT%H%M%SZ")
        dt = dt.replace(tzinfo=UTC)
        current_timew["start_dt"] = dt
        current_timew["tags"] = set(current_timew["tags"])
        return current_timew
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        # No active tracking, empty database, or invalid data
        return None


def timew_run(commands, dry_run=False, capture_to=None, hide_output=False):
    """
    Execute a timewarrior command, or show what would be done if dry_run=True.

    Args:
        commands: List of command arguments (without 'timew' prefix)
        dry_run: If True, don't execute, just print what would be done
        capture_to: Optional list to append commands to (for testing)
        hide_output: If True, don't print the "DRY RUN" or "Running" messages
    """
    commands = ["timew"] + commands

    if dry_run:
        if not hide_output:
            user_output(
                f"DRY RUN: Would execute: {' '.join(commands)}", color="yellow", attrs=["bold"]
            )
        if capture_to is not None:
            capture_to.append(commands)
        return

    if not hide_output:
        user_output(f"Running: {' '.join(commands)}")
    subprocess.run(commands)
    grace_time = float(os.environ.get("AW2TW_GRACE_TIME", 10))
    user_output(
        f"Use timew undo if you don't agree!  You have {grace_time} seconds to press ctrl^c",
        attrs=["bold"],
    )
    sleep(grace_time)


## TODO: do we need this backward compatibility function?
## not really retag, more like expand tags?  But it's my plan to allow replacement and not only addings
def retag_by_rules(source_tags, cfg=None):
    """Apply retagging rules to expand tags.

    This is a module-level function for backward compatibility.
    Delegates to TagExtractor for the actual logic.

    Args:
        source_tags: Original set of tags
        cfg: Configuration dict (uses global config if None)

    Returns:
        Expanded set of tags after applying retag rules
    """
    if cfg is None:
        cfg = config
    # Create a temporary TagExtractor to use the logic
    temp_extractor = TagExtractor(config=cfg, event_fetcher=None)
    return temp_extractor.apply_retag_rules(source_tags)


def timew_retag(timew_info, dry_run=False, capture_to=None):
    """Retag the current TimeWarrior interval according to rules.

    Args:
        timew_info: Current TimeWarrior interval info, or None if no active tracking
        dry_run: If True, don't execute commands
        capture_to: Optional list to capture commands to

    Returns:
        Updated timew_info, or None if no active tracking
    """
    if timew_info is None:
        # No active tracking, nothing to retag
        return None

    source_tags = set(timew_info["tags"])
    new_tags = retag_by_rules(source_tags)
    if new_tags != source_tags:
        timew_run(["retag"] + list(new_tags), dry_run=dry_run, capture_to=capture_to)
        if not dry_run:
            timew_info = get_timew_info()
            if timew_info:  # Check if still active
                assert set(timew_info["tags"]) == new_tags
        return timew_info
    return timew_info
