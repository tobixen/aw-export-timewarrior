"""Test that sync mode and diff mode produce equivalent intervals.

Invariant: running sync on a time window, then running diff on the same
window, should show no differences.

Limitation: true end_time=None sync mode cannot be driven purely from
static test data, because the "current event" logic keeps find_next_activity()
returning True indefinitely (see main.py tick()).  The test therefore runs
both modes with end_time inferred from the test-data metadata (which is what
`sync --once` does in practice).  The meaningful difference under test is
tick()-one-at-a-time (the continuous sync outer loop) vs tick(process_all=True)
(batch / diff processing): both must converge to the same intervals.

True continuous-sync vs diff equivalence (with a real TimeWarrior installation)
is covered by tests/test_functional.py::TestSyncWithRealDataHS.
"""

from pathlib import Path

from aw_export_timewarrior.compare import SuggestedInterval, TimewInterval, compare_intervals
from aw_export_timewarrior.main import Exporter
from tests.conftest import FixtureDataBuilder

CONFIG_FILE = Path(__file__).parent / "fixtures" / "test_config.toml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_sync_style(test_data: dict) -> list[SuggestedInterval]:
    """Simulate the continuous-sync outer loop: call tick() one at a time.

    end_time is inferred automatically from the test-data metadata, so the
    loop terminates when all events in the fixture have been consumed.
    """
    exporter = Exporter(
        dry_run=True,
        test_data=test_data,
        config_path=CONFIG_FILE,
        captured_commands=[],
    )
    for _ in range(1000):  # safety upper bound; normal runs take <20 iterations
        if not exporter.tick():
            break
    return exporter.get_suggested_intervals()


def _run_diff_style(test_data: dict) -> list[SuggestedInterval]:
    """Simulate diff mode: process all events in one tick(process_all=True) call."""
    exporter = Exporter(
        dry_run=True,
        test_data=test_data,
        config_path=CONFIG_FILE,
        captured_commands=[],
    )
    exporter.tick(process_all=True)
    return exporter.get_suggested_intervals()


def _suggested_to_timew(intervals: list[SuggestedInterval]) -> list[TimewInterval]:
    """Convert SuggestedInterval list → TimewInterval list for compare_intervals()."""
    return [
        TimewInterval(id=i, start=s.start, end=s.end, tags=s.tags) for i, s in enumerate(intervals)
    ]


def _assert_no_differences(sync_intervals: list, diff_intervals: list) -> None:
    """Assert sync and diff agree: no missing, extra, tag-mismatches, or orphaned intervals."""
    # Treat sync output as the simulated TimeWarrior state; diff output as suggestions.
    timew_like = _suggested_to_timew(sync_intervals)
    cmp = compare_intervals(timew_like, diff_intervals)

    def _fmt(items) -> str:
        return "\n  ".join(str(i) for i in items)

    assert cmp["missing"] == [], (
        f"Diff found intervals missing from sync output:\n  {_fmt(cmp['missing'])}"
    )
    assert cmp["extra"] == [], (
        f"Sync created extra intervals not suggested by diff:\n  {_fmt(cmp['extra'])}"
    )
    assert cmp["different_tags"] == [], "Tag mismatches between sync and diff:\n  " + "\n  ".join(
        f"timew={tw}  suggested={sg}" for tw, sg in cmp["different_tags"]
    )
    assert cmp["previously_synced"] == [], (
        f"Sync created intervals not accounted for by diff:\n  {_fmt(cmp['previously_synced'])}"
    )


def _assert_sync_diff_equivalent(test_data: dict) -> None:
    """Run both modes on the same test data and assert they agree."""
    sync = _run_sync_style(test_data)
    diff = _run_diff_style(test_data)
    _assert_no_differences(sync, diff)


# ---------------------------------------------------------------------------
# Fixtures / scenario builders
# ---------------------------------------------------------------------------


def _simple_coding_session() -> dict:
    """Single uninterrupted active window, no AFK transition."""
    return (
        FixtureDataBuilder()
        .add_window_event("Code", "main.py - VS Code", 600)
        .add_afk_event("not-afk", 600)
        .build()
    )


def _afk_sandwich() -> dict:
    """Active work → AFK break → active work."""
    builder = FixtureDataBuilder()
    # 5 min active
    builder.add_window_event("Code", "main.py - VS Code", 300)
    builder.add_afk_event("not-afk", 300)
    # 5 min AFK
    builder.add_window_event("Code", "screen locked", 300)
    builder.add_afk_event("afk", 300)  # starts at last_window_event_start = T+300
    # 5 min active again
    builder.add_window_event("Code", "main.py - VS Code", 300)
    builder.add_afk_event("not-afk", 300)
    return builder.build()


def _multiple_activity_switches() -> dict:
    """Several alternating activities to exercise the tag accumulator."""
    builder = FixtureDataBuilder()
    for _ in range(3):
        # 5 min coding
        builder.add_window_event("Code", "main.py - VS Code", 300)
        builder.add_afk_event("not-afk", 300)
        # 5 min browsing (no matching rule in test_config → UNKNOWN)
        builder.add_window_event("chromium", "Hacker News - Chromium", 300)
        builder.add_afk_event("not-afk", 300)
    return builder.build()


def _long_afk_then_work() -> dict:
    """Brief activity → long AFK (> max_mixed_interval) → activity."""
    builder = FixtureDataBuilder()
    # 5 min active
    builder.add_window_event("Code", "main.py - VS Code", 300)
    builder.add_afk_event("not-afk", 300)
    # 10 min AFK (> max_mixed_interval default of 240 s)
    builder.add_window_event("Code", "screen saver", 600)
    builder.add_afk_event("afk", 600)
    # 5 min active
    builder.add_window_event("Code", "main.py - VS Code", 300)
    builder.add_afk_event("not-afk", 300)
    return builder.build()


def _consecutive_afk_blocks() -> dict:
    """Multiple back-to-back AFK periods stress-tests AFK state machine."""
    builder = FixtureDataBuilder()
    for _ in range(3):
        # Brief activity
        builder.add_window_event("Code", "main.py - VS Code", 300)
        builder.add_afk_event("not-afk", 300)
        # AFK block
        builder.add_window_event("Code", "screensaver", 300)
        builder.add_afk_event("afk", 300)
    # Final activity block to close out
    builder.add_window_event("Code", "main.py - VS Code", 300)
    builder.add_afk_event("not-afk", 300)
    return builder.build()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSyncDiffEquivalence:
    """Sync and diff modes must produce equivalent intervals for every scenario."""

    def test_simple_coding_session(self) -> None:
        _assert_sync_diff_equivalent(_simple_coding_session())

    def test_afk_sandwich(self) -> None:
        """AFK transition causes find_next_activity() to return early; the next
        tick() call must pick up exactly where it left off."""
        _assert_sync_diff_equivalent(_afk_sandwich())

    def test_multiple_activity_switches(self) -> None:
        _assert_sync_diff_equivalent(_multiple_activity_switches())

    def test_long_afk_then_work(self) -> None:
        _assert_sync_diff_equivalent(_long_afk_then_work())

    def test_consecutive_afk_blocks(self) -> None:
        _assert_sync_diff_equivalent(_consecutive_afk_blocks())

    def test_from_existing_sample_fixture(self) -> None:
        """Use the 15-minute sample fixture to cover realistic event patterns."""
        from pathlib import Path

        from aw_export_timewarrior.export import load_test_data

        sample = Path(__file__).parent / "fixtures" / "sample_15min.json"
        test_data = load_test_data(sample)
        _assert_sync_diff_equivalent(test_data)
