# Test Fixtures

This directory contains test fixtures for aw-export-timewarrior testing and development.

## What are Test Fixtures?

Test fixtures are pre-recorded or hand-crafted ActivityWatch data samples that can be used to:
- Test the exporter without a running ActivityWatch instance
- Reproduce specific bugs or corner cases
- Validate configuration changes safely
- Develop new features

## Using Test Fixtures

### Command Line

Run the exporter with a test fixture in dry-run mode:

```bash
# See what would be tracked
aw-export-timewarrior --dry-run --test-data tests/fixtures/simple_work_session.json --once

# Test with your actual config
aw-export-timewarrior --dry-run --test-data tests/fixtures/simple_work_session.json --config ~/.config/aw-export-timewarrior/config.toml --once
```

### In Unit Tests

```python
from tests.helpers import TestDataBuilder

def test_my_scenario():
    # Option 1: Use the builder
    data = (TestDataBuilder()
        .add_window_event("vscode", "main.py", 600)
        .add_afk_event("not-afk", 600)
        .build())

    # Option 2: Load from file
    from aw_export_timewarrior.export import load_test_data
    data = load_test_data('tests/fixtures/simple_work_session.json')

    # Use the data
    exporter = Exporter(test_data=data, dry_run=True)
    exporter.tick()
```

## Fixture Format

Test fixtures are JSON files with this structure:

```json
{
  "description": "What this fixture tests",
  "metadata": {
    "test_data": true,
    "start_time": "ISO timestamp",
    "end_time": "ISO timestamp"
  },
  "buckets": {
    "bucket-id": {
      "id": "bucket-id",
      "client": "aw-watcher-type",
      "hostname": "test-machine",
      "last_updated": "ISO timestamp"
    }
  },
  "events": {
    "bucket-id": [
      {
        "timestamp": "ISO timestamp",
        "duration": 123.45,
        "data": {
          "app": "application-name",
          "title": "window title"
        }
      }
    ]
  },
  "expected_output": {
    "description": "What should happen",
    "tags": ["expected", "tags"],
    "timew_commands": ["expected commands"]
  }
}
```

## Creating New Fixtures

### Method 1: Export Real Data

```bash
# Export your actual ActivityWatch data
aw-export-timewarrior --export-data my_session.json \
    --start "2025-01-01 09:00" \
    --end "2025-01-01 17:00"

# Optionally anonymize
aw-export-timewarrior --export-data my_session.json \
    --start "2025-01-01 09:00" \
    --end "2025-01-01 17:00" \
    --anonymize
```

Then edit the file to:
- Remove sensitive information
- Simplify to the essential events
- Add `expected_output` section

### Method 2: Use the Builder

```python
from tests.helpers import TestDataBuilder
import json

data = (TestDataBuilder()
    .add_window_event('vscode', 'bug.py', 300)
    .add_afk_event('not-afk', 300)
    .add_browser_event('https://stackoverflow.com/...', 'Stack Overflow', 180)
    .build())

with open('tests/fixtures/debugging_session.json', 'w') as f:
    json.dump(data, f, indent=2)
```

### Method 3: Hand-Write

Copy an existing fixture and modify it. This is useful for creating specific corner cases.

## Available Fixtures

- **simple_work_session.json**: Basic 30-minute work session with coding and docs
- **afk_transition.json**: AFK transition mid-session

## Tips for Good Fixtures

1. **Keep them minimal**: Only include events necessary to demonstrate the scenario
2. **Use realistic timings**: Match actual usage patterns
3. **Document expected behavior**: Add `expected_output` section
4. **Anonymize sensitive data**: No real URLs, file paths, or project names
5. **Use descriptive names**: Fixture filename should describe what it tests
