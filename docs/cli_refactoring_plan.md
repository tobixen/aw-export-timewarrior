# CLI Refactoring Plan: Subcommands

## Current State Analysis

### Existing Modes
The CLI currently has several operational modes that are controlled by flag combinations:

1. **Sync mode** (default): Continuously monitor and sync ActivityWatch → TimeWarrior
2. **Dry-run mode** (`--dry-run`): Show what would be done without modifying TimeWarrior
3. **Export mode** (`--export-data`): Export ActivityWatch data to file
4. **Validate mode** (`--validate-config`): Check configuration file
5. **Comparison mode** (`--diff`): Compare TimeWarrior with ActivityWatch suggestions
6. **Analysis mode** (`--show-unmatched`): Show events not matching rules

### Current Issues

1. **Confusing flag combinations**: Users must know which flags work together
   - `--diff` requires `--dry-run` + `--start` + `--end`
   - `--apply-fix` requires `--diff` but conflicts with `--dry-run`
   - `--show-fix-commands` requires `--diff`
   - `--show-unmatched` works with or without `--dry-run`

2. **Cluttered help output**: 20+ options make it hard to discover features

3. **Mode discovery**: Not obvious what the tool can do from `--help`

4. **Validation complexity**: Many cross-option validation rules

## Proposed Subcommand Structure

### Main Command Groups

```
aw-export-timewarrior <subcommand> [options]

Subcommands:
  sync              Synchronize ActivityWatch to TimeWarrior (default)
  diff              Compare TimeWarrior with ActivityWatch suggestions
  analyze           Analyze events and show unmatched activities
  export            Export ActivityWatch data to file
  validate          Validate configuration file
```

### Detailed Subcommand Design

#### 1. `sync` - Main synchronization mode (default)

**Purpose**: Continuously monitor ActivityWatch and sync to TimeWarrior

**Usage**:
```bash
aw-export-timewarrior sync [options]
aw-export-timewarrior [options]  # implicit sync
```

**Options**:
- `--dry-run`: Show what would be done without modifying TimeWarrior
- `--once`: Process once and exit (instead of continuous monitoring)
- `--from/--since/--begin DATETIME`: Start time for processing window. Defaults to last observed timew tagging timestamp.
- `--to/--until/--end DATETIME`: End time. In continuous mode (no `--once`): runs indefinitely.  With `--once` or `--dry-run`: defaults to now. (TODO: In dry-run mode, there is no sleep in the loop!  It has to be fixed if --dry-run should run continuous)
- `--verbose, -v`: Enable verbose output
- `--hide-processing-output`: Hide command execution messages
- `--quiet, -q`: Suppress all console output (for headless/systemd usage)
- `--pdb`: Drop into debugger on unexpected states (for development)
- `--test-data FILE`: Use test data instead of live ActivityWatch

**Note**: When run from systemd, use `--quiet` to suppress console output. All logs go to the configured log file and can be viewed with `journalctl -u aw-export-timewarrior`.

**Examples**:
```bash
# Continuous sync (default)
aw-export-timewarrior sync

# Dry-run for yesterday
aw-export-timewarrior sync --dry-run --from yesterday --to today

# Process specific time range once
aw-export-timewarrior sync --from "2025-12-08 09:00" --to "2025-12-08 17:00" --once
```

#### 2. `diff` - Comparison and fixing mode

**Purpose**: Compare TimeWarrior database with ActivityWatch suggestions and optionally fix differences

**Usage**:
```bash
aw-export-timewarrior diff --from START --to END [options]
```

**Options**:
- `--from/--since/--begin DATETIME`: Start of comparison window. Defaults to beginning of current day (00:00).
- `--to/--until/--end DATETIME`: End of comparison window. Defaults to now.
- `--show-commands`: Show timew track commands to fix differences
- `--apply`: Execute the fix commands (implies --show-commands)
- `--hide-report`: Hide the detailed diff report
- `--verbose, -v`: Show more details in the diff

**Examples**:
```bash
# Show differences for yesterday
aw-export-timewarrior diff --from yesterday --to today

# Show differences with fix commands
aw-export-timewarrior diff --from "2025-12-08 10:00" --show-commands

# Apply fixes automatically
aw-export-timewarrior diff --from "2025-12-08 10:00" --to "2025-12-08 11:00" --apply

# Just show fix commands without diff report
aw-export-timewarrior diff --from today --show-commands --hide-report
```

#### 3. `analyze` - Event analysis mode

**Purpose**: Analyze ActivityWatch events to find unmatched activities and gaps in rules

**Usage**:
```bash
aw-export-timewarrior analyze --from=START --to=END [options]
```

