# TODO

## High Priority

## Medium Priority

- [ ] Research aw-watcher-ask-away project
  - Investigate what it does and if there's useful integration potential
  - Consider if similar functionality would be useful for timewarrior export

## Low Priority

- [ ] Add aw-watcher-lid to ActivityWatch watchers documentation
  - Repository: https://github.com/ActivityWatch/docs
  - File to edit: `src/watchers.rst` (reStructuredText format)
  - Branch: master
  - Add to "Other watchers" section
  - Example format: `:gh-user:`tobixen`/aw-watcher-lid` - Tracks laptop lid open/close and suspend/resume events
  - Submit PR after adding the entry

## Completed ✅

- [x] Fix sleep problem causing aw-server 100% CPU usage
  - Added 0.1s sleep between ticks in main() loop
  - Check tick() return value properly
  - Prevents busy-waiting when processing events
