"""Regression test: tz-less test-data metadata must yield aware start/end times.

Exporter.__post_init__ derives start_time/end_time from test-data metadata when
they aren't passed explicitly. It must normalize those strings to timezone-aware
datetimes (via parse_datetime), because EventPipeline.fetch_and_prepare_events
now compares end_time against datetime.now(UTC). A naive end_time would raise
`TypeError: can't compare offset-naive and offset-aware datetimes`.
"""

from datetime import datetime, timedelta

from .conftest import FixtureDataBuilder


def _naive_metadata_test_data() -> dict:
    """Build valid test data, then strip the tz offset from its metadata times."""
    start_time = datetime(2025, 1, 1, 9, 0, 0)  # naive on purpose
    builder = FixtureDataBuilder(start_time=start_time.astimezone())
    builder.add_afk_event("not-afk", duration=300)
    data = builder.build()

    # Rewrite the metadata timestamps to a tz-less ISO string, as a hand-written
    # or older export could contain.
    data["metadata"]["start_time"] = "2025-01-01T09:00:00"
    data["metadata"]["end_time"] = "2025-01-01T09:05:00"
    return data


def test_naive_metadata_times_are_normalized_to_aware() -> None:
    from aw_export_timewarrior.main import Exporter

    exporter = Exporter(
        dry_run=True,
        test_data=_naive_metadata_test_data(),
        config={"exclusive": {}, "tags": {}, "rules": {}, "terminal_apps": []},
        enable_assert=False,
    )

    assert exporter.start_time is not None
    assert exporter.end_time is not None
    # The crux: both must be timezone-aware so the batch-memo gate's
    # `end_time <= datetime.now(UTC)` comparison doesn't raise.
    assert exporter.start_time.tzinfo is not None
    assert exporter.end_time.tzinfo is not None

    # And the comparison the pipeline actually performs must not raise.
    from datetime import UTC

    assert exporter.end_time <= datetime.now(UTC) + timedelta(days=1)
