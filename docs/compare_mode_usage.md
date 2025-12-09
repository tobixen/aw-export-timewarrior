# Compare Mode Usage Guide

## Overview

The `--diff` flag enables comparison mode, which compares what's currently in your TimeWarrior database with what ActivityWatch suggests should be there based on your activity.

## Requirements

- Must be used with `--dry-run` (won't modify your timewarrior database)
- Must specify `--start` and `--end` to define the comparison time window
- Must use `--once` (comparison only makes sense for a specific time range, not continuous monitoring)

## Basic Usage

```bash
# Compare today's activity from 9 AM to 5 PM
aw-export-timewarrior --dry-run --diff --once \
    --start "2025-12-08T09:00:00" \
    --end "2025-12-08T17:00:00"
```

## What It Shows

The comparison shows four categories of differences:

### ✓ Matching Intervals
Intervals that exist in both TimeWarrior and ActivityWatch with identical tags.

### ⚠ Different Tags
Intervals that exist in both but have different tags. Shows:
- Tags only in TimeWarrior
- Tags only suggested by ActivityWatch
- Common tags (when `--verbose` is used)

### - Missing from TimeWarrior
Intervals suggested by ActivityWatch but not found in TimeWarrior.
These are activities you did but forgot to track.

### + Extra in TimeWarrior
Intervals in TimeWarrior but not suggested by ActivityWatch.
These might be:
- Manual entries
- Activities that ActivityWatch couldn't detect
- Errors in TimeWarrior

## Example Output

```
================================================================================
TimeWarrior vs ActivityWatch Comparison
================================================================================

Summary:
  ✓ Matching intervals:      15
  ⚠ Different tags:          3
  - Missing from TimeWarrior: 2
  + Extra in TimeWarrior:     1

Missing from TimeWarrior (suggested by ActivityWatch):
  - 10:30:00 - 10:45:00 (15.0min)
    Tags: 4work, email, not-afk
  - 14:15:00 - 14:30:00 (15.0min)
    Tags: 4me, break, not-afk

Extra in TimeWarrior (not suggested by ActivityWatch):
  + 12:00:00 - 12:30:00 (30.0min)
    Tags: lunch, manual-entry

Intervals with different tags:
  11:00:00 - 12:00:00
    - In timew:  meeting, 4work
    + Suggested: slack, 4work, communication
```

## Verbose Mode

Add `--verbose` to see more details:

```bash
aw-export-timewarrior --dry-run --diff --once --verbose \
    --start "2025-12-08T09:00:00" \
    --end "2025-12-08T17:00:00"
```

This will also show:
- All matching intervals
- Common tags for intervals with differences

## Typical Workflow

1. **Review a specific day:**
   ```bash
   aw-export-timewarrior --dry-run --diff --once \
       --start "2025-12-08T00:00:00" \
       --end "2025-12-08T23:59:59"
   ```

2. **Check a specific time range (e.g., working hours):**
   ```bash
   aw-export-timewarrior --dry-run --diff --once \
       --start "2025-12-08T09:00:00" \
       --end "2025-12-08T17:00:00"
   ```

3. **Review multiple days:**
   ```bash
   aw-export-timewarrior --dry-run --diff --once \
       --start "2025-12-01T00:00:00" \
       --end "2025-12-07T23:59:59"
   ```

## Use Cases

### 1. Verify Accuracy
Check if your automatic time tracking matches what's actually in TimeWarrior.

### 2. Find Gaps
Identify activities you were doing (according to ActivityWatch) but forgot to track in TimeWarrior.

### 3. Spot Errors
Find manual entries or tracking errors that don't match your actual activity.

### 4. Audit Tags
See where your tagging differs between manual entries and automatic suggestions.

## Tips

- **Start small**: Begin with a few hours to understand the output
- **Use verbose mode**: When tags differ, verbose mode shows what's common vs different
- **Check gaps**: "Missing" intervals are great candidates to add to TimeWarrior
- **Verify extras**: "Extra" intervals might be legitimate manual entries or errors
- **Tag mismatches**: Often indicate that your configuration rules need adjustment

## Limitations

- Only compares completed intervals (not ongoing tracking)
- Requires both TimeWarrior and ActivityWatch to have data for the time range
- Edge-touching intervals (e.g., 12:00-13:00 and 13:00-14:00) are considered overlapping
- Comparison is based on time overlap, not exact time matching

## Integration with Workflow

A typical daily review might look like:

```bash
#!/bin/bash
# Daily time tracking review script

TODAY=$(date +%Y-%m-%d)

echo "Reviewing today's time tracking..."
aw-export-timewarrior --dry-run --diff --once \
    --start "${TODAY}T00:00:00" \
    --end "${TODAY}T23:59:59"

echo ""
echo "Review the differences above."
echo "To update TimeWarrior based on ActivityWatch suggestions:"
echo "  aw-export-timewarrior --dry-run --once --start ... --end ..."
echo "Then run without --dry-run to apply changes."
```

## Troubleshooting

### "Error: --diff requires --dry-run"
You must use `--dry-run` with `--diff`.

### "Error: --diff requires both --start and --end"
You must specify the time window to compare.

### "Failed to fetch timew data"
- Ensure `timew` is installed and in your PATH
- Check that TimeWarrior has data for the specified time range
- Run `timew export <start> - <end>` manually to verify

### No differences shown
Either your TimeWarrior entries perfectly match ActivityWatch suggestions (great!), or there's no ActivityWatch data for that time range.
