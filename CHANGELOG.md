# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-01-10

### Added
- Add `--format=ndjson` option for newline-delimited JSON output (one object per line)

### Fixed
- Fix `--format=json` to output a valid JSON array instead of NDJSON
- Fix diagnostic output (DRY RUN messages, "Processing time range") going to stdout - now goes to stderr for clean JSON output that can be piped to jq
- Fix `accumulator_before` in export records showing post-stickyness values - now shows pre-stickyness values for accurate visibility into what triggered the export

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
- Add support for aw-watcher-ask-away integration - user-entered messages during AFK periods now appear as tags
- Add overlap-based matching for ask-away events (handles timestamp/duration mismatches)
- Add automatic tag extraction from ask-away messages (multi-word messages split into tags)
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
