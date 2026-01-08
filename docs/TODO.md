# TODO - aw-export-timewarrior

## High Priority

### Reconsider the "ignore treshold" for windows

The idea to ignore window visits less than three seconds was to avoid "noise" in the data (and logs) if the mouse coursor is dragged over multiple windows etc before starting to work on something.

However, sometimes rapid movement between windows is part of the workflow, other times the application may rapidly change the window title (example: spending an hour in `feh` browsing photos, spending less than three seconds for each).

I think the simplest solution is to just kill this logic entirely.  Assume the short window visits will drown out from the real data.

### Config confusion

In config.py, the `prepend` have been used to indicate additional tags.

In the real config file `add` is used instead.

For many other rules, `timew_tags` is used.

We don't need to care about backward compatibility yet.  `prepend` and `append` is meaningless as the tags is a set and not a list, it should be `add`.  `timew_tags` also doesn't make sense as we want to develop this in a "backend agnostic" tool, so probably only `tags`.  However, `add` and `tags` is not much consistent, so this may be thought better through.

As for te tag rules, we also need options to replace or remove tags.

### Maintain the CHANGELOG

ensure it's up-to-date

### Maintain the TODO-list

Many things here have already been done

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

### Fixed: oss-contrib over-tagging (Jan 5, 2026)

**Problem:** Almost everything was being tagged with `oss-contrib` and `activitywatch` even when working on unrelated projects.

**Root cause:** Config bug in `[rules.app.claude-activitywatch]` - the `title_regexp` ended with a trailing `|` creating an empty alternative that matched ANY string:
```
title_regexp = "...Timewarrior diff command|"
                                          ^ trailing pipe!
```

**Fix:** Removed the trailing `|` from the regex in the user's config file.

**Lesson:** The "Report should tell what rules have been applied" TODO item would have made this much easier to debug.

---

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

**Investigation:** The 00:26:05 - 00:44:11 discrepancy was correct data - AFK watcher showed `not-afk` until 23:44:11 UTC, while ask-away watcher recorded "4ME social" at 23:42:10 UTC. The old diff combined both, making it look contradictory.

**Affected file:** `src/aw_export_timewarrior/compare.py`

---

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
