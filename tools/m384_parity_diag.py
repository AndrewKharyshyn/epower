#!/usr/bin/env python3
"""M384 diagnosis (read-only): why does tools/regen_seasonal_raw.py's parity guard fail for CrawlStopGo and EngineStartsByType on a no-cache run?
Recomputes both blocks on ALL rows exactly as regen_seasonal_raw does (same builders, frame loader, staged raw_only/), compares canonical JSON with the stored
top-level blocks of summary_arrays.json and lists every differing leaf path (stored vs fresh). Two fresh computations are also compared with each other
(determinism). Writes analyses/M384_parity_diag.json only.
Usage: XT_RAW_DIR=$PWD/raw python tools/m384_parity_diag.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import regen_seasonal_raw as R
import compute_summary_arrays as C
import drive_raw_cache as drc


def leaves(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, f"{p}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, f"{p}[{i}]")
    else:
        yield p, o


def diff(a, b):
    la, lb = dict(leaves(json.loads(json.dumps(a, default=float)))), dict(leaves(json.loads(json.dumps(b, default=float))))
    only_a = sorted(set(la) - set(lb)); only_b = sorted(set(lb) - set(la))
    chg = sorted(p for p in set(la) & set(lb) if la[p] != lb[p])
    return {"nStored": len(la), "nFresh": len(lb), "onlyInStored": only_a[:40], "nOnlyInStored": len(only_a), "onlyInFresh": only_b[:40], "nOnlyInFresh": len(only_b),
            "changed": [{"path": p, "stored": la[p], "fresh": lb[p]} for p in chg[:40]], "nChanged": len(chg)}


def main():
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    fl = drc.make_frame_loader(raw_dir=R.RAW_DIR)
    out = {"nDrives": int(len(dm)), "charts": {}}
    for name, key in (("CrawlStopGo", "crawlStopGo"), ("EngineStartsByType", "engineStartsByType")):
        runs = []
        for _ in range(2):
            cf, cr = R.Counting(fl), R.Counting(R.raw_loader)
            if name == "CrawlStopGo":
                fresh = R.builders(cf, cr, R.RAW_DIR)[name](dm)
            else:
                fresh = C.category_B(dm, cr, frame_loader=cf).get(R.LC(name))
            runs.append(fresh)
        e = {"stamp": (A["_artifactStamps"].get(key) or {}), "sameRunTwice": R.canon(runs[0]) == R.canon(runs[1]), "parityWithStored": R.canon(runs[0]) == R.canon(A[key]),
             "diffStoredVsFresh": diff(A[key], runs[0]), "framesLoaded": cf.ok}
        out["charts"][name] = e
        print(name, "twice-equal", e["sameRunTwice"], "parity", e["parityWithStored"], "changed", e["diffStoredVsFresh"]["nChanged"], "onlyStored", e["diffStoredVsFresh"]["nOnlyInStored"], "onlyFresh", e["diffStoredVsFresh"]["nOnlyInFresh"], flush=True)
    json.dump(out, open("analyses/M384_parity_diag.json", "w", encoding="utf-8", newline="\n"), indent=1, default=float)


if __name__ == "__main__":
    main()
