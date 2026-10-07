"""A diff over one day must take in whole events crossing its edges.

aw-server clips events to the queried range, so a night's AFK period that
starts the evening before is handed over as starting at midnight, and the
afk-prompt answers on it are cut the same way.  Importing a day used to leave
such a night as a bare ``afk`` interval.  The diff range is now widened to the
full extent of afk-status (afk and not-afk) and afk-prompt events crossing
either edge.
"""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aw_export_timewarrior.aw_client import EventFetcher
from aw_export_timewarrior.cli import create_diff_exporter
from aw_export_timewarrior.main import Exporter
from aw_export_timewarrior.utils import normalize_duration, normalize_timestamp
from tests.conftest import FixtureDataBuilder

CONFIG_FILE = Path(__file__).parent / "fixtures" / "test_config.toml"

DAY_START = datetime(2025, 1, 2, 0, 0, tzinfo=UTC)
DAY_END = DAY_START + timedelta(days=1)
AFK_START = datetime(2025, 1, 1, 22, 18, tzinfo=UTC)
AFK_END = datetime(2025, 1, 2, 8, 14, tzinfo=UTC)


@pytest.fixture
def clipping_server(monkeypatch):
    """Make the test-data fetcher clip events to the range, like aw-server does."""
    unclipped = EventFetcher._get_events_from_test_data

    def clipped(self, bucket_id, start, end):
        result = []
        for event in unclipped(self, bucket_id, start, end):
            ev_start = normalize_timestamp(event["timestamp"])
            ev_end = ev_start + normalize_duration(event["duration"])
            if start:
                ev_start = max(ev_start, start)
            if end:
                ev_end = min(ev_end, end)
            if ev_end <= ev_start:
                continue
            result.append({**event, "timestamp": ev_start, "duration": ev_end - ev_start})
        return result

    monkeypatch.setattr(EventFetcher, "_get_events_from_test_data", clipped)


def _night_across_midnight(tmp_path: Path) -> Path:
    """Evening work, a night AFK from 22:18 to 08:14 answered in three parts, work."""
    builder = FixtureDataBuilder(start_time=datetime(2025, 1, 1, 21, 0, tzinfo=UTC))
    builder.add_window_event("Code", "main.py", AFK_START - builder.current_time)
    builder.add_afk_event("not-afk", timedelta(minutes=78))
    builder.add_afk_event("afk", AFK_END - AFK_START, timestamp=AFK_START)
    builder.add_ask_away_event(
        "reading", datetime(2025, 1, 1, 23, 59, 59, tzinfo=UTC) - AFK_START, timestamp=AFK_START
    )
    builder.add_ask_away_event("bedtime", timedelta(hours=8, minutes=3, seconds=1))
    builder.add_ask_away_event("tea", AFK_END - builder.current_time)
    builder.add_window_event("Code", "main.py", 2700, timestamp=AFK_END)
    builder.add_afk_event("not-afk", 2700, timestamp=AFK_END)
    path = tmp_path / "night.json"
    path.write_text(json.dumps(builder.build()))
    return path


def _diff_args(test_data: Path) -> argparse.Namespace:
    return argparse.Namespace(
        day=None,
        start=DAY_START.isoformat(),
        end=DAY_END.isoformat(),
        test_data=test_data,
        apply=False,
        show_commands=False,
        timeline=False,
        hide_report=True,
        config=CONFIG_FILE,
        verbose=False,
        enable_pdb=False,
        enable_assert=False,
    )


def test_diff_range_widened_to_events_crossing_midnight(tmp_path, clipping_server) -> None:
    exporter = create_diff_exporter(_diff_args(_night_across_midnight(tmp_path)))

    assert exporter.start_time == AFK_START
    # Nothing crosses the end of the day, so that edge stays put.
    assert exporter.end_time == DAY_END


def test_diff_tags_the_whole_night(tmp_path, clipping_server) -> None:
    exporter = create_diff_exporter(_diff_args(_night_across_midnight(tmp_path)))
    exporter.tick(process_all=True)

    def tags_at(moment: datetime) -> set[str]:
        for interval in exporter.get_suggested_intervals():
            if interval.start <= moment < interval.end:
                return interval.tags
        return set()

    assert {"afk", "reading"} <= tags_at(datetime(2025, 1, 1, 23, 0, tzinfo=UTC))
    assert {"afk", "bedtime"} <= tags_at(datetime(2025, 1, 2, 3, 0, tzinfo=UTC))
    assert {"afk", "tea"} <= tags_at(datetime(2025, 1, 2, 8, 10, tzinfo=UTC))


def test_diff_range_widened_to_night_crossing_its_end(tmp_path, clipping_server) -> None:
    args = _diff_args(_night_across_midnight(tmp_path))
    args.start, args.end = (DAY_START - timedelta(days=1)).isoformat(), DAY_START.isoformat()
    exporter = create_diff_exporter(args)

    assert exporter.end_time == AFK_END
    exporter.tick(process_all=True)
    tags = {frozenset(interval.tags) for interval in exporter.get_suggested_intervals()}
    assert any({"afk", "bedtime"} <= t for t in tags)
    assert any({"afk", "tea"} <= t for t in tags)


def test_diff_range_end_capped_at_now_for_ongoing_afk(tmp_path, clipping_server) -> None:
    """An AFK period still going on stretches the range to now, not into the future."""
    now = datetime.now(UTC).replace(microsecond=0)
    builder = FixtureDataBuilder(start_time=now - timedelta(hours=5))
    builder.add_window_event("Code", "main.py", 3600)
    builder.add_afk_event("not-afk", 3600)
    builder.add_afk_event("afk", timedelta(hours=10), timestamp=now - timedelta(hours=4))
    path = tmp_path / "ongoing.json"
    path.write_text(json.dumps(builder.build()))
    args = _diff_args(path)
    args.start = (now - timedelta(hours=5)).isoformat()
    args.end = (now - timedelta(hours=1)).isoformat()

    exporter = create_diff_exporter(args)

    assert now <= exporter.end_time <= datetime.now(UTC)


def test_batch_sync_records_afk_period_opening_the_range(tmp_path, clipping_server) -> None:
    """`sync --from/--to` starting inside an AFK period records it, like diff does."""
    data = json.loads(_night_across_midnight(tmp_path).read_text())
    exporter = Exporter(
        test_data=data,
        dry_run=True,
        config_path=CONFIG_FILE,
        start_time=DAY_START,
        end_time=DAY_END,
        captured_commands=[],
        enable_assert=False,
    )
    exporter.tick(process_all=True)

    first = exporter.get_suggested_intervals()[0]
    assert first.start == DAY_START
    assert {"afk", "bedtime"} <= first.tags