**Options**:
- `--from/--since/--begin DATETIME`: Start of analysis window (defaults to beginning of current day, 00:00)
- `--to/--until/--end DATETIME`: End of analysis window (defaults to now)
- `--verbose, -v`: Show more details per event
- `--group-by {app,hour,day}`: How to group results (default: app)
- `--min-duration MINUTES`: Only show events longer than X minutes

**Examples**:
```bash
# Analyze yesterday's unmatched events
aw-export-timewarrior analyze --from yesterday --to today

# Analyze with detailed output
aw-export-timewarrior analyze --from "2025-12-08 09:00" --verbose

# Find long unmatched events
aw-export-timewarrior analyze --from yesterday --to today --min-duration 5
```

#### 4. `export` - Data export mode

**Purpose**: Export ActivityWatch data to file for testing or analysis

**Usage**:
```bash
aw-export-timewarrior export --output FILE [options]
```

**Options**:
- `--from/--since/--begin DATETIME`: Start time (defaults to beginning of current day, 00:00)
- `--to/--until/--end DATETIME`: End time (defaults to now)
- `--output, -o FILE`: Output file path (required)

**Examples**:
```bash
# Export a day's data
aw-export-timewarrior export --from "2025-12-08 09:00" --to "2025-12-08 17:00" -o sample.json
```

#### 5. `validate` - Config validation mode

**Purpose**: Validate configuration file syntax and rules

**Usage**:
```bash
aw-export-timewarrior validate [--config FILE]
```

**Options**:
- `--config FILE`: Path to config file (default: standard locations)

**Examples**:
```bash
# Validate default config
aw-export-timewarrior validate

# Validate custom config
aw-export-timewarrior validate --config my_config.toml
```

## Global Options

These options work across all subcommands:

- `--config FILE`: Path to configuration file (defaults to standard config locations)
- `--log-level LEVEL`: Set logging level (default: DEBUG)
- `--console-log-level LEVEL`: Set console logging level (default: ERROR)
- `--log-file FILE`: Log file path (default: ~/.local/share/aw-export-timewarrior/aw-export.json.log)
- `--no-log-json`: Disable JSON logging (use plain text format instead)
- `--pdb`: Drop into Python debugger on breakpoints (for development)
- `--help, -h`: Show help
- `--version`: Show version

**Note**: All logging and config options that are currently command-line arguments are now available as global options in the CLI.

## Implementation Plan

**Note**: Backward compatibility is not a concern (v0.x with single user). We can make breaking changes freely.

### Phase 1: Subcommand Structure

1. Add subcommand parser structure using argparse subparsers
2. Make subcommands optional (default to 'sync' if no subcommand given)
3. Remove old flag-based modes entirely
4. Implement clear validation for each subcommand's options

### Phase 2: Subcommand Implementation
1. Implement `sync` subcommand (maps to current default behavior)
2. Implement `diff` subcommand (consolidates --diff, --show-fix-commands, --apply-fix)
3. Implement `analyze` subcommand (consolidates --show-unmatched)
4. Implement `export` subcommand (--export-data)
5. Implement `validate` subcommand (--validate-config)

### Phase 3: Documentation and Polish
1. Update help text with clear examples for each subcommand
2. Add inline examples to CLI help output
3. Update README with subcommand-based usage examples
4. Document migration from old flag-based CLI (for reference)

## Benefits of This Approach

1. **Clearer intent**: `aw-export-timewarrior diff` immediately tells you what you're doing
2. **Better help**: Each subcommand has its own focused help text
3. **Fewer validation rules**: Subcommands naturally enforce which options make sense together
4. **Easier discovery**: Users can explore subcommands to learn features
5. **Room for growth**: Easy to add new subcommands (e.g., `stats`, `report`)
6. **Backward compatible**: Can maintain existing CLI during transition

## Alternative: Option Groups

If subcommands feel too heavyweight, an alternative is better organization with option groups:

```
positional arguments:
  ...

optional arguments:
  -h, --help            show this help message and exit

operational modes:
  --dry-run             Don't modify TimeWarrior
  --once                Process once and exit
  --validate-config     Validate configuration

time range:
  --from, --start, --since DATETIME
  --to, --end, --until DATETIME

comparison & fixing:
  --diff                Compare TimeWarrior with ActivityWatch
  --show-fix-commands   Show commands to fix differences
  --apply-fix           Apply fix commands

analysis:
  --show-unmatched      Show events not matching rules

output control:
  --verbose, -v         Verbose output
  --hide-processing-output
  --hide-diff-report
```

This is simpler but doesn't solve the validation complexity issue.

## Recommendation

**Implement the full subcommand approach in one go**:
- Add subcommand structure with argparse subparsers
- Default to 'sync' subcommand if none specified
- Remove old flag-based modes completely
- Test with real usage patterns

Since backward compatibility isn't a concern, we can make a clean break and implement the better UX immediately.
