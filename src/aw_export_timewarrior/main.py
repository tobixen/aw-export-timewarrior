import aw_client
import subprocess
import json
import logging
from time import time, sleep
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
from termcolor import cprint
import re
import os
import sys

## We have lots of breakpoints in the code.  Remove this line while debugging/developing ...
breakpoint = lambda: None

from .config import config

# Configure structured logging
logger = logging.getLogger(__name__)

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
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Add run mode information (for filtering in log analysis)
        if self.run_mode:
            log_data['run_mode'] = self.run_mode

        # Add custom fields if present
        for key in ['event_ts', 'event_duration', 'last_tick', 'tags', 'event_data']:
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
        now = datetime.now().strftime('%H:%M:%S')
        last_tick = log_data.get('last_tick', 'XX:XX:XX')
        event_ts = log_data.get('event_ts', '')

        # Build timestamp prefix
        if event_ts:
            ts_prefix = f"{now} / {last_tick} / {event_ts}"
        else:
            ts_prefix = f"{now} / {last_tick}"

        # Add duration if present
        if 'event_duration' in log_data:
            ts_prefix += log_data['event_duration']

        # Build message with context
        msg = log_data['message']
        if 'tags' in log_data:
            msg = f"{msg} (tags: {log_data['tags']})"
        if 'event_data' in log_data:
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
                attrs = ['bold', 'blink']
                color = 'red'
            elif record.levelno > logging.WARNING:
                attrs = ['bold']
                color = 'red'
            elif record.levelno > logging.INFO:
                # User-facing output - keep it clean
                attrs = ['bold']
                color = 'red'
            elif record.levelno == logging.INFO:
                color = 'yellow'
            # DEBUG level gets no special formatting

            if color or attrs:
                cprint(msg, color=color, attrs=attrs, file=self.stream)
            else:
                self.stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

def setup_logging(json_format: bool = False, log_level: int = logging.DEBUG, console_log_level: int = logging.ERROR, log_file: str = None, run_mode: dict = None) -> None:
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

## Those should be moved to config.py before releasing.  Possibly renamed.
AW_WARN_THRESHOLD=float(os.environ.get('AW2TW_AW_WARN_THRESHOLD') or 300) ## the recent data from activity watch should not be elder than this
SLEEP_INTERVAL=float(os.environ.get('AW2TW_SLEEP_INTERVAL') or 30) ## Sleeps between each run when the program is run in real-time
IGNORE_INTERVAL=float(os.environ.get('AW2TW_IGNORE_INTERVAL') or 3) ## ignore any window visits lasting for less than five seconds (TODO: may need tuning if terminal windows change title for every command run)
MIN_RECORDING_INTERVAL=float(os.environ.get('AW2TW_MIN_RECORDING_INTERVAL') or 90) ## Never record an activities more frequently than once per minute.
MIN_TAG_RECORDING_INTERVAL=float(os.environ.get('AW2TW_MIN_TAG_RECORDING_INTERVAL') or 50) ## When recording something, include every tag that has been observed for more than 50s
STICKYNESS_FACTOR=float(os.environ.get('AW2TW_STICKYNESS_FACTOR') or 0.2) ## Don't reset everything on each "tick".
MAX_MIXED_INTERVAL=float(os.environ.get('AW2TW_MAX_MIXED_INTERVAL') or 240) ## Any window event lasting for more than four minutes should be considered independently from what you did before and after

GRACE_TIME=float(os.environ.get('AW2TW_GRACE_TIME') or 10)

SPECIAL_TAGS={'manual', 'override', 'not-afk'}

MIN_RECORDING_INTERVAL_ADJ=MIN_RECORDING_INTERVAL*(1+STICKYNESS_FACTOR)
MIN_TAG_RECORDING_INTERVAL_ADJ=MIN_TAG_RECORDING_INTERVAL*(1+STICKYNESS_FACTOR)


def ts2str(ts, format="%FT%H:%M:%S"):
    return(ts.astimezone().strftime(format))

def ts2strtime(ts):
    if not ts:
        return "XX:XX:XX:"
    return ts2str(ts, "%H:%M:%S")

