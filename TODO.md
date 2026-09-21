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

## Emacs buffer names that are not file basenames

Observation by AI (code review, 2026-09-22):

`_emacs_candidate_filter` accepts a speculative sub-event match only when
`basename(sub_event.file)` equals the buffer name parsed out of the window
title.  Where the two legitimately differ, the widened lookahead and the
bracketing search are disabled for emacs altogether — a `rename-buffer`'d
buffer, a non-default `frame-title-format`, a `uniquify-buffer-name-style`
other than `post-forward-angle-brackets` (only that one is stripped), an
indirect buffer.  Sub-events that genuinely overlap the window event are
unaffected, so the loss is confined to the speculative band.

None of these apply to the current setup, which is why it is a note and not a
fix: the titles are the default format and the suffixes in the data are
post-forward-angle-brackets.  It would start losing matches silently on a
config change.  A fix means either recognising when a buffer name cannot be a
basename, or cross-checking `project` instead when it isn't.

The reviewer also claimed file-less sub-events (dired, magit, org-agenda) are
dropped by the same guard.  They are not: `activity-watch-mode` only sends a
heartbeat when `buffer-file-name` is non-nil, and no event in the bucket lacks
a `file`.

## Cache range is sized globally for the widest per-bucket search

Observation by AI (code review, 2026-09-22):

`CACHE_LOOKBACK_BUFFER` and `CACHE_LOOKAHEAD_MARGIN` (`main.py`) are one pair
of numbers for every bucket, sized off the widest search any bucket needs —
now `EMACS_CANDIDATE_REACH`, which took the lookback from 11 to 31 minutes.
In rolling `sync` the cache is rebuilt at least every 10 s, so window, afk,
web and tmux are all refetched over a range only the editor bucket needs.

Measured across twelve busy anchor times: 9 KiB → 30 KiB per rebuild, worst
case 53 KiB, over localhost.  Too small to justify the refactor today, but the
next reach that gets widened pays the same global cost, so the fix is a
per-bucket cache range in `EventFetcher.reset_cache`.

Correctness is not at stake in the other direction: an undersized range loses
matches, it never invents one.
