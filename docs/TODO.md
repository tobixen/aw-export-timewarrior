# TODO - aw-export-timewarrior

## Medium Priority

(No current medium priority items)

## Low Priority

### Reconsider the tests

There are tons and tons of test code, and still lots of bugs have been found and fixed.

Probably quite much of the tests are redundant, probably we don't need this many tests, probably they could be consolidated.

Would it make sense to have a fixture containing a semi-large dataset containing real data as well as data known to have caused problems earlier, combined with a relatively large ruleset, and then verify that all the different commands will do as predicted with this data set and produce the same timeline?

**Analysis (Jan 11, 2026):** Reviewed 35 test files (~12,000 lines). Found that:
- Bug-specific test files (10 files, ~2300 lines) test distinct subsystems and are well-organized
- Time tracker test files test different implementations (DryRunTracker vs TimewTracker), not duplicates
- Consolidated shared fixtures for 3 report test files into conftest.py (saved ~16 lines)

The comprehensive fixture approach remains a future option but the current test structure is reasonable.

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

### Fix: Error handling consistency (Jan 11, 2026)

**Change:** Improved error handling throughout the codebase.

**Details:**
- Replaced silent `except Exception: pass` handlers with logging
- Added logger to report.py, export.py, retag.py
- Log debug messages when specialized data extraction fails (report.py)
- Log warnings when bucket export fails or PyYAML unavailable (export.py)
- Log warnings with error details on retag failures (retag.py)
- Log debug message when no active timew tracking in dry-run mode (main.py)

### Refactor: Extract event pipeline from main.py (Jan 11, 2026)

**Change:** Moved event processing logic to new `event_pipeline.py` module.

**Details:**
- New `EventPipeline` class handles fetching, filtering, and merging events
- `EventPipelineConfig` dataclass for pipeline configuration
- Methods extracted: `_fetch_and_prepare_events`, `_split_window_events_by_afk`,
  `_apply_afk_gap_workaround`, `_merge_afk_and_lid_events`, `_resolve_event_conflicts`
- Reduces main.py by ~395 lines (from 2170 to 1795 lines)

### Added: Configuration validation (Jan 10, 2026)

**Feature:** Added comprehensive validation for TOML configuration files.

**Details:**
- New `config_validation.py` module with `ConfigValidator` class
- Validates top-level settings, tuning parameters, tag rules, matching rules, and exclusive groups
- Type checking for all known fields with proper error messages
- Range validation (e.g., `stickyness_factor` must be between 0 and 1)
- Regex syntax validation with helpful error messages
- Warns about common mistakes (trailing `|` in regex, empty tag lists)
- Warns about unknown fields (possible typos)
- `validate` CLI subcommand for explicit validation
- Config is automatically validated on load

### Fixed: GitHub CI tests failing (Jan 10, 2026)

**Problem:** Tests in `test_functional_timew.py` failed in GitHub Actions because TimeWarrior (`timew`) is not installed on the CI runner.

**Fix:** Added `pytestmark` to skip all tests in the module when `timew` is not available using `shutil.which("timew")`.

### Config terminology cleanup (Jan 10, 2026)

**Change:** Standardized config terminology to use `tags` and `add` as the preferred keys, with backward compatibility for legacy `timew_tags` and `prepend` keys.

**Details:**
- Rule definitions now prefer `tags` over legacy `timew_tags`
- Retag rules now prefer `add` over legacy `prepend`
- Both legacy keys still work for backward compatibility with existing user config files
- Updated default config and test fixtures to use new terminology
- Updated documentation (README.md) to use new terminology

### Fixed: Empty tags in export (Jan 10, 2026)

**Problem:** `_should_export_accumulator()` could return `should_export=True` with an empty tags set when the threshold adjustment for exclusive tag conflicts raised `min_tag_recording_interval` above all accumulated tag times.

**Root cause:** When two exclusive tags had exactly the same accumulated time, the while loop would raise the threshold until both were eliminated, but the function would still return `should_export=True` with an empty tags set.

**Fix:** Added a check after tag collection - if no tags remain after conflict resolution, return `False` instead of `True` with empty tags. The accumulator is still decayed to prevent indefinite growth.

**Test:** Added `tests/test_empty_tags_export.py` with regression tests.

### Fixed: Report command stuck on recent events (Jan 10, 2026)

**Problem:** `report --start '2 minutes ago'` would get stuck for a long time when processing recent browser/editor/terminal events.

**Root cause:** `extract_specialized_data()` in report.py was calling `get_corresponding_event()` with the default `retry=6` parameter. For recent events (within 90 seconds of current time), this would sleep up to 6 times (~90s total) if no matching sub-event was found.

**Fix:** Added `retry=0` to all `get_corresponding_event()` calls in `extract_specialized_data()` since the report command is just reading historical data and shouldn't wait for events to propagate.

**Tests:** Added `tests/test_report_no_sleep.py` with 8 tests verifying the fix.

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
