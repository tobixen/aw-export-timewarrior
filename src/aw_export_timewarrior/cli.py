#!/usr/bin/env python3
"""
Command-line interface for aw-export-timewarrior with subcommand structure.

Provides subcommands for different operational modes: sync, diff, analyze, export, validate.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from .main import Exporter, setup_logging


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description='Export ActivityWatch data to Timewarrior',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Subcommands:
  sync      Synchronize ActivityWatch to TimeWarrior (default)
  diff      Compare TimeWarrior with ActivityWatch and optionally fix
  analyze   Analyze events and show unmatched activities
  export    Export ActivityWatch data to file
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
        """
    )

    # Global options (available for all subcommands)
    parser.add_argument(
        '--config',
        metavar='FILE',
        type=Path,
        help='Path to configuration file (default: uses standard config locations)'
    )
    parser.add_argument(
        '--log-level',
        choices=['NONE', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='DEBUG',
        help='Set logging level (default: DEBUG)'
    )
    parser.add_argument(
        '--console-log-level',
        choices=['NONE', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='ERROR',
        help='Set console logging level (default: ERROR)'
    )
    parser.add_argument(
        '--log-file',
        metavar='FILE',
        type=Path,
        help='Log file path (default: ~/.local/share/aw-export-timewarrior/aw-export.json.log)'
    )
    parser.add_argument(
        '--no-log-json',
        action='store_true',
        help='Do not output logs in JSON format'
    )
    parser.add_argument(
        '--pdb',
        action='store_true',
        help='Drop into debugger on unexpected states (for development)'
    )

    # Create subparsers
    subparsers = parser.add_subparsers(dest='subcommand', help='Subcommand to run')

    # ===== SYNC subcommand =====
    sync_parser = subparsers.add_parser(
        'sync',
        help='Synchronize ActivityWatch to TimeWarrior (default)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Continuous sync (default)
  %(prog)s

  # Dry-run for yesterday
  %(prog)s --dry-run --from yesterday --to today

  # Process specific time range once
  %(prog)s --from "2025-12-08 09:00" --to "2025-12-08 17:00" --once
        """
    )
    sync_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without modifying TimeWarrior'
    )
    sync_parser.add_argument(
        '--once',
        action='store_true',
        help='Process once and exit (instead of continuous monitoring)'
    )

    # Start time aliases
    sync_start_group = sync_parser.add_mutually_exclusive_group()
    sync_start_group.add_argument(
        '--from', '--since', '--begin', '--start',
        dest='start',
        metavar='DATETIME',
        help='Start time for processing window (defaults to last observed timew tagging timestamp)'
    )

    # End time aliases
    sync_end_group = sync_parser.add_mutually_exclusive_group()
    sync_end_group.add_argument(
        '--to', '--until', '--end',
        dest='end',
        metavar='DATETIME',
        help='End time (continuous mode: runs indefinitely; with --once or --dry-run: defaults to now)'
    )

    sync_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )
    sync_parser.add_argument(
        '--hide-processing-output',
        action='store_true',
        help='Hide command execution messages'
    )
    sync_parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress all console output (for headless/systemd usage)'
    )
    sync_parser.add_argument(
        '--test-data',
        metavar='FILE',
        type=Path,
        help='Use test data instead of live ActivityWatch'
    )

    # ===== DIFF subcommand =====
    diff_parser = subparsers.add_parser(
        'diff',
        help='Compare TimeWarrior with ActivityWatch and optionally fix',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show differences for yesterday
  %(prog)s --from yesterday --to today

  # Show differences with fix commands
  %(prog)s --from "2025-12-08 10:00" --show-commands

  # Apply fixes automatically
  %(prog)s --from "2025-12-08 10:00" --to "2025-12-08 11:00" --apply
        """
    )

    # Start time aliases
    diff_start_group = diff_parser.add_mutually_exclusive_group()
    diff_start_group.add_argument(
        '--from', '--since', '--begin', '--start',
        dest='start',
        metavar='DATETIME',
        help='Start of comparison window (defaults to beginning of current day)'
    )

    # End time aliases
    diff_end_group = diff_parser.add_mutually_exclusive_group()
    diff_end_group.add_argument(
        '--to', '--until', '--end',
        dest='end',
        metavar='DATETIME',
        help='End of comparison window (defaults to now)'
    )

    diff_parser.add_argument(
        '--show-commands',
        action='store_true',
        help='Show timew track commands to fix differences'
    )
    diff_parser.add_argument(
        '--apply',
        action='store_true',
        help='Execute the fix commands (implies --show-commands)'
    )
    diff_parser.add_argument(
        '--hide-report',
        action='store_true',
        help='Hide the detailed diff report'
    )
    diff_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show more details in the diff'
    )

    # ===== ANALYZE subcommand =====
    analyze_parser = subparsers.add_parser(
        'analyze',
        help='Analyze events and show unmatched activities',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze yesterday's unmatched events
  %(prog)s --from yesterday --to today

  # Analyze with detailed output
  %(prog)s --from "2025-12-08 09:00" --verbose

  # Find long unmatched events
  %(prog)s --from yesterday --to today --min-duration 5
        """
    )

    # Start time aliases
    analyze_start_group = analyze_parser.add_mutually_exclusive_group()
    analyze_start_group.add_argument(
        '--from', '--since', '--begin', '--start',
        dest='start',
        metavar='DATETIME',
        help='Start of analysis window (defaults to beginning of current day)'
    )

    # End time aliases
    analyze_end_group = analyze_parser.add_mutually_exclusive_group()
    analyze_end_group.add_argument(
        '--to', '--until', '--end',
        dest='end',
        metavar='DATETIME',
        help='End of analysis window (defaults to now)'
    )

    analyze_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show more details per event'
    )
    analyze_parser.add_argument(
        '--group-by',
        choices=['app', 'hour', 'day'],
        default='app',
        help='How to group results (default: app)'
    )
    analyze_parser.add_argument(
        '--min-duration',
        type=int,
        metavar='MINUTES',
        help='Only show events longer than X minutes'
    )

    # ===== EXPORT subcommand =====
    export_parser = subparsers.add_parser(
        'export',
        help='Export ActivityWatch data to file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export to stdout (default)
  %(prog)s --from "2025-12-08 09:00" --to "2025-12-08 17:00"

  # Export to file
  %(prog)s --from "2025-12-08 09:00" --to "2025-12-08 17:00" -o sample.json

  # Export and pipe to jq
  %(prog)s --from yesterday | jq '.events'
        """
    )

    # Start time aliases
    export_start_group = export_parser.add_mutually_exclusive_group()
    export_start_group.add_argument(
        '--from', '--since', '--begin', '--start',
        dest='start',
        metavar='DATETIME',
        help='Start time (defaults to beginning of current day)'
    )

    # End time aliases
    export_end_group = export_parser.add_mutually_exclusive_group()
    export_end_group.add_argument(
        '--to', '--until', '--end',
        dest='end',
        metavar='DATETIME',
        help='End time (defaults to now)'
    )

    export_parser.add_argument(
        '--output', '-o',
        metavar='FILE',
        default='-',
        help='Output file path (default: stdout). Use "-" for stdout or specify a file path'
    )

    # ===== VALIDATE subcommand =====
    validate_parser = subparsers.add_parser(
        'validate',
        help='Validate configuration file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate default config
  %(prog)s

  # Validate custom config
  %(prog)s --config my_config.toml
        """
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
    data_home = os.environ.get('XDG_DATA_HOME')
    if data_home:
        data_dir = Path(data_home)
    else:
        data_dir = Path.home() / '.local' / 'share'

    log_dir = data_dir / 'aw-export-timewarrior'
    log_dir.mkdir(parents=True, exist_ok=True)

    json_postfix = '.json' if json else ''

    return log_dir / f'aw-export{json_postfix}.log'


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
    if hasattr(args, 'verbose') and args.verbose:
        console_log_level = logging.DEBUG

    # If quiet mode (sync only), suppress console output
    if hasattr(args, 'quiet') and args.quiet:
        console_log_level = logging.CRITICAL + 1  # Above all levels

    # Determine log file
    log_file = None
    if args.log_file and log_level > 0:
        log_file = args.log_file  # Explicit log file
    elif log_level > 0:
        log_file = get_default_log_file(not args.no_log_json)  # Default log file

    # Build run mode info for structured logging (allows filtering logs)
    run_mode = {
        'subcommand': subcommand,
        'dry_run': getattr(args, 'dry_run', False),
        'test_data': hasattr(args, 'test_data') and args.test_data is not None,
        'once': getattr(args, 'once', False),
    }

    # Configure the logging system
    setup_logging(
        json_format=not args.no_log_json,
        log_level=log_level,
        console_log_level=console_log_level,
        log_file=log_file,
        run_mode=run_mode
    )


def validate_sync_args(args: argparse.Namespace) -> Optional[str]:
    """Validate arguments for sync subcommand."""
    if args.test_data:
        if not args.test_data.exists():
            return f"Error: Test data file not found: {args.test_data}"
        if args.start or args.end:
            return "Error: --start/--end not compatible with --test-data (test data has its own time range)"

    # Dry-run without --once requires time boundaries to prevent infinite loop
    if args.dry_run and not args.once:
        if not (args.start and args.end):
            return "Error: --dry-run without --once requires both --start and --end (to prevent infinite loop)"

    # End without start doesn't make sense
    if args.end and not args.start:
        return "Error: --end requires --start to be specified"

    return None


def validate_diff_args(args: argparse.Namespace) -> Optional[str]:
    """Validate arguments for diff subcommand."""
    return None


def validate_analyze_args(args: argparse.Namespace) -> Optional[str]:
    """Validate arguments for analyze subcommand."""
    # End without start doesn't make sense
    return None


def validate_export_args(args: argparse.Namespace) -> Optional[str]:
    """Validate arguments for export subcommand."""
    # Export requires output file (enforced by required=True in argparse)
    # End without start doesn't make sense
    return None


def validate_validate_args(args: argparse.Namespace) -> Optional[str]:
    """Validate arguments for validate subcommand."""
    # No special validation needed
    return None


def run_sync(args: argparse.Namespace) -> int:
    """Execute the sync subcommand."""
    from .export import parse_datetime, load_test_data

    # Parse start/end times if provided
    start_time = None
    end_time = None
    if args.start:
        start_time = parse_datetime(args.start)
        # Default end time to now if not specified
        if args.end:
            end_time = parse_datetime(args.end)
        else:
            end_time = datetime.now(timezone.utc)
        print(f"Processing time range: {start_time} to {end_time}")

    # Load test data if specified
    test_data = None
    if args.test_data:
        print(f"Loading test data from {args.test_data}")
        test_data = load_test_data(args.test_data)

        # Extract start/end times from test data metadata if not provided via CLI
        if not start_time and 'metadata' in test_data and 'start_time' in test_data['metadata']:
            start_time = parse_datetime(test_data['metadata']['start_time'])
            print(f"Using start time from test data: {start_time}")
        if not end_time and 'metadata' in test_data and 'end_time' in test_data['metadata']:
            end_time = parse_datetime(test_data['metadata']['end_time'])
            print(f"Using end time from test data: {end_time}")

    # Create exporter with options
    exporter = Exporter(
        dry_run=args.dry_run,
        config_path=args.config,
        verbose=args.verbose,
        hide_processing_output=args.hide_processing_output,
        enable_pdb=args.pdb,
        start_time=start_time,
        end_time=end_time,
        test_data=test_data
    )

    # Run exporter
    if args.dry_run:
        print("=== DRY RUN MODE ===")
        print("No changes will be made to timewarrior\n")

    if args.once:
        # Process all available events in one call
        exporter.tick(process_all=True)
        print("\nProcessing completed")
    else:
        # Continuous monitoring mode
        if start_time and end_time:
            print(f"Processing time range: {start_time} to {end_time}")
        else:
            print("Starting continuous monitoring (Ctrl+C to stop)...")

        while exporter.tick():
            pass  # tick() returns False when we should stop

        if start_time and end_time:
            print(f"\nReached end of time range at {end_time}")

    return 0


def run_diff(args: argparse.Namespace) -> int:
    """Execute the diff subcommand."""
    from .export import parse_datetime

    # Parse start/end times with defaults
    start_time = parse_datetime(args.start) if args.start else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = parse_datetime(args.end) if args.end else datetime.now(timezone.utc)

    print(f"Comparing time range: {start_time} to {end_time}")

    # Create exporter in dry-run mode (diff doesn't modify unless --apply)
    exporter = Exporter(
        dry_run=not args.apply,  # dry_run=False only if applying
        config_path=args.config,
        verbose=args.verbose,
        show_diff=True,
        show_fix_commands=args.show_commands or args.apply,
        apply_fix=args.apply,
        hide_diff_report=args.hide_report,
        enable_pdb=args.pdb,
        start_time=start_time,
        end_time=end_time
    )

    # Process all events first (to build suggested intervals)
    exporter.tick(process_all=True)

    # Run comparison
    exporter.run_comparison()

    return 0


def run_analyze(args: argparse.Namespace) -> int:
    """Execute the analyze subcommand."""
    from .export import parse_datetime

    # Parse start/end times with defaults
    start_time = parse_datetime(args.start) if args.start else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = parse_datetime(args.end) if args.end else datetime.now(timezone.utc)

    print(f"Analyzing time range: {start_time} to {end_time}")

    # Create exporter in dry-run mode with show_unmatched
    exporter = Exporter(
        dry_run=True,
        config_path=args.config,
        verbose=args.verbose,
        show_unmatched=True,
        enable_pdb=args.pdb,
        start_time=start_time,
        end_time=end_time
    )

    # Process all events
    exporter.tick(process_all=True)

    # Show unmatched events report
    exporter.show_unmatched_events_report()

    return 0


def run_export(args: argparse.Namespace) -> int:
    """Execute the export subcommand."""
    from .export import export_aw_data, parse_datetime
    import sys

    # Parse start/end times with defaults
    start_time = parse_datetime(args.start) if args.start else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = parse_datetime(args.end) if args.end else datetime.now(timezone.utc)

    # Direct progress messages to stderr if outputting to stdout
    use_stdout = str(args.output) == '-'
    progress_output = sys.stderr if use_stdout else sys.stdout

    print(f"Exporting data from {start_time} to {end_time}...", file=progress_output)
    export_aw_data(args.start or str(start_time), args.end or str(end_time), args.output)

    # Don't print completion message when outputting to stdout (export_aw_data already prints summary to stderr)
    if not use_stdout:
        print(f"Data exported to {args.output}")

    return 0


def run_validate(args: argparse.Namespace) -> int:
    """Execute the validate subcommand."""
    from .config import config, validate_config

    errors = validate_config(config, args.config)
    if errors:
        print("Configuration errors found:")
        for error in errors:
            print(f"  - {error}")
        return 1
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
    subcommand = args.subcommand or 'sync'
    if not args.subcommand:
        # Re-parse with 'sync' as the subcommand
        argv_with_sync = ['sync'] + (argv if argv else sys.argv[1:])
        args = parser.parse_args(argv_with_sync)
        args.subcommand = 'sync'

    # Validate config file if specified
    if args.config and not args.config.exists():
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        return 1

    # Configure logging based on arguments
    configure_logging(args, subcommand)

    try:
        # Validate and run the appropriate subcommand
        if subcommand == 'sync':
            error = validate_sync_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_sync(args)

        elif subcommand == 'diff':
            error = validate_diff_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_diff(args)

        elif subcommand == 'analyze':
            error = validate_analyze_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_analyze(args)

        elif subcommand == 'export':
            error = validate_export_args(args)
            if error:
                print(error, file=sys.stderr)
                return 1
            return run_export(args)

        elif subcommand == 'validate':
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
        if hasattr(args, 'verbose') and args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
