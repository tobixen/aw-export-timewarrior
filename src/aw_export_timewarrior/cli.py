#!/usr/bin/env python3
"""
Command-line interface for aw-export-timewarrior with subcommand structure.

Provides subcommands for different operational modes: sync, diff, analyze, export, validate.
"""

import argparse
import logging
import sys
import time
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .export import load_test_data
from .main import Exporter
from .output import setup_logging
from .utils import parse_datetime


def create_exporter_from_args(args: argparse.Namespace, method: str, **overrides) -> Exporter:
    """
    Create an Exporter instance from CLI arguments.

    Maps argparse.Namespace to Exporter dataclass fields automatically,
    with explicit overrides for special cases.

    Args:
        args: Parsed command-line arguments
        **overrides: Explicit parameter overrides (e.g., dry_run=True)

    Returns:
        Configured Exporter instance
    """
    # Build kwargs from args
    kwargs = {}

    arg_mapping = {"timeline": "show_timeline", "config": "config_path", "apply": "apply_fix"}

    exporter_field_names = {f.name for f in fields(Exporter)}

    for arg_name, arg_value in vars(args).items():
        # Map CLI arg name to Exporter field name
        field_name = arg_mapping.get(arg_name, arg_name)

        if field_name in exporter_field_names and arg_value is not None:
            kwargs[field_name] = arg_value

    _handle_start_stop_testdata_from_args(args, kwargs, method)

    # Apply overrides (takes precedence)
    kwargs.update(overrides)

    return Exporter(**kwargs)


def add_timespan_arguments(parser):
    start_group = parser.add_mutually_exclusive_group()
    start_group.add_argument(
        "--from",
        "--since",
        "--begin",
        "--start",
        dest="start",
        metavar="DATETIME",
        help="Start time for processing window (defaults to last observed timew tagging timestamp)",
    )

    # End time aliases
    end_group = parser.add_mutually_exclusive_group()
    end_group.add_argument(
        "--to",
        "--until",
        "--end",
        dest="end",
        metavar="DATETIME",
        help="End time (continuous mode: runs indefinitely; with --once or --dry-run: defaults to now)",
    )

    start_group.add_argument("--day", metavar="DATE")


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="Export ActivityWatch data to Timewarrior",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Subcommands:
  sync      Synchronize ActivityWatch to TimeWarrior (default)
  diff      Compare TimeWarrior with ActivityWatch and optionally fix
  analyze   Analyze events and show unmatched activities
  export    Export ActivityWatch data to file
  report    Generate detailed activity report
  validate  Validate configuration file

