import json
import os
import subprocess

from aw_export_timewarrior.main import retag_by_rules, timew_run

start = int(os.environ.get("START", 1))
stop = int(os.environ.get("STOP", 1150))

if __name__ == "__main__":
    for i in range(start, stop):
        print(i)
        timew_data = json.loads(subprocess.check_output(["timew", "get", f"dom.tracked.{i}.json"]))
        source_tags = set(timew_data["tags"])
        try:
            new_tags = retag_by_rules(source_tags)
        except Exception:
            print(f"problems with {source_tags}")
            continue

        if new_tags != source_tags:
            print(f"{source_tags} -> {new_tags}")
            timew_run(["retag", f"@{i}"] + list(new_tags))
        else:
            print(f"nothing to do with {source_tags}")
