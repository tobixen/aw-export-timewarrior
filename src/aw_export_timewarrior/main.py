import json
import logging
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from time import sleep, time

from termcolor import cprint

from .aw_client import EventFetcher
from .config import config
from .state import AfkState, StateManager
from .tag_extractor import TagExtractor
from .timew_tracker import TimewTracker

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


class StructuredFormatter(logging.Formatter):
    """
    Formatter that outputs structured logs with all relevant context.
    Can output in JSON format for analysis/export to OpenSearch.
    """

    def __init__(self, use_json: bool = False, run_mode: dict = None) -> None:
        super().__init__()
        self.use_json = use_json
        self.run_mode = run_mode or {}

    def format(self, record: logging.LogRecord) -> str:
        # Build structured log data
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add run mode information (for filtering in log analysis)
        if self.run_mode:
            log_data["run_mode"] = self.run_mode

        # Add custom fields if present
        for key in ["event_ts", "event_duration", "last_tick", "tags", "event_data"]:
            if hasattr(record, key):
                val = getattr(record, key)
                # Convert datetime and timedelta to strings
                if isinstance(val, datetime):
                    log_data[key] = val.isoformat()
                elif isinstance(val, timedelta):
                    log_data[key] = f"{val.total_seconds():.1f}s"
                elif isinstance(val, set):
                    log_data[key] = list(val)
                else:
                    log_data[key] = str(val)

        if self.use_json:
            return json.dumps(log_data)
        else:
            # Human-readable format with colors
            return self._format_human(log_data, record.levelno)

    def _format_human(self, log_data: dict, level: int) -> str:
        """Format log data in a human-readable way with optional colors."""
        now = datetime.now().strftime("%H:%M:%S")
        last_tick = log_data.get("last_tick", "XX:XX:XX")
        event_ts = log_data.get("event_ts", "")

        # Build timestamp prefix
        ts_prefix = f"{now} / {last_tick} / {event_ts}" if event_ts else f"{now} / {last_tick}"

        # Add duration if present
        if "event_duration" in log_data:
            ts_prefix += log_data["event_duration"]

        # Build message with context
        msg = log_data["message"]
        if "tags" in log_data:
            msg = f"{msg} (tags: {log_data['tags']})"
        if "event_data" in log_data:
            msg = f"{msg} (data: {log_data['event_data']})"

        full_msg = f"{ts_prefix}: {msg}"

        # No color formatting here - that's handled by the handler
        return full_msg


class ColoredConsoleHandler(logging.StreamHandler):
    """
    Console handler that adds colors based on log level.
    Warnings are bold, errors/criticals are bold and red.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            attrs = []
            color = None

            # Map log levels to visual attributes
            if record.levelno > logging.ERROR:
                attrs = ["bold", "blink"]
                color = "red"
            elif record.levelno > logging.WARNING:
                attrs = ["bold"]
                color = "red"
            elif record.levelno > logging.INFO:
                # User-facing output - keep it clean
                attrs = ["bold"]
                color = "red"
            elif record.levelno == logging.INFO:
                color = "yellow"
            # DEBUG level gets no special formatting

            if color or attrs:
                cprint(msg, color=color, attrs=attrs, file=self.stream)
            else:
                self.stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logging(
    json_format: bool = False,
    log_level: int = logging.DEBUG,
    console_log_level: int = logging.ERROR,
    log_file: str = None,
    run_mode: dict = None,
) -> None:
    """
    Set up the logging system.

    Args:
        json_format: If True, output logs in JSON format
        level: Logging level (default: INFO)
        log_file: Optional file path to write logs to. If None, logs to console.
        run_mode: Optional dict with run mode info (dry_run, export_data, test_data, etc.) for filtering logs
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # If logging to file, use file handler; otherwise use console
    if log_file and log_level:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        file_handler.setFormatter(StructuredFormatter(use_json=json_format, run_mode=run_mode))
        root_logger.addHandler(file_handler)
    if console_log_level:
        # Console handler with colors
        console_handler = ColoredConsoleHandler(sys.stdout)
        console_handler.setLevel(console_log_level)
        console_handler.setFormatter(StructuredFormatter(run_mode=run_mode))
        root_logger.addHandler(console_handler)


