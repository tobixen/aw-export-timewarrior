"""Tests for CLI argument parsing, validation, and factory functions."""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.cli import (
    create_exporter_from_args,
    create_parser,
    validate_sync_args,
)


class TestCreateParser:
    """Tests for argument parser creation."""

    def test_parser_has_all_subcommands(self) -> None:
        """Test that parser includes all expected subcommands."""
        parser = create_parser()

        # Parse with different subcommands to verify they exist
        for subcommand in ["sync", "diff", "analyze", "export", "report", "validate"]:
            args = parser.parse_args([subcommand])
            assert args.subcommand == subcommand

    def test_global_options_available(self) -> None:
        """Test that global options are available (must come before subcommand)."""
        parser = create_parser()

        # Global options must come BEFORE the subcommand
        args = parser.parse_args(
            ["--config", "test.toml", "--log-level", "DEBUG", "--enable-pdb", "sync"]
        )

        assert args.config == Path("test.toml")
        assert args.log_level == "DEBUG"
        assert args.enable_pdb is True
        assert args.enable_assert is False  # Mutually exclusive with enable_pdb

    def test_pdb_and_break_assert_mutually_exclusive(self) -> None:
        """Test that --enable-pdb and --enable-assert cannot be used together."""
        parser = create_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(["--enable-pdb", "--enable-assert", "sync"])

    def test_timespan_arguments_sync(self) -> None:
        """Test timespan arguments for sync subcommand."""
        parser = create_parser()

        # Test --from/--to
        args = parser.parse_args(["sync", "--from", "2025-01-01", "--to", "2025-01-02"])
        assert args.start == "2025-01-01"
        assert args.end == "2025-01-02"

        # Test aliases
        args = parser.parse_args(["sync", "--since", "2025-01-01", "--until", "2025-01-02"])
        assert args.start == "2025-01-01"
        assert args.end == "2025-01-02"

    def test_sync_subcommand_options(self) -> None:
        """Test sync-specific options."""
        parser = create_parser()

        args = parser.parse_args(
            ["sync", "--dry-run", "--once", "--verbose", "--hide-processing-output"]
        )

        assert args.dry_run is True
        assert args.once is True
        assert args.verbose is True
        assert args.hide_processing_output is True

    def test_diff_subcommand_options(self) -> None:
        """Test diff-specific options."""
        parser = create_parser()

        args = parser.parse_args(
            ["diff", "--show-commands", "--apply", "--timeline", "--hide-report"]
        )

        assert args.show_commands is True
        assert args.apply is True
        assert args.timeline is True
        assert args.hide_report is True

    def test_report_subcommand_options(self) -> None:
        """Test report-specific options."""
        parser = create_parser()

        args = parser.parse_args(["report", "--all-columns", "--format", "csv", "--no-truncate"])

        assert args.all_columns is True
        assert args.format == "csv"
        assert args.no_truncate is True


