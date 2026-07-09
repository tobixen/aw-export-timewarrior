# Code Review: aw-export-timewarrior (full codebase)

**Review Date:** 2026-07-09
**Reviewer:** Claude (AI code review, `/code-review` high effort)
**Scope:** Entire codebase (`src/aw_export_timewarrior/`, ~8 600 lines), not a diff.
**Method:** 8 independent finder angles (line-by-line scans, invariant audit,
cross-file contract tracing, reuse/simplification/efficiency/altitude/conventions),
~28 deduplicated candidates, each verified against the code. Verdicts:
**CONFIRMED** = demonstrable from the code (some verified by execution),
**PLAUSIBLE** = realistic but depends on runtime state, **REFUTED** = dropped.

See also `CODE_REVIEW.md` (December 2025 review, separate effort).

**Fix status:** findings are marked ✅ FIXED inline as they're resolved (with a
regression test in each case). As of 2026-07-09: #1-#5, #9 fixed.

---

## Top findings (ranked by severity)

### 1. ✅ FIXED — 🔴 None-deref crash in AFK state handling — `main.py:1044` (CONFIRMED)

`check_and_handle_afk_state_change` dereferences `self.timew_info["tags"]`
without a None guard, and `timew_info` stays `None` in sync mode when
TimeWarrior has no active interval: `set_timew_info(None)` keeps it `None`
(`main.py:1662-1665`) and `tick()`'s retry path returns `None` again when
nothing is being tracked.

**Failure:** start `sync` after `timew stop`; the first afk event sets
`AfkState.AFK` via the UNKNOWN branch, then the next window event reaches
line 1044 → `TypeError: 'NoneType' object is not subscriptable`, crashing the
sync loop.

### 2. ✅ FIXED — 🔴 `retag()` only adds tags, never removes — `timew_tracker.py:155` (CONFIRMED)

`TimewTracker.retag()` runs `timew tag @1 <tags>`, which only ADDS tags, while
its docstring and callers assume the new set REPLACES existing tags.

**Failure:** any `[tags.*]` rule using `remove` or `replace` (both supported,
`tag_extractor.py:783-795`): `retag_current_interval` computes `new_tags`
without the removed tag, `timew tag` keeps it, then the assertion at
`main.py:978` (`set(timew_info['tags']) == new_tags`) raises `AssertionError`
and crashes live sync; with assertions off, tags silently never converge.
Fix direction: diff old vs new sets and issue `timew untag` for removals.

### 3. ✅ FIXED — 🔴 Stale current-tracking cache hides manual `timew start` — `timew_tracker.py:106` (CONFIRMED)

`get_current_tracking()`'s `_current_cache` is only invalidated by the
exporter's *own* `_run_timew` calls — there is no TTL — so a manual
`timew start` run by the user between exports is invisible.

**Failure:** user runs `timew start meeting override` in another terminal
mid-sync: every per-event `retag_current_interval` call returns the stale
cached interval, the manual-tracking guard in `set_timew_info`
(`main.py:1674-1684`) never fires, and the next automatic export issues a
`timew start <auto tags>` that truncates the user's manual interval.

### 4. ✅ FIXED — 🔴 Manual-start detection violates the accumulator invariant — `main.py:1682` (CONFIRMED)

The manual-`timew start` detection path calls
`set_known_tick_stats(start=..., manual=True, tags=...)` with the default
`reset_accumulator=False`, advancing `last_known_tick` without resetting
`known_events_time` (`state.record_export(reset_stats=False)`).

**Failure:** sync mode with ~120 s accumulated `known_events_time`; user runs
`timew start foo`: `last_known_tick` jumps forward but the accumulator
survives, so at the next export `tracked_gap < known_events_time` →
`ensure_tag_exported`'s breakpoint/`AssertionError` fires.

### 5. ✅ FIXED — 🔴 AFK merge can shrink the merged event — `event_pipeline.py:331` (CONFIRMED)

