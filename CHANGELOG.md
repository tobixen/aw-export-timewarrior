# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

A full code review was done by Claude Fable - it found multiple potential bugs that have been fixed.  Quite a bit of code refactoring has also been done, cleaning up, deduplicating and fixing performance issues.

### Added
- `[lists]` config section for reusable named lists, referenced as `@name` in list fields (`tags`, `app_names`, `source_tags`, ...) and in regexp fields (`url_regexp`, `title_regexp`, `path_regexp`, ...), where a reference expands to a non-capturing alternation `(?:item1|item2|...)`. Supersedes `[app_groups]`, which remains as an alias.
- `report --min-duration SECONDS`: filter out events shorter than the given duration (e.g. `--min-duration 2` hides sub-2-second window flickers)
- `--stop` as an alias for `--to`/`--until`/`--end` when giving the end of a time range.

### Fixed
- Fix captured `timew start`/`stop` timestamps recorded in UTC (`Z` suffix) being shifted by your local UTC offset, placing those intervals at the wrong time of day.
- Fix the ~2-minute idle-timeout countdown being credited to the previously tracked tag instead of being left as afk/away time.
- Fix the currently in-progress event being double-counted when it spans an export boundary, which could distort the known-vs-unknown time accounting during sync.
- Fix `report --show-exports` always printing `Total exports: 0`; it now shows the real number of exports.
- Fix failed `timew` commands (e.g. a database lock or a hook rejection) being silently ignored, which let internal tracking drift out of sync with what TimeWarrior actually recorded; such failures now raise an error instead.
- Fix global flags being rejected when running with no subcommand — e.g. `aw-export-timewarrior --log-level DEBUG` errored out instead of running `sync`.
- Fix `main()` (the CLI entry point, e.g. when called programmatically with an explicit empty argument list) falling back to the host process's `sys.argv` instead of running with defaults, since it couldn't distinguish "no arguments given" from "use the default arguments".
- Fix `--config FILE` being silently reset to the default whenever it was given before a subcommand (e.g. `--config x.toml diff ...`): the `diff` subcommand redefined `--config` under the same name as the global option, and argparse's per-subcommand default always overwrote the already-parsed global value.
- Fix `diff --hide-report` being silently ignored.
- Fix `min_lid_duration` being silently ignored when set under `[tuning]` (its documented location).
- Fix a laptop-lid boot-gap wiping out a whole day of activity: a bedtime boot-gap can span 24+ hours and was treated as away-time for the entire day. It is now clipped to the first real AFK event, after which normal activity tracking resumes.
- Fix activity blocks entered via ask-away (e.g. a tea break) being invisible to TimeWarrior when they happened while already in an away state; `diff` also left existing `~aw` blocks untouched in this case.
- Fix split ask-away events being exported twice, producing duplicate intervals and sometimes causing the following work events to be mistagged as UNKNOWN.
- Fix tmux tag matching for 0-second window events that occur just before tmux activity begins (matching now looks forward as well as backward).
- Fix flatpak Chromium not being recognized as a browser, so its visited URLs never showed up as tags in `sync` or `report`.
- Fix a terminal window not running tmux picking up tmux tags from another terminal that was running tmux, mistagging the focused window.
- Fix `diff` crashing when an existing TimeWarrior interval carried tags that violate an exclusive-group rule; it now warns and keeps the original tags.
- Fix `diff` dropping the last interval of a time range when it was still open at the range end, and being too quick to mark activity as UNKNOWN.
- Fix `diff --apply` truncating or splitting a currently-running (open) TimeWarrior interval, which it had wrongly treated as missing.
- Fix `diff --apply` never converging for intervals carrying a multi-word tag (e.g. the default `personal communication`), which was being torn into separate tags.
- Fix retag rules that remove or replace tags having no effect — only tag additions were applied.
- Fix `sync` crashing shortly after a `timew stop` when nothing was being tracked but its internal state was still "away".

### Changed
- **Breaking:** `--config FILE` must now be given before the subcommand (e.g. `--config FILE sync`, not `sync --config FILE`), like every other global flag. `diff --config FILE` (config placed after the subcommand) happened to work before as a side effect of the bug fixed above, and will now error with "unrecognized arguments" instead.

### Performance
- `diff`, `report`, `analyze` and time-bounded `sync` are dramatically faster on historical ranges: each range is now fetched and processed once instead of being repeatedly re-fetched and re-processed. A 3-hour `diff` that previously took ~12 s now completes in under 1 s.
- Reading TimeWarrior intervals now queries only the requested date range instead of exporting the entire database, so commands stay fast as your TimeWarrior history grows (automatically falls back on older `timew` versions).
- Continuous `sync` mode no longer re-fetches all events on every tick, cutting its steady-state load on the ActivityWatch server from ~20% CPU to near-idle.
- Scripted/bulk commands with hidden output no longer wait out the 10 s undo grace period, speeding up operations like bulk retagging.

## [0.6.5] - 2026-01-27

### Fixed
- Fix version 0.0.0 in published packages: move version to `[tool.poetry]` and use `dynamic = ["version"]` in `[project]` for poetry-dynamic-versioning PEP 621 compatibility

## [0.6.4] - 2026-01-27

### Fixed
- Fix CI publish workflow to use PEP 517 build with debug output (matches working plann/caldav-server-tester setup)
- Update poetry-core requirement to >=2.0.0 for compatibility with poetry-dynamic-versioning

## [0.6.3] - 2026-01-27

### Fixed
- Fix CI publish workflow to use snok/install-poetry action with poetry build (matches working aw-watcher-lid setup)

## [0.6.2] - 2026-01-27

### Fixed
- Fix CI publish workflow to use PEP 517 build (python -m build)

