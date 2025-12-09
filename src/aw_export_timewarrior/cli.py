#!/usr/bin/env python3
"""
Command-line interface for aw-export-timewarrior.

Provides options for dry-run mode, custom configs, and test data.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .main import Exporter, setup_logging


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description='Export ActivityWatch data to Timewarrior',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Normal operation (live tracking)
  %(prog)s

  # Dry run - see what would be done without modifying timewarrior
  %(prog)s --dry-run

  # Use custom config file
  %(prog)s --config my_config.toml

  # Test with recorded data
  %(prog)s --dry-run --test-data tests/fixtures/sample_day.json

  # Validate config without running
  %(prog)s --validate-config

  # Export current AW data for testing
  %(prog)s --export-data output.json --start "2025-01-01 09:00" --end "2025-01-01 17:00"
        """
    )

    # Main operational modes
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without actually modifying timewarrior'
    )
    mode_group.add_argument(
        '--validate-config',
        action='store_true',
        help='Validate configuration file and exit'
    )
    mode_group.add_argument(
        '--export-data',
        metavar='FILE',
        type=Path,
        help='Export ActivityWatch data to file (JSON/YAML format)'
    )

    # Data source options
    parser.add_argument(
        '--test-data',
        metavar='FILE',
        type=Path,
        help='Load test data from file instead of querying ActivityWatch'
    )

    # Configuration options
    parser.add_argument(
        '--config',
        metavar='FILE',
        type=Path,
        help='Path to configuration file (default: uses standard config locations)'
    )

    # Time range options (for export, dry-run, or limiting processing)
    # Start time aliases
    start_group = parser.add_mutually_exclusive_group()
    start_group.add_argument(
        '--start', '--from', '--since', '--begin', '--after',
        dest='start',
        metavar='DATETIME',
        help='Start time (aliases: --from, --since, --begin, --after)'
    )

    # End time aliases
    end_group = parser.add_mutually_exclusive_group()
    end_group.add_argument(
        '--end', '--to', '--until', '--before',
        dest='end',
        metavar='DATETIME',
        help='End time (aliases: --to, --until, --before). Defaults to current time if start is specified.'
    )

    # Output options
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output (show decisions and reasoning)'
    )
    parser.add_argument(
        '--diff',
        action='store_true',
        help='In dry-run mode, show differences from current timewarrior state'
    )
    parser.add_argument(
        '--show-fix-commands',
        action='store_true',
        help='With --diff, show timew track commands to fix differences'
    )
    parser.add_argument(
        '--apply-fix',
        action='store_true',
        help='With --diff, execute timew track commands to fix differences (implies --show-fix-commands)'
    )
    parser.add_argument(
        '--hide-diff-report',
        action='store_true',
        help='With --diff, hide the detailed comparison report'
    )
    parser.add_argument(
        '--hide-processing-output',
        action='store_true',
        help='Hide the "would execute" messages during processing'
    )
    parser.add_argument(
        '--show-unmatched',
        action='store_true',
        help='Show events that did not match any configuration rules'
    )

    # Logging options
    parser.add_argument(
        '--log-level',
        choices=['NONE', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='DEBUG',
        help='Set normal logging level (default: DEBUG)'
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

    # Single-run mode
    parser.add_argument(
        '--once',
        action='store_true',
        help='Process once and exit (instead of continuous monitoring)'
    )

    return parser


def get_default_log_file(json) -> Path:
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


def configure_logging(args: argparse.Namespace) -> None:
    """
    Configure logging based on command-line arguments.

    Default behavior:
    - Always log to file by default (unless --log-to-console is specified)
    - Log file includes run_mode info for filtering (dry_run, export_data, test_data)

    Args:
        args: Parsed command-line arguments
    """
    # Determine log level
    log_level = getattr(logging, args.log_level, 0)
    console_log_level = getattr(logging, args.console_log_level, 0)

    # If verbose mode, enable DEBUG logging
    if args.verbose:
        console_log_level = logging.DEBUG

    # Determine log file
    log_file = None
    if args.log_file and log_level > 0:
        log_file = args.log_file  # Explicit log file
    elif log_level > 0:
        log_file = get_default_log_file(not args.no_log_json)  # Default log file

    # Build run mode info for structured logging (allows filtering logs)
    run_mode = {
        'dry_run': args.dry_run,
        'export_data': bool(args.export_data),
        'test_data': bool(args.test_data),
        'once': args.once,
    }

    # Configure the logging system
    setup_logging(
        json_format=not args.no_log_json,
        log_level=log_level,
        console_log_level=console_log_level,
        log_file=log_file,
        run_mode=run_mode
    )

def validate_args(args: argparse.Namespace) -> Optional[str]:
    """
    Validate argument combinations.

    Returns:
        Error message if validation fails, None otherwise
    """
    if args.export_data:
        if not args.start or not args.end:
            return "Error: --export-data requires both --start and --end"
        if args.test_data:
            return "Error: --export-data and --test-data are mutually exclusive"

    if args.diff:
        if not args.dry_run:
            return "Error: --diff requires --dry-run"
        if not args.start or not args.end:
            return "Error: --diff requires both --start and --end to define the comparison window"

    if args.show_fix_commands and not args.diff:
        return "Error: --show-fix-commands requires --diff"

    if args.apply_fix:
        if not args.diff:
            return "Error: --apply-fix requires --diff"
        if args.dry_run:
            return "Error: --apply-fix and --dry-run are incompatible (--apply-fix actually modifies the database)"

    if args.hide_diff_report and not args.diff:
        return "Error: --hide-diff-report requires --diff"

    if args.test_data:
        if not args.test_data.exists():
            return f"Error: Test data file not found: {args.test_data}"
        if args.start or args.end:
            return "Error: --start/--end not compatible with --test-data (test data has its own time range)"

    if args.config and not args.config.exists():
        return f"Error: Config file not found: {args.config}"

    # For export-data, both start and end are required
    # For other modes, start alone is allowed (end defaults to now)
    if args.export_data and not (args.start and args.end):
        return "Error: --export-data requires both --start and --end"

    # End without start doesn't make sense
    if args.end and not args.start:
        return "Error: --end requires --start to be specified"

    return None


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

    # Validate arguments
    error = validate_args(args)
    if error:
        print(error, file=sys.stderr)
        return 1

    # Configure logging based on arguments
    configure_logging(args)

    try:
        # Handle export mode
        if args.export_data:
            from .export import export_aw_data
            print(f"Exporting data from {args.start} to {args.end}...")
            export_aw_data(args.start, args.end, args.export_data)
            print(f"Data exported to {args.export_data}")
            return 0

        # Handle config validation mode
        if args.validate_config:
            from .config import config, validate_config
            errors = validate_config(config, args.config)
            if errors:
                print("Configuration errors found:")
                for error in errors:
                    print(f"  - {error}")
                return 1
            print("Configuration is valid")
            return 0

        # Import helper functions
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
                from datetime import datetime, timezone
                end_time = datetime.now(timezone.utc)
            print(f"Processing time range: {start_time} to {end_time}")
        elif args.end:
            # End without start doesn't make sense, but parse it anyway
            end_time = parse_datetime(args.end)

        # Load test data if specified (must be done before creating Exporter)
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
            show_diff=args.diff,
            show_fix_commands=args.show_fix_commands,
            apply_fix=args.apply_fix,
            hide_diff_report=args.hide_diff_report,
            hide_processing_output=args.hide_processing_output,
            show_unmatched=args.show_unmatched,
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

            # Run comparison if in diff mode
            if args.diff:
                exporter.run_comparison()

            # Show unmatched events if requested
            if args.show_unmatched:
                exporter.show_unmatched_events_report()
        else:
            # Continuous monitoring mode
            # In dry-run, we need a time range to avoid infinite looping
            if args.dry_run and not (start_time and end_time):
                print("Error: --dry-run requires --start and --end when not using --once", file=sys.stderr)
                return 1

            if start_time and end_time:
                print(f"Processing time range: {start_time} to {end_time}")
            else:
                print("Starting continuous monitoring (Ctrl+C to stop)...")

            while exporter.tick():
                pass  # tick() returns False when we should stop

            if start_time and end_time:
                print(f"\nReached end of time range at {end_time}")
                # Run comparison if in diff mode
                if args.diff:
                    exporter.run_comparison()
                # Show unmatched events if requested
                if args.show_unmatched:
                    exporter.show_unmatched_events_report()

    except KeyboardInterrupt:
        print("\nExiting...")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
