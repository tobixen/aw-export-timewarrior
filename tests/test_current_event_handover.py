"""What an ongoing event already contributed when it reappears completed.

Live sync counts the ongoing event tick by tick, and when it reappears as a
completed event only the remainder is added - to known_events_time and to
the tag accumulator alike.  "Already counted" must mean what was actually
added, and must not outlive a reset of the statistics it was added to.
"""

import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aw_export_timewarrior.main import Exporter
from aw_export_timewarrior.state import AfkState, StateManager
from tests.conftest import FixtureDataBuilder

CONFIG_FILE = Path(__file__).parent / "fixtures" / "test_config.toml"
T0 = datetime(2025, 1, 1, 9, 0, tzinfo=UTC)


def _live_exporter(data: dict) -> Exporter:
    data["metadata"].pop("start_time", None)
    data["metadata"].pop("end_time", None)
    return Exporter(
        test_data=data,
        config_path=CONFIG_FILE,
        dry_run=True,
        start_time=T0,
        enable_assert=False,
        hide_processing_output=True,
    )


def _tick_at(exporter: Exporter, aw_clock: list, at: datetime) -> None:
    aw_clock[0] = at
    # A dry run with nothing new to read refuses to sleep; the daemon would.
    with contextlib.suppress(ValueError):
        exporter.tick()


def _editing(seconds: int) -> dict:
    """One Code window on a .py file (tagged 'coding'), then another."""
    builder = FixtureDataBuilder(start_time=T0)
    builder.add_window_event("Code", "main.py", seconds)
    builder.add_window_event("Code", "other.py", 600)
    builder.add_afk_event("not-afk", seconds + 600, timestamp=T0)
    return builder.build()


def test_tag_accumulator_adds_only_the_remainder(aw_clock, monkeypatch) -> None:
    monkeypatch.setenv("AW2TW_MIN_RECORDING_INTERVAL", "3600")  # no export in between
    exporter = _live_exporter(_editing(48))

    _tick_at(exporter, aw_clock, T0 + timedelta(seconds=30))  # ongoing, 30 s counted
    _tick_at(exporter, aw_clock, T0 + timedelta(seconds=50))  # completed at 48 s

    # other.py's 2 s so far are under ignore_interval, so main.py alone
    assert exporter.state.stats.tags_accumulated_time["coding"] == timedelta(seconds=48)


def test_ignored_increment_is_not_taken_back(aw_clock, monkeypatch) -> None:
    """A first sighting under ignore_interval adds nothing, so nothing of it
    may be subtracted when the event completes."""
    monkeypatch.setenv("AW2TW_MIN_RECORDING_INTERVAL", "3600")
    monkeypatch.setenv("AW2TW_IGNORE_INTERVAL", "3")
    exporter = _live_exporter(_editing(30))

    _tick_at(exporter, aw_clock, T0 + timedelta(seconds=2))  # 2 s: ignored
    known_after_ignored = exporter.state.stats.known_events_time
    _tick_at(exporter, aw_clock, T0 + timedelta(seconds=40))  # completed at 30 s

    assert known_after_ignored == timedelta(0)
    # main.py's 30 s plus the 10 s of other.py so far
    assert exporter.state.stats.known_events_time == timedelta(seconds=40)


def test_afk_transition_forgets_the_ongoing_event() -> None:
    state = StateManager()
    state.set_afk_state(AfkState.ACTIVE)
    state.current_event_timestamp = T0
    state.current_event_processed_duration = timedelta(seconds=100)

    state.handle_afk_transition(new_state=AfkState.AFK, current_time=T0 + timedelta(minutes=5))

    assert state.current_event_timestamp is None
    assert state.current_event_processed_duration == timedelta(0)


def test_long_event_export_resets_what_was_counted(aw_clock, monkeypatch) -> None:
    """A long completed event is exported on its own, which resets the
    accumulator; what was counted before that reset must not be subtracted
    from what comes after."""
    monkeypatch.setenv("AW2TW_MIN_RECORDING_INTERVAL", "3600")
    exporter = _live_exporter(_editing(300))

    _tick_at(exporter, aw_clock, T0 + timedelta(seconds=100))  # ongoing, 100 s counted
    _tick_at(exporter, aw_clock, T0 + timedelta(seconds=310))  # completed at 300 s

    assert exporter.state.stats.tags_accumulated_time["coding"] >= timedelta(seconds=300)
