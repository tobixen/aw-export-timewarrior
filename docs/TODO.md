* ~~The "concurrent" issue needs to be solved.  The program should act snappy (currently it doesn't, because it skips the current event from the watcher), yet it should be consistent and idempotent.  For the "current" event, we do not know the final duration - in each loop we'll get the same event out, but with increased duration.  This has to be handled well.~~
  **SOLVED**: Implemented incremental processing of current events. The program now tracks the current ongoing event separately and processes only the incremental duration on each loop iteration, making it both snappy (immediate processing) and idempotent (no duplicate work).
* Deal with "Quick wins" and "High-priority refactorings" in REFACTORING_PRIORITIES.md
* fix precommit for ruff
* We need some idempotence tests: 
  * adding data with sync and then later doing a diff, the diff should show nothing.  I think we already have this test and it's passing, but my real-world experience is that there are always differences, I should try to catch this with some test data.
  * When having a significant diff and running all the commands, another diff should return that everything is OK.
* Algoithm need thorough QA.  We should make functional tests asserting idempotence.
* Improved AFK watchers.  See and fix `test_lid_afk.py`
* `test_cli.py` should be made.
* tmux watcher
* terminal watcher
* Rebrand from "timewarrior exporter" to "tags exporter", and let the timew backend export be optional.  The "export" method needs to be renamed to "export_testdata"
