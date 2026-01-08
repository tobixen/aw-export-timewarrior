"""Tests for mixed events/exports report feature."""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

import pytest

from src.aw_export_timewarrior.state import ExportRecord, StateManager


class TestExportRecord:
    """Tests for ExportRecord dataclass."""

    def test_export_record_creation(self):
        """Test creating an export record."""
        now = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
        accumulator_before = {"work": timedelta(minutes=5), "coding": timedelta(minutes=3)}
        accumulator_after = {"work": timedelta(minutes=2)}

        record = ExportRecord(
            timestamp=now,
            duration=timedelta(minutes=10),
            tags={"work", "coding"},
            accumulator_before=accumulator_before,
            accumulator_after=accumulator_after,
        )

        assert record.timestamp == now
        assert record.duration == timedelta(minutes=10)
        assert record.tags == {"work", "coding"}
        assert record.accumulator_before == accumulator_before
        assert record.accumulator_after == accumulator_after

    def test_export_record_row_type(self):
        """Export record should identify as 'export' row type."""
        record = ExportRecord(
            timestamp=datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC),
            duration=timedelta(minutes=10),
            tags={"work"},
            accumulator_before={},
            accumulator_after={},
        )

        assert record.row_type == "export"


class TestStateManagerExportHistory:
    """Tests for export history tracking in StateManager."""

    def test_state_manager_tracks_exports(self):
        """StateManager should track export history when enabled."""
        state = StateManager(track_exports=True)

        # Simulate export
        state.record_export(
            start=datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 11, 9, 10, 0, tzinfo=UTC),
            tags={"work"},
            record_export_history=True,
        )

        assert len(state.export_history) == 1
        assert state.export_history[0].tags == {"work"}

    def test_export_history_disabled_by_default(self):
        """Export history tracking should be disabled by default for performance."""
        state = StateManager()

        state.record_export(
            start=datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 11, 9, 10, 0, tzinfo=UTC),
            tags={"work"},
            record_export_history=True,
        )

        assert len(state.export_history) == 0

    def test_export_history_captures_accumulator_before(self):
        """Export record should capture accumulator state before the export."""
        state = StateManager(track_exports=True)

        # Add some accumulated time
        state.stats.add_tag_time("work", timedelta(minutes=5))
        state.stats.add_tag_time("coding", timedelta(minutes=3))

        state.record_export(
            start=datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 11, 9, 10, 0, tzinfo=UTC),
            tags={"work"},
            reset_stats=True,
            record_export_history=True,
        )

        record = state.export_history[0]
        assert "work" in record.accumulator_before
        assert record.accumulator_before["work"] == timedelta(minutes=5)
        assert "coding" in record.accumulator_before
        assert record.accumulator_before["coding"] == timedelta(minutes=3)

    def test_export_history_captures_accumulator_after(self):
        """Export record should capture accumulator state after the export."""
        state = StateManager(track_exports=True)

        # Add some accumulated time
        state.stats.add_tag_time("work", timedelta(minutes=5))

        # Export with retention
        state.record_export(
            start=datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 11, 9, 10, 0, tzinfo=UTC),
            tags={"work"},
            reset_stats=True,
            retain_tags={"work"},
            stickyness_factor=0.5,
            record_export_history=True,
        )

        record = state.export_history[0]
        # After with 0.5 stickyness, should have 2.5 minutes
        assert "work" in record.accumulator_after
        assert record.accumulator_after["work"] == timedelta(minutes=2, seconds=30)

    def test_export_history_multiple_exports(self):
        """StateManager should track multiple exports in order."""
        state = StateManager(track_exports=True)

        for i in range(3):
            state.record_export(
                start=datetime(2025, 12, 11, 9 + i, 0, 0, tzinfo=UTC),
                end=datetime(2025, 12, 11, 9 + i, 10, 0, tzinfo=UTC),
                tags={f"tag{i}"},
                record_export_history=True,
            )

        assert len(state.export_history) == 3
        assert state.export_history[0].tags == {"tag0"}
        assert state.export_history[1].tags == {"tag1"}
        assert state.export_history[2].tags == {"tag2"}

    def test_get_exports_in_range(self):
        """StateManager should filter exports by time range."""
        state = StateManager(track_exports=True)

        # Add exports at different times
        state.record_export(
            start=datetime(2025, 12, 11, 8, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 11, 8, 10, 0, tzinfo=UTC),
            tags={"early"},
            record_export_history=True,
        )
        state.record_export(
            start=datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 11, 9, 10, 0, tzinfo=UTC),
            tags={"middle"},
            record_export_history=True,
        )
        state.record_export(
            start=datetime(2025, 12, 11, 10, 0, 0, tzinfo=UTC),
            end=datetime(2025, 12, 11, 10, 10, 0, tzinfo=UTC),
            tags={"late"},
            record_export_history=True,
        )

        # Filter to 9:00-9:30 range
        start = datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC)
        end = datetime(2025, 12, 11, 9, 30, 0, tzinfo=UTC)

        exports = state.get_exports_in_range(start, end)

        assert len(exports) == 1
        assert exports[0].tags == {"middle"}


