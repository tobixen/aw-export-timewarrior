# Project Split Plan

## Overview

Split aw-export-timewarrior into three projects that share the same config file format:

1. **aw-export-tags** - Core ActivityWatch → tags functionality (no Timewarrior dependency)
2. **aw-export-timewarrior** - Timewarrior integration (depends on aw-export-tags)
3. **timewarrior-check-tags** - Standalone Timewarrior tag management (no ActivityWatch dependency)

## Current Module Analysis

### Modules by Dependency

| Module | ActivityWatch | Timewarrior | Purpose |
|--------|---------------|-------------|---------|
| config.py | aw-core | - | Config loading |
| tag_extractor.py | - | - | Tag rules, exclusive groups |
| state.py | - | - | State management |
| aw_client.py | aw-client | - | Event fetching |
| utils.py | - | - | Utilities |
| output.py | - | - | Logging/output |
| main.py | Yes | Yes | Core Exporter |
| cli.py | Yes | Yes | CLI commands |
| timew_tracker.py | - | Yes | Timewarrior tracking |
| time_tracker.py | - | - | Abstract tracker |
| compare.py | - | Yes | Interval comparison |
| retag.py | - | Yes | Retag command |
| report.py | Yes | - | Activity reports |
| export.py | Yes | - | Data export |

## Project 1: aw-export-tags

**Purpose:** Extract tags from ActivityWatch events using configurable rules.

### Modules to Include
- `config.py` - Shared config loading
- `tag_extractor.py` - Tag rules, exclusive groups, retag rules
- `state.py` - Core state management (AfkState, ExportStats)
- `aw_client.py` - ActivityWatch event fetching
- `utils.py` - Shared utilities
- `output.py` - Logging infrastructure

### Dependencies
- aw-client
- aw-core (for config path discovery)
- dateparser
- toml
- termcolor

### CLI Commands
```bash
aw-export-tags analyze          # Show what tags would be extracted
aw-export-tags validate-config  # Validate config file
aw-export-tags export           # Export tagged events (JSON/CSV)
```

### Config Sections Used
- `[rules.*]` - Tag extraction rules
- `[tags.*]` - Retag rules
- `[exclusive.*]` - Exclusive group definitions

---

## Project 2: aw-export-timewarrior

**Purpose:** Sync ActivityWatch data to Timewarrior, compare and fix intervals.

### Modules to Include
- `main.py` - Exporter class (imports from aw-export-tags)
- `cli.py` - Full CLI
- `timew_tracker.py` - Timewarrior backend
- `time_tracker.py` - Abstract tracker interface
- `compare.py` - Interval comparison
- `retag.py` - Retag command
- `report.py` - Activity reports

### Dependencies
- aw-export-tags (the core library)
- timewarrior (external command)

### CLI Commands (existing)
```bash
aw-export-timewarrior sync      # Real-time sync
aw-export-timewarrior diff      # Compare and optionally fix
aw-export-timewarrior analyze   # Show unmatched events
aw-export-timewarrior export    # Export data
aw-export-timewarrior report    # Activity report
aw-export-timewarrior validate  # Validate config
aw-export-timewarrior retag     # Apply retag rules
```

### Config Sections Used
All sections (full config)

---

## Project 3: timewarrior-check-tags

**Purpose:** Validate and manage Timewarrior tags against rules (no AW dependency).

### New Modules
- `timew_client.py` - Read Timewarrior intervals
- `validator.py` - Tag validation against rules
- `fixer.py` - Apply fixes to intervals

### Dependencies
- toml (for config)
- timewarrior (external command)

### CLI Commands
```bash
timewarrior-check-tags check     # Check for exclusive group violations
timewarrior-check-tags fix       # Apply retag rules to existing intervals
timewarrior-check-tags report    # Show tag statistics
timewarrior-check-tags validate  # Validate config
```

### Config Sections Used
- `[tags.*]` - Retag rules
- `[exclusive.*]` - Exclusive group definitions

---

## Shared Config File

All three projects read the same config file (`~/.config/activitywatch/aw-export-timewarrior/aw-export-timewarrior.toml`):

```toml
# Sections used by aw-export-tags
[rules.browser.github]
url_regexp = "github\\.com"
timew_tags = ["coding", "github"]

[rules.app.terminal]
app_names = ["foot", "alacritty"]
timew_tags = ["terminal"]

# Sections used by all three projects
[tags.work]
source_tags = ["coding", "terminal"]
add = ["4work"]

[exclusive.category]
tags = ["4work", "4break", "4chores"]

# Sections used by aw-export-timewarrior only
[tuning]
min_event_duration = 3.0
stickyness_factor = 0.1
```

---

## Implementation Order

### Phase 1: Extract Core Library
1. Create `aw-export-tags` package
2. Move core modules (tag_extractor, config, state, aw_client, utils, output)
3. Update aw-export-timewarrior to depend on aw-export-tags
4. Ensure all tests still pass

### Phase 2: Create Timewarrior Tool
1. Create `timewarrior-check-tags` package
2. Implement timew_client.py to read Timewarrior data
3. Reuse TagExtractor from aw-export-tags for validation
4. Add CLI commands for check/fix/report

### Phase 3: Clean Up
1. Move retag.py logic into timewarrior-check-tags
2. Share config validation code
3. Update documentation

---

## Benefits

1. **Lighter dependencies:** Users who only need tag validation don't need ActivityWatch
2. **Reusability:** The core tag logic can be used by other projects
3. **Testability:** Smaller, focused modules are easier to test
4. **Maintenance:** Clear separation of concerns

## Risks

1. **Breaking changes:** Need to maintain backward compatibility during transition
2. **Config path:** All three tools need to find the same config file
3. **Version sync:** Need to keep versions coordinated

---

*Created: 2025-12-22*