class TestCreateExporterFromArgs:
    """Tests for create_exporter_from_args factory function."""

    def test_basic_exporter_creation(self) -> None:
        """Test basic exporter creation from args."""
        args = argparse.Namespace(
            config=None,
            verbose=False,
            dry_run=False,
            enable_pdb=False,
            enable_assert=False,
            start=None,
            end=None,
            test_data={"buckets": {}},  # Provide test data to avoid AW client creation
            subcommand="sync",
        )

        with patch("aw_export_timewarrior.cli._handle_start_stop_testdata_from_args"):
            exporter = create_exporter_from_args(args, "sync")

        assert exporter is not None
        assert exporter.verbose is False
        assert exporter.dry_run is False

    def test_arg_mapping_timeline_to_show_timeline(self) -> None:
        """Test that 'timeline' arg maps to 'show_timeline' field."""
        args = argparse.Namespace(
            timeline=True,
            config=None,
            enable_pdb=False,
            enable_assert=False,
            start=None,
            end=None,
            test_data={"buckets": {}},  # Provide test data
            subcommand="diff",
        )

        with patch("aw_export_timewarrior.cli._handle_start_stop_testdata_from_args"):
            exporter = create_exporter_from_args(args, "diff")

        assert exporter.show_timeline is True

    def test_arg_mapping_config_to_config_path(self) -> None:
        """Test that 'config' arg maps to 'config_path' field."""
        args = argparse.Namespace(
            config=Path("test_config.toml"),
            enable_pdb=False,
            enable_assert=False,
            start=None,
            end=None,
            test_data={"buckets": {}},  # Provide test data
            subcommand="sync",
        )

        # Mock load_config in main.py where Exporter __post_init__ calls it
        with patch("aw_export_timewarrior.main.load_config") as mock_load:
            mock_load.return_value = {"exclusive": {}, "tags": {}, "terminal_apps": []}
            with patch("aw_export_timewarrior.cli._handle_start_stop_testdata_from_args"):
                exporter = create_exporter_from_args(args, "sync")

        assert exporter.config_path == Path("test_config.toml")

    def test_overrides_take_precedence(self) -> None:
        """Test that explicit overrides take precedence over args."""
        args = argparse.Namespace(
            dry_run=False,
            verbose=False,
            config=None,
            enable_pdb=False,
            enable_assert=False,
            start=None,
            end=None,
            test_data={"buckets": {}},  # Provide test data
            subcommand="diff",
        )

        with patch("aw_export_timewarrior.cli._handle_start_stop_testdata_from_args"):
            exporter = create_exporter_from_args(
                args,
                "diff",
                dry_run=True,  # Override
                show_diff=True,  # Additional param
            )

        assert exporter.dry_run is True  # Override applied
        assert exporter.show_diff is True  # Additional param set

    def test_none_values_not_included(self) -> None:
        """Test that None values from args are not passed to Exporter."""
        args = argparse.Namespace(
            verbose=None,  # Should be filtered out
            dry_run=False,
            config=None,
            enable_pdb=False,
            enable_assert=False,
            start=None,
            end=None,
            test_data={"buckets": {}},  # Provide test data
            subcommand="sync",
        )

        with patch("aw_export_timewarrior.cli._handle_start_stop_testdata_from_args"):
            exporter = create_exporter_from_args(args, "sync")

        # verbose should use Exporter's default (False) since None was filtered
        assert exporter.verbose is False

    def test_calls_handle_start_stop_testdata(self) -> None:
        """Test that factory calls _handle_start_stop_testdata_from_args."""
        args = argparse.Namespace(
            config=None,
            enable_pdb=False,
            enable_assert=False,
            start="2025-01-01",
            end="2025-01-02",
            test_data={"buckets": {}},  # Provide test data
            subcommand="sync",
        )

        with patch(
            "aw_export_timewarrior.cli._handle_start_stop_testdata_from_args"
        ) as mock_handle:
            create_exporter_from_args(args, "sync")

            # Verify it was called with args, kwargs dict, and method
            mock_handle.assert_called_once()
            call_args = mock_handle.call_args[0]
            assert call_args[0] == args
            assert isinstance(call_args[1], dict)
            assert call_args[2] == "sync"


class TestValidateSyncArgs:
    """Tests for sync argument validation."""

    def test_dry_run_without_once_requires_time_boundaries(self) -> None:
        """Test that dry-run without --once requires both --start and --end."""
        args = argparse.Namespace(dry_run=True, once=False, start=None, end=None, test_data=None)

        error = validate_sync_args(args)
        assert error is not None
        assert "--start and --end" in error

    def test_dry_run_with_once_allowed_without_boundaries(self) -> None:
        """Test that dry-run with --once doesn't require time boundaries."""
        args = argparse.Namespace(dry_run=True, once=True, start=None, end=None, test_data=None)

        error = validate_sync_args(args)
        assert error is None

    def test_dry_run_with_boundaries_is_valid(self) -> None:
        """Test that dry-run with both boundaries is valid."""
        args = argparse.Namespace(
            dry_run=True, once=False, start="2025-01-01", end="2025-01-02", test_data=None
        )

        error = validate_sync_args(args)
        assert error is None

    def test_end_without_start_is_invalid(self) -> None:
        """Test that --end without --start is invalid."""
        args = argparse.Namespace(
            dry_run=False, once=True, start=None, end="2025-01-02", test_data=None
        )

        error = validate_sync_args(args)
        assert error is not None
        assert "--end requires --start" in error

    def test_test_data_with_time_args_is_invalid(self, tmp_path: Path) -> None:
        """Test that --test-data with --start/--end is invalid."""
        # Create a temporary test file
        test_file = tmp_path / "test.json"
        test_file.write_text("{}")

        args = argparse.Namespace(
            dry_run=False, once=True, start="2025-01-01", end="2025-01-02", test_data=test_file
        )

        error = validate_sync_args(args)
        assert error is not None
        assert "not compatible" in error

    def test_test_data_file_not_found(self) -> None:
        """Test that validation fails if test data file doesn't exist."""
        args = argparse.Namespace(
            dry_run=False, once=True, start=None, end=None, test_data=Path("/nonexistent/test.json")
        )

        error = validate_sync_args(args)
        assert error is not None
        assert "not found" in error

    def test_normal_sync_no_validation_errors(self) -> None:
        """Test that normal sync without special flags is valid."""
        args = argparse.Namespace(dry_run=False, once=False, start=None, end=None, test_data=None)

        error = validate_sync_args(args)
        assert error is None


