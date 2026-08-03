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
