"""Test that tmux events with path ~/caldav match the claude-oss rule.

Real-world case from Dec 30, 2025:
- Window event at 01:29:44 (foot terminal, title "tmux")
- Tmux event at 01:28:31 showing cmd=claude, path=/home/tobias/caldav
- Expected: should match rules.tmux.claude-oss and return caldav tags
- Actual bug: returns tags without 'caldav' because command match shadows path capture groups
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from aw_export_timewarrior.tag_extractor import TagExtractor


class TestTmuxCaldavRule:
    """Test that caldav path matches the tmux rule."""

    @pytest.fixture
    def config_with_caldav_rule(self):
        """Config with the claude-oss rule that should match caldav."""
        return {
            "rules": {
                "tmux": {
                    "claude-oss": {
                        "command": "claude",
                        "path": r"(?:/home/tobias|~)/(activitywatch.*|caldav|inventory-system|mobilizon)",
                        "tags": ["$1", "4OSS", "oss-contrib", "claude"],
                    }
                }
            },
            "terminal_apps": ["foot"],
        }

    @pytest.fixture
    def tmux_events_caldav(self):
        """Real tmux events from Dec 30, 2025 showing caldav work."""
        return [
            {
                "id": 484821,
                "timestamp": datetime(2025, 12, 30, 1, 28, 31, tzinfo=UTC),
                "duration": timedelta(seconds=5.0),
                "data": {
                    "pane_current_command": "claude",
                    "pane_current_path": "/home/tobias/caldav",
                    "pane_title": "✳ has_component bug",
                    "session_name": "0",
                    "window_name": "claude",
                },
            },
            {
                "id": 484773,
                "timestamp": datetime(2025, 12, 30, 1, 24, 34, tzinfo=UTC),
                "duration": timedelta(seconds=7.0),
                "data": {
                    "pane_current_command": "claude",
                    "pane_current_path": "/home/tobias/caldav",
                    "pane_title": "✳ has_component bug",
                    "session_name": "0",
                    "window_name": "claude",
                },
            },
        ]

    @pytest.fixture
    def window_event_in_caldav_session(self):
        """Window event from Dec 30, 2025 that should match caldav rule."""
        return {
            "id": 484833,
            "timestamp": datetime(2025, 12, 30, 1, 29, 44, tzinfo=UTC),
            "duration": timedelta(seconds=15.245),
            "data": {"app": "foot", "title": "tmux"},
        }

    @pytest.fixture
    def mock_event_fetcher(self, tmux_events_caldav):
        """Mock EventFetcher that returns caldav tmux events."""
        fetcher = MagicMock()
        fetcher.log_callback = lambda *args, **kwargs: None
        fetcher.bucket_short = {}

        def get_tmux_bucket():
            return "aw-watcher-tmux"

        fetcher.get_tmux_bucket = get_tmux_bucket

        def get_corresponding_event(
            window_event, bucket_id, ignorable=False, fallback_to_recent=False, retry=6
        ):
            # Return the first tmux event (simulating fallback finding it)
            if bucket_id == "aw-watcher-tmux":
                return tmux_events_caldav[0]
            return None

        fetcher.get_corresponding_event = get_corresponding_event

        return fetcher

    def test_caldav_path_matches_rule_via_tag_extractor(
        self, config_with_caldav_rule, mock_event_fetcher, window_event_in_caldav_session
    ):
        """Tmux event with path=/home/tobias/caldav should match claude-oss rule.

        Tests the TagExtractor.get_tmux_tags() method directly.
        """
        tag_extractor = TagExtractor(
            config=config_with_caldav_rule,
            event_fetcher=mock_event_fetcher,
            terminal_apps={"foot"},
        )

        result = tag_extractor.get_tmux_tags(window_event_in_caldav_session)

        # Should match and return tags including 'caldav' from $1
        assert result is not None
        assert result != []
        assert result is not False
        assert "caldav" in result, f"Expected 'caldav' in tags, got {result}"
        assert "4OSS" in result
        assert "oss-contrib" in result
        assert "claude" in result
        assert "not-afk" in result

    def test_caldav_path_matches_rule_via_get_tags(
        self, config_with_caldav_rule, mock_event_fetcher, window_event_in_caldav_session
    ):
        """Test the main get_tags() entry point used by event processing.

        This is the same code path used by find_tags_from_event() in main.py.
        """
        tag_extractor = TagExtractor(
            config=config_with_caldav_rule,
            event_fetcher=mock_event_fetcher,
            terminal_apps={"foot"},
        )

        result = tag_extractor.get_tags(window_event_in_caldav_session)

        # Should match and return tags including 'caldav' from $1
        assert result is not None
        assert result != []
        assert result is not False
        assert "caldav" in result, f"Expected 'caldav' in tags, got {result}"
        assert "4OSS" in result

    def test_path_regex_matches_caldav(self, config_with_caldav_rule):
        """Verify the regex pattern matches /home/tobias/caldav."""
        import re

        pattern = config_with_caldav_rule["rules"]["tmux"]["claude-oss"]["path"]
        path = "/home/tobias/caldav"

        match = re.search(pattern, path)
        assert match is not None, f"Pattern {pattern!r} should match {path!r}"
        assert match.group(1) == "caldav", (
            f"Capture group should be 'caldav', got {match.group(1)!r}"
        )

    def test_command_regex_matches_claude(self, config_with_caldav_rule):
        """Verify the command pattern matches 'claude'."""
        import re

        pattern = config_with_caldav_rule["rules"]["tmux"]["claude-oss"]["command"]
        command = "claude"

        match = re.search(pattern, command)
        assert match is not None, f"Pattern {pattern!r} should match {command!r}"
