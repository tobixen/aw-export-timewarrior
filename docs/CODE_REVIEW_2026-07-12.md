# Code Review: aw-export-timewarrior (diff since `1abdd1a`)

**Review Date:** 2026-07-12
**Reviewer:** Claude (AI code review, `/code-review` high effort)
**Scope:** `git diff 1abdd1af90dcf29f75d3aabaeccaed548f18059c..HEAD` — 30 commits
(~2 000 lines changed across `src/`, `tests/`, docs) of bug fixes, dedup
refactors, and perf work.
**Method:** 8 independent finder angles (line-by-line scan, removed-behavior
audit, cross-file contract tracing, reuse/simplification/efficiency/altitude/
conventions), deduplicated to 12 distinct defects, each verified against the
code (several confirmed by execution). Verdicts:
**CONFIRMED** = demonstrable from the code (some verified by execution),
**PLAUSIBLE** = realistic but depends on runtime state, **REFUTED** = dropped.

See also `CODE_REVIEW_2026-07.md` (2026-07-09 full-codebase review) and
`CODE_REVIEW.md` (December 2025 review).

**Fix status (2026-07-12, follow-up session):** #1, #2, #5, #9, #10 fixed;
#3 and #4 addressed as documented/flagged known limitations (maintainer
decision, no code change); all 6 "Lower-priority cleanups" bullets applied.
See commit history from `790e0ef` through `e6e766d` for the individual changes
(one commit per finding, mostly without CHANGELOG entries since almost all of
this diff's bugs were introduced and fixed within the same unreleased window).

**PLAUSIBLE follow-up (2026-07-12, later session):** #6, #7, #8 were
re-researched. **#7 fixed** — `compare.py` now reads `config` per call
(`tests/test_compare_config_rebind.py`). **#8 fixed** — batch memo gated on
`end_time <= now`; the doc's original "start and end set" fix suggestion was
wrong, see below (`tests/test_batch_memo_future_end.py`). **#6 not reachable**
today — every real path that advances `last_known_tick` also zeroes
`known_events_time` (record_export's reset_stats coupling / the `main.py:776`
reset), so no code change; an invariant-guarding regression test was added
(`test_ongoing_event_survives_export_advancing_last_known_tick`).

**Refuted / not reported:** `min_lid_duration` moving to `[tuning]` (commit
`c2f3930`) is a correct fix, not a regression — the shipped default config,
`config_validation.py`, and docs all place it under `[tuning]`; the old
top-level read was the bug. `retag.py`'s bulk loop aborting on the new
fail-loud path is a `__main__` maintenance script that already crashes
unguarded on out-of-range ids, so not worth reporting separately.

---

## Correctness

### 1. 🔴 `retag()` is non-atomic and can strip tags with no rollback — `timew_tracker.py:192-195` (CONFIRMED)

`retag()` now issues `timew untag @1 …` then `timew tag @1 …` as two separate
commands, and `_run_timew` raises `RuntimeError` on any nonzero exit
(`timew_tracker.py:89-97`). If the `untag` succeeds but the following `tag`
fails (db lock, on-modify hook rejection), the live interval is left with the
old tags stripped and the new ones never applied — silent data loss, no
rollback.

**Failure:** current interval `{4work, personal}`; `retag({4work, meeting})`
runs `timew untag @1 personal` (succeeds), then `timew tag @1 meeting` fails →
`RuntimeError`, interval left as `{4work}`.

**Fix:** use the atomic tag-set replacement `timew retag @1 <tags>`, already
wrapped one method down in `retag_interval_by_id` (`:210`). Secondary: the diff
is computed from `get_current_tracking()`, which serves a ≤`cache_ttl` (5s)
stale snapshot (`:132`), so a tag changed externally within that window can make
`to_remove` target a tag that is no longer present.

### 2. 🔴 Second non-split ask-away answer in one AFK period is silently, permanently dropped — `main.py:1627-1630` (+ `:800-830`, `:934`) (CONFIRMED)

The "already AFK" path calls `ensure_tag_exported()` **once** for a list of
`new_overlapping` ask-away events, then marks **all** of their timestamps
exported (`main.py:1629-1630`). But the non-split handler inside
`ensure_tag_exported` only consumes `overlapping_events[0]` (`:812`, tags →
`:820`; a single `start_tracking` at `:934`). The second answer is marked
exported without being tracked, and `exclude_exported=True` blocks any retry.

**Failure:** one merged AFK event 09:00–10:00 overlaps two non-split answers,
"tea" at 09:05 and "meeting" at 09:35. Only "tea" reaches TimeWarrior;
"meeting" is permanently lost. The split path loops correctly
(`:883-915`); only the non-split-multiple case — and the mixed case where
`is_split` is read solely from `overlapping_events[0]` (`:805`/`:871`) — break.

### 3. 🟠 `diff --config FILE` (flag after the subcommand) now errors — `cli.py` (diff subparser `--config` removed) (CONFIRMED, verified by execution)

`create_parser().parse_args(['diff','--config','/tmp/x.toml'])` →
`SystemExit(2)` ("unrecognized arguments: --config"). The old `diff` subparser
had its own `--config` (old `cli.py:267`), so that invocation worked before;
now only `--config` *before* the subcommand parses. Removing the duplicate was
intentional (it fixed argparse's subparser default clobbering the top-level
value), but any existing script/habit using `diff … --config x` is now broken.

**Fix:** re-add the option on the subparser sharing `dest="config"` (so it
doesn't clobber), or document the position change as a behavior break in the
CHANGELOG.

### 4. 🟠 Fail-loud `_run_timew` terminates the continuous sync daemon on a transient failure — `timew_tracker.py:89-97` + `cli.py:610` (CONFIRMED behavior change)

The old module-level `timew_run` ran `check=False` and ignored the return code;
the daemon logged and kept looping. Now any nonzero exit raises, and the
continuous `while exporter.tick():` loop (`cli.py:610`) has no tolerance — the
exception propagates to `main()`'s generic `except Exception` (`:809`), which
prints `Error:` and returns 1, killing the daemon.

**Failure:** a one-off `timew` db lock (user runs `timew` in another terminal)
or a single flaky on-modify hook takes down a long-running `sync`. The
desync-safety intent is sound, but the continuous loop needs per-tick
retry/tolerance rather than dying.

### 5. 🟠 `main([])` re-parses the host process's `sys.argv` — `cli.py:780` (CONFIRMED)

`argv_with_sync = (argv if argv else sys.argv[1:]) + ["sync"]` uses a falsy
test, so an explicit empty list `main([])` ("run with defaults") falls through
to `sys.argv[1:]`.

**Failure:** under pytest or any wrapper, `sys.argv[1:]` is unrelated tokens →
`SystemExit(2)`, or silently honoring flags never passed to `main`.

**Fix:** distinguish `None` from `[]` — `if argv is None: argv = sys.argv[1:]`.

### 6. 🟡 Clipping the ongoing event shifts the dedup key, risking double-counted time — `main.py:1268` / `:1278` (PLAUSIBLE)

`_process_current_event_incrementally` now clips the open event to
`last_known_tick` and uses the **clipped** start as `current_event_timestamp`
(`:1274`, `:1278`). If an export advances `last_known_tick` (L1→L2) while the
same event stays open across ticks, the key changes, the `else` "new ongoing
event" branch runs (`:1317`), resets `processed_duration` to 0, and re-adds the
full `[L2, now]` span to `known_events_time` / `tags_accumulated_time`. Whether
this double-counts depends on whether the intervening export reset those stats;
on a retain-accumulator export path it would, violating the
`known_events_time <= tracked_gap` invariant and tripping the assert.

**Suggested action:** a targeted regression test for "export advances
`last_known_tick` while an event stays open across ticks", given the project's
history of exactly these clipping bugs.

**Resolution (2026-07-12):** re-verified as **not reachable** — the double-count
needs `known_events_time` to survive a `last_known_tick` advance, but
`record_export` couples `reset_stats` to both the stats reset *and* clearing
current-event tracking (`state.py`), and the one `reset_stats=False` path (AFK
export) is preceded by the `main.py:776` `stats.reset()`. A repro that manually
advanced `last_known_tick` without zeroing stats does trip the assert, so the
coupling is load-bearing; the invariant is now guarded by
`test_ongoing_event_survives_export_advancing_last_known_tick`. No code change.

### 7. 🟡 `compare.py` binds the rebindable `config` global at import time — `compare.py:11` (PLAUSIBLE)

The old code imported `config` *inside* each function (re-reading the current
global per call); it is now module-level (`:11`, used at `:124`/`:457`).
`load_custom_config` **rebinds** the global
(`config.py:279` `config = expand_list_references(...)`), so if `compare` is
first imported before a custom config loads, its `config` name stays pinned to
the default and tag expansion ignores the user's `[tags]`/`[exclusive]` rules.
The normal one-shot CLI is safe (compare is imported lazily at `main.py:408`/
`:476`/`:515`, *after* `load_custom_config`), but test collection, library use,
or a second `--config` run in the same process would silently use stale rules.

**Fix:** pass `config` as a parameter, or keep the deferred per-call import.

**Fix (2026-07-12):** reverted to the deferred per-call `from .config import
config` in both `compare_intervals` and `generate_fix_commands`; confirmed by
execution that the stale binding ignored a post-import custom `[tags]` rule.
Test: `tests/test_compare_config_rebind.py`.

### 8. 🟡 Batch memo is served whenever `end_time` is set, not just true batch mode — `event_pipeline.py:99` (PLAUSIBLE, narrow)

`fetch_and_prepare_events` memoizes on `if self.end_time is not None` and the
docstring asserts "end_time set → underlying data is immutable." That only holds
for *past* ranges. A `sync --to <future>` (end_time set, start_time None) serves
the first-tick snapshot for the whole run, so heartbeats recorded during
processing are never fetched and the run ends early. If sync-until-a-future-time
isn't a supported invocation this is moot; if it is, the guard should require a
genuinely past/closed range.

**Follow-up research (2026-07-12):** the exact case above (`--to` with no
`--from`) is *blocked* — `cli.py` rejects `--end` without `--start`. But the
neighboring `sync --from <past> --to <future>` (continuous, no `--once`) IS
supported (`cli.py` prints "Starting sync until {end_time}") and reproduces the
early-exit. Note the "start **and** end set" discriminator floated above is
**wrong**: that bounded-live-sync has both set. The correct guard is
`end_time <= now`.

**Fix (2026-07-12):** memo is now gated on `self.end_time <= datetime.now(UTC)`
(`event_pipeline.py`); a future end_time re-runs the pipeline each call. Test:
`tests/test_batch_memo_future_end.py`.

**Follow-up fix (2026-07-12, later session):** the pipeline-memo gate alone was
insufficient — the underlying `EventFetcher` event cache (`main.py`) was still
enabled on `batch_mode` (start **and** end set), the exact discriminator flagged
wrong above. So `sync --from <past> --to <future>` re-ran the pipeline each tick
but read a *frozen* cache snapshot, freezing the live portion one layer down. The
cache is now gated on the same `end_time <= now` test. Test:
`tests/test_cache_regression.py::TestCacheGatedOnClosedRange`.

---

## Efficiency

### 9. 🟡 Event cache is only half-effective: linear lower bound + slice copy + double parse — `aw_client.py:180-216` (CONFIRMED)

`_filter_events_in_range` bisects only the upper bound (`hi`, `:207`) then does
`prepared_events[:hi]` (an O(hi) list copy, `:212`) and scans from index 0,
discarding early events via `event_end < start`. For the dominant pattern (many
forward-marching `get_events` per window event over a large bucket) that is
~O(calls × N) plus a slice allocation each call — the docstring's claimed
"O(log + matches)" only covers the upper bound. Also `_prepare_cached_events`
calls `normalize_timestamp(event["timestamp"])` twice per event (`:182-183`) —
the exact re-parsing this function exists to amortize.

**Fix:** bind `start` once in `_prepare_cached_events`; a correct lower bound
needs a prefix-max-of-end array (events are sorted by start, not end), but at
minimum iterate `range(lo, hi)` without slicing.

---

## Conventions

### 10. ⚪ CHANGELOG lists a bug whose whole lifecycle is between releases — `CHANGELOG.md:31` (CONFIRMED — judgment call)

The entry "Fix an ask-away event starting inside an AFK period being matched to
a later, unrelated AFK period…" concerns `_extend_afk_events_to_ask_away_start`,
first added by commit `cdd80d6` on 2026-03-29 — after the last release `v0.6.5`
(2026-01-27). Per the maintainer's CLAUDE.md rule: *"My CHANGELOGs only cover
changes since the last release — bugs introduced and fixed between releases
should not be mentioned."* Both the introduction and the fix are post-release,
so this line should be dropped — assuming the underlying misbehavior didn't also
exist in shipped v0.6.5 code (worth a quick confirm before removing).

---

## Lower-priority cleanups (in the diff's own dedup spirit)

- `get_intervals` re-introduces `astimezone().strftime` instead of
  `utils.ts2str` (`timew_tracker.py:222-223`) and the `datetime.max`
  open-interval sentinel instead of compare's new `_effective_end` (`:266-268`);
  the latter belongs in `utils.py` so the two overlap-math modules can't diverge.
- `_split_window_events_by_afk` open-codes `get_event_range` inline
  (`event_pipeline.py:640`), double-parsing each timestamp.
- `get_intervals`'s nested `try/except` has two near-identical `subprocess.run`
  arms differing only in the command list (`timew_tracker.py:226-243`); loop over
  the two candidate commands instead, and cache the "ranged-export unsupported"
  outcome so old-timew installs don't pay a failed subprocess on every call.
  **Done (2026-07-12).** Follow-up: the cache latch was refined so it only trips
  when the ranged attempt fails *and* the plain-export fallback then succeeds
  (proving the range syntax is the problem), not on any failure — a transient
  db-lock/hook failure no longer permanently degrades every later call to a
  full-DB scan. Test:
  `tests/test_timew_tracker.py::TestGetIntervals::test_get_intervals_transient_failure_does_not_latch_off_ranged`.
- `guarded_run` / `guarded_check_output` are copy-paste closures differing by one
  word (`tests/conftest.py:71`); build them from a factory.
- `_prepared_batch` is an untyped positional 4-tuple documented only in a comment
  (`event_pipeline.py:76`); a `NamedTuple` would make the positional accesses
  (`cached[0]`/`cached[1]`) self-describing.
- `ensure_tag_exported` recomputes `_overlapping_ask_away_events(event)` three
  times for the same event (`main.py:800`, `:854`, `:867`); compute once.