# Initialize logging with defaults
# This will be reconfigured by CLI with appropriate parameters
# For direct imports/testing, use basic console logging
setup_logging(log_file=None)  # Console logging by default until CLI configures it


def user_output(msg: str, color: str = None, attrs: list = None) -> None:
    """
    Output message to the user (program output, not debug logging).
    This is separate from logging and is for user-facing program output.

    Args:
        msg: Message to display to the user
        color: Optional color (e.g., 'yellow', 'red', 'white')
        attrs: Optional attributes (e.g., ['bold'], ['bold', 'blink'])
    """
    if color or attrs:
        cprint(msg, color=color, attrs=attrs)
    else:
        print(msg)


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


def ts2str(ts, format="%FT%H:%M:%S"):
    return ts.astimezone().strftime(format)


def ts2strtime(ts):
    if not ts:
        return "XX:XX:XX:"
    return ts2str(ts, "%H:%M:%S")


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

        ## TODO: we don't need to consider backward compatibility
        # Maintain backward compatibility - expose EventFetcher properties
        self.aw = self.event_fetcher.aw
        self.buckets = self.event_fetcher.buckets
        self.bucket_by_client = self.event_fetcher.bucket_by_client
        self.bucket_short = self.event_fetcher.bucket_short

        # Initialize TagExtractor for all tag matching logic
        # Pass lambda to support tests that change config after initialization
        self.tag_extractor = TagExtractor(
            config=lambda: self.config,
            event_fetcher=self.event_fetcher,
            terminal_apps=self.terminal_apps,
            log_callback=self.log,
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
                assert bucketclient in self.bucket_by_client
            self.event_fetcher.check_bucket_freshness()

    ## TODO: perhaps better to have an _assert method
    def breakpoint(self, reason: str = "Unexpected condition"):
        self.log(f"ASSERTION FAILED: {reason}", level=logging.ERROR)
        if self.enable_pdb:
            breakpoint()
        elif self.enable_assert:
            raise AssertionError(reason)

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

    def show_unmatched_events_report(self, limit: int = 10) -> None:
        """Display a report of events that didn't match any rules.

        Args:
            limit: Maximum number of output lines to show (default: 10)
        """
        if not self.unmatched_events:
            print("\nNo unmatched events found - all events matched configuration rules.")
            return

        print("\n" + "=" * 80)
        print("Events Not Matching Any Rules")
        print("=" * 80)

        # Calculate total unmatched time
        total_unmatched_seconds = sum(
            (e["duration"].total_seconds() for e in self.unmatched_events), 0
        )
        print(
            f"\nFound {len(self.unmatched_events)} unmatched events, {total_unmatched_seconds/60:.1f} min total:\n"
        )

        # Group by app and title for easier analysis
        by_app = defaultdict(list)

        for event in self.unmatched_events:
            app = event["data"].get("app", "unknown")
            by_app[app].append(event)

        # Sort apps by total duration (descending)
        app_durations = [
            (app, sum(e["duration"].total_seconds() for e in events))
            for app, events in by_app.items()
        ]
        app_durations.sort(key=lambda x: x[1], reverse=True)

        lines_printed = 5  # Header + summary lines already printed
        for app, app_total_seconds in app_durations:
            if lines_printed >= limit:
                remaining_apps = len(app_durations) - app_durations.index((app, app_total_seconds))
                print(f"\n... and {remaining_apps} more apps (use --limit to show more)")
                break

            events = by_app[app]
            print(f"\n{app} ({len(events)} events, {app_total_seconds/60:.1f} min total):")
            lines_printed += 2  # App header + blank line

            # Group by title and sum durations
            title_durations = defaultdict(float)
            title_count = defaultdict(int)
            for event in events:
                title = event["data"].get("title", "(no title)")
                title_durations[title] += event["duration"].total_seconds()
                title_count[title] += 1

            # Sort titles by duration (descending) and show top titles
            sorted_titles = sorted(title_durations.items(), key=lambda x: x[1], reverse=True)

            # Calculate how many titles we can show
            remaining_lines = limit - lines_printed
            # Reserve 1 line for potential long tail summary, but show all titles if space allows
            max_titles = max(0, remaining_lines - 1) if remaining_lines > 1 else 0

            for title, duration_seconds in sorted_titles[:max_titles]:
                count = title_count[title]
                title_display = title[:60] + "..." if len(title) > 60 else title
                print(f"  {duration_seconds/60:5.1f}min ({count:2d}x) - {title_display}")
                lines_printed += 1

            # Show "long tail" summary
            if len(sorted_titles) > max_titles:
                remaining_count = len(sorted_titles) - max_titles
                remaining_time = sum(duration for _, duration in sorted_titles[max_titles:])
                remaining_events = sum(
                    title_count[title] for title, _ in sorted_titles[max_titles:]
                )
                print(
                    f"  {remaining_time/60:5.1f}min ({remaining_events:2d}x) - ... and {remaining_count} other titles"
                )
                lines_printed += 1

        print("\n" + "=" * 80 + "\n")

    def set_known_tick_stats(
        self,
        event=None,
        start=None,
        end=None,
        manual=False,
        tags=None,
        reset_accumulator=False,
        retain_accumulator=True,
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
        """
        # Extract timestamps
        if event and not start:
            start = event["timestamp"]
        if event and not end:
            end = event["timestamp"] + event["duration"]
        if start and not end:
            end = start

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
    def ensure_tag_exported(self, tags, event, since=None):
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
                self.breakpoint(
                    f"last_activity_run_time ({last_activity_run_time.total_seconds()}s) < self.min_recording_interval-3 ({self.min_recording_interval-3}s), last_start_time={self.state.last_start_time}, since={since}"
                )

            ## If the tracked time is less than the known events time we've counted
            ## then something is a little bit wrong.
            if tags != {"afk"} and tracked_gap < self.state.stats.known_events_time:
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
                    f"Large gap ({tracked_gap.total_seconds()}s) with low known activity ({(self.state.stats.known_events_time/tracked_gap):.1%}), tagging as UNKNOWN",
                    event=event,
                    level=logging.WARNING,
                )
                tags = {"UNKNOWN", "not-afk"}

        if "afk" in tags:
            self.state.set_afk_state(AfkState.AFK)

        # For AFK events, only advance last_known_tick to the START of the interval,
        # not the END. This prevents skipping window events that occurred during AFK.
        # AFK events overlap with window events (user AFK while window active).
        if "afk" in tags:
            self.set_known_tick_stats(start=since, end=since)
        else:
            self.set_known_tick_stats(event=event, start=since)

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
            if set(tags).issubset(self.timew_info["tags"]):
                return
        tags = retag_by_rules(tags, self.config)
        assert not exclusive_overlapping(tags, self.config)

        # Check if tags are exactly the same as current tags (after rule application)
        # This prevents redundant timew start commands when tags haven't changed
        final_tags = tags | {"~aw"}  # Add ~aw tag as it's always added
        if self.timew_info is not None and final_tags == self.timew_info["tags"]:
            return

        # Look up ask-away message for this event and extract tags from it
        if hasattr(self, "_ask_away_messages") and self._ask_away_messages:
            event_key = (event["timestamp"], event["duration"])
            message = self._ask_away_messages.get(event_key)
            if message:
                # Create synthetic event with message as title for tag extraction
                synthetic_event = {
                    "timestamp": event["timestamp"],
                    "duration": event["duration"],
                    "data": {"app": "ask-away", "title": message},
                }
                # Extract tags from the message using tag extraction rules
                message_tags = self.tag_extractor.get_app_tags(synthetic_event)
                if message_tags and message_tags is not False:
                    if isinstance(message_tags, set):
                        final_tags = final_tags | message_tags
                    else:
                        final_tags = final_tags | set(message_tags)

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
        new_tags = self.tag_extractor.apply_retag_rules(source_tags)

        # Retag if tags changed
        if new_tags != source_tags:
            self.tracker.retag(new_tags)
            # Get updated info
            if not self.dry_run:
                timew_info = self.tracker.get_current_tracking()
                if timew_info:  # Check if still active
                    assert (
                        set(timew_info["tags"]) == new_tags
                    ), f"Expected {new_tags}, got {timew_info['tags']}"

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
                ## Something must have gone wrong somewhere?
                self.breakpoint()
            if "not-afk" in tags:
                self._afk_change_stats("not-afk", tags, event)
                self.log(
                    f"You have returned to the keyboard after {(event['timestamp']-self.state.last_start_time).total_seconds()}s absence",
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
            - IGNORED if event too short
            - NO_MATCH if event processed but no tags found
            - MATCHED if tags were extracted
        """
        if event["duration"].total_seconds() < self.ignore_interval:
            return TagResult(
                result=EventMatchResult.IGNORED, reason="Event duration below ignore_interval"
            )

        # Delegate to TagExtractor for all tag matching logic
        for method in (
            self.tag_extractor.get_afk_tags,
            self.tag_extractor.get_app_tags,
            self.tag_extractor.get_browser_tags,
            self.tag_extractor.get_editor_tags,
        ):
            tags = method(event)
            if tags is not False:
                break

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
                tags = retag_by_rules(tag_result.tags, self.config)

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
                tags = retag_by_rules(tag_result.tags, self.config)

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

            # Determine AFK status based on lid/suspend state
            # Lid closed or suspended -> afk
            # Lid open or resumed -> not-afk
            if data.get("lid_state") == "closed" or data.get("suspend_state") == "suspended":
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

        # For now, simple concatenation - lid events will be processed alongside AFK events
        # The event processing logic will naturally handle overlaps since events are sorted by timestamp
        # TODO Phase 4+: Add sophisticated conflict resolution for overlapping periods
        merged = afk_events + converted_lid_events
        merged.sort(key=lambda x: x["timestamp"])

        return merged

    def _fetch_and_prepare_events(self) -> tuple[list, dict | None]:
        """Fetch, filter, merge, and sort events from ActivityWatch.

        Returns:
            Tuple of (completed_events, current_event):
            - completed_events: List of finished events to process
            - current_event: The ongoing event (or None)
        """
        afk_id = self.bucket_by_client["aw-watcher-afk"][0]
        window_id = self.bucket_by_client["aw-watcher-window"][0]

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
                # Store ask-away messages for later annotation
                self._ask_away_messages = {
                    (e["timestamp"], e["duration"]): e["data"].get("message", "")
                    for e in ask_away_events
                }
        else:
            self._ask_away_messages = {}

        # Fetch window events and merge with merged AFK events
        afk_window_events = (
            self.event_fetcher.get_events(window_id, start=self.state.last_tick, end=self.end_time)
            + merged_afk_events
        )
        afk_window_events.sort(key=lambda x: x["timestamp"])

        # Split window events that overlap with AFK periods
        # This ensures window events are properly interrupted by AFK
        afk_window_events = self._split_window_events_by_afk(afk_window_events, merged_afk_events)

        # Filter out split events that end before or at last_tick to avoid reprocessing
        # This can happen when we fetch an event that overlaps with last_tick, split it,
        # and end up with segments that we've already processed
        if self.state.last_tick:
            afk_window_events = [
                e
                for e in afk_window_events
                if e["timestamp"] + e["duration"] > self.state.last_tick
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
            window_start = window_event["timestamp"]
            window_end = window_event["timestamp"] + window_event["duration"]

            # Find overlapping AFK events
            overlapping_afk = [
                afk
                for afk in afk_events
                if afk["data"].get("status") == "afk"
                and afk["timestamp"] < window_end
                and (afk["timestamp"] + afk["duration"]) > window_start
            ]

            if not overlapping_afk:
                # No overlap, keep window event as-is
                result.append(window_event)
                continue

            # Sort AFK events by timestamp
            overlapping_afk.sort(key=lambda x: x["timestamp"])

            # Split window event at AFK boundaries
            current_time = window_start
            for afk_event in overlapping_afk:
                afk_start = afk_event["timestamp"]
                afk_end = afk_event["timestamp"] + afk_event["duration"]

                # Add window portion before AFK (if any)
                if current_time < afk_start and afk_start < window_end:
                    result.append(
                        {
                            **window_event,
                            "timestamp": current_time,
                            "duration": afk_start - current_time,
                        }
                    )

                # Move current_time to after this AFK period
                current_time = max(current_time, afk_end)

            # Add remaining window portion after all AFK periods (if any)
            if current_time < window_end:
                result.append(
                    {
                        **window_event,
                        "timestamp": current_time,
                        "duration": window_end - current_time,
                    }
                )

        # Add all status events back and re-sort
        result.extend(status_events)
        result.sort(key=lambda x: x["timestamp"])

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
    ) -> tuple[bool, set[str], datetime]:
        """Decide if accumulator should be exported and get tags to export.

        Args:
            interval_since_last_tick: Time since last known tick
            event: Current event being processed

        Returns:
            Tuple of (should_export, tags_to_export, since_timestamp):
            - should_export: True if accumulator should be exported
            - tags_to_export: Set of tags that should be exported
            - since_timestamp: Timestamp to use for export
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
            return False, set(), self.state.last_known_tick

        self.log("Emptying the accumulator!")

        # Build set of tags that meet the threshold
        tags = set()

        # TODO: This looks like a bug - we reset tags, and then assert that they are not overlapping?
        assert not exclusive_overlapping(tags, self.config)

        # Find minimum threshold that avoids exclusive tag conflicts
        min_tag_recording_interval = self.min_tag_recording_interval
        while exclusive_overlapping(
            {
                tag
                for tag in self.state.stats.tags_accumulated_time
                if self.state.stats.tags_accumulated_time[tag].total_seconds()
                > min_tag_recording_interval
            },
            self.config,
        ):
            min_tag_recording_interval += 1

        # Collect tags above threshold and apply stickyness
        for tag in self.state.stats.tags_accumulated_time:
            if (
                self.state.stats.tags_accumulated_time[tag].total_seconds()
                > min_tag_recording_interval
            ):
                tags.add(tag)
            self.state.stats.tags_accumulated_time[tag] *= self.stickyness_factor

        # Determine since timestamp
        if self.state.manual_tracking:
            since = event["timestamp"] - self.state.stats.known_events_time + event["duration"]
        else:
            since = self.state.last_known_tick

        return True, tags, since

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
            tags = retag_by_rules(tag_result.tags, self.config)
            for tag in tags:
                self.state.stats.tags_accumulated_time[tag] += event["duration"]

    def find_next_activity(self):
        ## TODO: move all statistics from internal counters and up to the object

        ## Skipped events are events that takes so little time that we ignore it completely.
        ## The counter is nulled out when some non-skipped event comes in.
        ## Used only for debug logging.
        num_skipped_events = 0

        ## Unknown events are events lasting for some time, but without any
        ## rules identifying any tags.
        ## Nulled out only at the beginning of the function
        num_unknown_events = 0

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
                self.state.stats.known_events_time += event["duration"]

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

            # Track unknown events count
            if tag_result.result == EventMatchResult.NO_MATCH:
                num_unknown_events += 1

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
            should_export, tags_to_export, since = self._should_export_accumulator(
                interval_since_last_known_tick, event
            )
            if should_export:
                self.log(f"Ensuring tags export, tags={tags_to_export}")
                self.ensure_tag_exported(tags_to_export, event, since)

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


def check_bucket_updated(bucket: dict) -> None:
    aw_warn_threshold = float(os.environ.get("AW2TW_AW_WARN_THRESHOLD", 300))
    if (
        not bucket["last_updated_dt"]
        or time() - bucket["last_updated_dt"].timestamp() > aw_warn_threshold
    ):
        logger.warning(f"Bucket {bucket['id']} seems not to have recent data!")


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


## TODO: do we need this?
def exclusive_overlapping(tags, cfg=None):
    """Check if tags violate exclusive group rules.

    This is a module-level function for backward compatibility.
    Delegates to TagExtractor for the actual logic.

    Args:
        tags: Set of tags to check
        cfg: Configuration dict (uses global config if None)

    Returns:
        True if tags violate exclusivity (conflict detected)
    """
    if cfg is None:
        cfg = config
    # Create a temporary TagExtractor to use the logic
    temp_extractor = TagExtractor(config=cfg, event_fetcher=None)
    return temp_extractor.check_exclusive_groups(tags)


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


def main():
    exporter = Exporter()
    while True:
        should_continue = exporter.tick()
        if not should_continue:
            break
        # Always sleep briefly to prevent busy-waiting and reduce CPU usage
        sleep(0.1)  # Small delay to prevent 100% CPU when processing events


if __name__ == "__main__":
    main()
