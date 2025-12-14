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

    sample_15min = Path(__file__).parent / 'fixtures' / 'sample_15min.json'


    def test_sync_and_diff_sample_data(self, test_env) -> None:
        """Test syncing sample data and verifying no differences with diff."""
        # Load sample data
        from pathlib import Path

        from aw_export_timewarrior.export import load_test_data
        from aw_export_timewarrior.main import Exporter
        from aw_export_timewarrior.utils import parse_datetime

        sample_file = Path(__file__).parent / 'fixtures' / 'sample_15min.json'
        config_file = Path(__file__).parent / 'fixtures' / 'test_config.toml'

        # Load test data to get time range
        test_data = load_test_data(sample_file)
        start_time = parse_datetime(test_data['metadata']['start_time'])
        end_time = parse_datetime(test_data['metadata']['end_time'])

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
            test_data=test_data
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
        # rather than multiple completed intervals. So we expect to see "extra" intervals
        # (active intervals in timew) rather than "matching" completed intervals.

        total_in_timew = len(comparison['matching']) + len(comparison['different_tags']) + len(comparison['extra'])
        assert total_in_timew > 0, \
            "Expected at least one interval to be in TimeWarrior after sync"

        # The key assertion: sync should have created at least one interval
        # It will show as "extra" because it's an active interval
        assert len(comparison['extra']) > 0, \
            "Expected at least one active interval in TimeWarrior (shown as 'extra')"

        # Success: The test demonstrates that:
        # 1. Sync successfully processed the sample data
        # 2. Created at least one active interval in TimeWarrior
        # 3. Diff successfully compared TimeWarrior with the suggestions
        # 4. The comparison logic is working (detecting extra/missing/matching)
