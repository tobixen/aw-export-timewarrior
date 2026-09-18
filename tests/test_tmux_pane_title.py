"""Matching `[rules.tmux.*]` on the tmux pane title.

`_match_tmux_rule()` could match on session, window, command and path, and it
already substituted `$title`, but there was no way to *match* on the pane
title -- which is where Claude Code puts the session topic, often the only
place the subject of the work appears.  See TODO.md, "Match on `pane_title` in
tmux rules".
"""

from datetime import UTC, datetime, timedelta

from aw_export_timewarrior.config_validation import ConfigValidator
from tests.test_tmux import create_tmux_event, setup_tmux_test


def _claude_event(pane_title: str, pane_command: str = "claude"):
    event = create_tmux_event(
        timestamp=datetime.now(UTC),
        duration=timedelta(minutes=5),
        session_name="work",
        window_name="claude",
        pane_command=pane_command,
    )
    event["data"]["pane_title"] = pane_title
    return event


def test_pane_title_rule_matches() -> None:
    config = {
        "rules": {"tmux": {"kamailio": {"pane_title": "(?i)kamailio", "tags": ["kamailio"]}}},
        "exclusive": {},
        "tags": {},
    }
    extractor, window_event = setup_tmux_test(
        config, _claude_event("✳ Kamailio session duration analysis")
    )

    assert extractor.get_tmux_tags(window_event) == {"kamailio", "not-afk"}
    assert extractor.last_matched_rule == "tmux:kamailio"


def test_pane_title_rule_does_not_match_other_title() -> None:
    config = {
        "rules": {"tmux": {"kamailio": {"pane_title": "(?i)kamailio", "tags": ["kamailio"]}}},
        "exclusive": {},
        "tags": {},
    }
    extractor, window_event = setup_tmux_test(config, _claude_event("✳ Grocery receipt parsing"))

    assert extractor.get_tmux_tags(window_event) is False


def test_pane_title_capture_group_substitution() -> None:
    """Capture groups from pane_title feed the same $N substitutions."""
    config = {
        "rules": {
            "tmux": {
                "project": {
                    "pane_title": r"project:(\w+)",
                    "tags": ["$1", "4OSS"],
                }
            }
        },
        "exclusive": {},
        "tags": {},
    }
    extractor, window_event = setup_tmux_test(config, _claude_event("✳ project:caldav review"))

    assert extractor.get_tmux_tags(window_event) == {"caldav", "4OSS", "not-afk"}


def test_pane_title_combines_with_command() -> None:
    """pane_title narrows an otherwise too-broad command rule."""
    config = {
        "rules": {
            "tmux": {
                "claude-boat": {
                    "command": "claude",
                    "pane_title": "(?i)boat",
                    "tags": ["boat", "4BOAT"],
                }
            }
        },
        "exclusive": {},
        "tags": {},
    }
    extractor, matching = setup_tmux_test(config, _claude_event("✳ Boat maintenance log"))
    assert extractor.get_tmux_tags(matching) == {"boat", "4BOAT", "not-afk"}

    extractor, other = setup_tmux_test(config, _claude_event("✳ Something else"))
    assert extractor.get_tmux_tags(other) is False

    extractor, wrong_command = setup_tmux_test(
        config, _claude_event("✳ Boat maintenance log", pane_command="vim")
    )
    assert extractor.get_tmux_tags(wrong_command) is False


def test_pane_title_only_rule_is_not_warned_about() -> None:
    """`validate` must accept pane_title as a matcher in its own right."""
    config = {
        "rules": {"tmux": {"kamailio": {"pane_title": "(?i)kamailio", "tags": ["kamailio"]}}},
    }
    errors, warnings = ConfigValidator().validate(config)

    assert errors == []
    assert not [w for w in warnings if "rules.tmux.kamailio" in w]


def test_invalid_pane_title_regexp_is_an_error() -> None:
    config = {"rules": {"tmux": {"broken": {"pane_title": "(unclosed", "tags": ["x"]}}}}
    errors, _ = ConfigValidator().validate(config)

    assert any("pane_title" in e for e in errors)


def test_capture_group_numbering_is_title_then_command_then_path() -> None:
    """`$N` counts across the matchers in the order _match_tmux_rule tries them."""
    config = {
        "rules": {
            "tmux": {
                "ordered": {
                    "pane_title": r"p:(\w+)",
                    "command": r"(cl\w+)",
                    "path": r"/(\w+)$",
                    "tags": ["title-$1", "cmd-$2", "path-$3"],
                }
            }
        },
        "exclusive": {},
        "tags": {},
    }
    event = _claude_event("✳ p:kamailio duration analysis")
    event["data"]["pane_current_path"] = "/home/tobias/kamailio"
    extractor, window_event = setup_tmux_test(config, event)

    assert extractor.get_tmux_tags(window_event) == {
        "title-kamailio",
        "cmd-claude",
        "path-kamailio",
        "not-afk",
    }
