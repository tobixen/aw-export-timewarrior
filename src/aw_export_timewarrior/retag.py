import json
import logging
import os
import subprocess

from aw_export_timewarrior.main import retag_by_rules, timew_run

logger = logging.getLogger(__name__)

start = int(os.environ.get("START", 1))
stop = int(os.environ.get("STOP", 1150))

if __name__ == "__main__":
    for i in range(start, stop):
        print(i)
        timew_data = json.loads(subprocess.check_output(["timew", "get", f"dom.tracked.{i}.json"]))
        source_tags = set(timew_data["tags"])
        try:
            new_tags = retag_by_rules(source_tags)
        except Exception as e:
            logger.warning("Failed to apply retag rules to %s: %s", source_tags, e)
            print(f"Error retagging {source_tags}: {e}")
            continue

        if new_tags != source_tags:
            print(f"{source_tags} -> {new_tags}")
            timew_run(["retag", f"@{i}"] + list(new_tags))
        else:
            print(f"nothing to do with {source_tags}")