`_merge_consecutive_afk_events` extends the merged event with
`current["_end"] = event_end` instead of `max(current_end, event_end)`, so a
same-status event *contained* inside the merged span rewinds its end.

**Failure:** AFK event `[09:00, +60min]` followed (sorted by start) by a
contained heartbeat `[09:10, +5min]`: gap is negative (≤300 s), same status →
`_end` rewound from 10:00 to 09:15; the 09:15–10:00 AFK tail is lost, may
then fall under the `max_mixed_interval` filter, and window "ghost" events in
that period are no longer split away. Overlapping AFK periods are explicitly
acknowledged as occurring (`main.py:1035`).

### 6. 🔴 Multi-word tags corrupted by fix commands — `compare.py:525` + `main.py:504` (CONFIRMED)

`generate_fix_commands` joins tags space-separated with no quoting, and
`run_comparison` applies commands via `command_part.split()`.

**Failure:** the shipped default config contains the tag
`"personal communication"` (`config.py:239`): `diff --apply` builds
`timew track ... personal communication :adjust` and `split()` records two
separate tags, so every subsequent diff sees `different_tags` again and never
converges. Use `shlex` quoting/splitting or pass an args list.

### 7. 🟠 Rolling event cache defeats the sub-event retry loop — `aw_client.py:156` (CONFIRMED)

With a `cache_range` active, `get_events` never refetches a cached bucket, so
`get_corresponding_event`'s sleep-and-retry loop re-reads the same stale
snapshot — and live sync installs a rolling cache too (`main.py:1781`),
making the retry mechanism a no-op.

**Failure:** a window event completes just before the per-tick cache rebuild
and its browser URL event reaches aw-server a few seconds later: each of the
6 retries sleeps ~15 s then re-reads the cache populated at tick start
(`cache_end` is `now+16s` anyway), so ~90 s is wasted and the event is
permanently exported without URL-based tags — a silent regression versus the
pre-cache behavior where each retry hit AW directly. Fix direction: evict the
bucket from `_events_cache` (or bypass the cache) on the retry path.

### 8. 🟠 Ongoing TimeWarrior intervals invisible to diff — `compare.py:159` (CONFIRMED)

`compare_intervals` requires `tw.end` when searching overlapping intervals,
so the currently-open interval is excluded and its time is classified as
"missing". Related: `timew_tracker.py:195` `get_intervals` similarly drops an
ongoing interval that started before the requested range (all in-range
branches require `interval_end`).

**Failure:** run `diff --apply` while timew is actively tracking correct tags
for the last hour: the open interval is invisible to the overlap search, the
whole span lands in `result["missing"]`, and `generate_fix_commands` emits a
`timew track <start> - <end> :adjust` that truncates/splits the live interval.

### 9. ✅ FIXED — 🟠 AFK gap workaround manufactures false gaps — `event_pipeline.py:275` (CONFIRMED)

`_apply_afk_gap_workaround` measures gaps from the *previous* event's end
(events sorted by start only), not the max end seen so far, so an event
nested inside a longer one manufactures a false gap that becomes a synthetic
afk event.

**Failure:** overlapping AFK events: not-afk `[10:00, +100min]` containing
heartbeat `[10:10, +10s]`, next event at 11:45 — the gap is measured from
10:10:10, producing a synthetic `{'status': 'afk'}` event over 10:10–11:45
even though the user was demonstrably active until 11:40; active time is
exported as afk. Track `max(end)` over the sweep instead.

### 10. 🟠 `@list` regexp expansion breaks anchors and metacharacters — `config.py:75` (CONFIRMED by execution)

`expand_regexp` substitutes `@list` with a bare `'|'.join(items)` — no
`(?:...)` grouping and no `re.escape`.

