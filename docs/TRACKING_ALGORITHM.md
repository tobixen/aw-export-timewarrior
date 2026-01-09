# Tracking Algorithm

This document explains how aw-export-timewarrior processes ActivityWatch events and exports them to TimeWarrior.

## Overview

The exporter processes a stream of window events from ActivityWatch and decides when to create TimeWarrior intervals. The core challenge is determining **when** to export tags and **what time range** they should cover.

## Key Concepts

### Three Timestamps for Each Export

Each export decision involves three distinct timestamps:

1. **Interval Start**: When the exported activity period began (calculated retroactively)
2. **Interval End**: When the exported activity period ended (= start of the triggering event)
3. **Decision Point**: When the export decision is triggered (while processing the triggering event)

#### Export Decision Triggers

An export is triggered when EITHER condition is met:

1. **Single-window threshold**: A single window has been active for more than `max_mixed_interval` (default: 4 minutes)
2. **Accumulator threshold**: Some tag has accumulated more than `min_recording_interval` (default: 90s) of activity time

#### Example Timeline

```
19:00:00  User starts browsing entertainment site
          Event A: entertainment website
          [Tags accumulating: entertainment, browser]

19:01:30  Still on same site
          Event B: same entertainment website (90s accumulated)
          → Accumulator threshold reached!
          → DECISION POINT: Export triggered while processing Event B
          → INTERVAL END: 19:01:30 (start of Event B)
          → INTERVAL START: calculated as ~19:00:00
          → timew start entertainment browser 19:00:00
          → Accumulator reset (with stickyness carry-forward)

19:01:30  Continue tracking...
          [New accumulation starts]

19:04:00  User switches to coding
          Event C: editor window opens
          [Tags change: coding, editor start accumulating]

19:05:30  Still coding
          Event D: editor activity (90s accumulated)
          → Accumulator threshold reached!
          → DECISION POINT: Export triggered while processing Event D
          → INTERVAL END: 19:05:30 (start of Event D)
          → INTERVAL START: calculated as ~19:04:00
          → timew start coding editor 19:04:00
          → This implicitly ENDS the entertainment period at 19:04:00
```

**Key insight**: The interval end equals the START of the event that triggers the export decision, not its end. The exported interval covers all the activity that was accumulated BEFORE the triggering event.

### Tag Accumulation

Tags accumulate in `tags_accumulated_time` as events are processed:

```python
tags_accumulated_time = {
    "entertainment": timedelta(minutes=3, seconds=45),
    "browser": timedelta(minutes=3, seconds=45),
    "not-afk": timedelta(minutes=3, seconds=45),
}
```

Each event's duration is added to its extracted tags. Tags compete for dominance based on accumulated time.

### Export Thresholds

An export is triggered when EITHER of these conditions is met:

1. **Single-window duration**: A single window (with matching tags) has been active for more than `max_mixed_interval` (default: 240s = 4 minutes). This handles focused work on a single task.

2. **Accumulated time**: BOTH of these must be true:
   - Time since last known tick > `min_recording_interval` (default: 90s)
   - At least one tag has `accumulated_time > min_tag_recording_interval` (default: 50s)

The thresholds prevent noise from brief window switches while ensuring responsive tracking of sustained activity.

## Tracking Modes

### Manual Tracking Mode

When the user manually runs `timew start`, the exporter enters "manual tracking" mode. In this mode, the interval start is calculated as:

```python
since = event["timestamp"] - known_events_time + event["duration"]
```

This back-calculates the start time based on how much activity has been observed, ensuring the exported interval accurately reflects when activity began.

### Automatic Tracking Mode

When tracking automatically (no manual intervention), the interval start is simply:

```python
since = last_known_tick
```

This uses the timestamp of the last successfully matched event.

## Event Processing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        Event Stream                              │
│  (window events + AFK events merged and split at AFK boundaries) │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    1. Tag Extraction                             │
│  find_tags_from_event() → TagResult (IGNORED/NO_MATCH/MATCHED)  │
│                                                                  │
│  - Events < 3s may be ignored (unless accumulated in same app)  │
│  - Rules applied: browser URLs, editor paths, app names, tmux   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   2. Tag Accumulation                            │
│  _update_tag_accumulator()                                       │
│                                                                  │
│  tags_accumulated_time[tag] += event["duration"]                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                3. Export Decision Check                          │
│  _should_export_accumulator()                                    │
│                                                                  │
│  Conditions:                                                     │
│  ✓ interval_since_last_tick > min_recording_interval (~99s)     │
│  ✓ any tag accumulated > min_tag_recording_interval (~55s)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
              (not met)            (both met)
                    │                   │
                    ▼                   ▼
            Continue to         ┌──────────────────────────────────┐
            next event          │       4. Export Tags              │
                                │  ensure_tag_exported()            │
                                │                                   │
                                │  → Calculate since timestamp      │
                                │  → Apply retag rules              │
                                │  → timew start <tags> <since>     │
                                │  → Reset accumulator (×stickyness)│
                                │  → Record export history          │
                                └──────────────────────────────────┘
