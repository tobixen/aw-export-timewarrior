"""Tests for tmux watcher integration."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from aw_export_timewarrior.aw_client import EventFetcher
from aw_export_timewarrior.tag_extractor import TagExtractor


def create_window_event(timestamp, duration, app, title=""):
    """Create a mock window event."""
    return {
        "timestamp": timestamp,
        "duration": duration,
        "data": {
            "app": app,
            "title": title,
        },
    }


def create_tmux_event(timestamp, duration, session_name, window_name, pane_command, pane_path=""):
    """Create a mock tmux event."""
    return {
        "timestamp": timestamp,
        "duration": duration,
        "data": {
            "title": session_name,
            "session_name": session_name,
            "window_name": window_name,
            "pane_title": "",
            "pane_current_command": pane_command,
            "pane_current_path": pane_path,
        },
    }


def setup_tmux_test(config, tmux_event):
    """Set up a tmux test with mocked event fetcher.

    Returns: (extractor, window_event)
    """
    mock_fetcher = Mock(spec=EventFetcher)
    mock_fetcher.get_tmux_bucket.return_value = "aw-watcher-tmux"
    mock_fetcher.get_corresponding_event.return_value = (
        tmux_event  # Singular, returns event or None
    )

    # Use the tmux session name in the window title (as real tmux terminals do)
    session_name = tmux_event["data"].get("session_name", "tmux")
    window_event = create_window_event(
        timestamp=datetime.now(UTC),
        duration=timedelta(minutes=5),
        app="foot",
        title=session_name,
    )

    extractor = TagExtractor(config, mock_fetcher)
    return extractor, window_event


class TestTmuxBucketDetection:
    """Tests for tmux bucket detection in EventFetcher."""

    def test_get_tmux_bucket_exists(self) -> None:
        """Test that get_tmux_bucket returns bucket ID when tmux watcher exists."""
        test_data = {
            "buckets": {
                "aw-watcher-tmux": {
                    "id": "aw-watcher-tmux",
                    "client": "aw-watcher-tmux",
                    "type": "tmux.sessions",
                    "hostname": "test-host",
                    "last_updated": datetime.now(UTC).isoformat(),
                }
            }
        }

        fetcher = EventFetcher(test_data=test_data)
        tmux_bucket = fetcher.get_tmux_bucket()

        assert tmux_bucket == "aw-watcher-tmux"
        assert fetcher.has_bucket_client("aw-watcher-tmux")

    def test_get_tmux_bucket_not_exists(self) -> None:
        """Test that get_tmux_bucket returns None when tmux watcher doesn't exist."""
        test_data = {
            "buckets": {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "client": "aw-watcher-window",
                    "last_updated": datetime.now(UTC).isoformat(),
                }
            }
        }

        fetcher = EventFetcher(test_data=test_data)
        tmux_bucket = fetcher.get_tmux_bucket()

        assert tmux_bucket is None
        assert not fetcher.has_bucket_client("aw-watcher-tmux")