Examples:
  # Continuous sync (default)
  %(prog)s sync
  %(prog)s  # implicit sync

  # Dry-run for yesterday
  %(prog)s sync --dry-run --from yesterday --to today

  # Show differences and fix commands
  %(prog)s diff --from yesterday --show-commands

  # Apply fixes automatically
  %(prog)s diff --from "2025-12-08 10:00" --to "2025-12-08 11:00" --apply

  # Analyze unmatched events
  %(prog)s analyze --from yesterday

  # Export data to file
  %(prog)s export --from "2025-01-01 09:00" --to "2025-01-01 17:00" -o output.json

  # Export to stdout and pipe to jq
  %(prog)s export --from yesterday | jq '.metadata'

  # Validate config
  %(prog)s validate
        """,
    )

    # Global options (available for all subcommands)
    parser.add_argument(
        "--config",
        metavar="FILE",
        type=Path,
        help="Path to configuration file (default: uses standard config locations)",
    )
    parser.add_argument(
        "--log-level",
        choices=["NONE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="WARNING",
        help="Set logging level (default: WARNING)",
    )
    parser.add_argument(
        "--console-log-level",
        choices=["NONE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="ERROR",
        help="Set console logging level (default: ERROR)",
    )
    parser.add_argument(
        "--log-file",
        metavar="FILE",
        type=Path,
        help="Log file path (default: ~/.local/share/aw-export-timewarrior/aw-export.json.log)",
    )
    parser.add_argument(
        "--no-log-json", action="store_true", help="Do not output logs in JSON format"
    )
    debug_group = parser.add_mutually_exclusive_group()
    debug_group.add_argument(
        "--enable-pdb",
        action="store_true",
        help="Drop into debugger on unexpected states (for development)",
    )
    debug_group.add_argument(
        "--enable-assert", action="store_true", help="Assert no unexpected states (for development)"
    )

    # Create subparsers
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to run")

    # ===== SYNC subcommand =====
    sync_parser = subparsers.add_parser(
        "sync",
        help="Synchronize ActivityWatch to TimeWarrior (default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Continuous sync (default)
  %(prog)s

  # Dry-run for yesterday
  %(prog)s --dry-run --from yesterday --to today

  # Process specific time range once
  %(prog)s --from "2025-12-08 09:00" --to "2025-12-08 17:00" --once
        """,
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying TimeWarrior.",
    )
    sync_parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="dry-run is by default enabled when using test-data.  This option explicitly disables dry run",
    )
    sync_parser.add_argument(
        "--once",
        action="store_true",
        help="Process once and exit (instead of continuous monitoring)",
    )

    # time aliases
    add_timespan_arguments(sync_parser)

    sync_parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    sync_parser.add_argument(
        "--hide-processing-output", action="store_true", help="Hide command execution messages"
    )
    sync_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress all console output (for headless/systemd usage)",
    )
    sync_parser.add_argument(
        "--test-data", metavar="FILE", type=Path, help="Use test data instead of live ActivityWatch"
    )

    # ===== DIFF subcommand =====
    diff_parser = subparsers.add_parser(
        "diff",
        help="Compare TimeWarrior with ActivityWatch and optionally fix",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show differences for yesterday
  %(prog)s --from yesterday --to today

  # Show differences with fix commands
  %(prog)s --from "2025-12-08 10:00" --show-commands

  # Apply fixes automatically
  %(prog)s --from "2025-12-08 10:00" --to "2025-12-08 11:00" --apply
        """,
    )

    # time aliases
    add_timespan_arguments(diff_parser)

    diff_parser.add_argument(
        "--show-commands", action="store_true", help="Show timew track commands to fix differences"
    )
    diff_parser.add_argument(
        "--apply", action="store_true", help="Execute the fix commands (implies --show-commands)"
    )
    diff_parser.add_argument(
        "--hide-report", action="store_true", help="Hide the detailed diff report"
    )
    diff_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show more details in the diff"
    )
    diff_parser.add_argument(
        "--timeline",
        action="store_true",
        help="Show side-by-side timeline of TimeWarrior vs ActivityWatch intervals",
    )
    diff_parser.add_argument(
        "--test-data", metavar="FILE", type=Path, help="Use test data instead of live ActivityWatch"
    )
    diff_parser.add_argument(
        "--config", metavar="FILE", type=Path, help="Path to configuration file"
    )

    # ===== ANALYZE subcommand =====
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze events and show unmatched activities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze yesterday's unmatched events
  %(prog)s --from yesterday --to today

  # Analyze with detailed output
  %(prog)s --from "2025-12-08 09:00" --verbose

  # Find long unmatched events
  %(prog)s --from yesterday --to today --min-duration 5
        """,
    )

    # Start time aliases
    add_timespan_arguments(analyze_parser)

    analyze_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show more details per event"
    )
    analyze_parser.add_argument(
        "--group-by",
        choices=["app", "hour", "day"],
        default="app",
        help="How to group results (default: app)",
    )
    analyze_parser.add_argument(
        "--min-duration", type=int, metavar="MINUTES", help="Only show events longer than X minutes"
    )
    analyze_parser.add_argument(
        "--limit", type=int, metavar="N", default=10, help="Limit output to N lines (default: 10)"
    )

    # ===== EXPORT subcommand =====
    export_parser = subparsers.add_parser(
        "export",
        help="Export ActivityWatch data to file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export to stdout (default)
  %(prog)s --from "2025-12-08 09:00" --to "2025-12-08 17:00"

  # Export to file
  %(prog)s --from "2025-12-08 09:00" --to "2025-12-08 17:00" -o sample.json

  # Export and pipe to jq
  %(prog)s --from yesterday | jq '.events'
        """,
    )

    add_timespan_arguments(export_parser)

    export_parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        default="-",
        help='Output file path (default: stdout). Use "-" for stdout or specify a file path',
    )

    # ===== REPORT subcommand =====
    report_parser = subparsers.add_parser(
        "report",
        help="Generate detailed activity report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Report for today
  %(prog)s --from today

  # Report for a specific time range
  %(prog)s --from "2025-12-10 09:00" --to "2025-12-10 17:00"

  # Report with all columns
  %(prog)s --from yesterday --all-columns

  # Export report as CSV
  %(prog)s --from yesterday --format csv > report.csv
        """,
    )
    add_timespan_arguments(report_parser)
    report_parser.add_argument(
        "--all-columns",
        action="store_true",
        help="Show all available columns (default shows main columns only)",
    )
    report_parser.add_argument(
        "--format",
        choices=["table", "csv", "tsv", "json", "ndjson"],
        default="table",
        help="Output format (default: table). JSON outputs a valid JSON array. NDJSON outputs one JSON object per line (newline-delimited JSON).",
    )
    report_parser.add_argument(
        "--no-truncate", action="store_true", help="Do not truncate long values in table mode"
    )
    report_parser.add_argument(
        "--show-rule",
        action="store_true",
        help="Show which rule matched each event",
    )
    report_parser.add_argument(
        "--show-exports",
        action="store_true",
        help="Show export decisions interleaved with events (colored in terminal)",
    )

    # ===== VALIDATE subcommand =====
    subparsers.add_parser(
        "validate",
        help="Validate configuration file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate default config
  %(prog)s

  # Validate custom config
  %(prog)s --config my_config.toml
        """,
    )

    return parser


def get_default_log_file(json: bool) -> Path:
    """
    Get the default log file path.

    Returns:
        Path to the default log file in the user's data directory
    """
    # Use XDG_DATA_HOME or fallback to ~/.local/share
    import os

    data_home = os.environ.get("XDG_DATA_HOME")
    data_dir = Path(data_home) if data_home else Path.home() / ".local" / "share"

    log_dir = data_dir / "aw-export-timewarrior"
    log_dir.mkdir(parents=True, exist_ok=True)

    json_postfix = ".json" if json else ""

    return log_dir / f"aw-export{json_postfix}.log"


def configure_logging(args: argparse.Namespace, subcommand: str) -> None:
    """
    Configure logging based on command-line arguments.

    Args:
        args: Parsed command-line arguments
        subcommand: The subcommand being executed
    """
    # Determine log level
    log_level = getattr(logging, args.log_level, 0)
    console_log_level = getattr(logging, args.console_log_level, 0)

    # If verbose mode, enable DEBUG logging
    if hasattr(args, "verbose") and args.verbose:
        console_log_level = logging.DEBUG

    # If quiet mode (sync only), suppress console output
    if hasattr(args, "quiet") and args.quiet:
        console_log_level = logging.CRITICAL + 1  # Above all levels

    # Determine log file
    log_file = None
    if args.log_file and log_level > 0:
        log_file = args.log_file  # Explicit log file
    elif log_level > 0:
        log_file = get_default_log_file(not args.no_log_json)  # Default log file

    # Build run mode info for structured logging (allows filtering logs)
    run_mode = {
        "subcommand": subcommand,
        "dry_run": getattr(args, "dry_run", False),
        "test_data": hasattr(args, "test_data") and args.test_data is not None,
        "once": getattr(args, "once", False),
    }

    # Configure the logging system
    setup_logging(
        json_format=not args.no_log_json,
        log_level=log_level,
        console_log_level=console_log_level,
        log_file=log_file,
        run_mode=run_mode,
    )


def validate_sync_args(args: argparse.Namespace) -> str | None:
    """Validate arguments for sync subcommand."""
    if getattr(args, "test_data", False):
        if not args.test_data.exists():
            return f"Error: Test data file not found: {args.test_data}"
        if args.start or args.end:
            return "Error: --start/--end not compatible with --test-data (test data has its own time range)"

    # Dry-run without --once requires time boundaries to prevent infinite loop
    if args.dry_run and not args.once and not (args.start and args.end):
        return "Error: --dry-run without --once requires both --start and --end (to prevent infinite loop)"

    # End without start doesn't make sense
    if args.end and not args.start:
        return "Error: --end requires --start to be specified"

    return None


def validate_diff_args(args: argparse.Namespace) -> str | None:
    """Validate arguments for diff subcommand."""
    return None


def validate_analyze_args(args: argparse.Namespace) -> str | None:
    """Validate arguments for analyze subcommand."""
    # End without start doesn't make sense
    return None


def validate_export_args(args: argparse.Namespace) -> str | None:
    """Validate arguments for export subcommand."""
    # Export requires output file (enforced by required=True in argparse)
    # End without start doesn't make sense
    return None


def validate_report_args(args: argparse.Namespace) -> str | None:
    """Validate arguments for report subcommand."""
    # No special validation needed
    return None


def validate_validate_args(args: argparse.Namespace) -> str | None:
    """Validate arguments for validate subcommand."""
    # No special validation needed
    return None


def _handle_start_stop_testdata_from_args(args, exporter_args, method):
    ## TODO: I want a --day parameter for processing a full day (local time, midnight to midnight)

    start = None
    end = None
    test_data = None

    if args.day:
        start = parse_datetime(args.day)
        # Normalize to start of day (midnight) in local timezone
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        # End is start of next day
        end = start + timedelta(days=1)

    if args.start:
        start = parse_datetime(args.start)

    if args.end:
        ## TODO - can we make this work?
        # if args.day:
        # end = args.day +parse_time(args.end)
        end = parse_datetime(args.end)

    if getattr(args, "test_data", False):
        print(f"Loading test data from {args.test_data}")
        test_data = load_test_data(args.test_data)

        # Extract start/end times from test data metadata if not provided via CLI
        if not start and "metadata" in test_data and "start_time" in test_data["metadata"]:
            start = parse_datetime(test_data["metadata"]["start_time"])
            print(f"Using start time from test data: {start}")
        if not end and "metadata" in test_data and "end_time" in test_data["metadata"]:
            end = parse_datetime(test_data["metadata"]["end_time"])
            print(f"Using end time from test data: {end}")

    ## The default for sync, "since last timew entry" is set somewhere else, otherwise it should be set here.
    if method != "sync" and not start:
        start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)

    ## The default for sync is "run forever" or "run once", otherwise we should end at current timestamp
    if method != "sync" and not end:
        end = datetime.now().astimezone()

    print(f"Processing time range: {start} to {end}", file=sys.stderr)
    exporter_args["start_time"] = start
    exporter_args["end_time"] = end
    exporter_args["test_data"] = test_data


def run_sync(args: argparse.Namespace) -> int:
    """Execute the sync subcommand."""
    if args.test_data and not args.no_dry_run:
        args.dry_run = True

    # Create exporter with options
    exporter = create_exporter_from_args(args, "sync")

    # Warn if using sync mode for historical batch processing
    if (
        not args.dry_run
        and args.start
        and args.end
        and args.once
        and exporter.end_time
        and exporter.end_time < datetime.now(UTC)
    ):
        print("WARNING: Sync mode is designed for live tracking, not historical batch processing.")
        print("For processing historical data, use 'diff' mode instead:")
        print(f"  aw-export-timewarrior diff --from {args.start} --to {args.end} --apply")
        print("\nSync mode may create intervals that extend to NOW, causing overlaps.")
        print("Continuing anyway...\n")

    # Run exporter
    if args.dry_run:
        print("=== DRY RUN MODE ===", file=sys.stderr)
        print("No changes will be made to timewarrior\n", file=sys.stderr)

    if args.once:
        # Process all available events in one call
        exporter.tick(process_all=True)
        print("\nProcessing completed")
    else:
        if not exporter.end_time:
            print("Starting continuous monitoring (Ctrl+C to stop)...")

        while exporter.tick():
            # Small sleep to prevent 100% CPU usage during continuous sync
            time.sleep(0.1)

        if exporter.end_time:
            print(f"\nReached end of time range at {exporter.end_time}")

    return 0


def run_diff(args: argparse.Namespace) -> int:
    """Execute the diff subcommand."""

    # Create exporter in dry-run mode for comparison
    # IMPORTANT: Always use dry_run=True so tick() doesn't modify timew
    # Only the fix commands (when --apply is set) should modify timew
    exporter = create_exporter_from_args(
        args,
        "diff",
        dry_run=True,  # Always dry-run for tick() - don't modify timew during comparison
        show_diff=True,
        show_fix_commands=args.show_commands or args.apply,
    )

    # Process all events first (to build suggested intervals)
    # This runs in dry-run mode and doesn't modify timew
    exporter.tick(process_all=True)

    # Run comparison and optionally apply fixes
    # The apply_fix flag controls whether fix commands are executed
    exporter.run_comparison()

    return 0


def run_analyze(args: argparse.Namespace) -> int:
    """Execute the analyze subcommand."""
    # Create exporter in dry-run mode with show_unmatched
    exporter = create_exporter_from_args(args, "analyze", dry_run=True, show_unmatched=True)

    # Process all events
    exporter.tick(process_all=True)

    # Show unmatched events report with limit
    exporter.show_unmatched_events_report(limit=args.limit, verbose=args.verbose)

    return 0


def run_export(args: argparse.Namespace) -> int:
    """Execute the export subcommand."""

    import sys

    from .export import export_aw_data

    exporter_args = {}
    _handle_start_stop_testdata_from_args(args, exporter_args, "export")

    # Direct progress messages to stderr if outputting to stdout
    use_stdout = str(args.output) == "-"
    progress_output = sys.stderr if use_stdout else sys.stdout

    start_time = exporter_args.get("start_time")
    end_time = exporter_args.get("end_time")

    print(f"Exporting data from {start_time} to {end_time}...", file=progress_output)
    export_aw_data(args.start or str(start_time), args.end or str(end_time), args.output)

    # Don't print completion message when outputting to stdout (export_aw_data already prints summary to stderr)
    if not use_stdout:
        print(f"Data exported to {args.output}")

    return 0


def run_report(args: argparse.Namespace) -> int:
    """Execute the report subcommand."""
    from .report import generate_activity_report

    # Create exporter for reading ActivityWatch data
    exporter = create_exporter_from_args(args, "report", dry_run=True)

    # Generate report
    generate_activity_report(
        exporter=exporter,
        all_columns=args.all_columns,
        format=args.format,
        truncate=not args.no_truncate,
        show_rule=args.show_rule,
        show_exports=args.show_exports,
    )

    return 0


def run_validate(args: argparse.Namespace) -> int:
    """Execute the validate subcommand."""
    from .config import config, load_custom_config
    from .config_validation import validate_config

    # Load config without validation (we'll do it explicitly)
    if args.config:
        load_custom_config(args.config, validate=False)

    errors, warnings = validate_config(config)

    # Print warnings
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    # Print errors
    for error in errors:
        print(f"Error: {error}", file=sys.stderr)

    # Summary
    if errors:
        print(f"\nConfiguration has {len(errors)} error(s) and {len(warnings)} warning(s)")
        return 1
    elif warnings:
        print(f"\nConfiguration is valid with {len(warnings)} warning(s)")
        return 0
    else:
        print("Configuration is valid")
        return 0


def main(argv=None) -> int:
    """
    Main CLI entry point.

    Args:
        argv: Command-line arguments (defaults to sys.argv)

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    # Default to 'sync' if no subcommand specified
    subcommand = args.subcommand or "sync"
    if not args.subcommand:
        # Re-parse with 'sync' as the subcommand
        argv_with_sync = ["sync"] + (argv if argv else sys.argv[1:])
        args = parser.parse_args(argv_with_sync)
        args.subcommand = "sync"

    # Validate config file if specified
    if args.config and not args.config.exists():
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        return 1

    # Configure logging based on arguments
    configure_logging(args, subcommand)

    try:
        # Validate and run the appropriate subcommand
        if subcommand == "sync":
            error = validate_sync_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_sync(args)

        elif subcommand == "diff":
            error = validate_diff_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_diff(args)

        elif subcommand == "analyze":
            error = validate_analyze_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_analyze(args)

        elif subcommand == "export":
            error = validate_export_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_export(args)

        elif subcommand == "report":
            error = validate_report_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_report(args)

        elif subcommand == "validate":
            error = validate_validate_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_validate(args)

        else:
            print(f"Error: Unknown subcommand: {subcommand}", file=sys.stderr)
            return 1

    except KeyboardInterrupt:
        print("\nExiting...")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if hasattr(args, "verbose") and args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
