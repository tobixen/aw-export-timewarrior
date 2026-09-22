"""Failed writes to timew must show up in the exit code.

`timeføring` decides from the exit code alone whether the day's import went
through, and offers to move the watermark if it did.  A failure that is only
printed is a failure it cannot see.
"""

import argparse
import json
from pathlib import Path
from unittest import mock

from aw_export_timewarrior import retag
from aw_export_timewarrior.cli import create_exporter_from_args, run_diff

FIXTURES = Path(__file__).parent / "fixtures"


def make_exporter():
    args = argparse.Namespace(
        day=None,
        start="2025-01-01T00:00:00",
        end="2025-01-01T01:00:00",
        test_data=FIXTURES / "sample_15min.json",
        apply=True,
        show_commands=True,
        timeline=False,
        hide_report=False,
        config=FIXTURES / "test_config.toml",
        verbose=False,
        enable_pdb=False,
        enable_assert=True,
    )
    return create_exporter_from_args(
        args, "diff", dry_run=True, show_diff=True, show_fix_commands=True
    )


class TestApplyFixCommands:
    def test_single_command_reports_its_outcome(self) -> None:
        exporter = make_exporter()
        assert exporter._apply_single_fix_command("true") is True
        assert exporter._apply_single_fix_command("false") is False
        assert exporter._apply_single_fix_command("# manual entry") is True
        assert exporter._apply_single_fix_command("") is True

    def test_failures_are_counted_and_the_rest_still_run(self) -> None:
        exporter = make_exporter()
        with (
            mock.patch(
                "aw_export_timewarrior.compare.generate_fix_commands",
                return_value=["false", "true", "false"],
            ),
            mock.patch.object(
                exporter, "_apply_single_fix_command", wraps=exporter._apply_single_fix_command
            ) as spy,
        ):
            exporter._handle_fix_commands({})
        assert spy.call_count == 3
        assert exporter.failed_fix_commands == 2

    def test_run_diff_exits_nonzero_on_failed_fixes(self) -> None:
        fake = mock.Mock(failed_fix_commands=1)
        with mock.patch("aw_export_timewarrior.cli.create_exporter_from_args", return_value=fake):
            assert run_diff(argparse.Namespace(show_commands=True, apply=True)) == 1

    def test_run_diff_exits_zero_when_all_fixes_apply(self) -> None:
        fake = mock.Mock(failed_fix_commands=0)
        with mock.patch("aw_export_timewarrior.cli.create_exporter_from_args", return_value=fake):
            assert run_diff(argparse.Namespace(show_commands=True, apply=True)) == 0


class TestRetagScript:
    def run(self, tags_by_id: dict[int, list[str]], rules) -> tuple[int, mock.Mock]:
        def fake_get(argv):
            i = int(argv[2].split(".")[2])
            return json.dumps({"tags": tags_by_id[i]}).encode()

        tracker = mock.Mock()
        with (
            mock.patch.object(retag.subprocess, "check_output", side_effect=fake_get),
            mock.patch.object(retag, "TimewTracker", return_value=tracker),
            mock.patch.object(retag, "retag_by_rules", side_effect=rules),
        ):
            code = retag.main(start=1, stop=1 + len(tags_by_id))
        return code, tracker

    def test_clean_run_exits_zero(self) -> None:
        code, tracker = self.run({1: ["a"], 2: ["b"]}, lambda tags: tags | {"x"})
        assert code == 0
        assert tracker.retag_interval_by_id.call_count == 2

    def test_rule_error_exits_nonzero_but_finishes_the_range(self) -> None:
        def rules(tags):
            if "bad" in tags:
                raise ValueError("broken rule")
            return tags | {"x"}

        code, tracker = self.run({1: ["bad"], 2: ["b"]}, rules)
        assert code == 1
        tracker.retag_interval_by_id.assert_called_once_with(2, {"b", "x"})