## We keep quite some statistics here, all the counters should be documented
## TODO: Resetting counters should be done through explicit methods in this class and
## not through arbitrary assignments in unrelated methods
@dataclass
class Exporter:
    ## self.tags_accumulated_time is a time counter for each tags that has been observed.
    ## When enough time has been counted, we'll look through and run ensure_tag_exported on the tags that has accumulated most time.
    ## self.tags_accumulated_time is cleared ...
    ## 1) when coming/going afk/not-afk
    ## 3) when some event has been going on for MAX_MIXED_INTERVAL
    ## 4) when some mixed events is recorded, the numbers are reduced - we
    ## spill over some of the content to the next recording interval, to reduce flapping
    tags_accumulated_time: defaultdict = field(default_factory=lambda: defaultdict(timedelta))

    ## Last tick is updated all the time.  It's the end time of the last event handled.
    ## Used for determinating when we should start fetching window information
    last_tick: datetime = None

    ## last known tick is the end time of the last event causing tags to be "ensured"
    ## (that is, exported if needed).  Should be set in the ensure algorithm.
    last_known_tick: datetime = None

    ## last known start time is the start time of the last event causing tags to be "ensured".
    ## (that is, exported if needed).  Should be set in the ensure algorithm.
    last_start_time: datetime = None

    ## Assume we're afk when script is started ... but ... why?
    afk: bool = None

    ## total_time_known_events is summing up the time spent on
    ## tag-generating activities since last time a tag was
    ## recorded.  So it should be nulled out only when ensure_tag
    ## is run It is useful for debugging; if
    ## total_time_known_events is very low compared to the time
    ## since last known tick, then something is wrong.
    total_time_known_events: timedelta = timedelta(0)

    ## Special case when one has just arrived to the computer.  It's
    ## important that all the not-afk time is tagged up.  Should be
    ## not-None only when the time hasn't been tagged yet.  TODO:
    ## better naming?
    last_not_afk: datetime = None

    ## manual_tracking is set to True whenever you have used timew manually
    manual_tracking: bool = True

    ## Information from timew about the current tagging
    timew_info: dict = None

    ## This is not quite reliable
    total_time_unknown_events: timedelta = timedelta(0)

    ## Testing and debugging options
    dry_run: bool = False  # If True, don't actually modify timewarrior
    verbose: bool = False  # If True, show detailed reasoning
    show_diff: bool = False  # If True, show diffs in dry-run mode
    show_fix_commands: bool = False  # If True, show timew track commands to fix differences
    apply_fix: bool = False  # If True, execute timew track commands to fix differences
    hide_diff_report: bool = False  # If True, hide the detailed comparison report
    hide_processing_output: bool = False  # If True, hide "would execute" messages
    show_unmatched: bool = False  # If True, show events that didn't match any rules
    enable_pdb: bool = False  # If True, drop into debugger on unexpected states
    config_path: str = None  # Optional path to config file
    test_data: dict = None  # Optional test data instead of querying AW
    start_time: datetime = None  # Optional start time for processing window
    end_time: datetime = None  # Optional end time for processing window
    captured_commands: list = field(default_factory=list)  # Captures timew commands in dry-run mode for testing
    unmatched_events: list = field(default_factory=list)  # Tracks events that didn't match any rules

    def __post_init__(self):
        # Load custom config if provided
        if self.config_path:
            from . import config as config_module
            config_module.load_custom_config(self.config_path)
            self.config = config_module.config
        else:
            from .config import config as global_config
            self.config = global_config

        ## data fetching - skip if using test data
        if not self.test_data:
            if self.dry_run:
                client_name = "timewarrior_test_export"
            else:
                client_name = "timewarrior_export"
            self.aw = aw_client.ActivityWatchClient(client_name=client_name)
            self.buckets = self.aw.get_buckets()
        else:
            # Using test data - create mock AW client
            self.aw = None
            self.buckets = self.test_data.get('buckets', {})

        self.bucket_by_client = defaultdict(list)
        self.bucket_short = {}

        for x in self.buckets:
            lu = self.buckets[x].get('last_updated')
            self.buckets[x]['last_updated_dt'] = datetime.fromisoformat(lu) if lu else None
            client = self.buckets[x]['client']
            self.bucket_by_client[client].append(x)
            bucket_short = x[:x.find('_')]
            assert not bucket_short in self.bucket_short
            self.bucket_short[bucket_short] = self.buckets[x]
        # Only check bucket freshness when using real ActivityWatch data
        if not self.test_data:
            for bucketclient in ('aw-watcher-window', 'aw-watcher-afk'):
                assert bucketclient in self.bucket_by_client
                for b in self.bucket_by_client[bucketclient]:
                    check_bucket_updated(self.buckets[b])

    def load_test_data(self, file_path):
        """Load test data from a JSON/YAML file."""
        from .export import load_test_data as load_file
        self.test_data = load_file(file_path)
        # Reinitialize with test data
        self.__post_init__()

    def get_captured_commands(self):
        """
        Get the list of captured timew commands.

        Returns:
            List of command lists, e.g. [['timew', 'start', 'tag1', 'tag2', '2025-01-01T10:00:00'], ...]
        """
        return self.captured_commands

    def clear_captured_commands(self):
        """Clear the captured commands list."""
        self.captured_commands.clear()

    def get_suggested_intervals(self):
        """
        Extract suggested intervals from captured timew commands.

        Returns:
            List of SuggestedInterval objects
        """
        from .compare import SuggestedInterval

        intervals = []
        current_start = None
        current_tags = set()

        for cmd in self.captured_commands:
            if len(cmd) < 2:
                continue

            command = cmd[1]  # 'start', 'stop', etc.

            if command == 'start':
                # Extract tags and timestamp
                # Format: ['timew', 'start', 'tag1', 'tag2', ..., '2025-01-01T10:00:00']
                tags = set(cmd[2:-1])  # All elements between 'start' and timestamp
                timestamp_str = cmd[-1]

                # Parse timestamp - timestamps in commands are in local timezone
                # (because they're generated with since.astimezone().strftime())
                start = datetime.fromisoformat(timestamp_str.replace('T', ' ', 1).rstrip('Z'))
                if start.tzinfo is None:
                    # Assume local timezone, then convert to UTC
                    start = start.astimezone(timezone.utc)

                # If there was a previous interval, close it
                if current_start:
                    intervals.append(SuggestedInterval(
                        start=current_start,
                        end=start,
                        tags=current_tags
                    ))

                # Start new interval
                current_start = start
                current_tags = tags

            elif command == 'stop' and current_start:
                # Close current interval
                # May have timestamp as last arg
                if len(cmd) > 2 and cmd[-1].count('T') == 1:
                    end = datetime.fromisoformat(cmd[-1].replace('T', ' ', 1).rstrip('Z'))
                    if end.tzinfo is None:
                        # Assume local timezone, then convert to UTC
                        end = end.astimezone(timezone.utc)
                else:
                    end = datetime.now(timezone.utc)

                intervals.append(SuggestedInterval(
                    start=current_start,
                    end=end,
                    tags=current_tags
                ))

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
        from .compare import fetch_timew_intervals, compare_intervals, format_diff_output, generate_fix_commands

        if not self.show_diff:
            return {}

        if not self.start_time or not self.end_time:
            raise ValueError("show_diff mode requires start_time and end_time to be set")

        # Fetch what's in TimeWarrior
        timew_intervals = fetch_timew_intervals(self.start_time, self.end_time)

        # Get what we suggested
        suggested_intervals = self.get_suggested_intervals()

        # Compare
        comparison = compare_intervals(timew_intervals, suggested_intervals)

        # Display comparison report (unless hidden)
        if not self.hide_diff_report:
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
                        print(f"Executing: {cmd}")
                        # Parse and execute the command
                        import subprocess
                        try:
                            result = subprocess.run(
                                cmd.split(),
                                capture_output=True,
                                text=True,
                                check=True
                            )
                            print("  ✓ Success")
                        except subprocess.CalledProcessError as e:
                            print(f"  ✗ Failed: {e.stderr}")

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

    def show_unmatched_events_report(self) -> None:
        """Display a report of events that didn't match any rules."""
        if not self.unmatched_events:
            print("\nNo unmatched events found - all events matched configuration rules.")
            return

        print("\n" + "=" * 80)
        print("Events Not Matching Any Rules")
        print("=" * 80)

        # Calculate total unmatched time
        total_unmatched_seconds = sum((e['duration'].total_seconds() for e in self.unmatched_events), 0)
        print(f"\nFound {len(self.unmatched_events)} unmatched events, {total_unmatched_seconds/60:.1f} min total:\n")

        # Group by app and title for easier analysis
        from collections import defaultdict
        by_app = defaultdict(list)

        for event in self.unmatched_events:
            app = event['data'].get('app', 'unknown')
            by_app[app].append(event)

        # Sort apps by total duration (descending)
        app_durations = [(app, sum(e['duration'].total_seconds() for e in events))
                         for app, events in by_app.items()]
        app_durations.sort(key=lambda x: x[1], reverse=True)

        for app, app_total_seconds in app_durations:
            events = by_app[app]
            print(f"\n{app} ({len(events)} events, {app_total_seconds/60:.1f} min total):")

            # Group by title and sum durations
            title_durations = defaultdict(float)
            title_count = defaultdict(int)
            for event in events:
                title = event['data'].get('title', '(no title)')
                title_durations[title] += event['duration'].total_seconds()
                title_count[title] += 1

            # Sort titles by duration (descending) and show top 5
            sorted_titles = sorted(title_durations.items(), key=lambda x: x[1], reverse=True)

            for title, duration_seconds in sorted_titles[:5]:
                count = title_count[title]
                title_display = title[:60] + "..." if len(title) > 60 else title
                print(f"  {duration_seconds/60:5.1f}min ({count:2d}x) - {title_display}")

            # Show "long tail" summary
            if len(sorted_titles) > 5:
                remaining_count = len(sorted_titles) - 5
                remaining_time = sum(duration for _, duration in sorted_titles[5:])
                remaining_events = sum(title_count[title] for title, _ in sorted_titles[5:])
                print(f"  {remaining_time/60:5.1f}min ({remaining_events:2d}x) - ... and {remaining_count} other titles")

        print("\n" + "=" * 80 + "\n")

    def get_events(self, bucket_id, start=None, end=None):
        """Get events from ActivityWatch or test data."""
        if self.test_data:
            # Return events from test data
            events = self.test_data.get('events', {}).get(bucket_id, [])

            # Convert dict events to Event objects supporting both dict and attribute access
            class Event(dict):
                def _convert_value(self, key, val):
                    """Convert values for consistency between dict and attribute access."""
                    # Convert timestamp strings to datetime
                    if key == 'timestamp' and isinstance(val, str):
                        return datetime.fromisoformat(val)
                    # Convert duration to timedelta
                    if key == 'duration' and isinstance(val, (int, float)):
                        return timedelta(seconds=val)
                    return val

                def __getitem__(self, key):
                    val = super().__getitem__(key)
                    return self._convert_value(key, val)

                def __getattr__(self, key):
                    if key.startswith('_'):
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
        else:
            return self.aw.get_events(bucket_id, start=start, end=end)

    def set_known_tick_stats(self, event=None, start=None, end=None, manual=False, tags=None, reset_accumulator=False, retain_accumulator=True):
        if event and not start:
            start = event['timestamp']
        if event and not end:
            end = event['timestamp'] + event['duration']
        if start and not end:
            end = start
        self.last_known_tick = end
        self.last_tick = end
        self.last_start_time = start
        self.manual_tracking = manual
        self.total_time_unknown_events = timedelta(0)
        if reset_accumulator:
            self.tags_accumulated_time = defaultdict(timedelta)
            if retain_accumulator:
                for tag in tags:
                    self.tags_accumulated_time[tag] = STICKYNESS_FACTOR*MIN_RECORDING_INTERVAL
        self.total_time_known_events = timedelta(0)                


    ## TODO: move all dealings with statistics to explicit statistics-handling methods
    def ensure_tag_exported(self, tags, event, since=None):
        if since is None:
            since = event['timestamp']

        if isinstance(tags, str):
            tags = { tags }

        ## Now, the previously tagged thing has been running (at least) since self.last_known_tick,
        ## no matter if we have activity supporting it or not since self.last_known_tick.
        last_activity_run_time = since - self.last_start_time

        ## We'd like to compare with self.total_time_known_event, but it's counted from the end of the previous event to the end of the current event
        tracked_gap = event['timestamp'] + event['duration'] - self.last_known_tick

        ## if the time tracked is significantly less than the minimum
        ## time we're supposed to track, something is also probably
        ## wrong and should be investigated
        if tags != { 'afk' } and not self.afk and not self.manual_tracking and last_activity_run_time.total_seconds() < MIN_RECORDING_INTERVAL-3:
            breakpoint()

        ## If the tracked time is less than the known events time we've counted
        ## then something is a little bit wrong.
        if tags != { 'afk' } and tracked_gap < self.total_time_known_events:
            breakpoint()

        ## If he time tracked is way longer than the
        ## self.total_time_known_events, something is probably wrong
        ## and should be investigated
        if tags != { 'afk' } and tracked_gap.total_seconds()>MAX_MIXED_INTERVAL and self.total_time_known_events/tracked_gap < 0.3 and not self.manual_tracking:
            breakpoint()

        if 'afk' in tags:
            self.afk = True

        self.set_known_tick_stats(event=event, start=since)

        # Only update timew_info if not in dry-run mode
        if not self.dry_run and not self.test_data:
            self.set_timew_info(timew_retag(get_timew_info(), capture_to=self.captured_commands))

        ## Special logic with 'override', 'manual' and 'unknown' should be documented or removed!
        if 'override' in self.timew_info['tags']:
            return
        if 'manual' in self.timew_info['tags'] and 'unknown' in tags:
            return
        if set(tags).issubset(self.timew_info['tags']):
            return
        tags = retag_by_rules(tags, self.config)
        assert not exclusive_overlapping(tags, self.config)
        timew_run(['start'] + list(tags) + ['~aw', since.astimezone().strftime('%FT%H:%M:%S')],
                  dry_run=self.dry_run or bool(self.test_data),
                  capture_to=self.captured_commands if self.dry_run else None,
                  hide_output=self.hide_processing_output)

        # Only update timew_info after command if not in dry-run mode
        if not self.dry_run and not self.test_data:
            self.set_timew_info(timew_retag(get_timew_info(), dry_run=self.dry_run, capture_to=self.captured_commands))

    def pretty_accumulator_string(self) -> str:
        a = self.tags_accumulated_time
        tags = [x for x in a if a[x].total_seconds() > MIN_TAG_RECORDING_INTERVAL]
        tags.sort(key=lambda x: -a[x])
        return "\n".join([f"{x}: {a[x].total_seconds():5.1f}s" for x in tags])

    def log(self, msg: str, tags=None, event=None, ts=None, level: int = logging.INFO, extra=None) -> None:
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
        extra.update({
            'last_tick': ts2strtime(self.last_tick) if self.last_tick else 'XX:XX:XX',
        })

        if ts:
            extra['ts'] = ts2strtime(ts)

        if event:
            extra['event_start'] = event['timestamp']
            extra['event_stop'] = event['timestamp'] + event['duration']
            extra['event_duration'] = f"+ {event['duration'].total_seconds():6.1f}s"
            if event.get('data'):
                extra['event_data'] = event['data']

        if tags:
            extra['tags'] = tags

        # Log with appropriate level
        logger.log(level, msg, extra=extra)

    def get_editor_tags(self, window_event):
        """Get tags for editor events."""
        return self._get_subevent_tags(
            window_event=window_event,
            subtype='editor',
            apps=('emacs', 'vi', 'vim'),
            bucket_pattern='aw-watcher-{app}',
            matchers=[
                ('projects', self._match_project),
                ('path_regexp', self._match_path_regexp),
            ]
        )

    def get_browser_tags(self, window_event):
        """Get tags for browser events."""
        return self._get_subevent_tags(
            window_event=window_event,
            subtype='browser',
            apps=('chromium', 'chrome', 'firefox'),
            bucket_pattern='aw-watcher-web-{app}',
            app_normalizer=lambda app: 'chrome' if app == 'chromium' else app,
            matchers=[
                ('url_regexp', self._match_url_regexp),
            ],
            skip_if=lambda sub_event: sub_event['data'].get('url') in ('chrome://newtab/', 'about:newtab')
        )

    def _is_ignorable_event(self, app: str, window_event: dict) -> bool:
        """Check if an event should be ignored (e.g., emacs internal buffers)."""
        if app == 'emacs':
            return bool(re.match(r'^( )?\*.*\*', window_event['data']['title']))
        return False

    def _match_project(self, rule: dict, sub_event: dict, rule_key: str):
        """Match editor events by project name."""
        for project in rule.get('projects', []):
            if project == sub_event['data'].get('project'):
                return self._build_tags(rule['timew_tags'])
        return None

    def _match_path_regexp(self, rule: dict, sub_event: dict, rule_key: str):
        """Match editor events by file path regexp."""
        return self._match_regexp(
            rule=rule,
            text=sub_event['data'].get('file', ''),
            rule_key=rule_key
        )

    def _match_url_regexp(self, rule: dict, sub_event: dict, rule_key: str):
        """Match browser events by URL regexp."""
        return self._match_regexp(
            rule=rule,
            text=sub_event['data'].get('url', ''),
            rule_key=rule_key
        )

    def _match_regexp(self, rule: dict, text: str, rule_key: str):
        """
        Generic regexp matcher with group substitution.

        Args:
            rule: The rule dict containing the regexp and timew_tags
            text: The text to match against
            rule_key: The key in the rule containing the regexp pattern

        Returns:
            Set of tags with substitutions applied, or None if no match
        """
        if rule_key not in rule:
            return None

        match = re.search(rule[rule_key], text)
        if not match:
            return None

        # Build substitutions from match groups
        substitutions = {}
        for i, group in enumerate(match.groups(), start=1):
            substitutions[f'${i}'] = group

        return self._build_tags(rule['timew_tags'], substitutions)

    def _build_tags(self, tag_templates: list, substitutions: dict = None):
        """
        Build a set of tags from templates with variable substitution.

        Args:
            tag_templates: List of tag templates (e.g., ['4work', 'github', '$1'])
            substitutions: Dict of {variable: value} for substitution (e.g., {'$1': 'python-caldav'})

        Returns:
            Set of tags with 'not-afk' added
        """
        substitutions = substitutions or {}
        tags = set()

        for tag in tag_templates:
            # Skip tags with variables that have no value
            if '$' in tag:
                # Try to substitute all variables
                new_tag = tag
                has_missing_var = False

                for var, value in substitutions.items():
                    if var in tag:
                        if value is None:
                            has_missing_var = True
                            break
                        new_tag = new_tag.replace(var, value)

                # Skip if we couldn't substitute all variables
                if has_missing_var or '$' in new_tag:
                    continue

                tags.add(new_tag)
            else:
                tags.add(tag)

        tags.add('not-afk')
        return tags

    def _get_subevent_tags(self, window_event: dict, subtype: str, apps: tuple,
                          bucket_pattern: str, app_normalizer=None, matchers=None, skip_if=None):
        """
        Generic method to extract tags from events that require sub-events.

        Args:
            window_event: The main window event
            subtype: Type of rule ('browser', 'editor')
            apps: Tuple of app names to match
            bucket_pattern: Pattern for bucket ID (e.g., 'aw-watcher-{app}')
            app_normalizer: Optional function to normalize app name (e.g., chromium -> chrome)
            matchers: List of (rule_key, matcher_function) tuples to try in order
            skip_if: Optional function that returns True if we should skip this sub_event

        Returns:
            Set of tags, empty list if no match, or False if wrong app type
        """
        # Check if this is the right app type
        if window_event['data'].get('app', '').lower() not in apps:
            return False

        app = window_event['data']['app'].lower()

        # Normalize app name if needed
        app_normalized = app_normalizer(app) if app_normalizer else app

        # Get the bucket ID
        bucket_id = self.bucket_short[bucket_pattern.format(app=app_normalized)]['id']

        # Determine if we should ignore certain events (e.g., emacs buffers)
        ignorable = self._is_ignorable_event(app, window_event)

        # Get the corresponding sub-event
        sub_event = self.get_corresponding_event(window_event, bucket_id, ignorable=ignorable)

        if not sub_event:
            return []

        # Check if we should skip this sub-event
        if skip_if and skip_if(sub_event):
            return []

        # Try each matcher in order
        for rule_key, matcher_func in (matchers or []):
            for rule_name in self.config.get('rules', {}).get(subtype, {}):
                rule = self.config['rules'][subtype][rule_name]

                # Skip rules that don't have this key
                if rule_key not in rule:
                    continue

                # Try to match
                tags = matcher_func(rule, sub_event, rule_key)
                if tags:
                    return tags

        # No rules matched
        self.log(
            f"Unhandled {subtype} event",
            event=window_event,
            extra={'sub_event': sub_event, 'event_type': subtype, 'log_event': 'unhandled'},
            level=logging.WARNING
        )
        return []

    ## TODO - remove hard coded constants!
    def get_corresponding_event(self, window_event, event_type_id, ignorable=False, retry=6):
        ret = self.get_events(event_type_id, start=window_event['timestamp']-timedelta(seconds=1), end=window_event['timestamp']+window_event['duration'])

        ## If nothing found ... try harder
        if not ret and not ignorable and retry:
            ## Perhaps the event hasn't reached ActivityWatch yet?  Perhaps it helps to sleep?
            ## Obviously, it may only help if the wall clock matches the event time
            if time() - SLEEP_INTERVAL*3 < (window_event['timestamp'] + window_event['duration']).timestamp():
                self.log(f"Event details for {window_event} not in yet, attempting to sleep for a while", event=window_event)
                sleep(SLEEP_INTERVAL*3/retry+0.2)
                retry -= 1
                return self.get_corresponding_event(window_event, event_type_id, ignorable, retry)
        
        if not ret and not ignorable:
            ret = self.get_events(event_type_id, start=window_event['timestamp']-timedelta(seconds=15), end=window_event['timestamp']+window_event['duration']+timedelta(seconds=15))
        if not ret:
            if not ignorable and not window_event['duration']<timedelta(seconds=IGNORE_INTERVAL*4):
                self.log(f"No corresponding {event_type_id} found.  Window title: {window_event['data']['title']}.  If you see this often, you should verify that the relevant watchers are active and running.", event=window_event)
            return None
        if len(ret)>1:
            ret2 = [x for x in ret if x.duration > timedelta(seconds=IGNORE_INTERVAL)]
            if ret2:
                ret = ret2
            ## TODO this is maybe too simplistic
            ret.sort(key=lambda x: -x['duration'])
        return ret[0]

    def get_app_tags(self, event):
        """
        Get tags for app events (doesn't need sub-events).

        Args:
            event: The window event

        Returns:
            Set of tags, or False if no rules matched
        """
        for rule_name in self.config.get('rules', {}).get('app', {}):
            rule = self.config['rules']['app'][rule_name]

            # Check if app matches
            if event['data'].get('app') not in rule.get('app_names', []):
                continue

            # Try to match title regexp if present
            title_match = None
            if 'title_regexp' in rule:
                title_match = re.search(rule['title_regexp'], event['data'].get('title', ''))
                if not title_match:
                    continue  # Required regexp didn't match

            # Build tags with variable substitution
            substitutions = {
                '$app': event['data'].get('app'),
                '$1': title_match.group(1) if title_match and title_match.groups() else None,
            }

            return self._build_tags(rule['timew_tags'], substitutions)

        return False


    def get_afk_tags(self, event):
        if 'status' in event['data']:
            return { event['data']['status'] }
        else:
            return False

    def _afk_change_stats(self, afk, tags, event):
        """
        Internal method used from check_and_handle_afk_state_change.
        Reset statistics counters when coming/going afk
        
        TODO: self.afk should ONLY be set here and on initialization
        """
        if tags == { 'afk' }:
            ## This event may overlap other events.
            ## We should ignore all other overlapping events, the afk tag
            ## takes precedence.
            ## By setting last_known_tick to the end of the afk event
            ## we mark up that the activity up until then is known.
            ## (This is redundant, if the afk event is also exported).
            self.last_known_tick = event['timestamp'] + event['duration']
            self.last_tick = self.last_known_tick
        elif tags == { 'not-afk' }:
            ## This event may overlap other events.
            ## The duration of this event should be ignored.
            ## The below statements should be kind of redundant, possibly harmful
            ## if we have extra not-afk events, so they are commented out:
            #self.last_tick = event['timestamp']
            #self.last_known_tick = self.last_tick
            ## All time since the start of the not-afk event should be tracked.
            ## We keep a special counter on this.
            self.last_not_afk = event['timestamp']
            ## TODO: the statistic above should be honored
        self.tags_accumulated_time = defaultdict(timedelta)
        ## TODO - there is more to be done, isn't it?  Or perhaps not?
        self.afk = afk=='afk'

    def check_and_handle_afk_state_change(self, tags, event=None):
        """
        * Checks if I've gone afk or returned to keyboard
        * Resets the statistics that should be reset if I'm coming or leaving
        * Exports the tracking, if applicable
        * Returns False if the event/tags needs further handling
        * Returns True if all logic has been handled in this function, meaning that the event/tags does not need further handling
        """
        if not tags: ## Not much to do here.  Except, we could verify that the event is compatible with the self.afk setting
            return False
        if 'afk' in tags and 'not-afk' in tags:
            ## Those are exclusive, should not happen!
            breakpoint()
        if self.afk is None:
            ## Program has just been started, and we don't know if we're afk or not
            if 'afk' in tags:
                self.afk = True
            if 'not-afk' in tags:
                self.afk = False
            ## unless tags are { 'afk' } or { 'non-afk' } we'll return False
            ## to indicate that we haven't handled any state change, and that
            ## the tags still needs handling
            return self.afk is not None and len(tags) == 1
        if self.afk:
            if tags == { 'afk' }:
                ## This should probably be checked up ... we're already afk, but now
                ## we got a new afk tag?
                ## (possible reason: we had some few tags in between the afk runs, but without any tags)
                breakpoint()
                self._afk_change_stats('afk', tags, event)
                return True
            if not 'afk' in self.timew_info['tags']:
                ## I'm apparently afk, but we're not tracking it in timew?
                ## Something must have gone wrong somewhere?
                breakpoint()
            if 'not-afk' in tags:
                self._afk_change_stats('not-afk', tags, event)
                self.log(f"You have returned to the keyboard after {(event['timestamp']-self.last_start_time).total_seconds()}s absence", event=event)
                if tags != { 'not-afk' }:
                    ## Some possibilities:
                    ## 1) We have returned from the keyboard without the 'not-afk' special event triggered?
                    ## 2) We're catching up some "ghost tracking" of window events while we're afk?
                    ## 3) The 'not-afk' special event is not in the right order in the event queue?
                    ## 4) The data from the afk/not-afk watcher is unreliable
                    ## I think I found out that 3 is normal, but we may want to investigate TODO
                    return False
                else:
                    return True
        else: ## We're not afk
            if tags == { 'not-afk' }:
                ## Check this up manually.  Possibilities:
                ## 1) We're wrongly marked as 'not-afk' while we've actually been afk
                ## 2) The 'not-afk' special event is not in the right order in the event queue?
                ## 3) The data from the afk/not-afk watcher is unreliable
                ## I think I found 2 is normal, but we may want to investigate TODO
                return True
            elif tags == { 'afk' }:
                ## Meaning we've just gone afk.
                self.ensure_tag_exported(tags, event)
                self._afk_change_stats('afk', tags, event)
                self.log(f"You're going to be afk for at least {event['duration']}s", event=event)
                return True
            elif 'afk' in tags:
                ## We've gone afk ... in some weird way?
                self._afk_change_stats('afk', tags, event)
                breakpoint()
                return False
            else:
                ## We're not afk and we've not gone afk
                return False

        return False



    ## TODO: this is a bit messy - this will return None if the event is small
    ## enough to be found "ignorable" and False if no tags are found
    ## Otherwise a set of tags
    def find_tags_from_event(self, event):
        if event['duration'].total_seconds() < IGNORE_INTERVAL:
            return None

        for method in (self.get_afk_tags, self.get_app_tags, self.get_browser_tags, self.get_editor_tags):
            tags = method(event)
            if tags is not False:
                break
        return tags
    
    def find_next_activity(self):
        afk_id = self.bucket_by_client['aw-watcher-afk'][0]
        window_id = self.bucket_by_client['aw-watcher-window'][0]

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

        ## just to make sure we won't lose any events
        #self.last_tick = self.last_tick - timedelta(1)
        
        afk_events = self.get_events(afk_id, start=self.last_tick, end=self.end_time)

        ### START WORKAROUND
        ## TODO
        ## workaround for https://github.com/ActivityWatch/aw-watcher-window-wayland/issues/41
        ## assume all gaps are afk
        #if len(afk_events) == 0:
            #afk_events = [{'data': {'status': 'afk'}, 'timestamp': self.last_tick, 'duration': timedelta(seconds=time()-self.last_tick.timestamp())}]
        if len(afk_events)>1: #and not any(x for x in afk_events if x['data']['status'] != 'not-afk'):
            afk_events.reverse()
            afk_events.sort(key=lambda x: x['timestamp'])
            for i in range(1, len(afk_events)):
                end = afk_events[i]['timestamp']
                start = afk_events[i-1]['timestamp'] + afk_events[i-1]['duration']
                duration = end-start
                if duration.total_seconds() < MIN_RECORDING_INTERVAL:
                    continue
                afk_events.append({'data': {'status': 'afk'}, 'timestamp': start, 'duration': duration})
        ### END WORKAROUND

        ## The afk tracker is not reliable.  Sometimes it shows me
        ## being afk even when I've been sitting constantly by the
        ## computer, working most of the time, perhaps spending a
        ## minute reading something?
        afk_events = [ x for x in afk_events if x['duration'] > timedelta(seconds=MAX_MIXED_INTERVAL) ]

        ## afk and window_events
        afk_window_events = self.get_events(window_id, start=self.last_tick, end=self.end_time) + afk_events
        afk_window_events.sort(key=lambda x: x['timestamp'])
        if len(afk_window_events)<2:
            return False
        ## The last event on the list is unreliable, as it's about non-ended events
        afk_window_events.pop()

        cnt = 0
        for event in afk_window_events[:-1]:
            if event['timestamp'] < self.last_tick or event['timestamp'] < self.last_known_tick:
                if event['data'] == {'status': 'not-afk'}:
                    continue
                #if event['timestamp']+event['duration'] > self.last_known_tick:
                    #import pdb; pdb.set_trace()
                elif event['data'] != {'status': 'afk'} and event['timestamp'] > self.last_start_time:
                    #if event['duration']>timedelta(seconds=30):
                        #import pdb; pdb.set_trace()
                    ## Do we need an exception here for afk events?
                    self.log(f"skipping event as the timestamp is too old - {event}", event=event)
                    continue
            tags = self.find_tags_from_event(event)

            ## Handling afk/not-afk
            if self.check_and_handle_afk_state_change(tags, event):
                ## TODO:
                ## Doh!  Some of the point of moving things to a separate
                ## function is to avoid the below logic here
                ## Returning after handling { 'not-afk' }
                ## and we'll come back and pick up the same event again!
                ## continue after handling { 'afk' } and
                ## we will pick up "ghost" events that should be
                ## ignored.  (we could add some logic to skip handled or skippable events)
                if self.afk:
                    return True
                continue

            if tags:
                self.total_time_known_events += event['duration']

            ## tags can be False or None and those means different things.
            ## TODO: Bad design
            ## TODO: duplicated code
            if tags is None:
                num_skipped_events += 1
                total_time_skipped_events += event['duration']
                if total_time_skipped_events.total_seconds()>MIN_RECORDING_INTERVAL:
                    breakpoint()
                continue
            
            if tags is False:
                num_unknown_events += 1
                self.total_time_unknown_events += event['duration']
                # Track unmatched event if requested
                if self.show_unmatched:
                    self.unmatched_events.append(event)
                if self.total_time_unknown_events.total_seconds()>MAX_MIXED_INTERVAL*2:
                    # Significant unknown activity - tag it as UNKNOWN
                    self.log(f"Significant unknown activity ({self.total_time_unknown_events.total_seconds()}s), tagging as UNKNOWN", event=event)
                    self.ensure_tag_exported({'UNKNOWN', 'not-afk'}, event)
                    self.total_time_unknown_events = timedelta(0)
                else:
                    self.log(f"{self.total_time_unknown_events.total_seconds()}s unknown events.  Data: {event['data']} - ({num_skipped_events} smaller events skipped, total duration {total_time_skipped_events.total_seconds()}s)", event=event)
            else:
                self.log(f"{event['data']} - tags found: {tags} ({num_skipped_events} smaller events skipped, total duration {total_time_skipped_events.total_seconds()}s)")
            num_skipped_events = 0
            total_time_skipped_events = timedelta(0)

            ## Ref README, if MAX_MIXED_INTERVAL is met, ignore accumulated minor activity
            ## (the mixed time will be attributed to the previous work task)
            if tags and event['duration'].total_seconds() > MAX_MIXED_INTERVAL:
                ## Theoretically, we may do lots of different things causing hundred of different independent tags to collect less than the minimum needed to record something.  In practice that doesn't happen.
                #print(f"We're tossing data: {self.tags_accumulated_time}")
                self.ensure_tag_exported(tags, event)

            interval_since_last_known_tick = event['timestamp'] + event['duration'] - self.last_known_tick
            if (interval_since_last_known_tick < timedelta(0)):
                ## Something is very wrong here, it needs investigation.
                breakpoint()
            assert(interval_since_last_known_tick >= timedelta(0))

            ## Track things in internal accumulator if the focus between windows changes often
            if tags:
                tags = retag_by_rules(tags, self.config)
                for tag in tags:
                    self.tags_accumulated_time[tag] += event['duration']

            ## Check - if `timew start` was run manually since last "known tick", then reset everything
            # Only update timew_info if not in dry-run mode
            if not self.dry_run and not self.test_data:
                self.set_timew_info(timew_retag(get_timew_info(), capture_to=self.captured_commands))
            if interval_since_last_known_tick.total_seconds() > MIN_RECORDING_INTERVAL_ADJ and any(x for x in self.tags_accumulated_time if x not in SPECIAL_TAGS and self.tags_accumulated_time[x].total_seconds()>MIN_RECORDING_INTERVAL_ADJ):
                self.log("Emptying the accumulator!")
                tags = set()
                ## TODO: This looks like a bug - we reset tags, and then assert that they are not overlapping?
                assert not exclusive_overlapping(tags, self.config)
                min_tag_recording_interval=MIN_TAG_RECORDING_INTERVAL
                while exclusive_overlapping(set([tag for tag in self.tags_accumulated_time if  self.tags_accumulated_time[tag].total_seconds() > min_tag_recording_interval]), self.config):
                    min_tag_recording_interval += 1
                for tag in self.tags_accumulated_time:
                    if self.tags_accumulated_time[tag].total_seconds() > min_tag_recording_interval:
                        tags.add(tag)
                    self.tags_accumulated_time[tag] *= STICKYNESS_FACTOR
                if self.manual_tracking:
                    since = event['timestamp']-self.total_time_known_events+event['duration']
                else:
                    since = self.last_known_tick
                self.log(f"Ensuring tags export, tags={tags}")
                self.ensure_tag_exported(tags, event, since)

            self.last_tick = event['timestamp'] + event['duration']
            cnt += 1

            if tags is not False:
                pass
            
            elif event['data'].get('app', '').lower() in ('foot', 'xterm', ...): ## TODO: complete the list
                self.log(f"Unknown terminal event {event['data']['title']}", event=event, level=logging.WARNING)
            else:
                self.log(f"No rules found for event {event['data']}", event=event, level=logging.WARNING)
        return cnt>1

    def set_timew_info(self, timew_info):
        if self.afk is None and 'afk' in timew_info['tags']:
            self.afk = True
        if self.afk is None and 'not-afk' in timew_info['tags']:
            self.afk = False

        foo = self.timew_info
        self.timew_info = timew_info
        if foo != self.timew_info: ## timew has been run since last
            self.log(f"tracking from {ts2strtime(self.timew_info['start_dt'])}: {self.timew_info['tags']}")
            if not self.last_known_tick or timew_info['start_dt'] > self.last_known_tick:
                self.set_known_tick_stats(start=timew_info['start_dt'], manual=True, tags=timew_info['tags'])

    def tick(self, process_all: bool = False) -> bool:
        """
        Process one tick of events.

        Args:
            process_all: If True, keep processing until all events are consumed

        Returns:
            bool: True if processing should continue, False if we've reached the end
        """
        # In test mode or dry-run with start_time, skip getting real timew info
        if self.test_data or (self.dry_run and self.start_time):
            # Create mock timew_info for test/dry-run mode
            if not self.timew_info:
                mock_start = self.start_time or datetime.now(timezone.utc)
                self.timew_info = {
                    'start': mock_start.strftime('%Y%m%dT%H%M%SZ'),
                    'start_dt': mock_start,
                    'tags': set()
                }
        elif not self.timew_info:
            # Normal mode or dry-run without start_time - get current timew tracking state
            try:
                self.set_timew_info(timew_retag(get_timew_info(), dry_run=self.dry_run, capture_to=self.captured_commands))
            except Exception as e:
                # No active tracking - create mock info
                if self.dry_run:
                    mock_start = self.start_time or datetime.now(timezone.utc)
                    self.timew_info = {
                        'start': mock_start.strftime('%Y%m%dT%H%M%SZ'),
                        'start_dt': mock_start,
                        'tags': set()
                    }
                else:
                    raise

        if not self.last_tick:
            ## TODO: think more through this.  This is in practice program initialization
            # Use start_time if provided, otherwise use timew start
            if self.start_time:
                self.last_tick = self.start_time
            else:
                self.last_tick = self.timew_info['start_dt']
            self.last_known_tick = self.last_tick
            self.last_start_time = self.last_tick

        # If process_all is True, keep finding activity until there's none left
        if process_all:
            while True:
                found_activity = self.find_next_activity()
                if not found_activity:
                    # Check if we've reached end_time
                    if self.end_time and self.last_tick < self.end_time:
                        self.log(f"No more events before end_time, advancing to {self.end_time}")
                        if self.enable_pdb:
                            import pdb; pdb.set_trace()
                        self.last_tick = self.end_time
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
                if self.last_tick < self.end_time:
                    self.log(f"No more events before end_time, advancing to {self.end_time}")
                    self.last_tick = self.end_time
                    # Try one more time to find activity
                    found_activity = self.find_next_activity()

                # If still no activity, we've reached the end
                if not found_activity:
                    self.log(f"Reached end_time {self.end_time}, stopping")
                    return False

            if not found_activity:
                # In dry-run mode without end_time, we can't continue (would loop forever)
                if self.dry_run and not self.end_time:
                    if self.enable_pdb:
                        import pdb; pdb.set_trace()
                    raise ValueError("dry-run mode without end_time would loop forever - this should be prevented by CLI validation")

                self.log("sleeping, because no events found")
                if not self.dry_run:  # Don't sleep in dry-run mode
                    sleep(SLEEP_INTERVAL)

            return True

