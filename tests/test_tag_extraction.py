"""Tests for tag extraction from browser, editor, and app events."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.main import Exporter


def create_aw_event(timestamp, duration, data):
    """Create a mock ActivityWatch event object with proper attributes and dict access."""
    event = Mock()
    event.timestamp = timestamp
    event.duration = duration
    event.data = data
    # Support both attribute and dictionary access
    event.__getitem__ = lambda self, key: getattr(self, key)
    return event


@pytest.fixture
def mock_aw_client():
    """Fixture to create a mocked ActivityWatch client."""
    with patch('aw_export_timewarrior.main.aw_client') as mock_aw:
        # Create mock client instance
        mock_client_instance = Mock()

        # Get current time for last_updated
        current_time = datetime.now(UTC).isoformat()

        mock_client_instance.get_buckets.return_value = {
            'aw-watcher-window_test': {
                'id': 'aw-watcher-window_test',
                'client': 'aw-watcher-window',
                'last_updated': current_time
            },
            'aw-watcher-afk_test': {
                'id': 'aw-watcher-afk_test',
                'client': 'aw-watcher-afk',
                'last_updated': current_time
            },
            'aw-watcher-web-chrome_test': {
                'id': 'aw-watcher-web-chrome_test',
                'client': 'aw-watcher-web-chrome',
                'last_updated': current_time
            },
            'aw-watcher-web-firefox_test': {
                'id': 'aw-watcher-web-firefox_test',
                'client': 'aw-watcher-web-firefox',
                'last_updated': current_time
            },
            'aw-watcher-emacs_test': {
                'id': 'aw-watcher-emacs_test',
                'client': 'aw-watcher-emacs',
                'last_updated': current_time
            },
            'aw-watcher-vim_test': {
                'id': 'aw-watcher-vim_test',
                'client': 'aw-watcher-vim',
                'last_updated': current_time
            },
            'aw-watcher-vi_test': {
                'id': 'aw-watcher-vi_test',
                'client': 'aw-watcher-vi',
                'last_updated': current_time
            }
        }
        mock_client_instance.get_events.return_value = []

        mock_aw.ActivityWatchClient.return_value = mock_client_instance
        yield mock_client_instance


class TestBrowserTagExtraction:
    """Tests for get_browser_tags method."""

    def test_browser_github_url_matches(self, mock_aw_client: Mock) -> None:
        """Test browser event matching GitHub URL."""
        exporter = Exporter()
        exporter.config = {
            'rules': {
                'browser': {
                    'github': {
                        'url_regexp': r'github\.com/([^/]+)/([^/]+)',
                        'timew_tags': ['4work', 'github', '$1']
                    }
                }
            },
            'exclusive': {},
            'tags': {}
        }

        # Mock browser event
        browser_event = create_aw_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={
                'url': 'https://github.com/python-caldav/caldav',
                'title': 'GitHub - python-caldav/caldav'
            }
        )

        # Set up mock to return browser event
        mock_aw_client.get_events.return_value = [browser_event]

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {
                'app': 'chrome',
                'title': 'GitHub - python-caldav/caldav'
            }
        }

        tags = exporter.get_browser_tags(window_event)

        assert '4work' in tags
        assert 'github' in tags
        assert 'python-caldav' in tags  # $1 from regex
        assert 'not-afk' in tags

    def test_browser_new_tab_returns_empty(self, mock_aw_client: Mock) -> None:
        """Test that new tab pages return empty tag list."""
        exporter = Exporter()
        exporter.config = {
            'rules': {'browser': {}},
            'exclusive': {},
            'tags': {}
        }

        browser_event = create_aw_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(seconds=30),
            data={
                'url': 'chrome://newtab/',
                'title': 'New Tab'
            }
        )

        mock_aw_client.get_events.return_value = [browser_event]

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(seconds=30),
            'data': {
                'app': 'chromium',
                'title': 'New Tab'
            }
        }

        tags = exporter.get_browser_tags(window_event)

        assert tags == []

    def test_browser_non_browser_app_returns_false(self, mock_aw_client: Mock) -> None:
        """Test that non-browser apps return False."""
        exporter = Exporter()

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {
                'app': 'Terminal',
                'title': 'bash'
            }
        }

        tags = exporter.get_browser_tags(window_event)

        assert tags is False

    @patch('aw_export_timewarrior.main.config', {
        'rules': {
            'browser': {
                'docs': {
                    'url_regexp': r'docs\.python\.org',
                    'timew_tags': ['4work', 'python', 'documentation']
                }
            }
        },
        'exclusive': {},
        'tags': {}
    })
    @patch('aw_export_timewarrior.main.sleep')  # Mock sleep to prevent hanging
    def test_browser_no_corresponding_event(self, mock_sleep: Mock, mock_aw_client: Mock) -> None:
        """Test browser event when no corresponding web event found."""
        exporter = Exporter()

        # No browser event returned
        mock_aw_client.get_events.return_value = []

        # Use an older timestamp to avoid retry logic based on wall clock
        old_timestamp = datetime.now(UTC) - timedelta(hours=1)
        window_event = {
            'timestamp': old_timestamp,
            'duration': timedelta(minutes=5),
            'data': {
                'app': 'firefox',
                'title': 'Python Documentation'
            }
        }

        tags = exporter.get_browser_tags(window_event)

        assert tags == []


class TestEditorTagExtraction:
    """Tests for get_editor_tags method."""

    def test_editor_project_match(self, mock_aw_client: Mock) -> None:
        """Test editor event matching by project name."""
        exporter = Exporter()
        exporter.config = {
            'rules': {
                'editor': {
                    'caldav_project': {
                        'projects': ['caldav'],
                        'timew_tags': ['4work', 'caldav', 'python']
                    }
                }
            },
            'exclusive': {},
            'tags': {}
        }

        editor_event = create_aw_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=10),
            data={
                'project': 'caldav',
                'file': '/home/user/projects/caldav/lib/caldav.py',
                'language': 'python'
            }
        )

        mock_aw_client.get_events.return_value = [editor_event]

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=10),
            'data': {
                'app': 'emacs',
                'title': 'caldav.py - Emacs'
            }
        }

        tags = exporter.get_editor_tags(window_event)

        assert '4work' in tags
        assert 'caldav' in tags
        assert 'python' in tags
        assert 'not-afk' in tags

    def test_editor_path_regexp_match(self, mock_aw_client: Mock) -> None:
        """Test editor event matching by file path regexp."""
        exporter = Exporter()
        exporter.config = {
            'rules': {
                'editor': {
                    'config_files': {
                        'path_regexp': r'\.config/([^/]+)/',
                        'timew_tags': ['4me', 'config', '$1']
                    }
                }
            },
            'exclusive': {},
            'tags': {}
        }

        editor_event = create_aw_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=10),
            data={
                'project': 'dotfiles',
                'file': '/home/user/.config/nvim/init.vim',
                'language': 'vim'
            }
        )

        mock_aw_client.get_events.return_value = [editor_event]

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=10),
            'data': {
                'app': 'vim',
                'title': 'init.vim'
            }
        }

        tags = exporter.get_editor_tags(window_event)

        assert '4me' in tags
        assert 'config' in tags
        assert 'nvim' in tags  # $1 from regex
        assert 'not-afk' in tags

    def test_editor_non_editor_app_returns_false(self, mock_aw_client: Mock) -> None:
        """Test that non-editor apps return False."""
        exporter = Exporter()

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {
                'app': 'chrome',
                'title': 'GitHub'
            }
        }

        tags = exporter.get_editor_tags(window_event)

        assert tags is False


class TestAppTagExtraction:
    """Tests for get_app_tags method."""

    def test_app_simple_match(self, mock_aw_client: Mock) -> None:
        """Test app event with simple app name match."""
        exporter = Exporter()
        exporter.config = {
            'rules': {
                'app': {
                    'communication': {
                        'app_names': ['Signal', 'DeltaChat', 'Slack'],
                        'timew_tags': ['4me', 'communication', '$app']
                    }
                }
            },
            'exclusive': {},
            'tags': {}
        }

        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {
                'app': 'Signal',
                'title': 'Signal - Inbox'
            }
        }

        tags = exporter.get_app_tags(event)

        assert '4me' in tags
        assert 'communication' in tags
        assert 'Signal' in tags  # $app substitution
        assert 'not-afk' in tags

    def test_app_with_title_regexp(self, mock_aw_client: Mock) -> None:
        """Test app event with title regexp matching."""
        exporter = Exporter()
        exporter.config = {
            'rules': {
                'app': {
                    'terminal': {
                        'app_names': ['Terminal', 'foot', 'xterm'],
                        'title_regexp': r'ssh\s+(\S+)',
                        'timew_tags': ['4work', 'ssh', '$1']
                    }
                }
            },
            'exclusive': {},
            'tags': {}
        }

        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=15),
            'data': {
                'app': 'foot',
                'title': 'ssh production-server'
            }
        }

        tags = exporter.get_app_tags(event)

        assert '4work' in tags
        assert 'ssh' in tags
        assert 'production-server' in tags  # $1 from regex
        assert 'not-afk' in tags

    @patch('aw_export_timewarrior.main.config', {
        'rules': {
            'app': {
                'terminal': {
                    'app_names': ['Terminal'],
                    'title_regexp': r'important-task',
                    'timew_tags': ['4work']
                }
            }
        },
        'exclusive': {},
        'tags': {}
    })
    def test_app_title_regexp_no_match(self, mock_aw_client: Mock) -> None:
        """Test app event where title regexp doesn't match."""
        exporter = Exporter()

        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {
                'app': 'Terminal',
                'title': 'bash - regular work'
            }
        }

        tags = exporter.get_app_tags(event)

        # Should return False because title doesn't match regexp
        assert tags is False

    @patch('aw_export_timewarrior.main.config', {
        'rules': {
            'app': {}
        },
        'exclusive': {},
        'tags': {}
    })
    def test_app_no_matching_rules(self, mock_aw_client: Mock) -> None:
        """Test app event with no matching rules."""
        exporter = Exporter()

        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {
                'app': 'UnknownApp',
                'title': 'Some Window'
            }
        }

        tags = exporter.get_app_tags(event)

        assert tags is False


