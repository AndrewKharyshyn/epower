#!/usr/bin/env python3
"""M312 POST-HOC supplement (NOT pre-registered; prompted by the blind audit, 2026-09-30). Like-for-like slope comparison on ONE common row set.
The pre-registered M4(ii) compared the slope of the adjusted series as each pipeline variant would publish it (fit A: only the rows A keeps, n=433;
fit B: n=465). Here the adjusted level is computed for ALL 465 rows that are not excluded by ens_outlier_v2 under BOTH fits (fit A extrapolated to the 32 rows
it treated as outliers), so only the coefficients differ. Day-clustered bootstrap of the slope DIFFERENCE (resample calendar days, refit both Huber models and
the second-stage Huber slope per draw; seed 42, 4000 draws). Reads drive_master.csv only; writes analyses/M312_posthoc.json."""
import hashlib, json, os, sys
import numpy as np
import pandas as pd
from sklearn.linear_model import HuberRegressor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
Y, T, I, TREF, NB = "cell_spread_loaded_p95_mv", "T_pack_mean_avg", "peak_I_discharge", 25.0, 4000
dm = pd.read_csv("drive_master.csv", low_memory=False)
for c in ("ens_outlier", "ens_outlier_v2"):
    dm[c] = dm[c].fillna(False).astype(bool)
sc = dm.dropna(subset=[Y, T, I, "date"]).copy()
sc["day"] = pd.to_datetime(sc["date"]).dt.date.astype(str)
common = sc[~sc["ens_outlier_v2"]].reset_index(drop=True)
common["m"] = (pd.to_datetime(common["date"]) - pd.to_datetime(common["date"]).min()).dt.total_seconds() / (30.4375 * 86400)


def adj(fit_rows, eval_rows):
    h = HuberRegressor(epsilon=1.35, max_iter=500).fit(fit_rows[[T, I]].values, fit_rows[Y].values)
    iref = float(fit_rows[I].median())
    ref = h.predict([[TREF, iref]])[0]
    return np.round(ref + (eval_rows[Y].values - h.predict(eval_rows[[T, I]].values)), 1)


def slope(a, m):
    return float(HuberRegressor().fit(m.reshape(-1, 1), a).coef_[0])


def one(d):
    m = ((pd.to_datetime(d["date"]) - pd.to_datetime(d["date"]).min()).dt.total_seconds() / (30.4375 * 86400)).values
    a_keep, b_keep = d[~d["ens_outlier"]], d
    sa = slope(adj(a_keep, d), m)
    sb = slope(adj(b_keep, d), m)
    return sa, sb


sa, sb = one(common)
ud = common["day"].unique()
groups = [np.where(common["day"].values == u)[0] for u in ud]
rng = np.random.default_rng(42)
diffs, fail = [], 0
for _ in range(NB):
    idx = np.concatenate([groups[k] for k in rng.integers(0, len(ud), len(ud))])
    try:
        x, y = one(common.iloc[idx])
        diffs.append(y - x)
    except Exception:
        fail += 1
out = {"status": "POST-HOC, not pre-registered (prompted by the blind audit)", "master_md5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
       "common_rows": int(len(common)), "n_days": int(len(ud)),
       "slope_fitA_on_common_rows_mv_per_month": sa, "slope_fitB_on_common_rows_mv_per_month": sb, "difference_B_minus_A": sb - sa,
       "difference_ci95_day_clustered_bootstrap": [float(x) for x in np.percentile(diffs, [2.5, 97.5])], "failed_draws": fail,
       "note": "fit A = Huber on ~ens_outlier rows, applied to all common rows; fit B = Huber on ~ens_outlier_v2 rows (== the common rows)"}
json.dump(out, open("analyses/M312_posthoc.json", "w", encoding="utf-8"), indent=1)
print(json.dumps(out, indent=1))
