# Testing Framework Guide

This document explains the testing and dry-run framework for aw-export-timewarrior.

## Overview

The testing framework provides three key capabilities:

1. **Dry-run mode**: See what would be tracked without modifying timewarrior
2. **Test data export**: Record real ActivityWatch data for analysis and testing
3. **Test fixtures**: Hand-crafted or exported data for reproducible testing

## Dry-Run Mode

Dry-run mode shows you what the exporter would do without actually running timewarrior commands.

### Basic Usage

```bash
# See what would be tracked with your current config (process once)
aw-export-timewarrior sync --dry-run --once

# Continuous dry-run (Ctrl+C to stop)
aw-export-timewarrior sync --dry-run
```

### With Test Data

```bash
# Test a specific scenario
aw-export-timewarrior sync --dry-run --test-data tests/fixtures/simple_work_session.json --once

# Test with a different config
aw-export-timewarrior sync --dry-run --config my_test_config.toml --test-data tests/fixtures/afk_transition.json --once
```

### Output Example

```
=== DRY RUN MODE ===
No changes will be made to timewarrior

DRY RUN: Would execute: timew start 4work coding python 2025-01-01T09:00:00
DRY RUN: Would execute: timew retag 4work coding python docs
```

## Exporting ActivityWatch Data

Export real ActivityWatch data for analysis or creating test fixtures.

### Basic Export

```bash
# Export data for a time range
aw-export-timewarrior export \
    --from "2025-01-01 09:00" \
    --to "2025-01-01 17:00" \
    -o my_data.json
```

### Date/Time Formats Supported

```bash
# ISO format
--from "2025-01-01T09:00:00Z"

# Simple format
--from "2025-01-01 09:00"

# Relative (requires dateutil)
--from "2 hours ago"
--from "yesterday 9am"
```

### Anonymize Sensitive Data

```bash
# Replace URLs, titles, and file paths with placeholders
aw-export-timewarrior export \
    --from "today 9am" \
    --to "now" \
    --anonymize \
    -o anon_data.json
```

### Export Formats

```bash
# JSON (default)
aw-export-timewarrior export --from "..." --to "..." -o data.json

# YAML (requires PyYAML)
aw-export-timewarrior export --from "..." --to "..." -o data.yaml
```

## Test Fixtures

Test fixtures are JSON/YAML files containing ActivityWatch data.

### Using Fixtures in Development

```bash
# Test how your config handles a specific scenario
aw-export-timewarrior sync --dry-run --test-data tests/fixtures/simple_work_session.json --once

# See verbose reasoning
aw-export-timewarrior sync --dry-run --test-data tests/fixtures/afk_transition.json --verbose --once
```

### Creating Fixtures

#### Method 1: Export and Edit

1. Export real data:
   ```bash
   aw-export-timewarrior export --from "..." --to "..." -o raw.json
   ```

2. Edit the file:
   - Remove sensitive information
   - Simplify to essential events
   - Add expected output documentation

3. Save to `tests/fixtures/my_scenario.json`

#### Method 2: Use the Builder API

```python
from tests.conftest import FixtureDataBuilder
import json

# Build a test scenario
data = (FixtureDataBuilder()
    .add_window_event("vscode", "main.py", duration=600)
    .add_afk_event("not-afk", duration=600)
    .add_browser_event("https://github.com/user/repo", "GitHub", duration=300)
    .build())

# Save as fixture
with open('tests/fixtures/my_scenario.json', 'w') as f:
    json.dump(data, f, indent=2)
```

#### Method 3: Hand-Write JSON

Copy an existing fixture and modify it. See `tests/fixtures/README.md` for format details.

## Unit Testing

### Basic Test with Exporter

```python
from aw_export_timewarrior.main import Exporter
from tests.conftest import FixtureDataBuilder

def test_work_session_tagging():
    # Create test data
    data = (FixtureDataBuilder()
        .add_window_event("vscode", "main.py", 600)
        .add_afk_event("not-afk", 600)
        .build())

    # Create exporter with test data
    exporter = Exporter(test_data=data, dry_run=True, verbose=True)

    # Run one tick
    exporter.tick()

    # Assert expected behavior
    # (add your assertions here)
```

### Loading Fixture Files

```python
from aw_export_timewarrior.export import load_test_data
from aw_export_timewarrior.main import Exporter

def test_with_fixture():
    # Load fixture
    data = load_test_data('tests/fixtures/simple_work_session.json')

    # Use in test
    exporter = Exporter(test_data=data, dry_run=True)
    exporter.tick()
```

