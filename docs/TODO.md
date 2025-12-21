# TODO-tasks for the exporter

## Refactoring Priorities

* Look through the REFACTORING_PRIORITES.md again.  So much work has been done now that it's probably about time to write a new document from scratch.

## More watchers

### tmux watcher

Claude claims that this is ...

✅ **COMPLETED** - https://github.com/akohlbecker/aw-watcher-tmux

... however, it hasn't been tested!

Support has been added:
- Automatic detection of tmux bucket
- Tag extraction with configurable rules (`rules.tmux.*`)
- Supports matching on session, window, command, and path
- Variable substitution: `$session`, `$window`, `$command`, `$path`, `$1`, `$2`, `$3`, etc.
- Multiple regex capture groups supported (command takes priority over path)
- Default tag `tmux:$command` when no rules match
- Full test coverage (11 tests added)
- Documentation in README.md with examples


### terminal watcher

I haven't looked into this one yet.

## Split the project into three projects:

* aw-export-tags - make a cli that can do everything aw-export-timewarrior can do, except interacting with timewarrior.
* aw-export-timewarrior - should be 100% backward-compatible, but should only contain the logic for interacting with timewarrior and leave all the work to aw-export-tags.
* timewarrior-check-tags (?) - should read config sections `[tags.*]` and `[exclusive.*]` and interact with the timewarrior database:
  * add more tags automatically if needed (we should eventually also support removing, changing and retagging)
  * deal with exclusive-rules (report/warn, fix, ask, ...?)

All three projects should be able to read the same config file.

Two config file locations should be valid - because `timewarrior-check-tags` has nothing to do with activitywatch.
