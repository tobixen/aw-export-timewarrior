# TODO - aw-export-timewarrior

## High Priority

### Config terminology cleanup

In config.py, the `prepend` has been used to indicate additional tags.
In the real config file `add` is used instead.
For many other rules, `timew_tags` is used.

We don't need to care about backward compatibility yet. `prepend` and `append` is meaningless as the tags is a set and not a list, it should be `add`. `timew_tags` also doesn't make sense as we want to develop this in a "backend agnostic" tool, so probably only `tags`. However, `add` and `tags` is not much consistent, so this may be thought better through.

As for the tag rules, we also need options to replace or remove tags.

### Diff should apply (re)tagging rules

If "bedtime" is added to the afk in the timew database, then 4BREAK should also be applied.

### Empty tags in export

The `_should_export_accumulator()` function can return an empty tags set even when it returns `should_export=True`. This happens when the threshold adjustment for exclusive tag conflicts raises `min_tag_recording_interval` above all accumulated tag times. This should either be prevented (return `False` when tags would be empty) or documented as intentional behavior.

## Medium Priority

### Manual operations

* The logic in aw-watcher-ask-away should possibly also be applicable when not-afk.  Should consider to ask for activity when the hints in the acticitywatcher data is weak
* Should be easy to specify that "activity with tags X today was Y".  Like, feh was used for sorting inventory, etc.

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

### Added: Tracking algorithm documentation (Jan 8, 2026)

Created `docs/TRACKING_ALGORITHM.md` explaining:
- How events are processed and tags accumulated
- The three timestamps involved in each export (interval start, interval end, decision time)
- Manual vs automatic tracking modes
- Stickyness factor and accumulator behavior
- Export thresholds and configuration parameters

### Added: Report shows matched rules (Jan 7, 2026)

**Problem:** Hard to debug why events were tagged a certain way.

**Solution:** Added `--show-rule` option and `matched_rule` column to report output. Each event now shows which rule matched it (e.g., `browser:github`, `tmux:claude-oss`).

### Added: Export history in reports (Jan 8, 2026)

**Problem:** Hard to understand when exports happened and what was accumulated.

**Solution:** Added `--show-exports` option to report command. Shows export decisions inline with events, including:
- Interval start timestamp and duration
- Tags exported
- Accumulator state before/after the export

### Fixed: oss-contrib over-tagging (Jan 5, 2026)

**Problem:** Almost everything was being tagged with `oss-contrib` and `activitywatch` even when working on unrelated projects.

**Root cause:** Config bug in `[rules.app.claude-activitywatch]` - the `title_regexp` ended with a trailing `|` creating an empty alternative that matched ANY string:
```
title_regexp = "...Timewarrior diff command|"
                                          ^ trailing pipe!
```

**Fix:** Removed the trailing `|` from the regex in the user's config file.

### Fixed: Wonkyness in the diff output (Jan 5, 2026)

**Problems:**
1. Timeline showed empty AW column when AW activity was continuing from a previous row
2. Diff showed duplicate entries when a timew interval overlapped with multiple AW suggestions
3. Diff combined all suggested tags when timew interval spanned multiple AW intervals with different tags, making it look like contradictory tags (e.g., both `not-afk` and `afk`)
4. Diff wasn't showing the current timew tags, only the difference

**Fixes:**
1. Added "(continuing)" indicator in timeline when AW activity continues but has no boundary
2. Grouped diff output by timew interval to avoid duplicates
3. When a timew interval spans multiple AW suggestions with different tags, now shows each sub-interval separately with its time range
4. Always show current timew tags in diff output (excluding internal `~aw` tags)

**Affected file:** `src/aw_export_timewarrior/compare.py`

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

### Fixed: Transport block ignoring active window usage (Dec 20, 2025)

**Problem:** TimeWarrior showed one continuous "transport" block from 11:04:54 to 18:14:36 UTC, completely ignoring ~5-6 minutes of active window usage when the laptop was resumed.

**Root cause:** In `_resolve_event_conflicts()`, the merge logic was removing AFK events whenever they conflicted with lid events, regardless of which state the lid indicated. When the lid was "open" (not-afk) and overlapped with a user AFK event (afk), the AFK event was incorrectly removed.

**Fix:** Modified `events_conflict()` to only consider it a conflict when the lid event indicates AFK (closed/suspended). When lid is open (not-afk), user AFK events from aw-watcher-afk are now preserved.

**Affected file:** `src/aw_export_timewarrior/main.py`

**Test:** Added `test_lid_open_does_not_remove_afk_events()` regression test in `tests/test_lid_afk.py`

---

*See also: `docs/CODE_REVIEW.md` for detailed code review and improvement suggestions.*
*See also: `docs/TRACKING_ALGORITHM.md` for detailed explanation of the tracking algorithm.*
