import json
import logging
import os
import subprocess
import sys

from aw_export_timewarrior.main import retag_by_rules
from aw_export_timewarrior.timew_tracker import TimewTracker

logger = logging.getLogger(__name__)


def main(start: int, stop: int) -> int:
    """Re-apply the retag rules to timew intervals @start up to (not including) @stop.

    Returns 1 if the rules failed on any interval.  The rest of the range is
    still walked, but the caller has to be able to tell the run was incomplete.
    """
    tracker = TimewTracker()
    failures = 0
    for i in range(start, stop):
        print(i)
        timew_data = json.loads(subprocess.check_output(["timew", "get", f"dom.tracked.{i}.json"]))
        source_tags = set(timew_data["tags"])
        try:
            new_tags = retag_by_rules(source_tags)
        except Exception as e:
            logger.warning("Failed to apply retag rules to %s: %s", source_tags, e)
            print(f"Error retagging {source_tags}: {e}")
            failures += 1
            continue

        if new_tags != source_tags:
            print(f"{source_tags} -> {new_tags}")
            tracker.retag_interval_by_id(i, new_tags)
        else:
            print(f"nothing to do with {source_tags}")
    if failures:
        print(f"{failures} interval(s) could not be retagged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(int(os.environ.get("START", 1)), int(os.environ.get("STOP", 1150))))
