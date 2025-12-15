# TODO

## High Priority

## Medium Priority

## Low Priority

## Completed ✅

- [x] Add aw-watcher-lid to ActivityWatch watchers documentation
  - Pull request submitted and accepted

- [x] Fix sleep problem causing aw-server 100% CPU usage
  - Added 0.1s sleep between ticks in main() loop
  - Check tick() return value properly
  - Prevents busy-waiting when processing events

- [x] Research aw-watcher-ask-away project
  - Investigated functionality: pops up dialog when returning from AFK
  - Verified it works on the system (uses tkinter 8.6)
  - Created systemd service file for automatic startup
  - Updated README with running instructions
  - Conclusion: Works well, no direct integration needed with timewarrior export