```

## Stickyness Factor

When an export happens, the accumulator isn't fully reset. A "stickyness factor" (default: 0.1 = 10%) carries forward:

```python
# Before export: tags_accumulated_time["coding"] = 300s (5 min)
# After export:  tags_accumulated_time["coding"] = 30s  (10% retained)
```

This prevents rapid flip-flopping between tags when activities alternate.

## State Variables

| Variable | Purpose |
|----------|---------|
| `last_tick` | Most recent event timestamp (prevents reprocessing) |
| `last_known_tick` | Most recent matched event (used for interval calculation) |
| `last_start_time` | Start time of last export |
| `known_events_time` | Total matched event time since last export |
| `unknown_events_time` | Total unmatched event time since last export |
| `tags_accumulated_time` | Per-tag accumulated duration |

## AFK Handling

AFK (Away From Keyboard) events are special:

1. Window events are **split at AFK boundaries** to prevent time attribution errors
2. When user goes AFK, current accumulated tags may be exported
3. When user returns from AFK, accumulator is reset
4. AFK periods themselves can be tagged (e.g., `afk`, `4BREAK`)

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_mixed_interval` | 240s | Max duration before single-window export (4 min) |
| `min_recording_interval` | 90s | Minimum accumulated time before export decision |
| `min_tag_recording_interval` | 50s | Minimum per-tag accumulation for export |
| `stickyness_factor` | 0.1 | Fraction of accumulator retained after export |
| `ignore_interval` | 3s | Minimum event duration (unless accumulated) |

## Export Record Structure

When exports are recorded (for the `--show-exports` report feature), each record captures:

```python
ExportRecord(
    timestamp=since,           # Interval start time
    duration=end - since,      # Interval duration
    tags={"coding", "editor"}, # Tags exported
    accumulator_before={...},  # Tag accumulator state before reset
    accumulator_after={...},   # Tag accumulator state after reset
)
```

## Understanding Report Output

With `--show-exports`, the report shows three lines per export:

```
Time     Dur      Description
08:00:00 00:01:30 [EXPORT START] coding, editor
08:00:00 00:00:30 Working on feature.py          editor  file:~/project/feature.py
08:00:30 00:01:00 Working on test.py             editor  file:~/project/test.py
08:01:00 00:01:30 [EXPORT DECISION] coding, editor | accumulated: coding:1m, editor:1m
08:01:30 00:01:30 [EXPORT END] coding, editor | before: coding:1m30s | after: coding:9s
08:01:30 00:01:00 [EXPORT START] coding, editor    ← Next interval starts immediately
```

The three export lines show:
- **[EXPORT START]** (green): When the exported interval BEGAN
  - Time: Interval start timestamp
  - Dur: Total interval duration
  - Tags: What was exported

- **[EXPORT DECISION]** (yellow): When the THRESHOLD was reached
  - Time: Timestamp of the event that triggered the export decision
  - Dur: Total interval duration
  - Tags: What was exported
  - accumulated: Tag accumulator state at decision time

- **[EXPORT END]** (cyan): When the exported interval ENDED (= start of next interval)
  - Time: Interval end timestamp
  - Dur: Total interval duration
  - Tags: What was exported
  - before/after: Accumulator state before and after reset

Each export end is immediately followed by the next export start, forming contiguous intervals.

## Common Scenarios

### Scenario 1: Focused Work Session

User works on one project for 2 hours:
- Export every ~90-100 seconds
- Same tags repeated
- Stickyness prevents tag loss on brief interruptions

### Scenario 2: Multi-tasking

User alternates between email and coding:
- Whichever activity dominates gets exported
- Minor activities (< 50s accumulated) are absorbed
- Clear context switches trigger new exports

### Scenario 3: Brief Interruption

User checks phone for 30 seconds during coding:
- 30s < threshold, so no export triggered
- Coding accumulator continues growing
- Interruption effectively ignored

### Scenario 4: Unknown Activity

User does something with no matching rules:
- `unknown_events_time` accumulates
- After `max_mixed_interval × 2`, tagged as `UNKNOWN`
- Ensures no time is completely lost
