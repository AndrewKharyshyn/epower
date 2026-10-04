#!/usr/bin/env python3
"""M372 control: regenerated gtrClosure block (from analyses/M372_*) vs the published block in summary_arrays.json, under the stop rules pre-registered in
analyses/M372_spec.md Rev 2. Read-only; writes analyses/M372_closure_delta.json. Also diffs the 257 per-drive rows against the M336 baseline copy.
Stop rules (any one => Director): n / ID-set change; an estimate outside its previous 95% CI; any bool flag or verdict flip (incl. ciContains0p5, pointBelow0p5AllVariants,
stopTriggered, closed flags); a point-only numeric leaf whose relative change exceeds 2 % (absolute 0.002 when |previous| < 0.1); a key-set difference.
Always reports CI-width ratios (new / previous). Wording: 'consistent with the previous interval', never 'unchanged' or 'confirmed'.
Usage: python tools/m372_closure_diff.py"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
if "--m372" not in sys.argv:
    sys.argv.append("--m372")
import gtr_closure_block as GB          # builds the block from analyses/M372_*; main() is not run on import

OLD = json.load(open("summary_arrays.json", encoding="utf-8"))["generatorTractionRecon"]["gtrClosure"]
NEW = GB.build()
REL, ABS = 0.02, 0.002
out = {"keySetEqual": True, "keyDiffs": [], "ciChecks": [], "pointOnly": [], "boolFlips": [], "stringChanges": [], "scopeChanges": [], "stopTriggers": []}


def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def ci_check(path, old_est, old_ci, new_est, new_ci):
    inside = bool(old_ci[0] <= new_est <= old_ci[1])
    w_old, w_new = old_ci[1] - old_ci[0], new_ci[1] - new_ci[0]
    rec = {"path": path, "prev": [old_est, old_ci], "new": [new_est, new_ci], "newEstInsidePrevCI": inside, "ciWidthRatio": round(w_new / w_old, 4) if w_old else None}
    out["ciChecks"].append(rec)
    if not inside:
        out["stopTriggers"].append({"rule": "estimate outside previous CI", "path": path})


def walk(path, o, n):
    if isinstance(o, dict) and isinstance(n, dict):
        for k in sorted(set(o) | set(n)):
            if k not in o and f"{path}/{k}" == "/sources/fuelReconMaster":
                out["allowedAdditiveKeys"] = out.get("allowedAdditiveKeys", []) + [f"{path}/{k}"]     # Director ruling (M372 trigger)
                continue
            if k not in o or k not in n:
                out["keySetEqual"] = False
                out["keyDiffs"].append(f"{path}/{k}")
                out["stopTriggers"].append({"rule": "key-set difference", "path": f"{path}/{k}"})
        if "est" in o and "ci95" in o and "est" in n:
            ci_check(path, o["est"], o["ci95"], n["est"], n["ci95"])
            for k in sorted(set(o) & set(n)):
                if k not in ("est", "ci95"):
                    walk(f"{path}/{k}", o[k], n[k])
            return
        if "relToGenerator" in o and "ci95" in o and "relToGenerator" in n:
            ci_check(path, o["relToGenerator"], o["ci95"], n["relToGenerator"], n["ci95"])
            for k in sorted(set(o) & set(n)):
                if k not in ("relToGenerator", "ci95"):
                    walk(f"{path}/{k}", o[k], n[k])
            return
        for k in sorted(set(o) & set(n)):
            walk(f"{path}/{k}", o[k], n[k])
    elif isinstance(o, list) and isinstance(n, list):
        if len(o) != len(n):
            out["stopTriggers"].append({"rule": "list length changed", "path": path})
            return
        for i, (x, y) in enumerate(zip(o, n)):
            walk(f"{path}[{i}]", x, y)
    elif isinstance(o, bool) or isinstance(n, bool):
        if o != n:
            out["boolFlips"].append({"path": path, "prev": o, "new": n})
            out["stopTriggers"].append({"rule": "flag/verdict flip", "path": path})
    elif num(o) and num(n):
        if path.startswith("/scope/"):
            if o != n:
                out["scopeChanges"].append({"path": path, "prev": o, "new": n})
                out["stopTriggers"].append({"rule": "n / scope change", "path": path})
            return
        d = abs(n - o)
        tol = ABS if abs(o) < 0.1 else REL * abs(o)
        rec = {"path": path, "prev": o, "new": n, "absDiff": round(d, 6), "relDiff": round(d / abs(o), 5) if o else None, "withinTolerance": bool(d <= tol)}
        out["pointOnly"].append(rec)
        if d > tol:
            out["stopTriggers"].append({"rule": "point-only leaf beyond pre-registered tolerance", "path": path})
    elif o != n:
        out["stringChanges"].append({"path": path, "prev": o, "new": n})


walk("", OLD, NEW)
# drive-by-drive diff of the per-drive rows against the M336 baseline (locates any drift)
b = pd.read_csv("analyses/M372_baseline/M336_closure_perdrive.csv").set_index("file")
c = pd.read_csv("analyses/M372_closure_perdrive.csv").set_index("file")
assert set(b.index) == set(c.index), "per-drive ID set differs"
cols = [k for k in b.columns if k in c.columns and pd.api.types.is_numeric_dtype(b[k])]
drift = {}
for k in cols:
    dd = (c.loc[b.index, k] - b[k]).abs()
    drift[k] = {"maxAbs": round(float(dd.max()), 6), "nDrivesChanged": int((dd > 1e-5).sum()), "colSumRel": round(float(abs(c[k].sum() - b[k].sum()) / (abs(b[k].sum()) or 1)), 6)}
out["perDrive"] = {"nDrives": int(len(b)), "idSetEqual": True, "columns": drift,
                   "nDrivesAnyColumnChanged": int(((c.loc[b.index, cols] - b[cols]).abs() > 1e-5).any(axis=1).sum()),
                   "textColumnsEqual": {k: bool((c.loc[b.index, k].astype(str) == b[k].astype(str)).all()) for k in b.columns if k not in cols and k in c.columns}}
out["summary"] = {"nCiChecked": len(out["ciChecks"]), "nInsidePreviousCI": sum(r["newEstInsidePrevCI"] for r in out["ciChecks"]), "nPointOnly": len(out["pointOnly"]),
                  "nPointOnlyWithinTol": sum(r["withinTolerance"] for r in out["pointOnly"]), "nStopTriggers": len(out["stopTriggers"]),
                  "ciWidthRatioRange": [min((r["ciWidthRatio"] for r in out["ciChecks"] if r["ciWidthRatio"]), default=None), max((r["ciWidthRatio"] for r in out["ciChecks"] if r["ciWidthRatio"]), default=None)]}
with open("analyses/M372_closure_delta.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
    f.write("\n")
print(json.dumps(out["summary"], indent=1))
print("stop triggers:", json.dumps(out["stopTriggers"], indent=1) if out["stopTriggers"] else "none")
