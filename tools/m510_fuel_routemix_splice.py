#!/usr/bin/env python3
"""M510 (audit 2026-10-25 A02): recompute ONLY socBalancedFuel and splice it when the only differences are the new routeMix block and the methodology text
(allow-list; any other leaf moving is a STOP, so provenance drift is never mixed in). Reads staged raw_only/. Never writes drive_master.csv or raw files.
Usage: python tools/m510_fuel_routemix_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import compute_summary_arrays as cs
from m511_fuel_eligibility_splice import diff, rt

ARR = os.path.join(ROOT, "summary_arrays.json")


def main():
    A = json.load(open(ARR, encoding="utf-8"))
    old = A["socBalancedFuel"]
    new = rt(cs._soc_balanced_fuel(pd.read_csv(os.path.join(ROOT, "drive_master.csv")), None, "raw_only"))
    changed = diff(new, old)
    bad = [p for p in changed if not (p.startswith("/routeMix") or p == "/methodology")]
    if bad:
        print(json.dumps({"STOP": "leaves outside the allow-list changed", "leaves": bad[:20]})); sys.exit(3)
    if "--dry-run" not in sys.argv and changed:
        A["socBalancedFuel"] = new
        with open(ARR, "w", encoding="utf-8", newline="\n") as f:
            json.dump(A, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": "spliced" if changed else "unchanged", "nChanged": len(changed), "routeMix": new.get("routeMix")}))


if __name__ == "__main__":
    main()