**Failure:** `lists.projects = ['foo', 'bar']` with
`title_regexp = '^@projects: (.*)'` expands to `^foo|bar: (.*)`, which parses
as `(^foo)|(bar: (.*))` — verified: it matches `'unrelated bar: secret'`
despite the anchor, and matches `'foo: x'` without capturing group 1 (so `$1`
tag templates silently vanish). An item like `'c++'` yields an invalid
regexp. Fix: `'(?:' + '|'.join(re.escape(i) for i in items) + ')'` (escaping
assuming list items are literals).

---

## Additional confirmed findings (below the top-10 cut)

- **`event_pipeline.py:44`** — `min_lid_duration` is read from the config top
  level, but the shipped default config places it under `[tuning]`
  (`config.py:219`) and `config_validation.py:45` validates it as a tuning
  param, so a user tuning it per the docs is silently ignored (always 10.0).
- **`cli.py:40`** — `diff --hide-report` is silently dropped: no
  `hide_report → hide_diff_report` entry in `create_exporter_from_args`'s
  mapping. Verified by execution.
- **`cli.py:266`** — the diff subparser re-defines `--config` with the same
  dest as the global option, so `aw-export-timewarrior --config my.toml diff ...`
  ends up with `args.config == None`. Verified by execution.
- **`cli.py:752`** — the implicit-sync re-parse prepends `sync` to argv, but
  global flags aren't accepted after the subcommand, so
  `aw-export-timewarrior --log-level DEBUG` (no subcommand) exits with an
  argparse error instead of running sync. Verified by execution.
- **`timew_tracker.py:76`** — `_run_timew` uses `check=False` and no caller
  inspects the returncode, while `ensure_tag_exported` advances
  `last_known_tick` and resets stats *before* `start_tracking`; a failed
  timew command (db lock, hook failure) silently loses the interval with no
  retry or rollback.
- **`report.py:891`** — the summary counts `row_type == "export"` but only
  `export_start`/`export_decision`/`export_end` rows are produced, so
  "Total exports" never prints.
- **`main.py:1249` / `main.py:1577`** (PLAUSIBLE) — the March 2026 clipping
  fix doesn't cover `_process_current_event_incrementally` (adds unclipped
  duration), and clipping rewrites `event["timestamp"]`, breaking the
  `current_event_timestamp` dedup key; both are over-count paths, mostly
  reachable via finding #4.
- **`event_pipeline.py:616`** (PLAUSIBLE) — window events are split against
  the ask-away-*extended* AFK events, but the AFK events re-added to the
  stream are the original unextended ones (`afk_window_events` is built at
  line 158, before the extension at 166), so the idle-countdown window
  (~2 min) contains no events and its time is attributed to the previous
  interval's tags rather than afk/ask-away.

**Refuted:** the `fallback_to_recent` argument dropped in
`get_corresponding_event`'s retry recursion (`aw_client.py:276`) is
unreachable — both tmux call sites pass `ignorable=True`, which disables the
retry path entirely. (Still worth fixing the call signature while touching
the file.)

---

## Cleanup findings (reuse / simplification / efficiency / conventions)

All verified structurally; several were found independently by multiple
review angles.

### Duplication / reuse
- `tag_extractor.py:163` vs `:624` — `get_tmux_tags` duplicates ~50 lines of
  `_fetch_tmux_sub_event` (terminal-apps fallback set, tmux bucket lookup,
  title-indicates-tmux verification). `get_tmux_tags` should call
  `_fetch_tmux_sub_event`.
- `tag_extractor.py:328-351` vs `:700-715` — per-subtype sub-event specs
  (editor app list, bucket patterns, browser newtab skip rule) duplicated
  between tag extraction and `get_specialized_context`; commit c05f48d
  centralised only `BROWSER_APPS`. Generalize to one spec table consumed by
  both paths.
- `main.py:1849-1948` — legacy module-level `get_timew_info`/`timew_run`/
  `timew_retag` parallel `TimewTracker`; still called by `retag.py` and the
  retag flow, bypassing the tracker's cache invalidation. Fold onto
  `TimewTracker`.
