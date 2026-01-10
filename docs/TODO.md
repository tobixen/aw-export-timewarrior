# TODO - aw-export-timewarrior

## High Priority

### Github tests fail

Tests seems to be dependent on timew

```
$ gh run view --log-failed --job=60006961560
(...)
test	Run tests	2026-01-10T22:03:18.9797781Z ______________ TestDiffWithRealTimew.test_diff_matching_interval _______________
test	Run tests	2026-01-10T22:03:18.9798216Z tests/test_functional_timew.py:271: in test_diff_matching_interval
test	Run tests	2026-01-10T22:03:18.9798589Z     timew_db.add_interval(start, end, ["work", "python"])
test	Run tests	2026-01-10T22:03:18.9799005Z tests/test_functional_timew.py:80: in add_interval
test	Run tests	2026-01-10T22:03:18.9799353Z     result = self.run_timew("track", start_str, "-", end_str, *tags)
test	Run tests	2026-01-10T22:03:18.9799686Z              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
test	Run tests	2026-01-10T22:03:18.9799966Z tests/test_functional_timew.py:72: in run_timew
test	Run tests	2026-01-10T22:03:18.9800379Z     return subprocess.run(["timew"] + list(args), capture_output=True, text=True, check=False)
test	Run tests	2026-01-10T22:03:18.9800803Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
test	Run tests	2026-01-10T22:03:18.9801254Z /opt/hostedtoolcache/Python/3.13.11/x64/lib/python3.13/subprocess.py:554: in run
test	Run tests	2026-01-10T22:03:18.9801645Z     with Popen(*popenargs, **kwargs) as process:
test	Run tests	2026-01-10T22:03:18.9801904Z          ^^^^^^^^^^^^^^^^^^^^^^^^^^^
test	Run tests	2026-01-10T22:03:18.9802254Z /opt/hostedtoolcache/Python/3.13.11/x64/lib/python3.13/subprocess.py:1039: in __init__
test	Run tests	2026-01-10T22:03:18.9802696Z     self._execute_child(args, executable, preexec_fn, close_fds,
test	Run tests	2026-01-10T22:03:18.9803159Z /opt/hostedtoolcache/Python/3.13.11/x64/lib/python3.13/subprocess.py:1991: in _execute_child
test	Run tests	2026-01-10T22:03:18.9803637Z     raise child_exception_type(errno_num, err_msg, err_filename)
test	Run tests	2026-01-10T22:03:18.9804022Z E   FileNotFoundError: [Errno 2] No such file or directory: 'timew'

```

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

### Reconsider the tests

There are tons and tons of test code, and still lots of bugs have been found and fixed.

Probably quite much of the tests are redundant, probably we don't need this many tests, probably they could be consolidated.

Would it make sense to have a fixture containing a semi-large dataset containing real data as well as data known to have caused problems earlier, combined with a relatively large ruleset, and then verify that all the different commands will do as predicted with this data set and produce the same timeline?

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
