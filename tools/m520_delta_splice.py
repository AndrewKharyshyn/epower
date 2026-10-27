#!/usr/bin/env python3
"""M520 Part B (analyses/M520_spec.md Rev 2): arrays-only leaf splice of socBalancedFuel.allAccumulatorSensitivity.deltaVsPrimary computed from the UNROUNDED fleet figures
(the source fix is in compute_summary_arrays.py, so the next ingestion keeps it). Compute only the changed key, deep-diff against the stored block: ONLY the two deltaVsPrimary leaves may differ,
else STOP (provenance drift is never mixed in). Never writes drive_master.csv or raw files. Usage: python tools/m520_delta_splice.py [--dry-run]"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import pandas as pd
import compute_summary_arrays as cs

ARR = os.path.join(ROOT, "summary_arrays.json")
ALLOWED = ("/allAccumulatorSensitivity/deltaVsPrimary/socBalancedFleetL100", "/allAccumulatorSensitivity/deltaVsPrimary/rawFleetL100")


def diff(a, b, p=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += [p + "/" + k + " (missing)"] if (k not in a or k not in b) else diff(a[k], b[k], p + "/" + k)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, p + "[%d]" % i)
    elif a != b:
        out.append(p)
    return out


def main():
    dry = "--dry-run" in sys.argv
    raw = open(ARR, "r", encoding="utf-8", newline="").read()
    A = json.loads(raw)
    old = A["socBalancedFuel"]
    dm_path = os.path.join(ROOT, "drive_master.csv")
    md5 = hashlib.md5(open(dm_path, "rb").read()).hexdigest()
    new = json.loads(json.dumps(cs._soc_balanced_fuel(pd.read_csv(dm_path), None, "raw_only"), default=float))
    d = [p for p in diff(new, old) if p != "/methodology"]
    bad = [p for p in d if p not in ALLOWED]
    if bad:
        print(json.dumps({"STOP": "the recomputed block differs from the stored block outside the allowed leaves", "differences": bad[:20]}, indent=1)); return 2
    nd, od = new["allAccumulatorSensitivity"]["deltaVsPrimary"], old["allAccumulatorSensitivity"]["deltaVsPrimary"]
    print(json.dumps({"changed": d, "old": od, "new": nd, "dryRun": dry}))
    if d and not dry:
        old["allAccumulatorSensitivity"]["deltaVsPrimary"] = nd
        with open(ARR, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    assert hashlib.md5(open(dm_path, "rb").read()).hexdigest() == md5
    return 0


if __name__ == "__main__":
    sys.exit(main())