def check_bucket_updated(bucket: dict) -> None:
    if not bucket['last_updated_dt'] or time()-bucket['last_updated_dt'].timestamp() > AW_WARN_THRESHOLD:
        logger.warning(f"Bucket {bucket['id']} seems not to have recent data!")

## TODO: none of this has anything to do with ActivityWatch and can be moved to a separate module
def get_timew_info():
    ## TODO: this will break if there is no active tracking
    current_timew = json.loads(subprocess.check_output(["timew", "get", "dom.active.json"]))
    dt = datetime.strptime(current_timew['start'], "%Y%m%dT%H%M%SZ")
    dt = dt.replace(tzinfo=timezone.utc)
    current_timew['start_dt'] = dt
    current_timew['tags'] = set(current_timew['tags'])
    return current_timew

def timew_run(commands, dry_run=False, capture_to=None, hide_output=False):
    """
    Execute a timewarrior command, or show what would be done if dry_run=True.

    Args:
        commands: List of command arguments (without 'timew' prefix)
        dry_run: If True, don't execute, just print what would be done
        capture_to: Optional list to append commands to (for testing)
        hide_output: If True, don't print the "DRY RUN" or "Running" messages
    """
    commands = ['timew'] + commands

    if dry_run:
        if not hide_output:
            user_output(f"DRY RUN: Would execute: {' '.join(commands)}", color="yellow", attrs=["bold"])
        if capture_to is not None:
            capture_to.append(commands)
        return

    if not hide_output:
        user_output(f"Running: {' '.join(commands)}")
    subprocess.run(commands)
    user_output(f"Use timew undo if you don't agree!  You have {GRACE_TIME} seconds to press ctrl^c", attrs=["bold"])
    sleep(GRACE_TIME)

