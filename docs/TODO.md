# TODO - aw-export-timewarrior

## Medium priority

### Think more about the config file

My personal config file is getting huge.  That's to be expected when one is trying to track everything ... but could the config format be optimized?

### Think more about the accumulator, mutually exclusive tags, multitasking and task switching

Today there are two code paths for deciding tags, it's "single window for more than X minutes" and "tag accumulator".  In addition we have a third code path for ignoring very short events from Timewarrior.  I've currently disabled that logic in my local config, probably the latter logic should be removed completely.   Probably we should have only one code path instead of two.

Below are some use cases and wanted behaviour (those should probably be documented in the algorithm document).  We should think through how the algorithms may be tuned for optimal behaviour.  Today it's possible to configure sets of mutually exclusively tags.  In my configuration, "primary categories" and "secondary categories" are configured like that.  Probably the algorithms should be changed so that at the point a tag is observed that is incompatible with the current tagging, the old tags should be thrown away and a new export interval should begin (but it's for sure needed with some "grace time" here, merely checking what's in a browser tab and closing it should not cause new tagging).   Maybe it also makes sense to be able to cnofigure that it's *required* with one tag from the set?  For me, that would make sense for the "primary category" (and some of my "primary categories" also requires a "secondary category" to be set).

#### Single-tasking

I'm working on ONE task for an hour, and while doing that I browse github, I edit files, I have some sessions wit Claude, I do research through Google, Perplexity, etc.  Some of those things won't have matcing rules - oter things may have rules giving a bit different tags, but almost all of them having the main category tag, and most of them having the correct secondary category tag.  There will be some noise as my desktop is still cluttered with unrelated windows and browser tags, brief distractions, terminal windows with the wrong cwd etc yielding completely other tags.  Some activity may produce tags that don't include main and secondary categories.

**Wanted behavour:** The whole hour period should be tagged with all applicable tags.  The "noise" should be ignored, and the unmatched activity should not break the tagging.

**Current behaviour:** Not too far off.  The work period will most likely be broken up into smaller intervals with a little bit different tagging, but not too bad.

#### Multi-tasking

For a period I'm rapidly switching my attention between two or more tasks - say, for one hour I'm doing some work on a puppet project, it involves waiting for pipeline runs and deployments every now and then (tags: 4EMPLOYER, 4acme, puppet, ...), while waiting for it I write a story about my previous weekend activities in my personal diary (tags: 4ME, 4personal-admin, diary, ...).  75% of the hour is spent on work, 25% of the time on the journalling.

**Wanted behaviour**: The main thing is that when summing up the time spent on each task at the end of the day, the sum for each category should approximately reflect how much time I spent on it.  Some alternatives:
 * The "correct" approach is to log even the smallest intervals and start a new interval as soon as incompatible tags appears.  This may also be the simplest implementation.  I'm a bit concerned on scalability when timew is overloaded with hundreds of intervals during a single work day session, but perhaps I shouldn't be.
 * The "data compression method" alternative is to recognize the whole interval as a "multi tasking interval", split it up into two "artificial" intervals, 45 minutes recorded on 4EMPLOYER, 15 minutes recorded on 4ME.
 * The "data supression method" alternative is to just discard some of the data, somehow arbitrarily allow some activity to be recorded as work even if I was doing private things and vice versa.

**Unwanted behaviour:** Tag mixing, say, the interval is tagged both with 4customer1 and 4customer2.  This may make sense, it may be legitimate to bill the customer also for the time spent waiting for pipelines, and it may be legitimate to get salary for the time one spends reading news while waiting for pipeline runs.  However, for one thing this produces data that can be quite hard to process by reporting scripts, and it's also bad to slap "4ME" over the whole hour when only a quarter of the attention was spent on the private work task.

**Other consideration:** Humans are generally not very good at multi-tasking, quite much of the time will most likely not be spent on either of the tasks, but for mental context switching.

