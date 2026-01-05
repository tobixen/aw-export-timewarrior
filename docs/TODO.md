# TODO - aw-export-timewarrior

## High Priority

### Wonkyness in the diff

The output from diff, with and without `--timeline`, looks a bit wonky and should be investigated further.

Here are some examples:

```
$ aw-export-timewarrior  diff --day 2025-12-30  --timeline
(...)
01:17:27             4RL, 4oss-contrib, activitywatch, n...    4RL, 4oss-contrib, activitywatch, n...
01:26:29             4BREAK, 4entertainment, digi, enter...    4BREAK, 4entertainment, digi, enter...
01:26:50             4BREAK, 4entertainment, digi, enter...
01:36:22             4RL, 4oss-contrib, activitywatch, n...    4RL, 4oss-contrib, activitywatch, n...
(...)
```

What's going on between 01:26:29 and 01:36:22?

### Report should tell what rules have been applied

... and it should also give some info from the tmux watcher

### Diff should apply (re)tagging rules

if "bedtime" is added to the afk in the timew database, then 4BREAK should also be applied

### Recursion safety in tag rules
Add recursion depth limit to `apply_retag_rules()` to prevent infinite loops with circular tag rules.

### Return type annotations
Add missing return type annotations throughout codebase per coding standards.

### Empty tags assertion
Fix or document the confusing assertion on empty tags in `_should_export_accumulator()`.

## Medium Priority

### Further main.py reduction
Continue extracting modules from main.py:
- Event processing pipeline

### Configuration validation
Add validation for configuration values (currently no validation of loaded TOML).

### Error handling consistency
Improve error handling:
- Add logging for caught exceptions
- Use specific exception types
- Document expected vs. exceptional failure cases

## Low Priority

### Performance optimizations
- Event caching in `get_corresponding_event`
- Batch processing for historical sync

### Documentation
- Architecture diagrams
- Performance tuning guide

## Future Directions

### More watchers

#### tmux watcher
Support added for [aw-watcher-tmux](https://github.com/akohlbecker/aw-watcher-tmux):
- Automatic detection of tmux bucket
- Tag extraction with configurable rules (`rules.tmux.*`)
- Variable substitution: `$session`, `$window`, `$command`, `$path`, `$1`, `$2`, etc.
- Default tag `tmux:$command` when no rules match
- Documentation in README.md

#### terminal watcher
Not yet investigated.

### Interactivity

* Add an interactive way to create/edit rules in the configuration file:
 - Show unmatched events and prompt for tags
 - Suggest rules based on patterns (URL, app name, file path)
 - Write rules directly to config file
 - Could be CLI wizard or TUI interface

### Rename to aw-tagger
Rename project from `aw-export-timewarrior` to `aw-tagger` to reflect the core value proposition: rule-based categorization for ActivityWatch.

Key changes:
- Add meta watcher output (write tags to `aw-watcher-tags` bucket)
- Make Timewarrior an optional output
- Restructure CLI: `aw-tagger sync`, `aw-tagger timew sync`, etc.

See **[PROJECT_SPLIT_PLAN.md](PROJECT_SPLIT_PLAN.md)** for detailed implementation plan.

---

## Completed

### Fixed: Analyze not showing rapid activity in same app (Jan 5, 2026)

**Problem:** `analyze` command showed very little when `report` showed significant feh (image viewer) activity. Rapidly flipping through photos created many <3s events that were all ignored.

**Root cause:** The `ignore_interval` (3s) filter was applied before checking rules. Short events were discarded as "window-switching noise" even when they represented legitimate activity (same app, rapid title changes).

**Fix:** Modified `find_tags_from_event()` to:
1. First determine tags before checking duration
2. Track consecutive short events by (app, tags) context
3. Only ignore if wall-clock time in same context < `ignore_interval`

This preserves the original intent (filter brief window switches) while recognizing sustained activity with rapid updates.

**Affected file:** `src/aw_export_timewarrior/main.py`

**Test:** Added `tests/test_short_event_accumulation.py` with 5 regression tests

---

### Fixed: Transport block ignoring active window usage (Dec 20, 2025)

**Problem:** TimeWarrior showed one continuous "transport" block from 11:04:54 to 18:14:36 UTC, completely ignoring ~5-6 minutes of active window usage when the laptop was resumed.

**Root cause:** In `_resolve_event_conflicts()`, the merge logic was removing AFK events whenever they conflicted with lid events, regardless of which state the lid indicated. When the lid was "open" (not-afk) and overlapped with a user AFK event (afk), the AFK event was incorrectly removed.

**Fix:** Modified `events_conflict()` to only consider it a conflict when the lid event indicates AFK (closed/suspended). When lid is open (not-afk), user AFK events from aw-watcher-afk are now preserved.

**Affected file:** `src/aw_export_timewarrior/main.py`

**Test:** Added `test_lid_open_does_not_remove_afk_events()` regression test in `tests/test_lid_afk.py`

---

*See also: `docs/CODE_REVIEW.md` for detailed code review and improvement suggestions.*
