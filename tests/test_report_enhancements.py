"""Tests for report command enhancements: JSON output, rule display, column toggling."""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from src.aw_export_timewarrior.main import Exporter
from src.aw_export_timewarrior.report import (
    collect_report_data,
    format_as_json,
    format_as_table,
)


@pytest.fixture
def test_data_path() -> Path:
    """Path to the anonymized test data file."""
    return Path(__file__).parent / "fixtures" / "report_test_data.json"


@pytest.fixture
def exporter_with_test_data(test_data_path: Path) -> Exporter:
    """Create an Exporter instance with test data loaded."""
    from src.aw_export_timewarrior.export import load_test_data

    test_data = load_test_data(test_data_path)
    exporter = Exporter(dry_run=True, test_data=test_data)
    return exporter


@pytest.fixture
def sample_report_data() -> list[dict]:
    """Sample report data for testing output formats."""
    return [
        {
            "timestamp": datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC),
            "duration": timedelta(minutes=5),
            "window_title": "Test Window",
            "app": "chromium",
            "specialized_type": "browser",
            "specialized_data": "https://example.com",
            "afk_status": "not-afk",
            "tags": {"work", "4RL"},
            "matched_rule": "browser:example",
        },
        {
            "timestamp": datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC),
            "duration": timedelta(minutes=3),
            "window_title": "emacs@host",
            "app": "emacs",
            "specialized_type": "editor",
            "specialized_data": "/home/user/project/file.py",
            "afk_status": "not-afk",
            "tags": {"coding", "4RL"},
            "matched_rule": "editor:project",
        },
        {
            "timestamp": datetime(2025, 12, 11, 9, 8, 0, tzinfo=UTC),
            "duration": timedelta(minutes=2),
            "window_title": "Unknown App",
            "app": "unknown",
            "specialized_type": None,
            "specialized_data": "",
            "afk_status": "unknown",
            "tags": {"UNMATCHED"},
            "matched_rule": None,
        },
    ]


class TestJSONOutput:
    """Tests for JSON output format (JSONL - one dict per line)."""

    def test_format_as_json_outputs_valid_jsonl(self, sample_report_data):
        """Each line of output should be valid JSON."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_json(sample_report_data)

        lines = output.getvalue().strip().split("\n")
        assert len(lines) == len(sample_report_data)

        for line in lines:
            # Each line should be valid JSON
            parsed = json.loads(line)
            assert isinstance(parsed, dict)

    def test_format_as_json_includes_all_fields(self, sample_report_data):
        """JSON output with all_columns should include all required fields."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_json(sample_report_data, all_columns=True)

        lines = output.getvalue().strip().split("\n")
        first_record = json.loads(lines[0])

        expected_fields = {
            "timestamp",
            "duration_seconds",
            "window_title",
            "app",
            "specialized_type",
            "specialized_data",
            "afk_status",
            "tags",
        }
        assert expected_fields.issubset(set(first_record.keys()))

    def test_format_as_json_includes_rule_when_present(self, sample_report_data):
        """JSON output should include matched_rule field when available."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_json(sample_report_data, include_rule=True)

        lines = output.getvalue().strip().split("\n")
        first_record = json.loads(lines[0])

        assert "matched_rule" in first_record
        assert first_record["matched_rule"] == "browser:example"

    def test_format_as_json_tags_as_list(self, sample_report_data):
        """Tags should be serialized as a sorted list for JSON compatibility."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_json(sample_report_data)

        lines = output.getvalue().strip().split("\n")
        first_record = json.loads(lines[0])

        assert isinstance(first_record["tags"], list)
        assert set(first_record["tags"]) == {"work", "4RL"}

    def test_format_as_json_timestamp_iso_format(self, sample_report_data):
        """Timestamps should be in ISO format."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_json(sample_report_data)

        lines = output.getvalue().strip().split("\n")
        first_record = json.loads(lines[0])

        # Should be parseable as ISO timestamp
        parsed_ts = datetime.fromisoformat(first_record["timestamp"])
        assert parsed_ts.year == 2025

    def test_format_as_json_with_column_filter(self, sample_report_data):
        """JSON output should respect column filter."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_json(sample_report_data, columns=["timestamp", "tags", "app"])

        lines = output.getvalue().strip().split("\n")
        first_record = json.loads(lines[0])

        # Should only have specified columns
        assert set(first_record.keys()) == {"timestamp", "tags", "app"}


