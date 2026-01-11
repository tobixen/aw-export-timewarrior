"""Debug test to understand lid event processing."""

import logging

from aw_export_timewarrior.main import Exporter
from aw_export_timewarrior.output import setup_logging
from tests.conftest import FixtureDataBuilder


def test_simple_lid_event() -> None:
    """Simple test with just a lid event to debug processing."""
    # Enable detailed logging
    setup_logging(log_level=logging.DEBUG, console_log_level=logging.DEBUG)

    data = (
        FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 600)
        .add_afk_event("not-afk", 600)
        .add_lid_event("closed", 600)
        .build()
    )

    print("\n=== TEST DATA ===")
    print(f"Window events: {len(data['events']['aw-watcher-window_test'])}")
    print(f"AFK events: {len(data['events']['aw-watcher-afk_test'])}")
    print(f"Lid events: {len(data['events']['aw-watcher-lid_test'])}")

    print("\nWindow event:", data["events"]["aw-watcher-window_test"][0])
    print("AFK event:", data["events"]["aw-watcher-afk_test"][0])
    print("Lid event:", data["events"]["aw-watcher-lid_test"][0])

    exporter = Exporter(test_data=data, dry_run=True, enable_assert=False, verbose=True)

    print(f"\nExporter end_time: {exporter.end_time}")
    print(f"Exporter start_time: {exporter.start_time}")
    print(f"Exporter timew_info: {exporter.timew_info}")

    # Monkey-patch check_and_handle_afk_state_change to debug
    original_check_and_handle_afk = exporter.check_and_handle_afk_state_change

    def debug_check_and_handle_afk(tags, event=None):
        print(
            f"\n>>> check_and_handle_afk_state_change called: tags={tags}, event_data={event.get('data') if event else None}"
        )
        result = original_check_and_handle_afk(tags, event)
        print(f">>> check_and_handle_afk_state_change returned: {result}")
        return result

    exporter.check_and_handle_afk_state_change = debug_check_and_handle_afk

    # Monkey-patch ensure_tag_exported to debug
    original_ensure_tag_exported = exporter.ensure_tag_exported

    def debug_ensure_tag_exported(tags, event, since=None):
        print(f"\n>>> ensure_tag_exported called: tags={tags}, event_data={event.get('data')}")
        result = original_ensure_tag_exported(tags, event, since)
        print(f">>> ensure_tag_exported returned: {result}")
        return result

    exporter.ensure_tag_exported = debug_ensure_tag_exported

    # Monkey-patch start_tracking to debug
    original_start_tracking = exporter.tracker.start_tracking

    def debug_start_tracking(tags, start_time):
        print(f"\n>>> start_tracking called: tags={tags}, start_time={start_time}")
        return original_start_tracking(tags, start_time)

    exporter.tracker.start_tracking = debug_start_tracking

    # Fetch events
    completed_events, current_event = exporter._pipeline.fetch_and_prepare_events()

    print("\n=== FETCHED EVENTS ===")
    print(f"Completed events: {len(completed_events)}")
    print(f"Current event: {current_event}")

    for i, event in enumerate(completed_events):
        print(f"\nEvent {i}:")
        print(f"  Timestamp: {event['timestamp']}")
        print(f"  Duration: {event['duration']}")
        print(f"  Data: {event['data']}")

    # Test tag extraction for each event
    print("\n=== TAG EXTRACTION ===")
    for i, event in enumerate(completed_events):
        tag_result = exporter.find_tags_from_event(event)
        print(
            f"Event {i}: tags={tag_result.tags}, result={tag_result.result}, reason={tag_result.reason}"
        )

    # Process events
    exporter.tick(process_all=True)

    commands = exporter.get_captured_commands()
    print("\n=== CAPTURED COMMANDS ===")
    print(f"Total commands: {len(commands)}")
    for i, cmd in enumerate(commands):
        print(f"Command {i}: {cmd}")


if __name__ == "__main__":
    test_simple_lid_event()