class TestHandleStartStopTestdata:
    """Tests for _handle_start_stop_testdata_from_args function."""

    @patch("aw_export_timewarrior.cli.parse_datetime")
    def test_start_and_end_parsed(self, mock_parse: Mock) -> None:
        """Test that start and end times are parsed."""
        from aw_export_timewarrior.cli import _handle_start_stop_testdata_from_args

        mock_parse.side_effect = [
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
        ]

        args = argparse.Namespace(start="2025-01-01", end="2025-01-02", day=None, test_data=None)

        exporter_args = {}
        _handle_start_stop_testdata_from_args(args, exporter_args, "sync")

        assert exporter_args["start_time"] == datetime(2025, 1, 1, tzinfo=UTC)
        assert exporter_args["end_time"] == datetime(2025, 1, 2, tzinfo=UTC)
        assert mock_parse.call_count == 2

    @patch("aw_export_timewarrior.cli.datetime")
    def test_non_sync_defaults_to_today(self, mock_datetime: Mock) -> None:
        """Test that non-sync methods default start to midnight today."""
        from aw_export_timewarrior.cli import _handle_start_stop_testdata_from_args

        mock_datetime.now.return_value.astimezone.return_value.replace.return_value = datetime(
            2025, 1, 15, 0, 0, 0, tzinfo=UTC
        )

        args = argparse.Namespace(start=None, end=None, day=None, test_data=None)

        exporter_args = {}
        _handle_start_stop_testdata_from_args(args, exporter_args, "report")

        # Should default to midnight
        assert exporter_args["start_time"] == datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)

    def test_non_sync_defaults_end_to_now(self) -> None:
        """Test that non-sync methods default end to current time."""
        from aw_export_timewarrior.cli import _handle_start_stop_testdata_from_args

        args = argparse.Namespace(start=None, end=None, day=None, test_data=None)

        exporter_args = {}
        _handle_start_stop_testdata_from_args(args, exporter_args, "diff")

        # Should have set end_time to something (current time)
        assert exporter_args["end_time"] is not None
        # Should have set start_time to midnight today
        assert exporter_args["start_time"] is not None

    @patch("aw_export_timewarrior.cli.load_test_data")
    @patch("aw_export_timewarrior.cli.parse_datetime")
    def test_test_data_loads_time_from_metadata(self, mock_parse: Mock, mock_load: Mock) -> None:
        """Test that test data metadata provides default times."""
        from aw_export_timewarrior.cli import _handle_start_stop_testdata_from_args

        mock_load.return_value = {
            "metadata": {"start_time": "2025-01-01T00:00:00Z", "end_time": "2025-01-01T23:59:59Z"}
        }

        mock_parse.side_effect = [
            datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
            datetime(2025, 1, 1, 23, 59, 59, tzinfo=UTC),
        ]

        args = argparse.Namespace(start=None, end=None, day=None, test_data=Path("test.json"))

        exporter_args = {}
        _handle_start_stop_testdata_from_args(args, exporter_args, "sync")

        assert exporter_args["start_time"] == datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert exporter_args["end_time"] == datetime(2025, 1, 1, 23, 59, 59, tzinfo=UTC)
        assert exporter_args["test_data"] is not None

    def test_sync_method_no_default_times(self) -> None:
        """Test that sync method doesn't set default start/end times."""
        from aw_export_timewarrior.cli import _handle_start_stop_testdata_from_args

        args = argparse.Namespace(start=None, end=None, day=None, test_data=None)

        exporter_args = {}
        _handle_start_stop_testdata_from_args(args, exporter_args, "sync")

        # Sync should leave start/end as None if not specified
        assert exporter_args["start_time"] is None
        assert exporter_args["end_time"] is None


