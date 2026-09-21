# TODO

## Split multitasking sessions instead of picking one category

Observations by AI:

When events in one export window support two mutually exclusive
categories (say `4BREAK` and `4CHORES`, `4OSS` and `4RL` or two
different customers), the exporter currently has to pick one, and an
`add` that would violate an exclusive group is silently skipped
(`TagExtractor.apply_retag_rules`).  Both outcomes distort the
per-category totals, which matter more than exact start/end times.

Instead, consider splitting the interval and giving each category a share
proportional to its supporting evidence — e.g. an hour of genuine multitasking
across three tasks becomes three 20-minute intervals.  Even a crude even split
beats attributing the whole hour to one category.

Notes from doing this by hand (2026-08-03, 62 conflicting intervals):

- Evidence must be counted as *distinct signals*, not raw tag hits.  Several tags
  are mechanically derived from one another (`[tags.secondary]` mints
  `4$source_tag`, `[tags.blinking]` mints `~css_class:blinking`,
  `[tags.boat-maintenance]` folds in Norwegian synonyms), so naive counting lets
  one signal outvote a real one.
- `afk` is a strong hint: an afk interval is more likely the physical activity
  (`boat-maintenance`, `shower`) than the desk work whose tags were still in
  scope.
- `timew split @id` halves an interval and keeps all tags on both halves, which
  is a usable primitive.
- Manually adjusted intervals should lose the `~aw` marker.

---

Comments by human:

* Sometimes the solution may be to just operate on shorter intervals.  It will cause more noise in the output though.
* A solution where the activitywatch db keeps being the single source of truth and the ~aw-tag is kept and a reexport gives the same results is preferred.  The non-~aw-tagging is reserved for manual overrides, not for algorithmical transforms.
* The split (like it's currently done for the afk prompter) is a fair solution when the attention clearly has jumped between different tasks for a longer time period
* We should disregard "noise".  Working on a main activity, small breaks with other acitvities should still simply be ignored.

## `aw-report.py`: change the worklist from UNKNOWN to "no 4CATEGORY"

AI-generated:

Lives in https://github.com/tobixen/timewarrior-tools, not in this repo.

The manual worklist is `aw-report.py … UNKNOWN`, which only shows intervals the
exporter refused to categorise at all.  A rule that fires but produces no
`4CATEGORY` tag drops off that list while leaving the interval just as
unclassified.

`aw-report.py` already holds each interval's tags (`fetch_intervals_via_export`
/ `parse_timew_input`), so an `--uncategorised` mode would be a filter next to
the existing `--min-duration` skip: drop intervals that already carry a tag
matching `^4[A-Z]`.  Roughly ten lines.

Human notes:

UNKNOWN/unclassified activity and activity that does not automatically fall in under a top-category are two slightly different things, but it would probably be an idea handling both of them in the aw-report.  Today I handle it by running the myday.sh-script.
