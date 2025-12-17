# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Add support for aw-watcher-ask-away integration - user-entered messages during AFK periods now appear as tags
- Add overlap-based matching for ask-away events (handles timestamp/duration mismatches)
- Add automatic tag extraction from ask-away messages (multi-word messages split into tags)

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

### Changed
- Diff mode now always runs in dry-run mode, use `--apply` flag to execute changes
- Add warning when using sync mode with historical data, recommending diff mode instead
- Extra intervals (in TimeWarrior but not ActivityWatch) are now preserved instead of deleted, with informational comments in output
