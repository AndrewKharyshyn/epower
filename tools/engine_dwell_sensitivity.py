#!/usr/bin/env python3
"""M546 (analyses/M546_spec.md Rev 2, R5): count-only sensitivity of the engineDwellSurvival spell counts to the strict engine-on boundary. engineDwellSurvival keeps the stored boundary (rpm >= 400 is 'low'); this tool
counts the dwell spells per state with the stored classifier and with strict_off=True on the same state-grid sequences (same drive eligibility as the state machine) and writes analyses/M546_dwell_sensitivity.json (first output
kept). Nothing enters the payload and nothing is displayed; a sibling for the dwell-survival block is added only if the spell counts move beyond the order of the exactly-400 seconds (KA3). Usage: python tools/engine_dwell_sensitivity.py"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd

OUT = os.path.join(ROOT, "analyses", "M546_dwell_sensitivity.json")


def spells(st, S):
    cnt = {s: 0 for s in S}
    cur, n = st[0], len(st)
    for k in range(1, n + 1):
        if k == n or st[k] != cur:
            if cur >= 0:
                cnt[S[cur]] += 1
            if k < n:
                cur = st[k]
    return cnt


def main():
    os.chdir(ROOT)
    import compute_summary_arrays as C
    import drive_raw_cache as drc
    import ah_throughput as AH
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    fl = drc.make_frame_loader(raw_dir=os.path.abspath("raw_only")); rl = AH.raw_loader()
    S = C._ESM_STATES
    tot_a, tot_b, n400, nd = {s: 0 for s in S}, {s: 0 for s in S}, 0, 0
    for _, r in dm.iterrows():
        g = C._esm_grid(r["file"], rl, fl)
        if g is None or "rpm" not in g.columns:
            continue
        g = g.dropna(subset=["rpm"])
        if len(g) < 20:
            continue
        v = g["rpm"].values
        a, b = C._esm_classify(v), C._esm_classify(v, strict_off=True)
        if (a >= 0).sum() < 20:
            continue
        nd += 1
        n400 += int((v == 400.0).sum())
        for s, c in spells(a, S).items():
            tot_a[s] += c
        for s, c in spells(b, S).items():
            tot_b[s] += c
    res = {"spec": "analyses/M546_spec.md Rev 2 (R5)", "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "nDrives": nd, "secondsExactly400OnStateGrid": n400,
           "spellCountsStoredBoundary": tot_a, "spellCountsStrictBoundary": tot_b, "difference": {s: tot_b[s] - tot_a[s] for s in S},
           "note": "counts only, same drives and state-grid sequences; engineDwellSurvival keeps the stored boundary (label: stored basis, off = rpm < 400); never displayed, not in the payload"}
    if not os.path.exists(OUT):
        json.dump(res, open(OUT, "w", encoding="utf-8", newline=chr(10)), indent=1)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
