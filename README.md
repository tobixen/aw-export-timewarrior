# Better Categorizer and Timewarrior Companion

Be aware, this is not a mature project, there will be dragons, there are quite some debugger breakpoints and asserts in the code.  If you know some Python, like Activitywatch and use Timewarrior, then I'd encourage you to look into it and contribute.  I'm available by email tobias@redpill-linpro.com as well as by the GitHub issues if you should have any questions or suggestions.

Be aware, that this README may not reflect the latest version of the code (TODO: look through things!)

## Background and rationale

I found Timewarrior and Activitywatch to be the best open source tools for time tracking, but they do quite different things.  A combination would almost solve my time tracking needs perfectly.

I've had a journey into the "time tracking rabbit hole", this is covered in three blog posts - the rationale for this tool is covered in the third post.

* [General thoughts on time tracking](https://www.redpill-linpro.com/techblog/2025/05/13/time-tracking-thoughts.html)
* [Comparision of different software](https://www.redpill-linpro.com/techblog/2025/05/22/time-tracking-software.html)
* Experiences using Timewarrior and Activitywatch ... TODO, not published yet

## (Optional) Dependencies

Timewarrior needs to be installed (but I'm planning to refactor it so the Timewarrior part will not be so hard-coded), editor watcher(s) should to be running, and browser watcher(s) should also be running.  Support for more watchers will probably come at some future point. This has so far been tested with Emacs, Firefox and Chromium (TODO: add links to the watchers).

## What does it do

Briefly, this tool can do two things:

* More advanced categorization algorithms than what can readily be found in Activitywatch
* Auto-exporting activities from Activitywatch to Timewarrior

### Categorization rules

I believe that part of the work I've done here may be relevant for AcitvityWatch users even without using Timewarrior, and other parts of the work may be relevant for Timewarrior users even if they don't use ActivityWatch.  Perhaps the project should be split ... but I leave it as this for now.

Timewarrior don't use terms like categories, projects, tasks etc - it's all about tags, and up to the user to figure out how to use the tags.  Rules are currently stored in `$HOME/.config/activitywatch/aw-export-timewarrior/aw-export-timewarrior.toml`.  Some fallback-rules on things that can be ignored are currently hard-coded in the script, but should be moved to the config.

Those rules are currently supported:

* Exlusive rules (`exclusive.${id}`) - some tags should not be combined (like, in my system I do have some main categories, like work and break - and I cannot be working and having a break at the same time - and I cannot be afk and not-afk at the same time, etc).  Takes one input `tags` with a list of tags that are mutually exclusive.

* Tags (`tags.${id}`) - simple retagging rules, i.e. if running `timew start tea`, it may retag it into `break afk tea`.  This does not touch ActivityWatch at all, it's only about Timewarrior entries getting extra tags.  It eases the definition of the other rules as it's not needed to add all the tags to every rule.  Currently it can only add tags, but I'm intending to make it possible rewriting tags as well.  Takes `source_tags` and `add`, both lists of tags.

* Browser rules (`rules.browser.${id}`).  Currently it takes only take one input, `url_regexp`.

* Editor rules (`rules.editor.${id}`).  It takes two inputs, `project` (exact match on what the editor reports as "project") and `path_regexp` (regexp match on the full file name path).  If both are given, the union of matches is utilized (OR-logic applies).

* App rules (`rules.app.${id}`).  Takes two inputs, `app_names` and `title_regexp`.  Both has to pass (AND-logic).

The three latter takes the output parameter `timew_tags` and may start a new Timewarrior entry with the given tags.  For each category, currently the first match will be used, but it should probably be redone so that it uses a union of all tags matching.

I'm planning to support extensions - for instance, you may want to write up some special browser rule logic applying to some specific URL and specific page title, do an external look-up to find the appropriate tags, etc - advanced logic is better done in Python than in a configuration language like toml.

### Configuration tunables

There are some configuration hardcoded at the top of the script.  TODO: should be documented and moved to the toml-file.

### "Stickyness" and tuning

This is difficult!

General ideas:

* Very short visits to windows should be completely ignored (I'm not sure about your working patterns, but I frequently let the mouse cursor pass active windows, visit browser tabs searching for the right one, etc).
* Some "noise" should be ignored.  You don't want this script too frequently changing your activity status if you've set it manually.
* There will be lots of events that cannot easily be categorized, i.e. work on the command line - unless we have strong hints on something else, we should assume you're still working on the same.  This means you need to have an eye on the current tracked activity and change it manually if this script won't do it for you.
* Sometimes a work task involves frequent switching between windows - tags from both windows may apply in such situations.  Meaning we have to store tags internally for a while before dumping them to timewarrior.

Current logic:

* `IGNORE_INTERVAL=5` seconds by default, allows any visit to a window for less than 5s to be considered as noise
* `MIN_RECORDING_INTERVAL=60` seconds is the very minimum time between each distinct entry recorded in timewarror.
* Whenever some tags have been observed for accumulatively more than `MIN_RECORDING_INTERVAL`, we should consider to start some new activity.  All tags observed for more than `MIN_TAG_INTERVAL=30` seconds over the last open period applies.  If any of those tags are missing from the current activity tracking, `timew start` is appliced with the new list of tags.  It's possible to configure in the rule files that some tags are mutually exclusive, then they will not be combined.
* We should have some stickyness - the records should not be completely reset when sending tags to timew.  Rather, multiply all existing tags in the accumulator with `STICKINESS_FACTOR=0.1` (Considering removing it - it breaks the requirement that the script should always to the same if doing `timew undo` an arbitrary number of times and then restarting the script)
* If `timew start` has been run manually, the accumulator should be reset and populated with tags from the manual run.
* If a single window event lasts for more than, say, `MAX_MIXED_INTERVAL=300` seconds and can be identified with tags, then ignore all previous activity and treat it independently (if you did something quickly between two well-defined tasks, then that time will be attributed to the previous work task).

### Export algorithm

Currently it does support rewriting old Timewarrior history.  The export algorithm works like this:

* The starting time for the current activity in Timewarrior is used as a starting point (Timewarrior gaps are not supposed - *all* the time should be tracked).  It's currently not possible to use the exporter to rewrite the Timewarrior history (but it could be done).
* At three points of the code the retagging-algorithm kicks in - it's at startup, after starting a new activity, and before checking if it's relevant to start a new activity.  The retagging-algorithm will read retagging rules from `config['tags']` and add more tags if the configuration fits the tags given.
* All window events and afk-events will be checked.  For window-events coming from a browser, the corresponding browser-event (if any) will be looked up, and the URL checked towards the rules given.  Sort of the same with editor events.  Other events will be matched towards app-rules.
* If any of the tags that are found by the rules are not included in the current tracking, it's considered that a new activity have started, and `timew` will be invoked with the new tags and the timestamp from the event.  Duration is (as for now) ignored (and for good reasons, one may frequently switch i.e. between a browser, terminal windows and an editor while working).

## User interactions

Currently the program is tossing the user into python debugger breakpoints every so often, but this will go away before making a release.  The general idea is that all user interaction is done through the config file and through `timew`-commands:

* `timew undo` - will undo the last actions from the script.
  * If the script does anything weird, then `timew undo` may remove the entry, and keep tracking the previous entry.  However, this only works if it's a one-off.  If new events comes in and the rules kicks in, the script will continue insisting on doing a `timew start`.
  * If you stop the script and then undo all the work it's done through `timew undo`, and start the script again it will go through the timeline again.  Useful if you've changed some configuration.
* `timew tag` - will add tags to the current activity. Those tags will persist all until a new activity is started.
  * Useful for adding details to some activity.  Particularly the AFK-activity - Activitywatch doesn't know anything on what you've done when you're not at the laptop.  So if I was varnishing the boat while being afk, I can do `timew tag varnishing`.  Or I can proactively do a `timew start afk varnishing` just when leaving the laptop - since it has the afk-tag, it won't be touched when the afk-watcher figures out you're afk.
  * Special tags exists:
    * `override` - the tracking will persist until manually stopped, no matter what the watchers find.
	* `manual` - unknown activity will be ignored.  (Currently an "unknown" tag is slapped on if no tags are found within two minutes - though I'm considering to change this).
	* I'm considering to add more special tags.  Probably the special tags should be marked out somehow, like a special prepending.

## Configuration and tweaking

### Installing watchers

TODO: links to the editor and browser watchers, as well as aw-watcher-window-wayland.

### Fixing the terminal window title in bash

I'm using bash.  To make sure the window title of my terminal windows shows details on what I'm doing in the terminals, I added this to my `.bashrc`:

```bash
# Function to set window title to the running command
set_window_title() {
  # Get the currently running command from BASH_COMMAND
  local cmd="${BASH_COMMAND}"
  # Avoid setting the title for the prompt itself
  # (optionally filter out some commands)
  printf '\033]0;%s\007' "$cmd"
}

# Set the DEBUG trap to call the function before each command
trap 'set_window_title' DEBUG

source /usr/share/git/completion/git-prompt.sh

PS1="${PS1}"'\033]0;\u@\h:\w$(__git_ps1)\$ ${BASH_COMMAND}\007\]'
```

Dependent on your setup, this may crash with existing provisions to set window title.  YMMV.

