"""
Regression tests for tag matching bugs.

This test would have caught the bug where `rule` was out of scope
in the original refactoring attempt (line 549).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from aw_export_timewarrior.main import Exporter


def create_aw_event(timestamp, duration, data):
    """Create a mock ActivityWatch event."""
    event = Mock()
    event.timestamp = timestamp
    event.duration = duration
    event.data = data
    event.__getitem__ = lambda self, key: {'timestamp': timestamp, 'duration': duration, 'data': data}[key]
    return event


@pytest.fixture
def mock_aw_client():
    """Mock the ActivityWatch client."""
    with patch('aw_export_timewarrior.main.aw_client.ActivityWatchClient') as mock:
        mock_instance = Mock()
        mock.return_value = mock_instance
        now = datetime.now(UTC)
        mock_instance.get_buckets.return_value = {
            'aw-watcher-window_test': {
                'id': 'aw-watcher-window_test',
                'type': 'window',
                'client': 'aw-watcher-window',
                'hostname': 'test',
                'created': now.isoformat(),
                'last_updated': now.isoformat(),
            },
            'aw-watcher-afk_test': {
                'id': 'aw-watcher-afk_test',
                'type': 'afk',
                'client': 'aw-watcher-afk',
                'hostname': 'test',
                'created': now.isoformat(),
                'last_updated': now.isoformat(),
            },
            'aw-watcher-web-chrome_test': {
                'id': 'aw-watcher-web-chrome_test',
                'type': 'web',
                'client': 'aw-watcher-web-chrome',
                'hostname': 'test',
                'created': now.isoformat(),
                'last_updated': now.isoformat(),
            },
            'aw-watcher-vim_test': {
                'id': 'aw-watcher-vim_test',
                'type': 'editor',
                'client': 'aw-watcher-vim',
                'hostname': 'test',
                'created': now.isoformat(),
                'last_updated': now.isoformat(),
            },
        }
        yield mock


class TestRegexpMatchingBugRegression:
    """Test that would have caught the original regexp_matching scope bug."""

    def test_browser_multiple_rules_first_doesnt_match(self, mock_aw_client: Mock) -> None:
        """
        Test browser matching with multiple rules where first rule doesn't match.

        This would have caught the bug where `rule` was out of scope when
        regexp_matching was called (the `rule` variable was from the wrong loop iteration).
        """
        exporter = Exporter()
        exporter.config = {
            'rules': {
                'browser': {
                    # First rule - won't match
                    'gitlab': {
                        'url_regexp': r'gitlab\.com/([^/]+)/([^/]+)',
                        'timew_tags': ['4work', 'gitlab', '$1']
                    },
                    # Second rule - should match
                    'github': {
                        'url_regexp': r'github\.com/([^/]+)/([^/]+)',
                        'timew_tags': ['4work', 'github', '$1']
                    },
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

        mock_aw_client.return_value.get_events.return_value = [browser_event]

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {
                'app': 'chrome',
                'title': 'GitHub - python-caldav/caldav'
            }
        }

        tags = exporter.get_browser_tags(window_event)

        # If the bug existed, this would fail because `rule` would be
        # from the wrong iteration (gitlab rule instead of github rule)
        assert '4work' in tags
        assert 'github' in tags  # Not 'gitlab'!
        assert 'python-caldav' in tags
        assert 'not-afk' in tags

    def test_editor_multiple_rules_regexp_after_project(self, mock_aw_client: Mock) -> None:
        """
        Test editor matching where regexp rule comes after project rule.

        This tests that the matcher order works correctly and doesn't
        have scope issues when iterating through rules.
        """
        exporter = Exporter()
        exporter.config = {
            'rules': {
                'editor': {
                    # First rule - project based, won't match
                    'work_project': {
                        'projects': ['some-other-project'],
                        'timew_tags': ['4work', 'other-project']
                    },
                    # Second rule - regexp based, should match
                    'config_files': {
                        'path_regexp': r'\.config/([^/]+)/',
                        'timew_tags': ['4me', 'config', '$1']
                    }
                }
            },
            'exclusive': {},
            'tags': {}
        }

        # Mock editor event
        editor_event = create_aw_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=10),
            data={
                'project': 'dotfiles',
                'file': '/home/user/.config/nvim/init.vim',
                'language': 'vim'
            }
        )

        mock_aw_client.return_value.get_events.return_value = [editor_event]

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=10),
            'data': {
                'app': 'vim',
                'title': 'init.vim'
            }
        }

        tags = exporter.get_editor_tags(window_event)

        # Verify it matched the second rule correctly
        assert '4me' in tags
        assert 'config' in tags
        assert 'nvim' in tags  # $1 from path_regexp
        assert 'not-afk' in tags

    def test_multiple_regexp_groups_substitution(self, mock_aw_client: Mock) -> None:
        """
        Test that multiple regex groups ($1, $2) are substituted correctly.

        This ensures the tag building handles all groups, not just the first.
        """
        exporter = Exporter()
        exporter.config = {
            'rules': {
                'browser': {
                    'github_issue': {
                        'url_regexp': r'github\.com/([^/]+)/([^/]+)/issues',
                        'timew_tags': ['4work', 'github', '$1', '$2']
                    }
                }
            },
            'exclusive': {},
            'tags': {}
        }

        browser_event = create_aw_event(
            timestamp=datetime.now(UTC),
            duration=timedelta(minutes=5),
            data={
                'url': 'https://github.com/python-caldav/caldav/issues',
                'title': 'Issues - python-caldav/caldav'
            }
        )

        mock_aw_client.return_value.get_events.return_value = [browser_event]

        window_event = {
            'timestamp': datetime.now(UTC),
            'duration': timedelta(minutes=5),
            'data': {
                'app': 'chrome',
                'title': 'Issues - python-caldav/caldav'
            }
        }

        tags = exporter.get_browser_tags(window_event)

        # Both $1 and $2 should be substituted
        assert '4work' in tags
        assert 'github' in tags
        assert 'python-caldav' in tags  # $1
        assert 'caldav' in tags  # $2
        assert 'not-afk' in tags


class TestBuildTagsEdgeCases:
    """Test edge cases in tag building that could cause bugs."""

    def test_missing_variable_value_skips_tag(self, mock_aw_client: Mock) -> None:
        """Test that tags with variables that have no value are skipped."""
        exporter = Exporter()

        # Build tags where $1 is None
        tags = exporter._build_tags(
            tag_templates=['4work', 'project-$1', 'fixed-tag'],
            substitutions={'$1': None}
        )

        assert 'fixed-tag' in tags
        assert '4work' in tags
        assert 'not-afk' in tags
        # Tag with $1 should be skipped since $1 is None
        assert 'project-$1' not in tags
        assert not any('project-' in tag for tag in tags)

    def test_partial_substitution_skips_tag(self, mock_aw_client: Mock) -> None:
        """Test that tags with unsubstituted variables are skipped."""
        exporter = Exporter()

        # Build tags where we have $1 but the tag uses $2
        tags = exporter._build_tags(
            tag_templates=['4work', 'issue-$1-$2'],
            substitutions={'$1': 'repo'}  # No $2!
        )

        assert '4work' in tags
        assert 'not-afk' in tags
        # Tag should be skipped because $2 wasn't substituted
        assert 'issue-repo-$2' not in tags
        assert not any('issue-' in tag for tag in tags)

    def test_app_variable_substitution(self, mock_aw_client: Mock) -> None:
        """Test that $app variable works correctly in get_app_tags."""
        exporter = Exporter()
        exporter.config = {
            'rules': {
                'app': {
                    'communication': {
                        'app_names': ['Signal', 'Slack'],
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
        assert 'Signal' in tags  # $app substituted
        assert 'not-afk' in tags
