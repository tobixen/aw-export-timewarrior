"""The minimum-length check only applies to intervals the accumulator chose.

`last_activity_run_time < min_recording_interval-3` assumed every interval
lasted at least min_recording_interval.  An interval the accumulator did not
choose - the one opened on returning from AFK, an UNKNOWN fill, the first one
after a hand-made interval - is legitimately replaced sooner, and those were
all 56 of the hits in the daemon's journal.
"""

from datetime import UTC, datetime, timedelta

import pytest

from aw_export_timewarrior.main import Exporter
from tests.conftest import FixtureDataBuilder

T0 = datetime(2025, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _default_tuning(monkeypatch):
    """The default threshold, whatever the local configuration says."""
    monkeypatch.setenv("AW2TW_MIN_RECORDING_INTERVAL", "90")


def _exporter() -> Exporter:
    data = FixtureDataBuilder(start_time=T0).add_window_event("Code", "a.py", 60).build()
    # No range: live sync, where the check asserts instead of logging.
    del data["metadata"]["start_time"], data["metadata"]["end_time"]
    exporter = Exporter(test_data=data, dry_run=True, enable_assert=True)
    exporter.state.manual_tracking = False
    return exporter


def _event(at: datetime) -> dict:
    return {
        "timestamp": at,
        "duration": timedelta(seconds=5),
        "data": {"app": "Code", "title": "a.py"},
    }


def test_interval_after_afk_may_be_short() -> None:
    exporter = _exporter()
    exporter.ensure_tag_exported({"work", "not-afk"}, _event(T0))
    exporter.ensure_tag_exported({"afk"}, _event(T0 + timedelta(minutes=2)))
    exporter.state.set_afk_state(exporter.state.afk_state.ACTIVE)
    exporter.ensure_tag_exported({"work", "not-afk"}, _event(T0 + timedelta(minutes=4)))

    # Replaced 30 s after the return, under min_recording_interval: no assertion.
    exporter.ensure_tag_exported({"mail", "not-afk"}, _event(T0 + timedelta(minutes=4, seconds=30)))


def test_unknown_fill_may_be_short() -> None:
    exporter = _exporter()
    exporter.ensure_tag_exported({"work", "not-afk"}, _event(T0))
    exporter.ensure_tag_exported({"UNKNOWN", "not-afk"}, _event(T0 + timedelta(minutes=2)))

    exporter.ensure_tag_exported({"work", "not-afk"}, _event(T0 + timedelta(minutes=2, seconds=30)))


def test_interval_chosen_by_accumulator_is_still_checked() -> None:
    exporter = _exporter()
    exporter.ensure_tag_exported({"work", "not-afk"}, _event(T0))
    exporter.ensure_tag_exported({"mail", "not-afk"}, _event(T0 + timedelta(minutes=2)))

    with pytest.raises(AssertionError, match="last_activity_run_time"):
        exporter.ensure_tag_exported(
            {"work", "not-afk"}, _event(T0 + timedelta(minutes=2, seconds=30))
        )
