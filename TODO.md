# TODO

## Split multitasking sessions instead of picking one category

When events in one export window support two mutually exclusive categories (say
`4BREAK` and `4CHORES`, or `4BOAT` and `4RL`), the exporter currently has to pick
one, and an `add` that would violate an exclusive group is silently skipped
(`TagExtractor.apply_retag_rules`).  Both outcomes distort the per-category
totals, which matter more than exact start/end times.

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

## Warn about self-contradictory exclusive groups

An exclusive group that contains tags another rule deliberately adds together is
silently self-defeating: it turns a legitimate combination into a violation *and*
suppresses the intended `add`.  This bit `exclusive.secondary` containing both
`safemate` and `safemate-stage` while `[tags.safemate]` maps the latter to the
former — it suppressed the umbrella `safemate` tag and minted bogus
`4safemate-stage` tags.  `validate` could detect this statically: for each
exclusive group, check whether any `[tags.*]` rule can produce two of its members
from a single source tag.

## Cache the overlap probe in `start_tracking`

Every `start_tracking()` call shells out to `timew export` over a 7-day window
to decide whether `:adjust` would destroy foreign data — or, on an install
where ranged export is unsupported, over the entire database, parsed and
filtered in Python.  A batch run (`tick(process_all=True)`) calls it once per
activity block, so it is O(activity blocks) extra subprocesses on a path whose
fetch cost was deliberately optimised before.  Nothing caches it: the existing
`_current_cache`/`cache_ttl` covers only `get_current_tracking`.  Either
memoise `get_intervals` per tick behind that same TTL, or pass in the interval
list the caller already holds.

## Editor sub-events are missed when the watcher heartbeat lags

`get_corresponding_event()` looks for a sub-event overlapping the window event,
widening by `EVENT_MATCHING_BUFFER_SECONDS` (15 s) if nothing is found, and only
falls back to the nearest event when `fallback_to_recent` is set — which only
the tmux path does.

`activity-watch-mode` (the Emacs watcher) pulses on a timer, so its event can
start well after the window-focus event that it belongs to.  In a sample of 182
window events naming an editor buffer, 46 had no emacs event within the buffer
— the nearest one was +39 s to +82 s away, with the file path present in the
bucket all along.

Options: widen the editor lookahead, or make the buffer per-subtype (a
slow-heartbeat editor needs more than 15 s).  `fallback_to_recent` on its own is
*not* enough: only its lookback is generous (10 min), while its lookahead is the
same `EVENT_MATCHING_BUFFER_SECONDS` that already failed.  Worth checking
upstream whether `activity-watch-mode` should emit an event on buffer switch
rather than only on its pulse timer — that would be a `fix-other` job on
https://github.com/pauldub/activity-watch-mode

## `aw-report.py`: change the worklist from UNKNOWN to "no 4CATEGORY"

Lives in https://github.com/tobixen/timewarrior-tools, not in this repo.

The manual worklist is `aw-report.py … UNKNOWN`, which only shows intervals the
exporter refused to categorise at all.  A rule that fires but produces no
`4CATEGORY` tag drops off that list while leaving the interval just as
unclassified.

`aw-report.py` already holds each interval's tags (`fetch_intervals_via_export`
/ `parse_timew_input`), so an `--uncategorised` mode would be a filter next to
the existing `--min-duration` skip: drop intervals that already carry a tag
matching `^4[A-Z]`.  Roughly ten lines.
