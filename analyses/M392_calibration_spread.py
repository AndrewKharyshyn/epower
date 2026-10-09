#!/usr/bin/env python3
"""M392 calibration study, spread model (read-only, script-written JSON analyses/M392_calibration_spread.json). Companion of M392_calibration.py.
Retro-replay of k-day batches (k in 4, 7, 10; sliding by k, >= 30 earlier days) against the earlier corpus for the centred OLS spread fit (tools/recal_gate._ols; b0, bI; bT is
reported not_identifiable by the gate unless the batch spans enough temperature range):
  CUR  evaluability of the CURRENT block-null: windows of the same number of days that also have >= (batch drives) drives; evaluable only with >= 10 such windows (recal_gate._block_null)
  C1   window null with a fixed fit minimum (>= 8 drives per window, the gate's own 'new-only n >= 8'): rank of |batch fit - old fit| among all contiguous k-day windows of the old corpus, per coefficient
  M    median 95th percentile of the window deviations (minimum detectable shift)
Nothing here changes the gate. Usage: python analyses/M392_calibration_spread.py"""
import json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import recal_gate as rg

MIN_OLD_DAYS, MIN_FIT = 30, 8
dm = pd.read_csv("drive_master.csv", low_memory=False)
dm["_d"] = dm["date"].astype(str)
sx = rg._spread_xy(dm)
days = sorted(sx["_d"].unique())
out = {"min_old_days": MIN_OLD_DAYS, "min_fit_drives": MIN_FIT, "nDaysSpread": len(days), "results": {}}
for k in (4, 7, 10):
    rows = []
    for s in range(MIN_OLD_DAYS, len(days) - k + 1, k):
        bdays, odays = days[s:s + k], days[:s]
        old, new = sx[sx["_d"].isin(odays)], sx[sx["_d"].isin(bdays)]
        if len(new) < MIN_FIT:
            continue
        tref, iref = float(old["T_pack_mean_avg"].median()), float(old["peak_I_discharge"].median())
        bo, bn = rg._ols(old, tref, iref), rg._ols(new, tref, iref)
        nd = new["_d"].nunique()
        dstr = old["_d"].values
        fits, fits_cur = [], 0
        for j in range(0, len(odays) - nd + 1):
            blk = old[np.isin(dstr, odays[j:j + nd])]
            if len(blk) >= len(new):
                fits_cur += 1
            if len(blk) >= MIN_FIT:
                try:
                    fits.append(rg._ols(blk, tref, iref))
                except Exception:
                    pass
        F = np.array(fits)
        rec = {"start": bdays[0], "n_batch_drives": int(len(new)), "n_valid_windows_cur_rule": fits_cur, "cur_rule_evaluable": bool(fits_cur >= 10), "n_valid_windows_c1": int(len(F))}
        for ci, nm in ((0, "b0"), (2, "bI")):
            dev = np.abs(F[:, ci] - bo[ci]); obs = abs(bn[ci] - bo[ci])
            rec[nm] = {"obs_abs_dev": float(obs), "p": float((1 + np.sum(dev >= obs)) / (len(dev) + 1)), "mdd95": float(np.percentile(dev, 95))}
        rows.append(rec)
    n = len(rows)
    out["results"][f"k{k}"] = {"n_batches": n, "cur_rule_evaluable_rate": round(sum(r["cur_rule_evaluable"] for r in rows) / n, 3) if n else None,
                              "C1_rate_p05_b0": round(sum(r["b0"]["p"] <= 0.05 for r in rows) / n, 3) if n else None,
                              "C1_rate_p05_bI": round(sum(r["bI"]["p"] <= 0.05 for r in rows) / n, 3) if n else None,
                              "median_mdd95_b0": round(float(np.median([r["b0"]["mdd95"] for r in rows])), 3) if n else None,
                              "median_mdd95_bI": round(float(np.median([r["bI"]["mdd95"] for r in rows])), 4) if n else None,
                              "median_batch_drives": float(np.median([r["n_batch_drives"] for r in rows])) if n else None, "batches": rows}
json.dump(out, open("analyses/M392_calibration_spread.json", "w", encoding="utf-8", newline="\n"), indent=1)
for key, v in out["results"].items():
    print(key, {a: v[a] for a in v if a != "batches"})