class TestCollectReportDataWithExports:
    """Tests for collect_report_data with include_exports option."""

    @pytest.fixture
    def sample_report_data(self):
        """Sample report data with events."""
        return [
            {
                "timestamp": datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC),
                "duration": timedelta(minutes=5),
                "window_title": "Test Window 1",
                "app": "chromium",
                "specialized_type": "browser",
                "specialized_data": "https://example.com",
                "afk_status": "not-afk",
                "tags": {"work"},
                "matched_rule": "browser:example",
                "row_type": "event",
            },
            {
                "timestamp": datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC),
                "duration": timedelta(minutes=5),
                "window_title": "Test Window 2",
                "app": "chromium",
                "specialized_type": "browser",
                "specialized_data": "https://example.com",
                "afk_status": "not-afk",
                "tags": {"work"},
                "matched_rule": "browser:example",
                "row_type": "event",
            },
        ]

    @pytest.fixture
    def sample_export_record(self):
        """Sample export record."""
        return ExportRecord(
            timestamp=datetime(2025, 12, 11, 9, 2, 30, tzinfo=UTC),
            duration=timedelta(minutes=2, seconds=30),
            tags={"work"},
            accumulator_before={"work": timedelta(minutes=2, seconds=30)},
            accumulator_after={"work": timedelta(minutes=1, seconds=15)},
        )

    def test_interleave_exports_with_events(self, sample_report_data, sample_export_record):
        """Exports should be interleaved with events by timestamp."""
        from src.aw_export_timewarrior.report import interleave_exports

        result = interleave_exports(sample_report_data, [sample_export_record])

        # Should have 3 rows: event, export, event
        assert len(result) == 3
        assert result[0]["row_type"] == "event"
        assert result[1]["row_type"] == "export"
        assert result[2]["row_type"] == "event"

        # Verify order is by timestamp
        assert result[0]["timestamp"] < result[1]["timestamp"]
        assert result[1]["timestamp"] < result[2]["timestamp"]


class TestTableOutputWithExports:
    """Tests for table output with colored export lines."""

    @pytest.fixture
    def mixed_data(self):
        """Sample data with both events and exports."""
        return [
            {
                "timestamp": datetime(2025, 12, 11, 9, 0, 0, tzinfo=UTC),
                "duration": timedelta(minutes=5),
                "window_title": "Test Window",
                "app": "chromium",
                "specialized_type": "browser",
                "specialized_data": "https://example.com",
                "afk_status": "not-afk",
                "tags": {"work"},
                "row_type": "event",
            },
            {
                "timestamp": datetime(2025, 12, 11, 9, 5, 0, tzinfo=UTC),
                "duration": timedelta(minutes=5),
                "tags": {"work"},
                "accumulator_before": {"work": timedelta(minutes=5)},
                "accumulator_after": {"work": timedelta(minutes=2, seconds=30)},
                "row_type": "export",
            },
        ]

    def test_table_output_includes_export_rows(self, mixed_data):
        """Table output should include export rows."""
        from src.aw_export_timewarrior.report import format_as_table

        output = StringIO()
        with patch("sys.stdout", output):
            format_as_table(mixed_data, show_exports=True)

        table_output = output.getvalue()

        # Should contain "EXPORT" marker for export rows
        assert "EXPORT" in table_output or "export" in table_output.lower()

    def test_export_row_shows_accumulator_info(self, mixed_data):
        """Export row should show accumulator before/after."""
        from src.aw_export_timewarrior.report import format_as_table

        output = StringIO()
        with patch("sys.stdout", output):
            format_as_table(mixed_data, show_exports=True)

        table_output = output.getvalue()

        # Should contain accumulator info
        assert "work" in table_output

    def test_json_output_includes_exports(self, mixed_data):
        """JSON output should include export records."""
        from src.aw_export_timewarrior.report import format_as_json

        output = StringIO()
        with patch("sys.stdout", output):
            format_as_json(mixed_data, include_exports=True)

        lines = output.getvalue().strip().split("\n")
        assert len(lines) == 2

        # Second line should be export
        export_record = json.loads(lines[1])
        assert export_record["row_type"] == "export"
        assert "accumulator_before" in export_record
        assert "accumulator_after" in export_record


class TestExportFormatting:
    """Tests for export line formatting."""

    def test_format_accumulator_dict(self):
        """Accumulator dict should be formatted nicely."""
        from src.aw_export_timewarrior.report import format_accumulator

        acc = {
            "work": timedelta(minutes=5),
            "coding": timedelta(minutes=3, seconds=30),
        }

        result = format_accumulator(acc)

        assert "work" in result
        assert "5:00" in result or "05:00" in result or "5m" in result
        assert "coding" in result

    def test_format_accumulator_empty(self):
        """Empty accumulator should show as empty or dash."""
        from src.aw_export_timewarrior.report import format_accumulator

        result = format_accumulator({})

        assert result in ("-", "{}", "empty", "")
