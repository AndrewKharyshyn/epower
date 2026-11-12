#!/usr/bin/env python3
"""M627 (implements spec analyses/M626_spec.md Rev 1 / 1.1, W1-10) additive splice of the BMS possible-power block.
Recomputes ONLY `headroomUtilization` with the corpus function compute_summary_arrays._headroom_utilization_summary (the same function the arrays build calls at every ingestion)
from drive_master.csv and the staged raw files (raw_only/, names equal to drive_master.file), and refuses (exit 3, nothing written) unless
  * every other leaf of summary_arrays.json is identical (the deep diff lies inside headroomUtilization.*; _artifactStamps are not touched);
  * the unit gate passed (the function raises HeadroomUnitError otherwise).
The old block is archived beside the new one in the result JSON (old and new, per direction and statistic) so every displayed change is traceable.
Usage: python tools/m627_splice.py [--dry-run] [--json PATH]"""
import copy, json, os, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from walk(x, y, f"{path}[{i}]")
    elif a != b:
        yield path


def stop(msg):
    print("STOP:", msg)
    sys.exit(3)


def raw_loader(fn):
    with open(os.path.join(ROOT, "raw_only", fn), "rb") as f:
        return f.read()


def main(argv):
    import pandas as pd
    import compute_summary_arrays as C
    p = "summary_arrays.json"
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    t0 = time.time()
    try:
        new = C._headroom_utilization_summary(dm, raw_loader=raw_loader)
    except C.HeadroomUnitError as e:
        stop("unit gate: %s" % e)
    secs = round(time.time() - t0, 1)
    new = json.loads(json.dumps(new))
    B["headroomUtilization"] = new
    changed = list(walk(A, B))
    bad = [d for d in changed if not d.startswith("/headroomUtilization")]
    if bad:
        stop("deep-diff outside headroomUtilization: %s" % bad[:6])
    import subprocess
    try:                                   # the archived "old" block is the PUBLISHED one (git HEAD), not an intermediate working copy
        old_pub = json.loads(subprocess.run(["git", "show", "HEAD:summary_arrays.json"], capture_output=True, check=True).stdout.decode("utf-8"))["headroomUtilization"]
    except Exception:
        old_pub = A["headroomUtilization"]
    res = {"seconds": secs, "changedLeaves": len(changed), "old": old_pub, "new": new}
    print(json.dumps({k: v for k, v in res.items() if k != "old"}, indent=1)[:5000])
    if "--json" in argv:
        json.dump(res, open(argv[argv.index("--json") + 1], "w", encoding="utf-8", newline="\n"), indent=1)
    if "--dry-run" not in argv and changed:
        open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
