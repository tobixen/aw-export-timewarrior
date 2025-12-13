"""
Test that demonstrates the scope bug in the original refactoring.

The bug: In get_subevent_tags, when iterating through regexp_rules,
the code calls self.regexp_matching(rule, ...) but 'rule' is from
a different loop (the one iterating through config rules at line 541).

This test will FAIL with the buggy code and PASS with the fix.
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
    with patch('aw_export_timewarrior.main.aw_client.ActivityWatchClient') as mock, \
         patch('aw_export_timewarrior.aw_client.ActivityWatchClient') as mock_aw_class:
        mock_instance = Mock()
        mock.return_value = mock_instance
        mock_aw_class.return_value = mock_instance
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


def test_browser_scope_bug_multiple_rules(mock_aw_client: Mock) -> None:
    """
    This test demonstrates the scope bug.

    With the buggy code:
    - Line 541: for rule_name in self.config.get('rules', {}).get(subtype, {}):
    - Line 542:     rule = self.config['rules'][subtype][rule_name]
    - Line 548: for (rule_name, key) in regexp_rules:
    - Line 549:     tags = self.regexp_matching(rule, sub_event, rule_name, key)

    The problem: 'rule' at line 549 refers to the LAST iteration from the loop
    at lines 541-547, which is the 'projects_rule' in this test (which doesn't
    have url_regexp). So regexp_matching gets the wrong rule!

    This will cause the test to fail because:
    1. First loop iteration (projects_rule) - no 'projects' key, so doesn't match
    2. After loop, 'rule' still points to 'projects_rule'
    3. Second loop (regexp_rules) calls regexp_matching(projects_rule, ...)
    4. projects_rule doesn't have 'url_regexp', so it returns None
    5. Test fails because no tags are returned

    With the fix, 'rule' is properly scoped inside each iteration.
    """
    exporter = Exporter()
    exporter.config = {
        'rules': {
            'browser': {
                # First rule - has projects but no url_regexp (won't match)
                'projects_rule': {
                    'projects': ['some-other-project'],
                    'timew_tags': ['4work', 'wrong-tags']
                },
                # Second rule - has url_regexp (should match)
                'github': {
                    'url_regexp': r'github\.com/([^/]+)/([^/]+)',
                    'timew_tags': ['4work', 'github', '$1']
                }
            }
        },
        'exclusive': {},
        'tags': {}
    }

    # Mock browser event that should match the github rule
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

    # With the bug: tags will be [] because regexp_matching gets the wrong rule
    # With the fix: tags will contain the github tags
    assert tags != [], "Bug detected: No tags returned! The 'rule' variable is out of scope."
    assert '4work' in tags, "Should have matched the github rule"
    assert 'github' in tags, "Should have matched the github rule"
    assert 'python-caldav' in tags, "Should have extracted $1 from regex"
    assert 'not-afk' in tags


def test_editor_scope_bug_projects_then_regexp(mock_aw_client: Mock) -> None:
    """
    Similar test for editors - projects rule comes before path_regexp rule.

    The bug manifests when:
    1. First rule has 'projects' key
    2. Second rule has 'path_regexp' key
    3. The path_regexp matching should work, but gets the wrong rule
    """
    exporter = Exporter()
    exporter.config = {
        'rules': {
            'editor': {
                # First rule - projects only (won't match)
                'work_projects': {
                    'projects': ['work-project', 'client-project'],
                    'timew_tags': ['4work', 'wrong-tags']
                },
                # Second rule - path_regexp (should match)
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
            'project': 'dotfiles',  # Doesn't match work_projects
            'file': '/home/user/.config/nvim/init.vim',  # Should match path_regexp
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

    # With the bug: tags will be [] because regexp_matching gets work_projects rule
    # (which doesn't have path_regexp)
    # With the fix: tags will contain the config tags
    assert tags != [], "Bug detected: No tags returned! The 'rule' variable is out of scope."
    assert '4me' in tags, "Should have matched the config_files rule"
    assert 'config' in tags, "Should have matched the config_files rule"
    assert 'nvim' in tags, "Should have extracted $1 from path_regexp"
    assert 'not-afk' in tags