- `compare.py:56` — `fetch_timew_intervals` re-implements
  `TimewTracker.get_intervals` (which declares itself "the ONLY place that
  knows about TimeWarrior commands"); the two copies have already drifted in
  range semantics.
- `main.py:738-834` + `:1554-1562` — the ask-away interval-overlap predicate
  is implemented four times; extract one
  `_overlapping_ask_away_events(event, ...)` helper.
- `main.py:212-215` vs `:1778-1781` — the 11-min/16-s cache-buffer constants
  (with identical comments) are duplicated; they exist to cover
  `get_corresponding_event`'s 10-min lookback and belong next to it.
- `compare.py:128` and `:477` — identical nested `safe_retag_by_rules`
  closures, each constructing a new `TagExtractor` per interval inside the
  comparison loops; hoist to one module-level helper with a shared extractor.
- `compare.py` — `astimezone().strftime(...)` inlined ~16×; `utils.ts2str`/
  `ts2strtime` exist and `compare.py` never imports `utils`.
- `main.py:398/417` — inline `fromisoformat(...rstrip('Z'))` timestamp
  parsing instead of `utils.parse_datetime` (the `rstrip('Z')` would misparse
  a genuine UTC timestamp as local time if one ever appeared).

### Efficiency
- `aw_client.py:156` — every cache-served `get_events` linearly rescans the
  whole cached bucket, re-parsing ISO timestamps per event per call (O(N²)
  over a batch run). Normalize once at cache population and slice with
  bisect.
- `main.py:1478` — `find_next_activity` re-runs the full `EventPipeline` on
  every call; AFK-transition early-returns make batch mode re-merge/re-sort
  the same immutable cached data O(K·N) times. Prepare once, consume
  incrementally.
- `timew_tracker.py:170` — `get_intervals` runs a bare `timew export` (entire
  database, unbounded growth) to answer a 7-day question at sync startup;
  pass the range as `compare.py:73` already does.
- `timew_tracker.py:88` — the `grace_time` sleep (default 10 s) fires after
  *every* timew command even with `hide_output=True`, where the undo message
  is suppressed — N commands in a batch apply block 10·N seconds.
- `event_pipeline.py:568` — `_split_window_events_by_afk` re-normalizes all
  AFK event timestamps for every window event (O(W·A) re-parsing); both
  lists are sorted, so a merge-sweep is O(W+A).
- `compare.py:194` — tag-set expansion re-run inside the nested
  suggested×overlapping loop (loop-invariant for the outer iteration); hoist
  and memoize.

### Simplification / conventions
- `cli.py:490-517` + `:766-810` — six-branch dispatch with four empty
  `validate_*_args` stubs; replace with a dispatch table or argparse
  `set_defaults(func=...)`.
- `main.py:480` — `run_comparison`'s fix-command block nests six levels deep
  and re-imports `subprocess` (already imported at module top).
- `main.py:1276` / `:646` / `:1050` — batch-mode detection
  (`self.start_time and self.end_time`) re-tested per call site with its own
  log-vs-breakpoint policy; one `batch_mode` property plus a mode-aware
  breakpoint helper.
- Type annotations — public APIs lack them (`load_config` at `main.py:125`,
  `ensure_tag_exported`, `set_known_tick_stats`, the legacy timew functions),
  and `timew_info: dict = None` (`main.py:143`) is untrue as written (should
  be `dict | None`).

---

## Overall assessment

The riskiest cluster is TimeWarrior interaction: `retag()`'s add-only
semantics (#2), the stale current-tracking cache (#3), and ignored exit codes
— all three can silently corrupt or lose tracked data in live sync, and two
of them also crash via the `main.py:978` assertion / accumulator invariant.
The event-pipeline AFK handling (#5, #9) can silently misattribute active
time as afk and vice versa. The diff/apply path has two independent
convergence-breakers (#6, #8). Most cleanup findings cluster around the
`TimewTracker`-vs-legacy split and tag_extractor/report duplication — the
same divergence class that caused the flatpak-Chromium bug fixed in d66f04a.
