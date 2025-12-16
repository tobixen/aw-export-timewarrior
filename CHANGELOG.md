# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Fix interval touching-point false matches in overlap detection by using `<` instead of `<=`
- Remove `timew delete` commands to maintain continuous tracking without gaps - extra intervals are preserved and boundaries adjusted using `:adjust` flag

### Changed
- Diff mode now always runs in dry-run mode, use `--apply` flag to execute changes
- Add warning when using sync mode with historical data, recommending diff mode instead
- Extra intervals (in TimeWarrior but not ActivityWatch) are now preserved instead of deleted, with informational comments in output
