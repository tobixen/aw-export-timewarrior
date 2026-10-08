"""Live sync must take back known time an ongoing event loses to AFK.

While a window event is the ongoing one, sync counts its duration tick by
tick.  aw-watcher-window-wayland reports not-afk up to the last input and afk
only after the two-minute idle countdown, and the pipeline fills that gap
with AFK.  So once the AFK period shows up, the window event that ran through
the countdown comes back as a completed event two minutes shorter than what
was already counted for it.  The overcount stayed in known_events_time and
tripped `tracked_gap < known_events_time` on the next export, about 77 times
a month in the daemon's journal.

The fixture is that daemon's own data from such a night (window titles
anonymised), replayed as it looked tick by tick.
"""

import contextlib
import json
from datetime import timedelta
from pathlib import Path

from aw_export_timewarrior.main import Exporter
from aw_export_timewarrior.utils import parse_datetime

FIXTURE = Path(__file__).parent / "fixtures" / "live_countdown_overcount.json"
CONFIG = {
    "rules": {
        "app": {
            "everything": {
                "app_names": ["emacs", "foot", "org.chromium.Chromium", "firefox"],
                "tags": ["work"],
            }
        }
    }
}


def test_live_sync_takes_back_countdown_counted_as_known(aw_clock, monkeypatch, caplog) -> None:
    # The tuning of the setup the data came from: exports often enough that
    # one lands on the event the countdown is taken from.
    monkeypatch.setenv("AW2TW_MIN_RECORDING_INTERVAL", "60")
    monkeypatch.setenv("AW2TW_MIN_TAG_RECORDING_INTERVAL", "45")
    data = json.loads(FIXTURE.read_text())
    start = parse_datetime(data["metadata"]["start_time"])
    end = parse_datetime(data["metadata"].pop("end_time"))
    exporter = Exporter(
        test_data=data,
        config=CONFIG,
        dry_run=True,
        start_time=start,
        enable_assert=False,
        hide_processing_output=True,
    )

    aw_clock[0] = start + timedelta(minutes=2)
    while aw_clock[0] <= end:
        # A dry run with nothing new to read refuses to sleep; the daemon would.
        with contextlib.suppress(ValueError):
            exporter.tick()
        aw_clock[0] += timedelta(seconds=30)

    assert not [r.message for r in caplog.records if "tracked_gap" in r.message]
