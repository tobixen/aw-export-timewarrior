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
            code = retag.main(range(1, 1 + len(tags_by_id)))
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

    def test_explicit_ids_only_changes_reported_no_sleep(self, capsys) -> None:
        """The morning pass hands over just the hand-edited ids.  Only changes
        are reported, and a batch never waits out the grace period."""
        tags_by_id = {5: ["e24"], 6: ["afk"], 7: ["vg"]}

        def fake_get(argv):
            return json.dumps({"tags": tags_by_id[int(argv[2].split(".")[2])]}).encode()

        def rules(tags):
            return tags | {"~blink"} if tags != {"afk"} else set(tags)

        calls = []
        with (
            mock.patch.object(retag.subprocess, "check_output", side_effect=fake_get),
            mock.patch.object(retag, "retag_by_rules", side_effect=rules),
            mock.patch(
                "aw_export_timewarrior.timew_tracker.subprocess.run",
                side_effect=lambda cmd, **kw: calls.append(cmd) or mock.Mock(returncode=0),
            ),
            mock.patch("time.sleep") as sleep,
            mock.patch.dict("os.environ", {"AW2TW_GRACE_TIME": "10"}),
        ):
            assert retag.main([5, 6]) == 0
            sleep.assert_not_called()
        # :quiet keeps timew's own confirmation off the terminal (verbose=yes)
        assert calls == [["timew", "retag", "@5", "e24", "~blink", ":quiet"]]
        assert capsys.readouterr().out.splitlines() == ["@5: +~blink"]

    def run_with_starts(self, intervals: dict[int, tuple[str, list[str]]], targets):
        def fake_get(argv):
            start, tags = intervals[int(argv[2].split(".")[2])]
            return json.dumps({"start": start, "tags": tags}).encode()

        tracker = mock.Mock()
        with (
            mock.patch.object(retag.subprocess, "check_output", side_effect=fake_get),
            mock.patch.object(retag, "TimewTracker", return_value=tracker),
            mock.patch.object(retag, "retag_by_rules", side_effect=lambda t: t | {"x"}),
        ):
            code = retag.main(targets)
        return code, tracker

    def test_id_with_start_follows_a_shift(self) -> None:
        """Ids are relative: an interval recorded after the caller read them
        pushes the target from @5 to @6.  The start stamp finds it there,
        instead of retagging whatever now sits at @5."""
        intervals = {
            5: ("20260914T223000Z", ["new"]),
            6: ("20260914T120000Z", ["edited"]),
            7: ("20260914T060000Z", ["old"]),
        }
        code, tracker = self.run_with_starts(intervals, [(5, "20260914T120000Z")])
        assert code == 0
        tracker.retag_interval_by_id.assert_called_once_with(6, {"edited", "x"})

    def test_id_with_start_not_found_retags_nothing(self) -> None:
        intervals = {i: (f"20260914T0{i}0000Z", ["t"]) for i in range(5, 12)}
        code, tracker = self.run_with_starts(intervals, [(5, "20260914T120000Z")])
        assert code == 1
        tracker.retag_interval_by_id.assert_not_called()

    def test_parse_targets(self) -> None:
        assert retag.parse_targets(["12", "@13", "14:20260914T120000Z"]) == [
            12,
            13,
            (14, "20260914T120000Z"),
        ]
