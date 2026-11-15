"""Re-apply the retag rules to timew intervals.

Usage: retag.py [ID[:START]...]

Without arguments it walks @START up to (not including) @STOP from the
environment.  Ids are relative and shift up whenever an interval is recorded,
so a caller that read them earlier should pass the interval's start stamp as
well (`12:20260914T120000Z`, timew's own format): the interval is then looked
for at that id and a few above it, and skipped if it is not found.

Only intervals whose tags change are reported, one line each.
"""

import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterable

from aw_export_timewarrior.main import retag_by_rules
from aw_export_timewarrior.timew_tracker import TimewTracker

logger = logging.getLogger(__name__)

# How far above its given id an interval is looked for: one step for each
# interval recorded between the caller reading the ids and this run.
MAX_ID_SHIFT = 5

Target = int | tuple[int, str]


def parse_targets(args: list[str]) -> list[Target]:
    """`12`, `@12` or `12:20260914T120000Z` → 12 or (12, start)."""
    targets: list[Target] = []
    for arg in args:
        interval_id, _, start = arg.lstrip("@").partition(":")
        targets.append((int(interval_id), start) if start else int(interval_id))
    return targets


def get_interval(interval_id: int) -> dict:
    return json.loads(subprocess.check_output(["timew", "get", f"dom.tracked.{interval_id}.json"]))


def locate(target: Target) -> tuple[int, dict] | None:
    """The current id and data of a target, or None if its start is not found."""
    if isinstance(target, int):
        return target, get_interval(target)
    interval_id, start = target
    for candidate in range(interval_id, interval_id + MAX_ID_SHIFT + 1):
        data = get_interval(candidate)
        if data.get("start") == start:
            return candidate, data
    return None


def main(targets: Iterable[Target]) -> int:
    """Re-apply the retag rules to the given timew intervals.

    Returns 1 if any interval could not be found or the rules failed on it.
    The rest are still walked, but the caller has to be able to tell the run
    was incomplete.
    """
    # hide_output: this prints its own line per change, and a batch has no
    # use for the per-command undo message or the grace period behind it.
    tracker = TimewTracker(hide_output=True)
    failures = 0
    for target in targets:
        found = locate(target)
        if found is None:
            print(f"@{target[0]}: no interval starting {target[1]} at or just above it, skipped")
            failures += 1
            continue
        i, timew_data = found
        source_tags = set(timew_data["tags"])
        try:
            new_tags = retag_by_rules(source_tags)
        except Exception as e:
            logger.warning("Failed to apply retag rules to %s: %s", source_tags, e)
            print(f"@{i}: error retagging {sorted(source_tags)}: {e}")
            failures += 1
            continue

        if new_tags != source_tags:
            changes = [f"+{t}" for t in sorted(new_tags - source_tags)]
            changes += [f"-{t}" for t in sorted(source_tags - new_tags)]
            print(f"@{i}: {' '.join(changes)}")
            tracker.retag_interval_by_id(i, new_tags)
    if failures:
        print(f"{failures} interval(s) could not be retagged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        targets: Iterable[Target] = parse_targets(sys.argv[1:])
    else:
        targets = range(int(os.environ.get("START", 1)), int(os.environ.get("STOP", 1150)))
    sys.exit(main(targets))