## CLI Reference

### Subcommands

```
aw-export-timewarrior <subcommand> [OPTIONS]

Subcommands:
  sync        Synchronize ActivityWatch to TimeWarrior (default)
  diff        Compare TimeWarrior with ActivityWatch and optionally fix
  analyze     Analyze events and show unmatched activities
  export      Export ActivityWatch data to file
  validate    Validate configuration file
```

### Common Options

```
--config FILE             Use custom configuration file
--verbose, -v             Show detailed reasoning and decisions
```

### Sync Options

```
aw-export-timewarrior sync [OPTIONS]

--dry-run                 Show what would be done without modifying timewarrior
--once                    Process once and exit (default: continuous)
--test-data FILE          Use test data from file instead of ActivityWatch
--from/--to DATETIME      Time range to process
```

### Export Options

```
aw-export-timewarrior export [OPTIONS]

--from DATETIME           Start time for export
--to DATETIME             End time for export
-o/--output FILE          Output file path (required)
--anonymize               Replace sensitive data with placeholders
```

### Examples

```bash
# Normal operation (continuous sync)
aw-export-timewarrior
aw-export-timewarrior sync

# Dry run with current live data
aw-export-timewarrior sync --dry-run --once

# Test a config change
aw-export-timewarrior sync --dry-run --config new_config.toml --once

# Test with recorded data
aw-export-timewarrior sync --dry-run --test-data yesterday.json --once

# Export data for debugging
aw-export-timewarrior export --from "1 hour ago" --to "now" -o debug.json

# Validate configuration
aw-export-timewarrior validate

# Compare with TimeWarrior
aw-export-timewarrior diff --from yesterday

# Analyze unmatched events
aw-export-timewarrior analyze --from yesterday
```

## Common Workflows

### Testing a New Tag Rule

1. Create or modify your config
2. Test with existing fixture:
   ```bash
   aw-export-timewarrior sync --dry-run --config my_config.toml --test-data tests/fixtures/simple_work_session.json --once
   ```
3. If it looks good, test with real data:
   ```bash
   aw-export-timewarrior sync --dry-run --config my_config.toml --once
   ```
4. When confident, enable for real:
   ```bash
   aw-export-timewarrior sync --config my_config.toml
   ```

### Debugging a Tracking Issue

1. Export the problematic time period:
   ```bash
   aw-export-timewarrior export --from "when it failed" --to "now" -o issue.json
   ```

2. Examine the data:
   ```bash
   cat issue.json | jq .
   ```

3. Create a minimal fixture reproducing the issue

4. Test fixes with the fixture:
   ```bash
   aw-export-timewarrior sync --dry-run --test-data issue_minimal.json --verbose --once
   ```

### Creating Regression Tests

1. Export data from when bug occurred:
   ```bash
   aw-export-timewarrior export --from "..." --to "..." -o regression_case.json
   ```

2. Simplify to minimal reproducer

3. Add to test suite:
   ```python
   def test_regression_issue_123():
       data = load_test_data('tests/fixtures/regression_issue_123.json')
       exporter = Exporter(test_data=data, dry_run=True)
       # Test that the fix works
   ```

## Tips and Best Practices

### Dry-Run Mode

- **Use --once for quick tests**: Prevents infinite loop in dry-run
- **Combine with --verbose**: See detailed reasoning
- **Test before enabling**: Always dry-run new configs

### Test Data

- **Keep fixtures minimal**: Only include events needed to demonstrate behavior
- **Document expected output**: Add expectations to fixture files
- **Anonymize before sharing**: Use --anonymize for exported data
- **Use realistic timings**: Match actual usage patterns

### Development

- **Test with fixtures first**: Faster than waiting for real events
- **Export problematic periods**: When something goes wrong, export that data
- **Build comprehensive test suite**: Cover edge cases with fixtures
- **Use the builder for complex scenarios**: More maintainable than hand-writing JSON

## Troubleshooting

### "No events found"

The test data or time range might not contain the expected events. Check:
- Start/end times in export command
- Event timestamps in fixture file
- Bucket configuration

### "Bucket not found"

Test data must include required buckets. Ensure fixture has:
- `aw-watcher-window_test`
- `aw-watcher-afk_test`

### "Can't load test data"

Check:
- File exists and path is correct
- JSON/YAML is valid
- File has required structure (buckets, events)

## Further Reading

- `tests/fixtures/README.md` - Detailed fixture format documentation
- `tests/conftest.py` - FixtureDataBuilder API documentation
- `src/aw_export_timewarrior/export.py` - Export functionality source
