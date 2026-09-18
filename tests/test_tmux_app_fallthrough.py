"""A tmux window with no matching `[rules.tmux.*]` must still try app rules.

`get_tmux_tags()` used to return an empty list when a tmux sub-event was found
but no tmux rule matched.  `[] is not False`, so `get_tags()` accepted that as
the answer and never reached `[rules.app.*]` -- precisely where the window
title, the most informative thing available, is matched.  See TODO.md, "Let app
rules run when a tmux event matched no rule".
"""

from datetime import UTC, datetime, timedelta

from tests.test_tmux import create_tmux_event, setup_tmux_test

APP_RULE_CONFIG = {
    "rules": {
        "app": {
            "claude": {
                "app_names": ["foot"],
                "title_regexp": "kamailio",
                "tags": ["kamailio", "4WORK"],
            }
        }
    },
    "exclusive": {},
    "tags": {},
}


def _tmux_event():
    return create_tmux_event(
        timestamp=datetime.now(UTC),
        duration=timedelta(minutes=5),
        session_name="kamailio",
        window_name="claude",
        pane_command="claude",
    )


def test_tmux_no_rule_falls_through_to_app_rules() -> None:
    """An app rule matching the window title wins when no tmux rule matches."""
    extractor, window_event = setup_tmux_test(APP_RULE_CONFIG, _tmux_event())

    tags = extractor.get_tags(window_event)

    assert tags == {"kamailio", "4WORK", "not-afk"}
    assert extractor.last_matched_rule == "app:claude"


def test_tmux_no_rule_returns_false_not_empty_list() -> None:
    """get_tmux_tags() signals 'not applicable' so get_tags() keeps looking."""
    config = {"rules": {}, "exclusive": {}, "tags": {}}
    extractor, window_event = setup_tmux_test(config, _tmux_event())

    assert extractor.get_tmux_tags(window_event) is False


def test_tmux_rule_still_wins_over_app_rule() -> None:
    """Fall-through must not change precedence when a tmux rule does match."""
    config = {
        "rules": {
            "app": APP_RULE_CONFIG["rules"]["app"],
            "tmux": {"claude": {"command": "claude", "tags": ["ai-assisted"]}},
        },
        "exclusive": {},
        "tags": {},
    }
    extractor, window_event = setup_tmux_test(config, _tmux_event())

    tags = extractor.get_tags(window_event)

    assert tags == {"ai-assisted", "not-afk"}
    assert extractor.last_matched_rule == "tmux:claude"


def test_no_unhandled_warning_when_app_rule_matches() -> None:
    """The 'Unhandled tmux event' warning is for events nothing matched."""
    logged = []
    extractor, window_event = setup_tmux_test(APP_RULE_CONFIG, _tmux_event())
    extractor.log_callback = lambda msg, **kwargs: logged.append((msg, kwargs))

    extractor.get_tags(window_event)

    assert not [msg for msg, _ in logged if "Unhandled tmux" in msg]


def test_unhandled_warning_when_nothing_matches() -> None:
    """With no rule at all the warning must still be emitted, once."""
    logged = []
    config = {"rules": {}, "exclusive": {}, "tags": {}}
    extractor, window_event = setup_tmux_test(config, _tmux_event())
    extractor.log_callback = lambda msg, **kwargs: logged.append((msg, kwargs))

    assert extractor.get_tags(window_event) is False

    unhandled = [kwargs for msg, kwargs in logged if "Unhandled tmux" in msg]
    assert len(unhandled) == 1
    assert unhandled[0]["extra"]["event_type"] == "tmux"
    assert unhandled[0]["extra"]["sub_event"]["data"]["session_name"] == "kamailio"


def test_pending_warning_survives_an_unmatched_browser_event() -> None:
    """A later extractor returning [] must not swallow the tmux warning.

    `get_tags()` returns on the first result that is neither None nor False,
    and an unmatched browser/editor sub-event returns an empty list -- which
    would otherwise carry the tmux event's deferred warning out with it.
    """
    logged = []
    config = {"rules": {}, "exclusive": {}, "tags": {}}
    extractor, window_event = setup_tmux_test(config, _tmux_event())
    extractor.log_callback = lambda msg, **kwargs: logged.append((msg, kwargs))
    # Pretend the same window is also a browser whose sub-event matches no rule
    extractor.get_browser_tags = lambda event: []

    assert extractor.get_tags(window_event) == []

    assert len([msg for msg, _ in logged if "Unhandled tmux" in msg]) == 1


def test_pending_warning_is_not_carried_into_the_next_event() -> None:
    """Each get_tags() call reports its own event, or none at all."""
    logged = []
    config = {
        "rules": {"app": {"claude": {"app_names": ["foot"], "tags": ["4WORK"]}}},
        "exclusive": {},
        "tags": {},
    }
    extractor, matched = setup_tmux_test(config, _tmux_event())
    extractor.log_callback = lambda msg, **kwargs: logged.append((msg, kwargs))

    # 'kitty' is a terminal, so tmux applies -- but no app rule names it
    unmatched = {**matched, "data": {**matched["data"], "app": "kitty"}}
    extractor.get_tags(unmatched)
    assert len([msg for msg, _ in logged if "Unhandled tmux" in msg]) == 1

    # The next event does match an app rule, so nothing more may be reported
    logged.clear()
    assert extractor.get_tags(matched) == {"4WORK", "not-afk"}

    assert [msg for msg, _ in logged if "Unhandled tmux" in msg] == []
