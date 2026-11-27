"""Unknown activity after an AFK period starts where the AFK period ends.

Coming back to the keyboard and working in a window no rule matches used to
leave the AFK interval - an afk-prompt answer's tags, or plain ``afk`` -
running on until the UNKNOWN threshold was reached, and the UNKNOWN interval
then started only at the event that crossed it: minutes at the keyboard
tagged as away.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aw_export_timewarrior.main import Exporter
from tests.conftest import FixtureDataBuilder

CONFIG_FILE = Path(__file__).parent / "fixtures" / "test_config.toml"

T0 = datetime(2025, 1, 1, 9, 0, tzinfo=UTC)
AFK_START = T0 + timedelta(minutes=10)
AFK_END = AFK_START + timedelta(minutes=15)
END = AFK_END + timedelta(minutes=20)


@pytest.fixture(autouse=True)
def _default_tuning(monkeypatch):
    """The default thresholds, whatever the local configuration says."""
    monkeypatch.setenv("AW2TW_MIN_RECORDING_INTERVAL", "90")


def _data(
    answer: str | None,
    answer_length: timedelta = AFK_END - AFK_START,
    bursts: tuple[int, ...] = (5, 300, 100, 15, 13, 270),
    afk: bool = True,
) -> dict:
    builder = FixtureDataBuilder(start_time=T0)
    builder.add_window_event("Code", "main.py", 600)
    builder.add_afk_event("not-afk", 600)
    if afk:
        builder.add_afk_event("afk", AFK_END - AFK_START, timestamp=AFK_START)
        if answer:
            builder.add_ask_away_event(answer, answer_length, timestamp=AFK_START)
    else:
        builder.add_window_event("Code", "main.py", AFK_END - AFK_START, timestamp=AFK_START)
        builder.add_afk_event("not-afk", AFK_END - AFK_START, timestamp=AFK_START)
    # Back at the keyboard, in windows no rule knows, in bursts like the ones
    # that tipped the real case over the threshold.
    at = AFK_END
    for seconds in bursts:
        builder.add_window_event("Mystery", "asdf", seconds, timestamp=at)
        at += timedelta(seconds=seconds)
    builder.add_window_event("Code", "main.py", END - at, timestamp=at)
    builder.add_afk_event("not-afk", END - AFK_END, timestamp=AFK_END)
    return builder.build()


def _intervals(**kwargs) -> list:
    exporter = Exporter(
        test_data=json.loads(json.dumps(_data(**kwargs))),
        dry_run=True,
        config_path=CONFIG_FILE,
        start_time=T0,
        end_time=END,
        captured_commands=[],
        enable_assert=False,
    )
    exporter.tick(process_all=True)
    return exporter.get_suggested_intervals()


def _at(intervals: list, moment: datetime):
    return next(i for i in intervals if i.start <= moment < i.end)


@pytest.mark.parametrize("answer", ["tea", None])
def test_unknown_activity_starts_where_afk_ends(answer) -> None:
    intervals = _intervals(answer=answer)

    away = _at(intervals, AFK_END - timedelta(minutes=1))
    assert away.end == AFK_END
    unknown = _at(intervals, AFK_END)
    assert unknown.start == AFK_END
    assert {"UNKNOWN", "not-afk"} <= unknown.tags
    assert "afk" not in unknown.tags


def test_answer_covers_the_afk_period() -> None:
    assert {"afk", "tea"} <= _at(_intervals(answer="tea"), AFK_END - timedelta(minutes=1)).tags


def test_answer_reaching_past_afk_ends_with_it() -> None:
    """An answer longer than the AFK period stops where the keyboard is back."""
    intervals = _intervals(answer="tea", answer_length=timedelta(minutes=20))

    assert {"afk", "tea"} <= _at(intervals, AFK_START).tags
    assert _at(intervals, AFK_START).end == AFK_END
    assert "afk" not in _at(intervals, AFK_END).tags


@pytest.mark.parametrize("answer", ["tea", None])
def test_known_activity_after_short_unknown_starts_where_afk_ends(answer) -> None:
    """Under the UNKNOWN threshold, the long known event that follows takes
    the unmatched time; the AFK tags do not."""
    intervals = _intervals(answer=answer, bursts=(180,))

    assert _at(intervals, AFK_END - timedelta(minutes=1)).end == AFK_END
    work = _at(intervals, AFK_END)
    assert work.start == AFK_END
    assert "afk" not in work.tags


def test_backdating_only_right_after_afk() -> None:
    """Not after a task, and not over a manual interval started after AFK."""
    exporter = Exporter(
        test_data=json.loads(json.dumps(_data(answer=None))),
        dry_run=True,
        config_path=CONFIG_FILE,
        start_time=T0,
        end_time=END,
        captured_commands=[],
        enable_assert=False,
    )
    exporter.state.last_known_tick = AFK_END
    event = {"timestamp": AFK_END + timedelta(minutes=5), "duration": timedelta(seconds=10)}

    exporter.timew_info = {"start_dt": AFK_START, "tags": {"afk", "tea", "~aw"}}
    assert exporter._since_after_afk(event) == AFK_END
    exporter.timew_info = {"start_dt": AFK_END, "tags": {"reading"}}
    assert exporter._since_after_afk(event) is None
    exporter.timew_info = {"start_dt": T0, "tags": {"coding", "not-afk", "~aw"}}
    assert exporter._since_after_afk(event) is None
