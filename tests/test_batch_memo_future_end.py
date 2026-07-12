"""Regression test for CODE_REVIEW_2026-07-12.md #8.

fetch_and_prepare_events() memoized the whole pipeline preparation whenever
`end_time` was set, on the assumption "end_time set -> underlying data is
immutable". That only holds for a *closed* (past) range. In a bounded live
sync -- `sync --from <past> --to <future>` (continuous, no --once), which
cli.py explicitly supports ("Starting sync until {end_time}") -- end_time is
in the future, so the first-tick snapshot was frozen and served for the whole
run. Heartbeats recorded while the sync ran toward the cutoff were never
fetched, so the loop exhausted the stale snapshot and stopped early.

The memo must only be used for a genuinely past/closed range (end_time <= now).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aw_export_timewarrior.event_pipeline import EventPipeline, EventPipelineConfig


def _pipeline_with_spy(end_time: datetime, last_tick: datetime):
    pipeline = EventPipeline(
        event_fetcher=None,
        pipeline_config=EventPipelineConfig(),
        last_tick=last_tick,
        end_time=end_time,
    )
    calls: list[int] = []

    def fake_run_pipeline():
        calls.append(1)
        return ([], None)

    pipeline._run_pipeline = fake_run_pipeline
    return pipeline, calls


def test_future_end_time_refetches_each_call() -> None:
    """A future end_time is a live range: data can still change, so no memo."""
    now = datetime.now(UTC)
    pipeline, calls = _pipeline_with_spy(
        end_time=now + timedelta(hours=1), last_tick=now - timedelta(minutes=30)
    )

    pipeline.fetch_and_prepare_events()
    pipeline.last_tick = pipeline.last_tick + timedelta(minutes=1)
    pipeline.fetch_and_prepare_events()

    assert len(calls) == 2, (
        "future end_time must re-run the pipeline each call (data still mutable); "
        f"got {len(calls)} pipeline runs -- the stale-snapshot memo was served"
    )


def test_past_end_time_is_memoized() -> None:
    """A closed (past) range is immutable, so the memo must still kick in."""
    now = datetime.now(UTC)
    pipeline, calls = _pipeline_with_spy(
        end_time=now - timedelta(minutes=1), last_tick=now - timedelta(minutes=30)
    )

    pipeline.fetch_and_prepare_events()
    pipeline.last_tick = pipeline.last_tick + timedelta(minutes=1)
    pipeline.fetch_and_prepare_events()

    assert len(calls) == 1, (
        "a past/closed range must be prepared once and served from the memo; "
        f"got {len(calls)} pipeline runs"
    )
