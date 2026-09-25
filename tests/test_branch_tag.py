"""The git branch from the tmux and editor watchers is emitted as a tag.

aw-watcher-tmux records `git_branch` and aw-watcher-emacs records `branch`.
Whenever a tmux or editor rule matches, `branch:<name>` is added to its tags,
so the branch reaches timewarrior and retag rules (`[tags.*]` with
`source_tags = ["branch:..."]`) can map it further.  The watchers' `unknown`
placeholder is not a branch and is dropped.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from aw_export_timewarrior.main import Exporter
from tests.test_tag_extraction import create_aw_event, mock_aw_client  # noqa: F401
from tests.test_tmux import create_tmux_event, setup_tmux_test

TMUX_CONFIG = {
    "rules": {"tmux": {"caldav": {"path": "caldav", "tags": ["caldav"]}}},
    "exclusive": {},
    "tags": {},
}


def _tmux_event(**extra):
    event = create_tmux_event(
        timestamp=datetime.now(UTC),
        duration=timedelta(minutes=5),
        session_name="work",
        window_name="bash",
        pane_command="bash",
        pane_path="/home/user/caldav",
    )
    event["data"].update(extra)
    return event


def test_tmux_branch_becomes_tag() -> None:
    extractor, window_event = setup_tmux_test(
        TMUX_CONFIG, _tmux_event(git_branch="issue713-basic-auth")
    )

    assert extractor.get_tmux_tags(window_event) == {
        "caldav",
        "branch:issue713-basic-auth",
        "not-afk",
    }


def test_tmux_unknown_branch_is_dropped() -> None:
    extractor, window_event = setup_tmux_test(TMUX_CONFIG, _tmux_event(git_branch="unknown"))

    assert extractor.get_tmux_tags(window_event) == {"caldav", "not-afk"}


def test_tmux_without_branch_field() -> None:
    extractor, window_event = setup_tmux_test(TMUX_CONFIG, _tmux_event())

    assert extractor.get_tmux_tags(window_event) == {"caldav", "not-afk"}


def test_tmux_branch_alone_does_not_make_a_match() -> None:
    """No rule matched -> still unmatched; the branch is not a rule by itself."""
    extractor, window_event = setup_tmux_test(
        TMUX_CONFIG, _tmux_event(git_branch="main", pane_current_path="/elsewhere")
    )

    assert extractor.get_tmux_tags(window_event) is False


def test_branch_tag_feeds_retag_rules() -> None:
    config = {
        **TMUX_CONFIG,
        "tags": {"i713": {"source_tags": ["branch:issue713-basic-auth"], "add": ["issue713"]}},
    }
    extractor, window_event = setup_tmux_test(config, _tmux_event(git_branch="issue713-basic-auth"))

    tags = extractor.apply_retag_rules(extractor.get_tmux_tags(window_event))
    assert "issue713" in tags


def _editor_tags(mock_aw_client: Mock, branch: str | None):  # noqa: F811
    exporter = Exporter()
    exporter.config = {
        "rules": {"editor": {"caldav": {"projects": ["caldav"], "tags": ["caldav"]}}},
        "exclusive": {},
        "tags": {},
    }
    data = {"project": "caldav", "file": "/home/user/caldav/caldav.py", "language": "python"}
    if branch is not None:
        data["branch"] = branch
    mock_aw_client.get_events.return_value = [
        create_aw_event(timestamp=datetime.now(UTC), duration=timedelta(minutes=10), data=data)
    ]
    window_event = {
        "timestamp": datetime.now(UTC),
        "duration": timedelta(minutes=10),
        "data": {"app": "emacs", "title": "caldav.py - Emacs"},
    }
    return exporter.tag_extractor.get_editor_tags(window_event)


def test_editor_branch_becomes_tag(mock_aw_client: Mock) -> None:  # noqa: F811
    assert _editor_tags(mock_aw_client, "develop") == {"caldav", "branch:develop", "not-afk"}


def test_editor_unknown_branch_is_dropped(mock_aw_client: Mock) -> None:  # noqa: F811
    assert _editor_tags(mock_aw_client, "unknown") == {"caldav", "not-afk"}


def test_unknown_git_branch_falls_back_to_branch_field() -> None:
    extractor, window_event = setup_tmux_test(
        TMUX_CONFIG, _tmux_event(git_branch="unknown", branch="develop")
    )

    assert extractor.get_tmux_tags(window_event) == {"caldav", "branch:develop", "not-afk"}


def test_editor_without_branch_field(mock_aw_client: Mock) -> None:  # noqa: F811
    assert _editor_tags(mock_aw_client, None) == {"caldav", "not-afk"}


def test_browser_match_gets_no_branch_tag(mock_aw_client: Mock) -> None:  # noqa: F811
    """Only tmux and editor carry a branch; a browser event's `branch` is not one."""
    exporter = Exporter()
    exporter.config = {
        "rules": {"browser": {"gh": {"url_regexp": "github\\.com", "tags": ["github"]}}},
        "exclusive": {},
        "tags": {},
    }
    mock_aw_client.get_events.return_value = [
        create_aw_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=10),
            data={"url": "https://github.com/x/y", "title": "y", "branch": "main"},
        )
    ]
    window_event = {
        "timestamp": datetime.now(UTC),
        "duration": timedelta(minutes=10),
        "data": {"app": "chromium", "title": "y - Chromium"},
    }

    assert exporter.tag_extractor.get_browser_tags(window_event) == {"github", "not-afk"}
