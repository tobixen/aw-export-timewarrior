"""Tests to improve coverage of tag_extractor.py.

Covers:
- ExclusiveGroupViolation.__str__ and ExclusiveGroupError
- _match_tmux_rule edge cases (session/window/command/path mismatches)
- _fetch_tmux_sub_event method
- get_specialized_context method
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from aw_export_timewarrior.aw_client import EventFetcher
from aw_export_timewarrior.tag_extractor import (
    ExclusiveGroupError,
    ExclusiveGroupViolation,
    TagExtractor,
)


class TestExclusiveGroupViolation:
    """Tests for ExclusiveGroupViolation class."""

    def test_str_representation(self) -> None:
        """Test __str__ method formats violation correctly."""
        violation = ExclusiveGroupViolation(
            group_name="work-type",
            group_tags={"coding", "meeting", "review"},
            conflicting_tags={"coding", "meeting"},
        )

        result = str(violation)

        assert "work-type" in result
        assert "coding" in result
        assert "meeting" in result
        assert "conflict" in result

    def test_str_with_single_conflict(self) -> None:
        """Test __str__ with minimal conflict."""
        violation = ExclusiveGroupViolation(
            group_name="status",
            group_tags={"afk", "not-afk"},
            conflicting_tags={"afk", "not-afk"},
        )

        result = str(violation)

        assert "status" in result
        assert "afk" in result
        assert "not-afk" in result


class TestExclusiveGroupError:
    """Tests for ExclusiveGroupError exception class."""

    def test_exception_init_and_message(self) -> None:
        """Test ExclusiveGroupError initialization and message formatting."""
        violations = [
            ExclusiveGroupViolation(
                group_name="work-type",
                group_tags={"coding", "meeting"},
                conflicting_tags={"coding", "meeting"},
            )
        ]

        error = ExclusiveGroupError(
            source_tags={"coding", "meeting", "work"},
            violations=violations,
        )

        assert error.source_tags == {"coding", "meeting", "work"}
        assert error.violations == violations
        assert "exclusive group" in str(error).lower()
        assert "coding" in str(error)
        assert "meeting" in str(error)

    def test_exception_can_be_raised(self) -> None:
        """Test that ExclusiveGroupError can be raised and caught."""
        violations = [
            ExclusiveGroupViolation(
                group_name="test",
                group_tags={"a", "b"},
                conflicting_tags={"a", "b"},
            )
        ]

        with pytest.raises(ExclusiveGroupError) as exc_info:
            raise ExclusiveGroupError({"a", "b"}, violations)

        assert len(exc_info.value.violations) == 1


class TestMatchTmuxRule:
    """Tests for _match_tmux_rule method edge cases."""

    def create_tmux_event(
        self,
        session_name="main",
        window_name="code",
        pane_command="vim",
        pane_path="/home/user/project",
        pane_title="",
    ) -> dict:
        """Create a mock tmux event."""
        return {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {
                "session_name": session_name,
                "window_name": window_name,
                "pane_current_command": pane_command,
                "pane_current_path": pane_path,
                "pane_title": pane_title,
            },
        }

    def create_extractor(self, config: dict) -> TagExtractor:
        """Create a TagExtractor with mocked fetcher."""
        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.get_tmux_bucket.return_value = None
        return TagExtractor(config, mock_fetcher)

    def test_session_mismatch_returns_none(self) -> None:
        """Test that session mismatch returns None."""
        config = {
            "rules": {
                "tmux": {
                    "work": {
                        "session": r"^work$",
                        "tags": ["4work"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }
        extractor = self.create_extractor(config)
        tmux_event = self.create_tmux_event(session_name="personal")

        result = extractor._match_tmux_rule(
            config["rules"]["tmux"]["work"],
            tmux_event,
            "tags",
        )

        assert result is None

    def test_window_mismatch_returns_none(self) -> None:
        """Test that window mismatch returns None."""
        config = {
            "rules": {
                "tmux": {
                    "editor": {
                        "window": r"^editor$",
                        "tags": ["coding"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }
        extractor = self.create_extractor(config)
        tmux_event = self.create_tmux_event(window_name="shell")

        result = extractor._match_tmux_rule(
            config["rules"]["tmux"]["editor"],
            tmux_event,
            "tags",
        )

        assert result is None

    def test_command_mismatch_returns_none(self) -> None:
        """Test that command mismatch returns None."""
        config = {
            "rules": {
                "tmux": {
                    "vim": {
                        "command": r"^vim$",
                        "tags": ["editing"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }
        extractor = self.create_extractor(config)
        tmux_event = self.create_tmux_event(pane_command="emacs")

        result = extractor._match_tmux_rule(
            config["rules"]["tmux"]["vim"],
            tmux_event,
            "tags",
        )

        assert result is None

    def test_path_mismatch_returns_none(self) -> None:
        """Test that path mismatch returns None."""
        config = {
            "rules": {
                "tmux": {
                    "project": {
                        "path": r"/home/user/work",
                        "tags": ["work-project"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }
        extractor = self.create_extractor(config)
        tmux_event = self.create_tmux_event(pane_path="/home/user/personal")

        result = extractor._match_tmux_rule(
            config["rules"]["tmux"]["project"],
            tmux_event,
            "tags",
        )

        assert result is None

    def test_all_fields_match_returns_tags(self) -> None:
        """Test that matching all fields returns tags."""
        config = {
            "rules": {
                "tmux": {
                    "work": {
                        "session": r"^work$",
                        "window": r"^code$",
                        "command": r"^vim$",
                        "path": r"/project",
                        "tags": ["4work", "coding"],
                    }
                }
            },
            "exclusive": {},
            "tags": {},
        }
        extractor = self.create_extractor(config)
        tmux_event = self.create_tmux_event(
            session_name="work",
            window_name="code",
            pane_command="vim",
            pane_path="/home/user/project",
        )

        result = extractor._match_tmux_rule(
            config["rules"]["tmux"]["work"],
            tmux_event,
            "tags",
        )

        assert result is not None
        assert "4work" in result
        assert "coding" in result
        assert "not-afk" in result


class TestFetchTmuxSubEvent:
    """Tests for _fetch_tmux_sub_event method."""

    def test_non_terminal_app_returns_none(self) -> None:
        """Test that non-terminal apps return None."""
        mock_fetcher = Mock(spec=EventFetcher)
        extractor = TagExtractor(
            {"rules": {}, "exclusive": {}, "tags": {}},
            mock_fetcher,
            terminal_apps={"foot", "kitty"},
        )

        window_event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"app": "chrome", "title": "Browser"},
        }

        result = extractor._fetch_tmux_sub_event(window_event)

        assert result is None
        mock_fetcher.get_tmux_bucket.assert_not_called()

    def test_no_tmux_bucket_returns_none(self) -> None:
        """Test that missing tmux bucket returns None."""
        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.get_tmux_bucket.return_value = None

        extractor = TagExtractor(
            {"rules": {}, "exclusive": {}, "tags": {}},
            mock_fetcher,
            terminal_apps={"foot"},
        )

        window_event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"app": "foot", "title": "Terminal"},
        }

        result = extractor._fetch_tmux_sub_event(window_event)

        assert result is None

    def test_terminal_with_tmux_bucket_fetches_event(self) -> None:
        """Test that terminal window with tmux bucket fetches corresponding event."""
        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.get_tmux_bucket.return_value = "aw-watcher-tmux"
        expected_event = {"data": {"session_name": "main", "pane_current_command": "vim"}}
        mock_fetcher.get_corresponding_event.return_value = expected_event

        extractor = TagExtractor(
            {"rules": {}, "exclusive": {}, "tags": {}},
            mock_fetcher,
            terminal_apps={"foot"},
        )

        window_event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"app": "foot", "title": "Terminal"},
        }

        result = extractor._fetch_tmux_sub_event(window_event)

        assert result == expected_event
        mock_fetcher.get_corresponding_event.assert_called_once()


class TestGetSpecializedContext:
    """Tests for get_specialized_context method."""

    def test_browser_context(self) -> None:
        """Test getting browser context returns URL."""
        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.bucket_short = {"aw-watcher-web-chrome": {"id": "aw-watcher-web-chrome_host"}}
        browser_event = {"data": {"url": "https://github.com/python-caldav/caldav"}}
        mock_fetcher.get_corresponding_event.return_value = browser_event

        extractor = TagExtractor(
            {"rules": {}, "exclusive": {}, "tags": {}},
            mock_fetcher,
        )

        window_event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"app": "chromium", "title": "GitHub"},
        }

        result = extractor.get_specialized_context(window_event)

        assert result["type"] == "browser"
        assert "github.com" in result["data"]

    def test_editor_context_with_file(self) -> None:
        """Test getting editor context returns file path."""
        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.bucket_short = {"aw-watcher-emacs": {"id": "aw-watcher-emacs_host"}}
        editor_event = {"data": {"file": "/home/user/project/main.py", "project": "myproject"}}
        mock_fetcher.get_corresponding_event.return_value = editor_event

        extractor = TagExtractor(
            {"rules": {}, "exclusive": {}, "tags": {}},
            mock_fetcher,
        )

        window_event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"app": "emacs", "title": "main.py"},
        }

        result = extractor.get_specialized_context(window_event)

        assert result["type"] == "editor"
        assert "/home/user/project/main.py" in result["data"]

    def test_editor_context_with_project_only(self) -> None:
        """Test getting editor context with project but no file."""
        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.bucket_short = {"aw-watcher-vim": {"id": "aw-watcher-vim_host"}}
        editor_event = {"data": {"file": "", "project": "myproject"}}
        mock_fetcher.get_corresponding_event.return_value = editor_event

        extractor = TagExtractor(
            {"rules": {}, "exclusive": {}, "tags": {}},
            mock_fetcher,
        )

        window_event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"app": "vim", "title": "vim"},
        }

        result = extractor.get_specialized_context(window_event)

        assert result["type"] == "editor"
        assert "project:myproject" in result["data"]

    def test_terminal_context_with_tmux(self) -> None:
        """Test getting terminal context returns tmux info."""
        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.bucket_short = {}  # No browser/editor buckets
        mock_fetcher.get_tmux_bucket.return_value = "aw-watcher-tmux"
        tmux_event = {
            "data": {
                "pane_current_command": "vim",
                "pane_current_path": "/home/user/project",
                "pane_title": "editor",
            }
        }
        mock_fetcher.get_corresponding_event.return_value = tmux_event

        extractor = TagExtractor(
            {"rules": {}, "exclusive": {}, "tags": {}},
            mock_fetcher,
            terminal_apps={"foot"},
        )

        window_event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"app": "foot", "title": "Terminal"},
        }

        result = extractor.get_specialized_context(window_event)

        assert result["type"] == "terminal"
        assert "cmd:vim" in result["data"]
        assert "path:" in result["data"]

    def test_terminal_context_path_shortening(self) -> None:
        """Test that home directory paths are shortened."""
        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.bucket_short = {}
        mock_fetcher.get_tmux_bucket.return_value = "aw-watcher-tmux"
        tmux_event = {
            "data": {
                "pane_current_command": "bash",
                "pane_current_path": "/home/tobias/projects/myapp",
                "pane_title": "",
            }
        }
        mock_fetcher.get_corresponding_event.return_value = tmux_event

        extractor = TagExtractor(
            {"rules": {}, "exclusive": {}, "tags": {}},
            mock_fetcher,
            terminal_apps={"foot"},
        )

        window_event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"app": "foot", "title": "Terminal"},
        }

        result = extractor.get_specialized_context(window_event)

        assert result["type"] == "terminal"
        # Path should be shortened from /home/tobias/... to ~/...
        assert "~/" in result["data"]

    def test_no_context_returns_none(self) -> None:
        """Test that non-specialized app returns None context."""
        mock_fetcher = Mock(spec=EventFetcher)
        mock_fetcher.bucket_short = {}
        mock_fetcher.get_tmux_bucket.return_value = None

        extractor = TagExtractor(
            {"rules": {}, "exclusive": {}, "tags": {}},
            mock_fetcher,
        )

        window_event = {
            "timestamp": datetime.now(UTC),
            "duration": timedelta(minutes=5),
            "data": {"app": "feh", "title": "image.jpg"},
        }

        result = extractor.get_specialized_context(window_event)

        assert result["type"] is None
        assert result["data"] is None


class TestApplyRetagRulesExclusiveError:
    """Test that apply_retag_rules raises ExclusiveGroupError correctly."""

    def test_exclusive_violation_raises_error(self) -> None:
        """Test that exclusive group violation raises ExclusiveGroupError."""
        mock_fetcher = Mock(spec=EventFetcher)
        config = {
            "rules": {},
            "exclusive": {
                "afk-status": {
                    "tags": ["afk", "not-afk"],
                }
            },
            "tags": {},
        }

        extractor = TagExtractor(config, mock_fetcher)

        # Tags that violate exclusive group
        source_tags = {"afk", "not-afk", "work"}

        with pytest.raises(ExclusiveGroupError) as exc_info:
            extractor.apply_retag_rules(source_tags)

        assert len(exc_info.value.violations) == 1
        assert exc_info.value.violations[0].group_name == "afk-status"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
