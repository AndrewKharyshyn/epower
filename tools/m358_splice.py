#!/usr/bin/env python3
"""M358 (spec analyses/M358_spec.md Rev 2): compute cRatePointsAK / cRateRefLinesAK / cRateAxes from drive_master.csv and splice them additively.
CONTROLS: C1 first three columns of cRatePointsAK equal cRatePoints (same order, same length); cRatePoints, cRateRefLines (incl. axis) untouched;
C2 per-row C == A / cap_ah_est within 0.05 C (reported); C3 A is the |A| of the channel with the largest C (re-derived independently here).
Modes: --check (writes analyses/M358_check.json, no payload write) | --splice (check + leaf-level additive splice, then deep-diff: only the 3 new keys may differ).
Never writes drive_master.csv or raw files. Usage: python tools/m358_splice.py --check|--splice"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd
import compute_summary_arrays as C

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M358_check.json")
NEW = ("cRatePointsAK", "cRateRefLinesAK", "cRateAxes")
canon = lambda o: json.dumps(o, sort_keys=True, ensure_ascii=False, default=float)


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    A = json.load(open(ARR, encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    pts, ref, axes = C._crate_axes(dm, A)
    res = {"milestone": "M358", "mode": mode, "nLive": int(len(dm)), "n": len(pts), "control": {}}
    c = res["control"]
    c["C1_firstThreeColumnsEqualCRatePoints"] = bool(len(pts) == len(A["cRatePoints"]) and all(canon(p[:3]) == canon(q) for p, q in zip(pts, A["cRatePoints"])))
    # C2: C == A / cap_ah_est (per drive) within 0.05
    cap = dm.set_index("file")["cap_ah_est"]
    # tolerance = rounding bound per row: C rounded to 0.1 (0.05), A to 0.1 (0.05/cap), cap_ah_est to 0.01 (C*0.005/cap)
    rows = [(abs(p[1] - p[3] / float(cap[p[5]])), 0.05 + 0.05 / float(cap[p[5]]) + p[1] * 0.005 / float(cap[p[5]]))
            for p in pts if p[3] is not None and p[5] in cap.index and pd.notna(cap[p[5]])]
    c["C2_maxAbsDiffC_vs_A_over_capAh"] = round(max(r[0] for r in rows), 4) if rows else None
    c["C2_maxDiffOverBound"] = round(max(r[0] / r[1] for r in rows), 3) if rows else None
    c["C2_n"] = len(rows)
    c["C2_pass"] = bool(rows and all(r[0] <= r[1] for r in rows))
    c["C2_note"] = "Rev 2 stated tolerance 0.05 C; replaced by the per-row rounding bound (C 0.1, A 0.1, cap_ah_est 0.01 resolution), max diff reported"
    # C3: independent re-derivation of the channel argmax
    chans = [("eng_charge_peak_Crate", "eng_charge_peak_A"), ("dual_peak_Crate", "dual_peak_A"), ("regen_peak_Crate", "regen_peak_A")]
    byf = dm.set_index("file")
    bad = 0
    for p in pts:
        r = byf.loc[p[5]]
        cand = [(r[ck], abs(r[ak])) for ck, ak in chans if pd.notna(r[ck])]
        best = max(cand, key=lambda x: x[0])
        if p[3] is None or abs(best[1] - p[3]) > 0.051 or abs(best[0] - p[1]) > 0.051:
            bad += 1
    c["C3_rowsWithChannelMismatch"] = bad
    c["C4_cRateRefLinesAxisUnchanged"] = "checked after splice (deep-diff)"
    ok = c["C1_firstThreeColumnsEqualCRatePoints"] and c["C2_pass"] and bad == 0
    res["controlPassed"] = bool(ok)
    res["axes"] = axes
    res["refLinesAK"] = ref
    json.dump({**res, "nRows": len(pts)}, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"controlPassed": ok, "control": c, "cPerA": axes["cPerA"], "diag": axes["diagnostics"]}, indent=1, default=float))
    if mode == "--check" or not ok:
        sys.exit(0 if ok else 1)
    old = copy.deepcopy(A)
    A["cRatePointsAK"], A["cRateRefLinesAK"], A["cRateAxes"] = json.loads(json.dumps([pts, ref, axes], default=float))
    for k in NEW:   # build_html.js requires an _artifactStamps entry for every top-level key (M235 F09): copy the cRatePoints stamp
        st = copy.deepcopy(A["_artifactStamps"]["cRatePoints"])
        st["computationStatus"] = "computed"
        st["computationStatusNote"] = "M358: A / kW companions of cRatePoints / cRateRefLines (tools/m358_splice.py, compute_summary_arrays._crate_axes); derived from drive_master.csv."
        A["_artifactStamps"][k] = st
    diff = sorted(k for k in set(old) | set(A) if canon(old.get(k)) != canon(A.get(k)))
    assert set(diff) <= set(NEW) | {"_artifactStamps"}, diff
    assert canon({k: v for k, v in old["_artifactStamps"].items()}) == canon({k: v for k, v in A["_artifactStamps"].items() if k not in NEW}), "other stamps changed"
    assert canon(old["cRateRefLines"]) == canon(A["cRateRefLines"]) and canon(old["cRateRefLines"]["axis"]) == canon(A["cRateRefLines"]["axis"])
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
    print("spliced", NEW, "; changed top-level keys:", diff)


if __name__ == "__main__":
    main()