class TestRuleDisplay:
    """Tests for displaying which rule matched each event."""

    def test_collect_report_data_includes_matched_rule(self, exporter_with_test_data: Exporter):
        """Report data should include the matched rule name."""
        start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

        data = collect_report_data(exporter_with_test_data, start_time, end_time, include_rule=True)

        # All events should have matched_rule key
        for row in data:
            assert "matched_rule" in row
            # Value can be None (unmatched) or a string (rule name)
            assert row["matched_rule"] is None or isinstance(row["matched_rule"], str)

    def test_matched_rule_format(self, exporter_with_test_data: Exporter):
        """Matched rule should be in format 'type:name' (e.g., 'browser:github')."""
        start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

        data = collect_report_data(exporter_with_test_data, start_time, end_time, include_rule=True)

        # Find events with matched rules
        matched_events = [row for row in data if row.get("matched_rule")]

        for event in matched_events:
            rule = event["matched_rule"]
            # Should contain a colon separator (type:name format)
            assert ":" in rule, f"Rule '{rule}' should be in 'type:name' format"

    def test_unmatched_events_have_none_rule(self, exporter_with_test_data: Exporter):
        """Events that don't match any rule should have matched_rule=None."""
        start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

        data = collect_report_data(exporter_with_test_data, start_time, end_time, include_rule=True)

        # Find unmatched events
        unmatched = [row for row in data if "UNMATCHED" in row["tags"]]

        for event in unmatched:
            assert event["matched_rule"] is None

    def test_table_output_with_rule_column(self, sample_report_data):
        """Table output should show rule column when requested."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_table(sample_report_data, show_rule=True)

        table_output = output.getvalue()

        # Header should include "Rule" column
        assert "Rule" in table_output
        # Should show the rule name
        assert "browser:example" in table_output


class TestColumnToggle:
    """Tests for toggling which columns to display."""

    def test_format_as_table_default_columns(self, sample_report_data):
        """Default table output should show standard columns."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_table(sample_report_data)

        table_output = output.getvalue()

        # Default columns should be present
        assert "Time" in table_output
        assert "Dur" in table_output
        assert "Tags" in table_output

    @pytest.mark.skip(reason="Column selection for tables not yet implemented")
    def test_format_as_table_with_column_selection(self, sample_report_data):
        """Table output should respect column selection."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_table(sample_report_data, columns=["timestamp", "tags"])

        table_output = output.getvalue()

        # Selected columns should be present
        assert "Time" in table_output
        assert "Tags" in table_output

        # Non-selected columns should not have headers
        # (Window Title header should not appear)
        lines = table_output.split("\n")
        header_line = lines[0]
        assert "Window" not in header_line

    def test_format_as_json_with_all_columns(self, sample_report_data):
        """JSON output with all_columns should include everything."""
        output = StringIO()
        with patch("sys.stdout", output):
            format_as_json(sample_report_data, all_columns=True, include_rule=True)

        lines = output.getvalue().strip().split("\n")
        first_record = json.loads(lines[0])

        # Should have all fields including optional ones
        assert "matched_rule" in first_record
        assert "specialized_type" in first_record
        assert "specialized_data" in first_record

    def test_available_columns_constant(self):
        """There should be a constant defining all available columns."""
        from src.aw_export_timewarrior.report import AVAILABLE_COLUMNS

        expected_columns = {
            "timestamp",
            "duration",
            "window_title",
            "app",
            "specialized_type",
            "specialized_data",
            "afk_status",
            "tags",
            "matched_rule",
        }
        assert expected_columns.issubset(set(AVAILABLE_COLUMNS))


class TestIntegration:
    """Integration tests using real test data."""

    def test_json_output_from_real_data(self, exporter_with_test_data: Exporter):
        """Test JSON output with real anonymized test data."""
        start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

        data = collect_report_data(exporter_with_test_data, start_time, end_time, include_rule=True)

        output = StringIO()
        with patch("sys.stdout", output):
            format_as_json(data, include_rule=True)

        lines = output.getvalue().strip().split("\n")

        # Should have same number of records
        assert len(lines) == len(data)

        # All should be valid JSON
        for line in lines:
            record = json.loads(line)
            assert "timestamp" in record
            assert "tags" in record

    def test_csv_output_with_rule_column(self, exporter_with_test_data: Exporter):
        """Test CSV output includes rule column when requested."""
        from src.aw_export_timewarrior.report import format_as_csv

        start_time = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
        end_time = datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC)

        data = collect_report_data(exporter_with_test_data, start_time, end_time, include_rule=True)

        output = StringIO()
        with patch("sys.stdout", output):
            format_as_csv(data, include_rule=True)

        csv_output = output.getvalue()
        lines = csv_output.strip().split("\n")

        # Header should include matched_rule
        header = lines[0]
        assert "matched_rule" in header
