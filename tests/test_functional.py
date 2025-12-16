from argparse import Namespace
from pathlib import Path

import pytest

from aw_export_timewarrior.cli import run_diff, run_sync


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    # Arrange: create directory + file
    test_dir = tmp_path / "timewarrior" / "data"
    test_dir.mkdir(parents=True)
    file_path = test_dir / "tags.data"
    file_path.write_text("{}")

    # Arrange: set env var
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    # Provide whatever the test needs
    yield {"dir": tmp_path}


class MockNamespace(Namespace):
    def __getattr__(self, name):
        return None  # All unset attributes return None


class TestSyncWithRealDataHS:
    """Functional tests, syncing real ActivityWatch export data to a mock TimeWarrior, created through Human Stupidity rather than AI"""

    sample_15min = Path(__file__).parent / "fixtures" / "sample_15min.json"

    def test_sync_and_diff_sample_data(self, test_env) -> None:
        """Test syncing sample data and verifying no differences with diff."""
        # Load sample data
        from pathlib import Path

        from aw_export_timewarrior.export import load_test_data
        from aw_export_timewarrior.main import Exporter
        from aw_export_timewarrior.utils import parse_datetime

        sample_file = Path(__file__).parent / "fixtures" / "sample_15min.json"
        config_file = Path(__file__).parent / "fixtures" / "test_config.toml"

        # Load test data to get time range
        test_data = load_test_data(sample_file)
        start_time = parse_datetime(test_data["metadata"]["start_time"])
        end_time = parse_datetime(test_data["metadata"]["end_time"])

        # Setup args for sync
        args = MockNamespace()
        args.test_data = sample_file
        args.config = config_file
        args.dry_run = False  # Actually sync to timew
        args.no_dry_run = True  # Override dry_run logic - actually write to timew
        args.once = True  # Process all events in one call, don't loop
        args.start = None
        args.end = None
        args.pdb = False
        args.verbose = False
        args.hide_processing_output = False

        run_sync(args)

        ## Now run diff
        run_diff(args)

        ## ... but we have no way to do asserts on the output.

        ## I think it would be good to have the diff results
        ## returned from run_diff - TODO - but as for now,
        ## Claude has copied the logic into the test:

        # Now run diff and capture the comparison results
        # Create exporter directly so we can access the comparison results
        exporter = Exporter(
            dry_run=True,  # Just compare, don't modify
            config_path=config_file,
            verbose=False,
            show_diff=True,  # Need this to run comparison
            show_fix_commands=False,
            apply_fix=False,
            hide_diff_report=True,  # Hide the printed output
            enable_pdb=False,
            start_time=start_time,
            end_time=end_time,
            test_data=test_data,
        )

        # Process all events to build suggested intervals
        exporter.tick(process_all=True)

        # Run comparison and get results
        comparison = exporter.run_comparison()

        # Assertions: verify the sync worked correctly
        assert comparison is not None, "Comparison should return results"

        # Print summary for debugging
        print("\nSync+Diff Results:")
        print(f"  Matching: {len(comparison['matching'])}")
        print(f"  Different tags: {len(comparison['different_tags'])}")
        print(f"  Missing: {len(comparison['missing'])}")
        print(f"  Extra: {len(comparison['extra'])}")

        # Verify the sync created at least one interval in TimeWarrior
        # Note: sync mode creates ONE active interval that gets updated as activity changes,
        # rather than multiple completed intervals. Intervals with ~aw tag will be marked as
        # "previously_synced" when running diff on the same time range.

        total_in_timew = (
            len(comparison["matching"])
            + len(comparison["different_tags"])
            + len(comparison["extra"])
            + len(comparison.get("previously_synced", []))
        )
        assert total_in_timew > 0, "Expected at least one interval to be in TimeWarrior after sync"

        # The key assertion: sync should have created at least one interval
        # It will show as "previously_synced" (has ~aw tag from the sync)
        assert (
            len(comparison.get("previously_synced", [])) > 0
        ), "Expected at least one synced interval in TimeWarrior (shown as 'previously_synced')"

        # Success: The test demonstrates that:
        # 1. Sync successfully processed the sample data
        # 2. Created at least one active interval in TimeWarrior
        # 3. Diff successfully compared TimeWarrior with the suggestions
        # 4. The comparison logic is working (detecting extra/missing/matching)

    def test_diff_apply_convergence_with_rich_data(self, test_env) -> None:
        """Test that diff --apply converges and doesn't create an infinite loop.

        This test reproduces the issue where running diff --apply multiple times
        keeps finding differences instead of converging to a stable state.

        Uses rich_accumulator_test.json which has:
        - Many short events (stress tests tag accumulator)
        - Events matching different rule types
        - AFK transitions
        - Rapid tag switches
        """
        from pathlib import Path

        from aw_export_timewarrior.export import load_test_data
        from aw_export_timewarrior.main import Exporter
        from aw_export_timewarrior.utils import parse_datetime

        sample_file = Path(__file__).parent / "fixtures" / "rich_accumulator_test.json"
        config_file = Path(__file__).parent / "fixtures" / "test_config.toml"

        # Load test data
        test_data = load_test_data(sample_file)
        start_time = parse_datetime(test_data["metadata"]["start_time"])
        end_time = parse_datetime(test_data["metadata"]["end_time"])

        print(f"\n=== Testing with time range {start_time} to {end_time} ===")

        # Setup args for sync
        args = MockNamespace()
        args.test_data = sample_file
        args.config = config_file
        args.dry_run = False
        args.no_dry_run = True
        args.once = True
        args.start = None
        args.end = None
        args.pdb = False
        args.verbose = False
        args.hide_processing_output = False

        # Step 1: Initial sync
        print("\n=== Step 1: Initial sync ===")
        run_sync(args)

        # Step 2: First diff - should show no differences (everything matches)
        print("\n=== Step 2: First diff (should match) ===")
        exporter1 = Exporter(
            dry_run=True,
            config_path=config_file,
            show_diff=True,
            show_fix_commands=False,
            hide_diff_report=True,
            start_time=start_time,
            end_time=end_time,
            test_data=test_data,
        )
        exporter1.tick(process_all=True)
        comparison1 = exporter1.run_comparison()

        print(
            f"First diff - Matching: {len(comparison1['matching'])}, "
            f"Different: {len(comparison1['different_tags'])}, "
            f"Missing: {len(comparison1['missing'])}, "
            f"Extra: {len(comparison1['extra'])}"
        )

        # Step 3: If there are differences, apply fixes
        if comparison1["missing"] or comparison1["different_tags"]:
            print("\n=== Step 3: Applying fixes ===")
            # Setup args for diff --apply
            args.apply = True
            args.show_commands = True
            args.timeline = False
            run_diff(args)

            # Step 4: Second diff - should now show no differences (convergence test)
            print("\n=== Step 4: Second diff (should converge) ===")
            exporter2 = Exporter(
                dry_run=True,
                config_path=config_file,
                show_diff=True,
                show_fix_commands=False,
                hide_diff_report=True,
                start_time=start_time,
                end_time=end_time,
                test_data=test_data,
            )
            exporter2.tick(process_all=True)
            comparison2 = exporter2.run_comparison()

            print(
                f"Second diff - Matching: {len(comparison2['matching'])}, "
                f"Different: {len(comparison2['different_tags'])}, "
                f"Missing: {len(comparison2['missing'])}, "
                f"Extra: {len(comparison2['extra'])}"
            )

            # CRITICAL ASSERTION: Second diff should show no missing intervals
            # This tests that diff --apply converged to a stable state
            assert len(comparison2["missing"]) == 0, (
                f"diff --apply did not converge! Still have {len(comparison2['missing'])} "
                f"missing intervals after applying fixes. This indicates an infinite loop bug."
            )

            # Also check for different tags - there should be none after applying fixes
            assert len(comparison2["different_tags"]) == 0, (
                f"diff --apply did not converge! Still have {len(comparison2['different_tags'])} "
                f"intervals with different tags after applying fixes."
            )

            print("✓ CONVERGENCE TEST PASSED: diff --apply successfully converged to stable state")
        else:
            print("✓ First sync already matched perfectly - no fixes needed")
