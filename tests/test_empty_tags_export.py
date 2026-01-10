"""Tests for empty tags in export issue.

When exclusive tag conflicts cause the threshold to be raised so high that
no tags remain, _should_export_accumulator should return False instead of
returning True with an empty tags set.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.aw_export_timewarrior.main import Exporter


@pytest.fixture
def config_with_exclusive_groups(tmp_path: Path) -> Path:
    """Create a config with exclusive tag groups and low thresholds."""
    config_content = """
[tuning]
min_recording_interval = 45
min_tag_recording_interval = 20

[rules.app.work]
app = "work-app"
tags = ["work", "4EMPLOYER"]

[rules.app.personal]
app = "personal-app"
tags = ["personal", "4ME"]

[exclusive.primary_category]
tags = ["4EMPLOYER", "4ME"]
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(config_content)
    return config_file


@pytest.fixture
def test_data_with_mixed_tags():
    """Test data with events that produce conflicting exclusive tags.

    Both exclusive tags (4EMPLOYER and 4ME) accumulate exactly the same time,
    and both above the threshold. This forces the threshold to be raised
    until both are eliminated.
    """
    now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
    return {
        "metadata": {
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(minutes=10)).isoformat(),
        },
        "buckets": {
            "aw-watcher-window_test": {
                "id": "aw-watcher-window_test",
                "type": "currentwindow",
                "client": "aw-watcher-window",
                "hostname": "test",
            },
            "aw-watcher-afk_test": {
                "id": "aw-watcher-afk_test",
                "type": "afkstatus",
                "client": "aw-watcher-afk",
                "hostname": "test",
            },
        },
        "events": {
            "aw-watcher-window_test": [
                # Work activity for 55 seconds (above min_tag_recording_interval of 20)
                {
                    "id": 1,
                    "timestamp": now.isoformat(),
                    "duration": 55.0,
                    "data": {"app": "work-app", "title": "Work"},
                },
                # Personal activity for 55 seconds (same as work - conflict!)
                {
                    "id": 2,
                    "timestamp": (now + timedelta(seconds=55)).isoformat(),
                    "duration": 55.0,
                    "data": {"app": "personal-app", "title": "Personal"},
                },
            ],
            "aw-watcher-afk_test": [
                {
                    "id": 1,
                    "timestamp": now.isoformat(),
                    "duration": 600.0,
                    "data": {"status": "not-afk"},
                },
            ],
        },
    }


