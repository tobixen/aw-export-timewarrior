"""Logging and output utilities for aw-export-timewarrior."""

import json
import logging
import sys
from datetime import UTC, datetime, timedelta

from termcolor import cprint


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
        log_level: Logging level (default: DEBUG)
        console_log_level: Console logging level (default: ERROR)
        log_file: Optional file path to write logs to. If None, logs to console only.
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


# Initialize logging with defaults
# This will be reconfigured by CLI with appropriate parameters
# For direct imports/testing, use basic console logging
setup_logging(log_file=None)