def exclusive_overlapping(tags, cfg=None):
    if cfg is None:
        cfg = config
    for gid in cfg.get('exclusive', {}):
        group = set(cfg['exclusive'][gid]['tags'])
        if len(group.intersection(tags)) > 1:
            return True
    return False

## not really retag, more like expand tags?  But it's my plan to allow replacement and not only addings
def retag_by_rules(source_tags, cfg=None):
    if cfg is None:
        cfg = config
    assert not exclusive_overlapping(source_tags, cfg)
    new_tags = source_tags.copy()  ## TODO: bad variable naming.  `revised_tags` maybe?
    for tag_section in cfg.get('tags', {}):
        retags = cfg['tags'][tag_section]
        intersection = source_tags.intersection(set(retags['source_tags']))
        if intersection:
            new_tags_ = set()
            for tag in retags.get('add', []):
                if "$source_tag" in tag:
                    for source_tag in intersection:
                        new_tags_.add(tag.replace("$source_tag", source_tag))
                else:
                    new_tags_.add(tag)    
            new_tags_ = new_tags.union(new_tags_)
            if exclusive_overlapping(new_tags_):
                logger.warning(f"Excluding expanding tag rule {tag_section} due to exclusivity conflicts")
            else:
                new_tags = new_tags_
    if new_tags != source_tags:
        ## We could end up doing infinite recursion here
        ## TODO: add some recursion-safety here?
        return retag_by_rules(new_tags)
    return new_tags

def timew_retag(timew_info, dry_run=False, capture_to=None):
    source_tags = set(timew_info['tags'])
    new_tags = retag_by_rules(source_tags)
    if new_tags != source_tags:
        timew_run(["retag"] + list(new_tags), dry_run=dry_run, capture_to=capture_to)
        if not dry_run:
            timew_info = get_timew_info()
            assert set(timew_info['tags']) == new_tags
        return timew_info
    return timew_info

def main():
    exporter = Exporter()
    while True:
        exporter.tick()

if __name__ == '__main__':
    main()