class TestEndToEndCLI:
    """End-to-end tests for CLI workflows."""

    @patch("sys.argv", ["cli.py"])  # Mock sys.argv to avoid pytest args
    @patch("aw_export_timewarrior.cli.run_sync")
    def test_default_subcommand_is_sync(self, mock_run_sync: Mock) -> None:
        """Test that no subcommand defaults to sync."""
        from aw_export_timewarrior.cli import main

        mock_run_sync.return_value = 0

        result = main([])

        assert result == 0
        mock_run_sync.assert_called_once()

    def test_config_file_validation(self) -> None:
        """Test that missing config file is caught."""
        from aw_export_timewarrior.cli import main

        # Global options come before subcommand
        result = main(["--config", "/nonexistent/config.toml", "sync"])

        assert result == 1  # Error exit code


class TestDiffModeReadOnly:
    """Test that diff mode is read-only and doesn't execute timew commands."""

    def test_diff_without_apply_doesnt_execute_commands(self) -> None:
        """Test that diff mode without --apply doesn't execute timew start commands."""
        from aw_export_timewarrior.cli import create_exporter_from_args

        # Use real test data
        test_data_path = Path(__file__).parent / "fixtures" / "sample_15min.json"
        config_path = Path(__file__).parent / "fixtures" / "test_config.toml"

        args = argparse.Namespace(
            day=None,
            start="2025-01-01T00:00:00",
            end="2025-01-01T01:00:00",
            test_data=test_data_path,
            apply=False,  # No --apply flag
            show_commands=False,
            timeline=False,
            hide_report=False,
            config=config_path,
            verbose=False,
            enable_pdb=False,
            enable_assert=True,
        )

        # Create exporter with diff mode settings
        exporter = create_exporter_from_args(
            args,
            "diff",
            dry_run=not args.apply,  # Should be True
            show_diff=True,
            show_fix_commands=False,
        )

        # Verify dry_run is True
        assert exporter.dry_run is True, "diff mode without --apply should have dry_run=True"

        # Process all events
        exporter.tick(process_all=True)

        # Get captured commands
        commands = exporter.get_captured_commands()

        # Check that NO timew start commands were captured
        start_commands = [cmd for cmd in commands if "start" in cmd]

        assert (
            len(start_commands) == 0
        ), f"diff mode should not execute 'timew start' commands, but got: {start_commands}"

    def test_diff_with_apply_allows_execution(self) -> None:
        """Test that diff mode with --apply allows command execution."""
        from aw_export_timewarrior.cli import create_exporter_from_args

        test_data_path = Path(__file__).parent / "fixtures" / "sample_15min.json"
        config_path = Path(__file__).parent / "fixtures" / "test_config.toml"

        args = argparse.Namespace(
            day=None,
            start="2025-01-01T00:00:00",
            end="2025-01-01T01:00:00",
            test_data=test_data_path,
            apply=True,  # --apply flag set
            show_commands=True,
            timeline=False,
            hide_report=False,
            config=config_path,
            verbose=False,
            enable_pdb=False,
            enable_assert=True,
        )

        # Create exporter with diff mode settings
        exporter = create_exporter_from_args(
            args,
            "diff",
            dry_run=not args.apply,  # Should be False
            show_diff=True,
            show_fix_commands=True,
        )

        # Verify dry_run is False
        assert exporter.dry_run is False, "diff mode with --apply should have dry_run=False"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
