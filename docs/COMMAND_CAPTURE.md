# Command Capture Infrastructure

This document explains how to use the command capture infrastructure for testing that continuous and batch processing produce the same results.

## Overview

The command capture infrastructure allows you to:
1. Run the exporter in dry-run mode
2. Capture what `timew` commands would be executed
3. Compare outputs from different processing modes
4. Verify idempotence (same input → same output)

## Basic Usage

### Capturing Commands

```python
from aw_export_timewarrior.main import Exporter
from tests.helpers import FixtureDataBuilder

# Create test data
data = (FixtureDataBuilder()
    .add_window_event("Code", "main.py", duration=600)
    .add_afk_event("not-afk", duration=600)
    .add_window_event("Chrome", "GitHub", duration=600)
    .add_afk_event("not-afk", duration=600)
    .build())

# Create exporter in dry-run mode
exporter = Exporter(
    test_data=data,
    dry_run=True,  # Critical: enables command capture
    config_path='path/to/config.toml'
)

# Process events
exporter.tick()

# Get captured commands
commands = exporter.get_captured_commands()

# Each command is a list: ['timew', 'start', 'tag1', 'tag2', '2025-01-01T10:00:00']
for cmd in commands:
    print(' '.join(cmd))
```

### Working with Captured Commands

```python
# Get commands
commands = exporter.get_captured_commands()

# Clear commands
exporter.clear_captured_commands()

# Process more events
exporter.tick()

# Get new commands
new_commands = exporter.get_captured_commands()
```

## Testing Continuous vs Batch Processing

The key insight: **continuous mode and batch mode should produce identical commands**.

### Example Test

```python
def test_continuous_equals_batch():
    """Test that continuous and batch modes produce same results."""

    # Create test data for a full day
    data = create_full_day_scenario()

    # --- BATCH MODE ---
    batch_exporter = Exporter(
        test_data=data,
        dry_run=True,
        start_time=datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 1, 17, 0, 0, tzinfo=timezone.utc)
    )

    batch_exporter.tick()
    batch_commands = batch_exporter.get_captured_commands()

    # --- CONTINUOUS MODE ---
    # Simulate processing in smaller chunks
    continuous_commands = []

    # Process every hour
    for hour in range(9, 17):
        chunk_exporter = Exporter(
            test_data=data,
            dry_run=True,
            start_time=datetime(2025, 1, 1, hour, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2025, 1, 1, hour + 1, 0, 0, tzinfo=timezone.utc)
        )
        chunk_exporter.tick()
        continuous_commands.extend(chunk_exporter.get_captured_commands())

    # Compare
    assert normalize_commands(batch_commands) == normalize_commands(continuous_commands)
```

### Command Normalization

Commands might differ slightly in format but be semantically equivalent:

```python
def normalize_commands(commands):
    """Normalize commands for comparison."""
    normalized = []

    for cmd in commands:
        # Extract command type and tags
        cmd_type = cmd[1]  # 'start', 'stop', etc.

        if cmd_type == 'start':
            # Extract tags (everything between 'start' and timestamp)
            tags = set(cmd[2:-1])
            timestamp = cmd[-1]

            # Create normalized representation
            normalized.append({
                'type': cmd_type,
                'tags': tags,
                'timestamp': timestamp
            })

    # Sort for comparison
    normalized.sort(key=lambda x: x['timestamp'])

    return normalized
```

## Command Format

Captured commands have this structure:

```python
[
    'timew',           # Always 'timew'
    'start',           # Command: start, stop, retag, etc.
    'tag1',            # Tags (multiple)
    'tag2',
    'tag3',
    '2025-01-01T10:00:00'  # Timestamp (ISO format)
]
```

For `retag` commands:

```python
[
    'timew',
    'retag',
    'new_tag1',
    'new_tag2'
]
```

## Integration with Existing Tests

### In pytest

```python
def test_my_scenario():
    data = load_test_data('tests/fixtures/my_scenario.json')

    exporter = Exporter(
        test_data=data,
        dry_run=True,
        config_path='tests/fixtures/test_config.toml'
    )

    exporter.tick()
    commands = exporter.get_captured_commands()

    # Assert expected behavior
    assert len(commands) == 2
    assert commands[0][1] == 'start'
    assert 'coding' in commands[0]
    assert 'python' in commands[0]
```

### Fixtures with Expected Commands

```json
{
  "description": "Simple coding session",
  "events": { /* ... */ },
  "expected_commands": [
    ["timew", "start", "coding", "python", "not-afk", "2025-01-01T09:00:00"]
  ]
}
```

Then test against them:

```python
def test_fixture_with_expected_commands():
    data = load_test_data('tests/fixtures/with_expected.json')

    exporter = Exporter(test_data=data, dry_run=True, ...)
    exporter.tick()

    actual = exporter.get_captured_commands()
    expected = data['expected_commands']

    assert actual == expected
```

## Debugging with Command Capture

```python
def debug_processing():
    """Use command capture to debug what's happening."""

    data = load_problem_data()

    exporter = Exporter(
        test_data=data,
        dry_run=True,
        verbose=True  # See detailed logging
    )

    exporter.tick()

    print("\nCommands that would be executed:")
    for cmd in exporter.get_captured_commands():
        print(f"  {' '.join(cmd)}")

    # Inspect state
    print(f"\nLast tick: {exporter.last_tick}")
    print(f"Last known tick: {exporter.last_known_tick}")
    print(f"Accumulated tags: {exporter.tags_accumulated_time}")
```

## Important Notes

1. **Dry-run required**: Commands are only captured when `dry_run=True`
2. **Persistence**: Captured commands accumulate across multiple `tick()` calls
3. **Clearing**: Use `clear_captured_commands()` to reset between tests
4. **Format**: Commands are lists of strings, not space-separated strings
5. **No execution**: In dry-run mode with test_data, no actual timew commands run

## See Also

- `tests/test_command_capture.py` - Example tests
- `tests/helpers.py` - FixtureDataBuilder for creating fixtures
- `TESTING.md` - General testing documentation