**Current behaviour:** "Data supression" mostly - at least it is or was intended that no interval less than a minute or two should be recorded in timewarrior.  There is logic in the code for shedding data if tags are incompatible.  However, quite often one ends up with periods with sligthly conflicting tags - tag combinations that aren't explicitly forbidden in the configuration, but which doesn't make sense anyway.

#### Task switching

Say, I work on task A between 13:00 and 14:00 (tags A, python) and task B for the next hour (tags B, python) and A and B being explicily configured as mutually exclusive.

**Wanted behaviour:**:
* The exported tagging should change exactly at 14:00.
* diff, report etc should also reporting on a new activity exactly at 14:00, for any values of `--from` and `--to` that spans over the activity switch.
* If doing a continuous `aw-export-timewarrior sync` and then the next day does an `aw-export timewarrior diff --day=yesterday apply`, then

**Current behaviour:** I believe that if there is one window activity for a full hour followed by another lasting for a full hour, then things will work pretty well.  The problem is if there is a mix of activity giving slightly different tasks, then one may hit some weird corner cases:
* A short interval spanning the 14:00 timestamp having "python" as task but neither A nor B (due to the accumulator logic).
* I don't think one would always get 14:00 as the exact timestamp for the transition
* I think the `report`, `diff` and `sync --dryrun`  commands may give slightly different transition timestamps dependent on what is given in `--start` and `--end`.
* I think that in some circumstances a continuous `aw-export-timewarrior sync` may give different timestamps and taggings than an `aw-export-timewarrior sync --day` or `aw-export-timewarrior diff --apply`

### Manual operations

* The logic in aw-watcher-afk-prompt (formerly aw-watcher-ask-away) should possibly also be applicable when not-afk.  Should consider to ask for activity when the hints in the activitywatcher data is weak
* Should be easy to specify that "activity with tags X today was Y".  Like, feh was used for sorting inventory, etc.


## Low Priority


### Reconsider the tests

There are tons and tons of test code, and still lots of bugs have been found and fixed.

Probably quite much of the tests are redundant, probably we don't need this many tests, probably they could be consolidated.

Would it make sense to have a fixture containing a semi-large dataset containing real data as well as data known to have caused problems earlier, combined with a relatively large ruleset, and then verify that all the different commands will do as predicted with this data set and produce the same timeline?

**Analysis (Jan 11, 2026):** Reviewed 35 test files (~12,000 lines). Found that:
- Bug-specific test files (10 files, ~2300 lines) test distinct subsystems and are well-organized
- Time tracker test files test different implementations (DryRunTracker vs TimewTracker), not duplicates
- Consolidated shared fixtures for 3 report test files into conftest.py (saved ~16 lines)

The comprehensive fixture approach remains a future option but the current test structure is reasonable.

### Performance optimizations

- Event caching in `get_corresponding_event`
- Batch processing for historical sync

## Future Directions

### More watchers

#### terminal watcher

Not yet investigated.

### Interactivity

* Add an interactive way to create/edit rules in the configuration file:
 - Show unmatched events and prompt for tags
 - Suggest rules based on patterns (URL, app name, file path)
 - Write rules directly to config file
 - Could be CLI wizard or TUI interface

### Rename to aw-tagger

Rename project from `aw-export-timewarrior` to `aw-tagger` to reflect the core value proposition: rule-based categorization for ActivityWatch.

Key changes:
- Add meta watcher output (write tags to `aw-watcher-tags` bucket)
- Make Timewarrior an optional output
- Restructure CLI: `aw-tagger sync`, `aw-tagger timew sync`, etc.

See **[PROJECT_SPLIT_PLAN.md](PROJECT_SPLIT_PLAN.md)** for detailed implementation plan.

---


---

*See also: `docs/CODE_REVIEW.md` for detailed code review and improvement suggestions.*
*See also: `docs/TRACKING_ALGORITHM.md` for detailed explanation of the tracking algorithm.*
