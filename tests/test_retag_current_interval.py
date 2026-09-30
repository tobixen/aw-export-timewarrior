"""Tests for Exporter.retag_current_interval.

Retag rules are re-applied to an open interval only when it gains tags; a
tag the user removes afterwards (e.g. the waybar click that untags
``~css_class:blinking``) must stay removed, and a change made during the grace period must not crash the
daemon.
"""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.main import Exporter

BLINK_CONFIG = {
    "exclusive": {},
    "tags": {"blinking": {"source_tags": ["4entertainment"], "add": ["~css_class:blinking"]}},
}


def _interval(tags: set[str], start: str = "20260930T172434Z") -> dict:
    return {
        "id": 1,
        "start": start,
        "start_dt": datetime.strptime(start, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
        "tags": set(tags),
    }


@pytest.fixture
def exporter() -> Exporter:
    now = datetime.now(UTC).isoformat()
    buckets = {
        f"{client}_test": {"id": f"{client}_test", "client": client, "last_updated": now}
        for client in ("aw-watcher-window", "aw-watcher-afk")
    }
    with patch("aw_export_timewarrior.aw_client.ActivityWatchClient") as aw_class:
        aw_class.return_value.get_buckets.return_value = buckets
        exp = Exporter(config=BLINK_CONFIG, enable_assert=False)
    exp.tracker.retag = Mock()
    return exp


def test_rules_applied_to_new_interval(exporter: Exporter) -> None:
    after = _interval({"4entertainment", "~css_class:blinking"})
    exporter.tracker.get_current_tracking = Mock(side_effect=[_interval({"4entertainment"}), after])
    assert exporter.retag_current_interval() == after
    exporter.tracker.retag.assert_called_once_with({"4entertainment", "~css_class:blinking"})


def test_dismissed_tag_stays_dismissed(exporter: Exporter) -> None:
    exporter.tracker.get_current_tracking = Mock(
        return_value=_interval({"4entertainment", "~css_class:blinking"})
    )
    exporter.retag_current_interval()

    # User clicks waybar: `timew untag ~css_class:blinking`
    exporter.tracker.get_current_tracking = Mock(return_value=_interval({"4entertainment"}))
    exporter.retag_current_interval()
    exporter.tracker.retag.assert_not_called()


def test_rules_applied_again_on_next_interval(exporter: Exporter) -> None:
    exporter.tracker.get_current_tracking = Mock(
        return_value=_interval({"4entertainment", "~css_class:blinking"})
    )
    exporter.retag_current_interval()

    exporter.tracker.get_current_tracking = Mock(
        return_value=_interval({"4entertainment"}, start="20260930T173307Z")
    )
    exporter.retag_current_interval()
    exporter.tracker.retag.assert_called_once_with({"4entertainment", "~css_class:blinking"})


def test_change_during_grace_period_does_not_crash(exporter: Exporter) -> None:
    # The user untags again while the retag's grace period is running
    untagged = _interval({"4entertainment"})
    exporter.tracker.get_current_tracking = Mock(side_effect=[untagged, untagged])
    assert exporter.retag_current_interval() == untagged


def test_change_during_grace_period_logs_warning(
    exporter: Exporter, caplog: pytest.LogCaptureFixture
) -> None:
    untagged = _interval({"4entertainment"})
    exporter.tracker.get_current_tracking = Mock(side_effect=[untagged, untagged])
    exporter.retag_current_interval()
    assert "Interval changed during retag" in caplog.text


def test_tag_added_by_hand_triggers_rules(exporter: Exporter) -> None:
    exporter.tracker.get_current_tracking = Mock(return_value=_interval({"4work"}))
    exporter.retag_current_interval()

    # User runs `timew tag @1 4entertainment` on the same open interval
    after = _interval({"4work", "4entertainment", "~css_class:blinking"})
    exporter.tracker.get_current_tracking = Mock(
        side_effect=[_interval({"4work", "4entertainment"}), after]
    )
    assert exporter.retag_current_interval() == after
    exporter.tracker.retag.assert_called_once_with(
        {"4work", "4entertainment", "~css_class:blinking"}
    )


def test_failed_retag_is_retried(exporter: Exporter) -> None:
    exporter.tracker.get_current_tracking = Mock(return_value=_interval({"4entertainment"}))
    exporter.tracker.retag = Mock(side_effect=[RuntimeError("database locked"), None])
    with pytest.raises(RuntimeError):
        exporter.retag_current_interval()
    exporter.retag_current_interval()
    assert exporter.tracker.retag.call_count == 2


def test_fresh_interval_with_same_start_gets_rules(exporter: Exporter) -> None:
    exporter.tracker.get_current_tracking = Mock(
        return_value=_interval({"4entertainment", "~css_class:blinking"})
    )
    exporter.retag_current_interval()

    # The exporter itself starts a new interval that happens to share the start
    exporter.tracker.get_current_tracking = Mock(return_value=_interval({"4entertainment"}))
    exporter.retag_current_interval(fresh=True)
    exporter.tracker.retag.assert_called_once_with({"4entertainment", "~css_class:blinking"})