class TestTmuxTagExtraction:
    """Tests for tmux tag extraction."""

    def test_tmux_event_no_matching_rule(self) -> None:
        """A tmux event no rule matched falls through to the app rules.

        Unlike browser/editor (which return an empty list and end the search),
        tmux returns False so get_tags() goes on to `[rules.app.*]` -- see
        tests/test_tmux_app_fallthrough.py.
        """
        config = {"rules": {}, "exclusive": {}, "tags": {}}

        tmux_event = create_tmux_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            session_name="main",
            window_name="coding",
            pane_command="vim",
        )

        extractor, window_event = setup_tmux_test(config, tmux_event)
        tags = extractor.get_tmux_tags(window_event)
        # False, not [], so the remaining extractors still get a chance
        assert tags is False

    def test_tmux_event_with_command_rule(self) -> None:
        """Test tmux tag extraction with command matching rule."""
        config = {
            "rules": {
                "tmux": {
                    "editing": {
                        "command": r"(vim|emacs|nano)",
                        "tags": ["coding", "editing", "$command"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }

        tmux_event = create_tmux_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            session_name="main",
            window_name="work",
            pane_command="vim",
        )

        extractor, window_event = setup_tmux_test(config, tmux_event)
        tags = extractor.get_tmux_tags(window_event)
        assert "coding" in tags
        assert "editing" in tags
        assert "vim" in tags

    def test_tmux_event_with_session_rule(self) -> None:
        """Test tmux tag extraction with session matching rule."""
        config = {
            "rules": {
                "tmux": {
                    "work_session": {
                        "session": r"work",
                        "tags": ["work", "$session"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }

        tmux_event = create_tmux_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            session_name="work",
            window_name="coding",
            pane_command="python",
        )

        extractor, window_event = setup_tmux_test(config, tmux_event)
        tags = extractor.get_tmux_tags(window_event)
        assert "work" in tags

    def test_tmux_event_with_path_rule(self) -> None:
        """Test tmux tag extraction with path matching rule."""
        config = {
            "rules": {
                "tmux": {
                    "project": {
                        "path": r"/home/user/projects/([^/]+)",
                        "tags": ["coding", "project:$1"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }

        tmux_event = create_tmux_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            session_name="main",
            window_name="dev",
            pane_command="python",
            pane_path="/home/user/projects/myapp",
        )

        extractor, window_event = setup_tmux_test(config, tmux_event)
        tags = extractor.get_tmux_tags(window_event)
        assert "coding" in tags
        assert "project:myapp" in tags

    def test_tmux_event_with_combined_rules(self) -> None:
        """Test tmux tag extraction with multiple rule conditions."""
        config = {
            "rules": {
                "tmux": {
                    "dev_work": {
                        "session": r"work",
                        "command": r"(python|node)",
                        "tags": ["work", "dev", "$command"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }

        tmux_event = create_tmux_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            session_name="work",
            window_name="api",
            pane_command="python",
        )

        extractor, window_event = setup_tmux_test(config, tmux_event)
        tags = extractor.get_tmux_tags(window_event)
        assert "work" in tags
        assert "dev" in tags
        assert "python" in tags

    def test_non_terminal_app_returns_false(self) -> None:
        """Test that non-terminal apps return False."""
        config = {"rules": {}, "exclusive": {}, "tags": {}}

        mock_fetcher = Mock(spec=EventFetcher)
        extractor = TagExtractor(config, mock_fetcher)

        # Browser window event
        window_event = create_window_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            app="firefox",
            title="GitHub",
        )

        tags = extractor.get_tmux_tags(window_event)
        assert tags is False

    def test_terminal_without_tmux_returns_false(self) -> None:
        """Test that terminal window without tmux activity returns False.

        When there are no tmux events, get_tmux_tags returns False so that
        get_app_tags can handle the terminal window instead.
        """
        config = {"rules": {}, "exclusive": {}, "tags": {}}

        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.get_tmux_bucket.return_value = "aw-watcher-tmux"
        mock_fetcher.get_corresponding_event.return_value = None  # No tmux event

        extractor = TagExtractor(config, mock_fetcher)

        window_event = create_window_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            app="foot",
        )

        tags = extractor.get_tmux_tags(window_event)
        assert tags is False

    def test_tmux_event_no_command_falls_through(self) -> None:
        """Test tmux event without command falls through to the app rules."""
        config = {"rules": {}, "exclusive": {}, "tags": {}}

        tmux_event = create_tmux_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            session_name="main",
            window_name="shell",
            pane_command="",  # Empty command
            pane_path="/home/user",
        )

        extractor, window_event = setup_tmux_test(config, tmux_event)
        tags = extractor.get_tmux_tags(window_event)
        assert tags is False

    def test_tmux_multiple_capture_groups(self) -> None:
        """Test tmux tag extraction with multiple regex capture groups."""
        config = {
            "rules": {
                "tmux": {
                    "git_operations": {
                        "command": r"git\s+(push|pull|commit)",
                        "path": r"/home/user/projects/([^/]+)/([^/]+)",
                        "tags": ["git", "$1", "org:$2", "proj:$3"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }

        tmux_event = create_tmux_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            session_name="work",
            window_name="dev",
            pane_command="git push",
            pane_path="/home/user/projects/myorg/myproject",
        )

        extractor, window_event = setup_tmux_test(config, tmux_event)
        tags = extractor.get_tmux_tags(window_event)
        # $1 should be "push" from command match (command takes priority)
        assert "git" in tags
        assert "push" in tags

    def test_tmux_path_capture_groups(self) -> None:
        """Test tmux tag extraction with path capture groups when no command match."""
        config = {
            "rules": {
                "tmux": {
                    "project_work": {
                        "path": r"/home/user/projects/([^/]+)/([^/]+)",
                        "tags": ["coding", "org:$1", "project:$2"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }

        tmux_event = create_tmux_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            session_name="work",
            window_name="editor",
            pane_command="vim",
            pane_path="/home/user/projects/github/aw-export-timewarrior",
        )

        extractor, window_event = setup_tmux_test(config, tmux_event)
        tags = extractor.get_tmux_tags(window_event)
        assert "coding" in tags
        assert "org:github" in tags
        assert "project:aw-export-timewarrior" in tags

    def test_non_tmux_terminal_ignores_tmux_events(self) -> None:
        """Test that a terminal NOT running tmux doesn't pick up tmux events.

        This is a regression test for a bug where non-tmux terminals would
        incorrectly get tmux tags from other terminal windows running tmux.

        The fix verifies that the window title indicates tmux is running
        (contains 'tmux' or the session/window name) before using tmux events.

        When the window title doesn't indicate tmux, get_tmux_tags returns False
        so that get_app_tags can handle the terminal window instead.
        """
        config = {
            "rules": {
                "tmux": {
                    "coding": {
                        "command": r"vim",
                        "tags": ["coding"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }

        # Tmux event from another terminal running tmux
        tmux_event = create_tmux_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            session_name="work",
            window_name="editor",
            pane_command="vim",
            pane_path="/home/user",
        )

        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.get_tmux_bucket.return_value = "aw-watcher-tmux"
        mock_fetcher.get_corresponding_event.return_value = tmux_event

        # Window event for a terminal NOT running tmux (title doesn't contain tmux info)
        window_event = create_window_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            app="foot",
            title="bash",  # Plain bash, not tmux
        )

        extractor = TagExtractor(config, mock_fetcher)
        tags = extractor.get_tmux_tags(window_event)

        # Should return False (not tmux context) so that get_app_tags can handle it
        assert tags is False, (
            f"Non-tmux terminal should return False to allow app rules fallback. "
            f"Got: {tags}. Window title 'bash' doesn't indicate tmux is running."
        )