## [0.6.1] - 2026-01-27

### Fixed
- Fix CI publish workflow to install poetry-dynamic-versioning as plugin

## [0.6.0] - 2026-01-27

### Added
- Add warning when aw-watcher-window is not running or has stale events (helps diagnose "stuck" sync)
- Add "Waiting for new events..." message during sync sleep periods for better user feedback
- Add `UNHANDLED` result type to track events with specialized context (browser/editor/terminal) but no matching rules

### Fixed
- Fix `analyze` command undercounting unmatched events - now includes events where specialized watchers found data but no rules matched (e.g., Emacs files without editor rules)
- Fix editor file paths not showing in `report` output (was calling wrong method)

## [0.5.0] - 2026-01-12

### Added
- Add Makefile with targets for install, test, lint, format, and service management
- Add systemd user service file (`misc/aw-export-timewarrior.service`) for continuous sync mode
- Add comprehensive test coverage for tag_extractor.py (79% → 99%) and time_tracker.py (83% → 92%)

### Changed
- Rename aw-watcher-ask-away support to aw-watcher-afk-prompt (the project was forked and renamed)
- New bucket name `aw-watcher-afk-prompt` is checked first, with fallback to legacy `aw-watcher-ask-away`
- Update README with installation from source instructions and systemd service setup

## [0.4.1] - 2026-01-11

### Added
- Add configuration validation with comprehensive checks for all config sections
- Add `validate` CLI subcommand for explicit config validation
- Add retag rules application to manually edited TimeWarrior intervals in diff mode

### Changed
- Standardize config terminology: `tags` preferred over `timew_tags`, `add` preferred over `prepend`
- Legacy config keys (`timew_tags`, `prepend`) still supported for backward compatibility
- Config is now automatically validated on load with warnings/errors logged

### Fixed
- Fix CI tests failing when TimeWarrior is not installed - tests now skip gracefully
- Fix timezone-dependent test assertion in diff delete ordering test

## [0.3.0] - 2026-01-10

### Added
- Add `--format=ndjson` option for newline-delimited JSON output (one object per line)

### Fixed
- Fix `--format=json` to output a valid JSON array instead of NDJSON
- Fix diagnostic output (DRY RUN messages, "Processing time range") going to stdout - now goes to stderr for clean JSON output that can be piped to jq
- Fix `accumulator_before` in export records showing post-stickyness values - now shows pre-stickyness values for accurate visibility into what triggered the export
- Fix `_should_export_accumulator()` returning `should_export=True` with empty tags when exclusive tag conflicts eliminated all tags above threshold

## [0.2.0] - 2026-01-10

### Added
- Add GitHub Actions CI workflow (lint + test)
- Add GitHub Actions publish workflow for PyPI releases

### Changed
- Modernize pyproject.toml with full project metadata (description, license, classifiers, URLs)
- Use poetry-dynamic-versioning for automatic version from git tags
- Replace `toml` dependency with built-in `tomllib` (Python 3.11+)
- Streamline README with links to detailed documentation

## [0.1.0] - 2026-01-10

### Added
- Add support for aw-watcher-afk-prompt integration (formerly aw-watcher-ask-away) - user-entered messages during AFK periods now appear as tags
- Add overlap-based matching for afk-prompt events (handles timestamp/duration mismatches)
- Add automatic tag extraction from afk-prompt messages (multi-word messages split into tags)
- Add `--show-exports` option to report command showing export decisions with timestamps and accumulator state
- Add `--show-rule` option to report command showing which rule matched each event
- Add three-line export display: [EXPORT START], [EXPORT DECISION], [EXPORT END] for better visibility
- Add tracking algorithm documentation (docs/TRACKING_ALGORITHM.md)
- Add aw-watcher-tmux support with configurable tag extraction rules

### Fixed
- Fix interval touching-point false matches in overlap detection by using `<` instead of `<=`
- Remove `timew delete` commands to maintain continuous tracking without gaps - extra intervals are preserved and boundaries adjusted using `:adjust` flag
- Fix crash when `--apply` encounters empty command list (only comments/extra intervals)
- Disable old timestamp check in batch/diff mode to prevent spurious "skipping event" warnings for legitimate events within requested time range
- Fix assertion error in batch/diff mode when internal AFK state diverges from TimeWarrior state - normal when processing historical events
- Fix assertion error in batch/diff mode when last_activity_run_time is less than min_recording_interval - normal when processing historical events
- Fix diff comparison incorrectly marking previously synced intervals (with ~aw tag) as "extra" - now correctly identified as "previously_synced"
- Fix diff mode not applying recursive tag rules to suggested tags - commands now properly expand tags (e.g., "food" → "food", "4BREAK")
- Fix diff comparison not applying recursive tag rules to TimeWarrior tags - manually-entered tags now recognized as matching when they expand to same set
- Fix diff mode not detecting gaps in TimeWarrior coverage - now detects when suggested intervals are only partially covered and generates track commands to fill gaps (minimum 1 second to avoid timestamp precision issues)
- Fix diff mode convergence issues - now uses only `timew track :adjust` for all changes instead of `timew retag`, preventing multiple commands on same interval and ensuring stable convergence after first application
- Fix transport block ignoring active window usage when laptop resumed from suspend
- Fix analyze command not showing rapid activity in same app (e.g., quickly flipping through images)
- Fix oss-contrib over-tagging due to trailing pipe in regex config
- Fix report command getting stuck on recent events - now passes retry=0 to avoid sleeping

### Changed
- Diff mode now always runs in dry-run mode, use `--apply` flag to execute changes
- Add warning when using sync mode with historical data, recommending diff mode instead
- Extra intervals (in TimeWarrior but not ActivityWatch) are now preserved instead of deleted, with informational comments in output