class TestEmptyTagsExport:
    """Tests for the empty tags export fix."""

    def test_should_export_accumulator_returns_false_for_equal_exclusive_tags(
        self, config_with_exclusive_groups: Path
    ):
        """Direct test of _should_export_accumulator with equal exclusive tags.

        When two exclusive tags have exactly the same accumulated time,
        raising the threshold to avoid conflicts eliminates both,
        so should_export should return False.
        """
        now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)

        # Minimal test data just to initialize the exporter
        test_data = {
            "metadata": {
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(minutes=5)).isoformat(),
            },
            "buckets": {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "type": "currentwindow",
                    "client": "aw-watcher-window",
                    "hostname": "test",
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "type": "afkstatus",
                    "client": "aw-watcher-afk",
                    "hostname": "test",
                },
            },
            "events": {
                "aw-watcher-window_test": [],
                "aw-watcher-afk_test": [],
            },
        }

        exporter = Exporter(
            dry_run=True,
            test_data=test_data,
            config_path=config_with_exclusive_groups,
        )

        # Manually set up the accumulator state to trigger the bug
        # Both exclusive tags (4EMPLOYER and 4ME) have exactly 55 seconds
        exporter.state.stats.tags_accumulated_time = {
            "4EMPLOYER": timedelta(seconds=55),
            "4ME": timedelta(seconds=55),
            "work": timedelta(seconds=55),
            "personal": timedelta(seconds=55),
        }
        exporter.state.last_known_tick = now

        # Create a dummy event
        dummy_event = {
            "timestamp": now + timedelta(seconds=110),
            "duration": timedelta(seconds=1),
            "data": {"app": "test", "title": "test"},
        }

        # Call _should_export_accumulator with a large enough interval
        # (110 seconds since last tick, well above min_recording_interval of 45)
        interval = timedelta(seconds=110)
        should_export, tags, since, acc_before = exporter._should_export_accumulator(
            interval, dummy_event
        )

        # With the fix, should_export should be False because raising the threshold
        # to avoid the exclusive conflict between 4EMPLOYER and 4ME eliminates both
        assert not should_export, (
            f"Expected should_export=False when all tags eliminated by threshold, "
            f"but got should_export=True with tags={tags}"
        )

    def test_should_export_returns_false_when_tags_empty(
        self, config_with_exclusive_groups: Path, test_data_with_mixed_tags: dict
    ):
        """When exclusive conflicts remove all tags, should_export should be False."""
        exporter = Exporter(
            dry_run=True,
            test_data=test_data_with_mixed_tags,
            config_path=config_with_exclusive_groups,
        )

        # Process events to accumulate tags
        exporter.tick(process_all=True)

        # Get captured commands - if fix works, there should be no export
        # with empty tags
        commands = exporter.get_captured_commands()

        # Check that any 'start' commands have non-empty tags
        for cmd in commands:
            if "start" in cmd:
                # The command format is ['timew', 'start', ...tags..., timestamp]
                # Tags are between 'start' and the timestamp
                tags_in_cmd = [
                    arg for arg in cmd[2:-1] if not arg.startswith("20")
                ]  # Exclude timestamp
                # We should never have a start command with no tags
                assert len(tags_in_cmd) > 0, f"Found start command with no tags: {cmd}"

    def test_accumulator_still_decays_when_no_export(self, config_with_exclusive_groups: Path):
        """Even when not exporting, the accumulator should still decay."""
        now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)

        # Create test data where both exclusive tags accumulate equally
        test_data = {
            "metadata": {
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(minutes=2)).isoformat(),
            },
            "buckets": {
                "aw-watcher-window_test": {
                    "id": "aw-watcher-window_test",
                    "type": "currentwindow",
                    "client": "aw-watcher-window",
                    "hostname": "test",
                },
                "aw-watcher-afk_test": {
                    "id": "aw-watcher-afk_test",
                    "type": "afkstatus",
                    "client": "aw-watcher-afk",
                    "hostname": "test",
                },
            },
            "events": {
                "aw-watcher-window_test": [
                    # Alternating work and personal, equal time each
                    {
                        "id": 1,
                        "timestamp": now.isoformat(),
                        "duration": 25.0,
                        "data": {"app": "work-app", "title": "Work"},
                    },
                    {
                        "id": 2,
                        "timestamp": (now + timedelta(seconds=25)).isoformat(),
                        "duration": 25.0,
                        "data": {"app": "personal-app", "title": "Personal"},
                    },
                    {
                        "id": 3,
                        "timestamp": (now + timedelta(seconds=50)).isoformat(),
                        "duration": 25.0,
                        "data": {"app": "work-app", "title": "Work"},
                    },
                    {
                        "id": 4,
                        "timestamp": (now + timedelta(seconds=75)).isoformat(),
                        "duration": 25.0,
                        "data": {"app": "personal-app", "title": "Personal"},
                    },
                ],
                "aw-watcher-afk_test": [
                    {
                        "id": 1,
                        "timestamp": now.isoformat(),
                        "duration": 120.0,
                        "data": {"status": "not-afk"},
                    },
                ],
            },
        }

        exporter = Exporter(
            dry_run=True,
            test_data=test_data,
            config_path=config_with_exclusive_groups,
        )

        # Process events
        exporter.tick(process_all=True)

        # Accumulator should have decayed values (stickyness applied)
        # even if no export happened
        for tag, duration in exporter.state.stats.tags_accumulated_time.items():
            # Values should be less than original accumulated time
            # due to stickyness factor being applied
            assert duration.total_seconds() < 50, (
                f"Tag {tag} has {duration.total_seconds()}s, expected less due to decay"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
