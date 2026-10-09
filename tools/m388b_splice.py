#!/usr/bin/env python3
"""M388b (spec analyses/M388b_spec.md): arrays-only splice of interDriveCarryover/regressionModel/mixedEffects after the fallback-chain patch of
compute_summary_arrays._carryover_mixed. Rebuilds the pair table with the pipeline's own functions (read-only raw cache), recomputes the whole regression block,
asserts every key except mixedEffects is bit-identical to the stored block (bootstrap OLS untouched), then splices only mixedEffects.
Modes: --check (writes analyses/M388b_check.json, no payload write) | --splice (check + write summary_arrays.json, deep-diff: only mixedEffects may differ).
Never writes drive_master.csv or raw files. Usage: python tools/m388b_splice.py --check|--splice"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import pandas as pd
import compute_summary_arrays as C
import drive_raw_cache as drc

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M388b_check.json")
canon = lambda o: json.dumps(o, sort_keys=True, ensure_ascii=False, default=float)


def diff_paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += diff_paths(a.get(k), b.get(k), f"{p}/{k}") if (k in a and k in b) else [f"{p}/{k}"]
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, f"{p}/{i}")
        return out
    return [] if canon(a) == canon(b) else [p]


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    A = json.load(open(ARR, encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cfg = json.load(open("summary_config.json", encoding="utf-8"))
    fl = drc.make_frame_loader()
    traj = C._battery_temp_traj(dm, None, frame_loader=fl)
    pf = C._linked_adjacent_drive_table(dm, traj, cfg.get("ambientByDrive"), frame_loader=fl)
    new = C._carryover_regression(pf)
    old = A["interDriveCarryover"]["regressionModel"]
    others_new = {k: v for k, v in new.items() if k != "mixedEffects"}
    others_old = {k: v for k, v in old.items() if k != "mixedEffects"}
    res = {"milestone": "M388b", "mode": mode, "nPairs": int(len(pf)), "nDays": int(pf["day"].nunique()),
           "othersBitIdentical": canon(others_new) == canon(others_old), "othersDiff": diff_paths(others_old, others_new),
           "mixedEffects": new["mixedEffects"], "storedMixedEffectsWas": old.get("mixedEffects")}
    ok = res["othersBitIdentical"] and "error" not in new["mixedEffects"]
    res["ok"] = bool(ok)
    if mode == "--splice" and ok:
        B = copy.deepcopy(A)
        B["interDriveCarryover"]["regressionModel"]["mixedEffects"] = new["mixedEffects"]
        res["spliceDiff"] = diff_paths(A, B)
        assert all(p.startswith("/interDriveCarryover/regressionModel/mixedEffects") for p in res["spliceDiff"]), res["spliceDiff"][:5]
        raw = json.dumps(B, indent=1, ensure_ascii=False)
        nl = "\n" if open(ARR, encoding="utf-8", newline="").read().endswith("\n") else ""
        open(ARR, "w", encoding="utf-8", newline="\n").write(raw + nl)
    json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, default=float)
    print(json.dumps({k: res[k] for k in ("mode", "nPairs", "nDays", "othersBitIdentical", "ok")}), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
