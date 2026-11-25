"""Log file rotation and suppression of repeated warnings."""

import json
import logging
from pathlib import Path

import pytest

from aw_export_timewarrior.output import setup_logging


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in root.handlers:
        handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def _log_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_log_file_is_rotated_and_compressed(tmp_path, restore_logging):
    log_file = tmp_path / "aw-export.json.log"
    setup_logging(json_format=True, log_file=str(log_file), log_max_bytes=2000, log_backup_count=2)
    log = logging.getLogger("aw_export_timewarrior.test")
    for i in range(200):
        log.info("line %d with some padding to fill the file up", i)

    backups = sorted(p.name for p in tmp_path.glob("aw-export.json.log.*"))
    assert backups == ["aw-export.json.log.1.gz", "aw-export.json.log.2.gz"]
    assert log_file.stat().st_size <= 2000


def test_once_key_logs_a_message_only_once(tmp_path, restore_logging):
    log_file = tmp_path / "aw-export.json.log"
    setup_logging(json_format=True, log_file=str(log_file))
    log = logging.getLogger("aw_export_timewarrior.test")
    for _ in range(5):
        log.warning("repeated", extra={"once_key": ("a", 1)})
    log.warning("other key", extra={"once_key": ("a", 2)})
    log.warning("no key")
    log.warning("no key")

    messages = [line["message"] for line in _log_lines(log_file)]
    assert messages == ["repeated", "other key", "no key", "no key"]


def test_unhandled_event_warned_once_per_window(tmp_path, restore_logging):
    from aw_export_timewarrior.tag_extractor import TagExtractor

    log_file = tmp_path / "aw-export.json.log"
    setup_logging(json_format=True, log_file=str(log_file))
    extractor = TagExtractor(config={}, event_fetcher=None)
    window = {"data": {"app": "foot", "title": "x"}}
    other = {"data": {"app": "foot", "title": "y"}}
    for _ in range(3):
        extractor._emit_unhandled("tmux", window, {"data": {"pane": 1}})
    extractor._emit_unhandled("tmux", other, {"data": {"pane": 1}})

    assert [line["message"] for line in _log_lines(log_file)] == [
        "Unhandled tmux event",
        "Unhandled tmux event",
    ]


def test_exclusivity_conflict_warned_once_per_rule_and_tags(tmp_path, restore_logging):
    from aw_export_timewarrior.tag_extractor import TagExtractor

    log_file = tmp_path / "aw-export.json.log"
    setup_logging(json_format=True, log_file=str(log_file))
    config = {
        "exclusive": {"category": {"tags": ["4work", "4OSS"]}},
        "tags": {"oss": {"source_tags": ["caldav"], "add": ["4OSS"]}},
    }
    extractor = TagExtractor(config=config, event_fetcher=None)
    for _ in range(3):
        assert extractor.apply_retag_rules({"caldav", "4work"}) == {"caldav", "4work"}

    assert [line["message"] for line in _log_lines(log_file)] == [
        "Excluding expanding tag rule oss due to exclusivity conflicts"
    ]


def test_once_key_reaches_both_file_and_console(tmp_path, capsys, restore_logging):
    log_file = tmp_path / "aw-export.json.log"
    setup_logging(json_format=True, log_file=str(log_file), console_log_level=logging.WARNING)
    log = logging.getLogger("aw_export_timewarrior.test")
    log.warning("shown everywhere", extra={"once_key": "k"})
    log.warning("shown everywhere", extra={"once_key": "k"})

    assert [line["message"] for line in _log_lines(log_file)] == ["shown everywhere"]
    assert capsys.readouterr().out.count("shown everywhere") == 1


def test_unhashable_once_key_does_not_raise(tmp_path, restore_logging):
    log_file = tmp_path / "aw-export.json.log"
    setup_logging(json_format=True, log_file=str(log_file))
    log = logging.getLogger("aw_export_timewarrior.test")
    log.warning("dict key", extra={"once_key": {"a": 1}})
    log.warning("dict key", extra={"once_key": {"a": 1}})

    assert [line["message"] for line in _log_lines(log_file)] == ["dict key"]
