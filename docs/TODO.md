* [EXPORTER REFACTORING PLAN](EXPORTER_REFACTORING_PLAN.md)
* "today" and "yesterday" should work in the time parser.
* Deal with "Quick wins" and "High-priority refactorings" in REFACTORING_PRIORITIES.md
* fix precommit for ruff
* We need some idempotence tests:
  * adding data with sync and then later doing a diff, the diff should show nothing.  I think we already have this test and it's passing, but my real-world experience is that there are always differences, I should try to catch this with some test data.
  * When having a significant diff and running all the commands, another diff should return that everything is OK.
* Algoithm need thorough QA.  We should make functional tests asserting idempotence.
* Improved AFK watchers.  See and fix `test_lid_afk.py`
* `test_cli.py` should be made.
* tmux watcher - https://github.com/akohlbecker/aw-watcher-tmux
* terminal watcher
* Rebrand from "timewarrior exporter" to "tags exporter", and let the timew backend export be optional.  The "export" method needs to be renamed to "export_testdata"
* Deal with other things from REFACTORING_PRIORITIES.md
