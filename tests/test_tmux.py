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

    window_event = create_window_event(
        timestamp=datetime.now(UTC),
        duration=timedelta(minutes=5),
        app="foot",
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
        """Test that tmux events return empty list when no rules match (consistent with browser/editor)."""
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
        # Should return empty list when no rules match (will be marked UNMATCHED)
        assert tags == []

    def test_tmux_event_with_command_rule(self) -> None:
        """Test tmux tag extraction with command matching rule."""
        config = {
            "rules": {
                "tmux": {
                    "editing": {
                        "command": r"(vim|emacs|nano)",
                        "timew_tags": ["coding", "editing", "$command"],
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
                        "timew_tags": ["work", "$session"],
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
                        "timew_tags": ["coding", "project:$1"],
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
                        "timew_tags": ["work", "dev", "$command"],
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

    def test_terminal_without_tmux_returns_empty(self) -> None:
        """Test that terminal window without tmux activity returns empty list."""
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
        assert tags == []

    def test_tmux_event_no_command_returns_empty(self) -> None:
        """Test tmux event without command returns empty list."""
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
        assert tags == []

    def test_tmux_multiple_capture_groups(self) -> None:
        """Test tmux tag extraction with multiple regex capture groups."""
        config = {
            "rules": {
                "tmux": {
                    "git_operations": {
                        "command": r"git\s+(push|pull|commit)",
                        "path": r"/home/user/projects/([^/]+)/([^/]+)",
                        "timew_tags": ["git", "$1", "org:$2", "proj:$3"],
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
                        "timew_tags": ["coding", "org:$1", "project:$2"],
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
