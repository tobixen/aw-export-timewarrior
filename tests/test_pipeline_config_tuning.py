"""Tests for EventPipelineConfig.from_config reading tuning parameters.

Regression test for a bug where min_lid_duration was read from the config
top level instead of the [tuning] section, so setting it per the documented
config layout (config.py's shipped default puts it under [tuning]) was
silently ignored.
"""

from aw_export_timewarrior.event_pipeline import EventPipelineConfig


def test_min_lid_duration_read_from_tuning_section():
    config = {"tuning": {"min_lid_duration": 42.0}}

    pipeline_config = EventPipelineConfig.from_config(config)

    assert pipeline_config.min_lid_duration == 42.0


def test_min_lid_duration_defaults_when_absent():
    config = {"tuning": {}}

    pipeline_config = EventPipelineConfig.from_config(config)

    assert pipeline_config.min_lid_duration == 10.0