class TestGetCorrespondingEvent:
    """Tests for get_corresponding_event method."""

    def test_corresponding_event_found_immediately(self, mock_aw_client: Mock) -> None:
        """Test finding corresponding event on first try."""
        exporter = Exporter()

        corresponding_event = create_aw_event(
            timestamp=datetime(2025, 5, 28, 14, 30, 0, tzinfo=UTC),
            duration=timedelta(minutes=5),
            data={'url': 'https://example.com'}
        )

        mock_aw_client.get_events.return_value = [corresponding_event]

        window_event = {
            'timestamp': datetime(2025, 5, 28, 14, 30, 0, tzinfo=UTC),
            'duration': timedelta(minutes=5),
            'data': {'app': 'chrome', 'title': 'Example'}
        }

        result = exporter.get_corresponding_event(
            window_event,
            'aw-watcher-web-chrome_test'
        )

        assert result == corresponding_event

    def test_corresponding_event_multiple_events_picks_longest(self, mock_aw_client: Mock) -> None:
        """Test that longest event is picked when multiple match."""
        exporter = Exporter()

        short_event = create_aw_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(seconds=5),
            data={'url': 'https://example.com'}
        )

        long_event = create_aw_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=10),
            data={'url': 'https://example.com/page'}
        )

        mock_aw_client.get_events.return_value = [short_event, long_event]

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=10),
            'data': {'app': 'chrome', 'title': 'Example'}
        }

        result = exporter.get_corresponding_event(
            window_event,
            'aw-watcher-web-chrome_test'
        )

        assert result == long_event

    @patch('aw_export_timewarrior.main.IGNORE_INTERVAL', 3)
    def test_corresponding_event_not_found_ignorable(self, mock_aw_client: Mock) -> None:
        """Test ignorable event returns None without warning."""
        exporter = Exporter()

        mock_aw_client.get_events.return_value = []

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(seconds=2),  # Less than IGNORE_INTERVAL
            'data': {'app': 'emacs', 'title': '*scratch*'}
        }

        result = exporter.get_corresponding_event(
            window_event,
            'aw-watcher-emacs_test',
            ignorable=True
        )

        assert result is None


class TestGetAfkTags:
    """Tests for get_afk_tags method."""

    def test_afk_status_returns_afk(self, mock_aw_client: Mock) -> None:
        """Test AFK event returns afk tag."""
        exporter = Exporter()

        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=10),
            'data': {'status': 'afk'}
        }

        tags = exporter.get_afk_tags(event)

        assert tags == {'afk'}

    def test_not_afk_status_returns_not_afk(self, mock_aw_client: Mock) -> None:
        """Test not-afk event returns not-afk tag."""
        exporter = Exporter()

        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(seconds=1),
            'data': {'status': 'not-afk'}
        }

        tags = exporter.get_afk_tags(event)

        assert tags == {'not-afk'}

    def test_no_status_returns_false(self, mock_aw_client: Mock) -> None:
        """Test event without status returns False."""
        exporter = Exporter()

        event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {'app': 'chrome', 'title': 'Example'}
        }

        tags = exporter.get_afk_tags(event)

        assert tags is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
