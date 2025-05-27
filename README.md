# Better Categorizer and Timewarrior Companion

## Background and rationale

I found Timewarrior and Activitywatch to be the best open source tools for time tracking, but they do quite different things.  A combination would almost solve my time tracking needs perfectly.

I've had a journey into the "time tracking rabbit hole", this is covered in three blog posts - the rationale for this tool is covered in the third post.

* [General thoughts on time tracking](https://www.redpill-linpro.com/techblog/2025/05/13/time-tracking-thoughts.html)
* [Comparision of different software](https://www.redpill-linpro.com/techblog/2025/05/22/time-tracking-software.html)
* [Experiences using Timewarrior and Activitywatch](TODO)

## (Optional) Dependencies

Timewarrior needs to be installed (but I'm planning to refactor it so the Timewarrior part will not be so hard-coded), editor watcher(s) should to be running, and browser watcher(s) should also be running.  Support for more watchers will probably come at some future point. This has so far been tested with Emacs, Firefox and Chromium (TODO: add links to the watchers).

## What does it do

Briefly, this tool can do two things:

* More advanced categorization algorithms than what can readily be found in Activitywatch
* Auto-exporting activities from Activitywatch to Timewarrior

### Categorization algorithms

This should probably be moved out to a separate tool, but currently it's a bit hard-coded to Timewarrior.  Timewarrior don't use terms like categories, projects, tasks etc - it's all about tags, and up to the user to figure out how to use the tags, hence the categorization is tag-based.  The current implementation also stores intermediate data in timew, picks it out and expands on it (ugly design, should be redone).  Rules are currently stored in `$HOME/.config/activitywatch/aw-export-timewarrior/aw-export-timewarrior.toml`.  Some fallback-rules on things that can be ignored are currently hard-coded in the script, but should be moved to the config.

There are currently three kind of rules:

* Tags - simple retagging rules, i.e. if running `timew start tea`, it may retag it into `4break afk tea`.  This does not touch activitywatch at all and could be split into a separate project.  Anyway, it eases the definition of the other rules as it's not needed to add all the tags to every rule.  Currently it can only add tags, but I'm intending to make it possible rewriting tags as well.

* Browser rules.  Currently it takes only take one input, `url_regexp` and can add tags accordingly.

* Editor rules.  It takes two inputs, `project` (exact match on what the editor reports as "project") and `path_regexp` (regexp match on the full file name path).

I'm planning to support extentions - for instance, you may want to write up some special browser rule logic applying to some specific URL and specific page title, do an external look-up to find the appropriate tags, etc - advanced logic is better done in Python than in a configuration language like toml.

### Export algorithm

Currently it does support rewriting old Timewarrior history.  The export algorithm works like this:

* The starting time for the current activity in Timewarrior is used (Timewarrior gaps are not supposed - *all* the time should be tracked
