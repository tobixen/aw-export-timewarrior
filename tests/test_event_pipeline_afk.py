"""Regression tests for EventPipeline._merge_consecutive_afk_events (CODE_REVIEW_2026-07.md #5)."""

from datetime import UTC, datetime, timedelta

from aw_export_timewarrior.event_pipeline import EventPipeline, EventPipelineConfig


def make_pipeline() -> EventPipeline:
    return EventPipeline(event_fetcher=None, pipeline_config=EventPipelineConfig())


def afk_event(start: datetime, duration: timedelta, status: str = "afk") -> dict:
    return {"timestamp": start, "duration": duration, "data": {"status": status}}


class TestMergeConsecutiveAfkEvents:
    def test_contained_heartbeat_does_not_shrink_merged_event(self) -> None:
        """A same-status event nested inside a longer one must not rewind the merged end.

        Reproduces CODE_REVIEW_2026-07.md #5: AFK event [09:00, +60min] followed
        (sorted by start) by a contained heartbeat [09:10, +5min] previously
        rewound the merged event's end from 10:00 to 09:15, losing the
        09:15-10:00 AFK tail.
        """
        pipeline = make_pipeline()
        base = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

        events = [
            afk_event(base, timedelta(minutes=60)),  # [09:00, 10:00]
            afk_event(base + timedelta(minutes=10), timedelta(minutes=5)),  # [09:10, 09:15]
        ]

        merged = pipeline._merge_consecutive_afk_events(events)

        assert len(merged) == 1
        end = merged[0]["timestamp"] + merged[0]["duration"]
        assert end == base + timedelta(minutes=60), (
            f"Expected merged event to end at 10:00, got {end}"
        )


class TestApplyAfkGapWorkaround:
    def test_nested_event_does_not_manufacture_false_gap(self) -> None:
        """A short event nested inside a longer one must not reset the gap-tracking end.

        Reproduces CODE_REVIEW_2026-07.md #9: not-afk [10:00, +100min] (ends
        11:40) contains a heartbeat [10:10, +10s] (ends 10:10:10). The next
        event starts at 11:45. Measuring the gap from the heartbeat's end
        (10:10:10) instead of the true max end so far (11:40) manufactures a
        ~95min synthetic AFK event that swallows genuinely active time; the
        real gap is only 5 minutes (11:40-11:45).
        """
        pipeline = make_pipeline()
        base = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)

        events = [
            afk_event(base, timedelta(minutes=100), status="not-afk"),  # [10:00, 11:40]
            afk_event(
                base + timedelta(minutes=10), timedelta(seconds=10), status="not-afk"
            ),  # [10:10, 10:10:10]
            afk_event(base + timedelta(minutes=105), timedelta(minutes=5)),  # starts 11:45
        ]

        result = pipeline._apply_afk_gap_workaround(events)
        synthetic = [e for e in result if e not in events]

        assert len(synthetic) == 1, f"Expected exactly one synthetic gap event, got: {synthetic}"
        gap_start = synthetic[0]["timestamp"]
        gap_end = gap_start + synthetic[0]["duration"]
        assert gap_start == base + timedelta(minutes=100), (
            f"Expected synthetic gap to start at 11:40 (true max end), got {gap_start}"
        )
        assert gap_end == base + timedelta(minutes=105)
