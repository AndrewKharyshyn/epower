#!/usr/bin/env python3
"""M312 analysis (spec: analyses/M312_spec.md rev 2, committed before this script ran). READ-ONLY on drive_master.csv.
Computes M1-M5, the decision criteria against baselines B1 (Huber refit on the FROZEN ens_outlier keep set) and B2 (the published
column), and sensitivities S1-S4. Writes analyses/M312_results.json (provenance: master MD5, script sha, n_drives, n_days).
Usage: python tools/m312_analysis.py"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd
from sklearn.linear_model import HuberRegressor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import compute_drive_summary_v6 as v6

COL = "cell_spread_loaded_p95_adj_hub_mv"
Y, T, I = "cell_spread_loaded_p95_mv", "T_pack_mean_avg", "peak_I_discharge"
TREF, NB, SEED = v6.SPREAD_T_REF, 4000, 42
MED, P95, NEWPOP, NHUB, SLOPE_F, COEF_F = 0.5, 2.0, 0.10, 0.10, 0.25, 0.25
md5 = lambda f: hashlib.md5(open(f, "rb").read()).hexdigest()
sha = lambda f: hashlib.sha256(open(f, "rb").read()).hexdigest()

dm = pd.read_csv("drive_master.csv", low_memory=False)
for c in ("ens_outlier", "ens_outlier_v2"):
    dm[c] = dm[c].fillna(False).astype(bool)
sc = dm.dropna(subset=[Y, T, I, "date"]).copy()
sc["day"] = pd.to_datetime(sc["date"]).dt.date.astype(str)
months_all = (pd.to_datetime(sc["date"]) - pd.to_datetime(sc["date"]).min()).dt.days / 30.44


def fit(d, eps=1.35):
    h = HuberRegressor(epsilon=eps, max_iter=500).fit(d[[T, I]].values, d[Y].values)
    iref = float(d[I].median())
    ref = h.predict([[TREF, iref]])[0]
    adj = pd.Series(np.round(ref + (d[Y].values - h.predict(d[[T, I]].values)), 1), index=d.index)
    return {"b0": float(h.intercept_), "bT": float(h.coef_[0]), "bI": float(h.coef_[1]), "I_ref": iref}, adj


def huber_slope(series, rows):
    """cellHealthTrend-style: Huber slope of adj on months since first row, rows = canonical-clean frame with the series non-null."""
    g = rows.assign(_a=series.reindex(rows.index)).dropna(subset=["_a"])
    m = ((pd.to_datetime(g["date"]) - pd.to_datetime(g["date"]).min()).dt.total_seconds() / (30.4375 * 86400)).values
    return float(HuberRegressor().fit(m.reshape(-1, 1), g["_a"].values).coef_[0]), g, m


def boot_huber_slope(g, m):
    days = g["day"].values
    ud = np.unique(days)
    groups = [np.where(days == u)[0] for u in ud]
    rng = np.random.default_rng(SEED)
    out, fail = [], 0
    for _ in range(NB):
        idx = np.concatenate([groups[k] for k in rng.integers(0, len(ud), len(ud))])
        try:
            out.append(float(HuberRegressor().fit(m[idx].reshape(-1, 1), g["_a"].values[idx]).coef_[0]))
        except Exception:
            fail += 1
    return [float(x) for x in np.percentile(out, [2.5, 97.5])], fail


def boot_coef_ci(d):
    days = d["day"].values
    ud = np.unique(days)
    groups = [np.where(days == u)[0] for u in ud]
    rng = np.random.default_rng(SEED)
    bt, bi, fail = [], [], 0
    for _ in range(NB):
        idx = np.concatenate([groups[k] for k in rng.integers(0, len(ud), len(ud))])
        try:
            h = HuberRegressor(epsilon=1.35, max_iter=500).fit(d[[T, I]].values[idx], d[Y].values[idx])
            bt.append(float(h.coef_[0])); bi.append(float(h.coef_[1]))
        except Exception:
            fail += 1
    return {"bT": [float(x) for x in np.percentile(bt, [2.5, 97.5])], "bI": [float(x) for x in np.percentile(bi, [2.5, 97.5])], "failed_draws": fail}


keep_old, keep_new = sc[~sc["ens_outlier"]], sc[~sc["ens_outlier_v2"]]
coef_B1, adj_B1 = fit(keep_old)
coef_N, adj_N = fit(keep_new)
B2 = dm.loc[sc.index, COL]
out = {"spec": "analyses/M312_spec.md rev 2", "spec_git_blob": "d7a2ef8e2b90048f6e5e290a10385a71a207b8b7",
       "master_md5": md5("drive_master.csv"), "script_sha256": sha(__file__), "n_drives_master": int(len(dm)),
       "sc": {"n": int(len(sc)), "n_days": int(sc["day"].nunique())},
       "keep_old_E_old": {"n": int(len(keep_old)), "n_days": int(keep_old["day"].nunique())},
       "keep_new_E_new": {"n": int(len(keep_new)), "n_days": int(keep_new["day"].nunique())}}
# M1
only_new = sc[(sc["ens_outlier"]) & (~sc["ens_outlier_v2"])]
only_old = sc[(~sc["ens_outlier"]) & (sc["ens_outlier_v2"])]
out["M1"] = {"n_ens_outlier_ne_v2": int(len(only_new) + len(only_old)), "newly_populated_kept_by_v2_only": int(len(only_new)),
             "kept_by_old_only": int(len(only_old)), "newly_populated_share_of_sc": float(len(only_new) / len(sc))}


def delta_stats(a, b, rows=None):
    j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    if rows is not None:
        j = j.loc[j.index.intersection(rows)]
    d = (j["a"] - j["b"]).abs()
    return {"n_rows": int(len(d)), "median": float(d.median()), "p95": float(d.quantile(0.95)), "max": float(d.max())}


same_status = sc.index[(sc["ens_outlier"] == sc["ens_outlier_v2"])]
resid_scale = float(np.median(np.abs(keep_old[Y].values - HuberRegressor(epsilon=1.35, max_iter=500).fit(keep_old[[T, I]].values, keep_old[Y].values).predict(keep_old[[T, I]].values))))
out["M2"] = {"residual_MAD_scale_mv": resid_scale,
             "new_vs_B1": delta_stats(adj_N, adj_B1), "new_vs_B2": delta_stats(adj_N, B2),
             "refit_drift_B2_vs_B1": delta_stats(B2, adj_B1),
             "S4_same_status_rows": {"new_vs_B1": delta_stats(adj_N, adj_B1, same_status), "new_vs_B2": delta_stats(adj_N, B2, same_status)},
             "rows_now_nan_vs_B2": int((B2.notna() & ~adj_N.reindex(B2.index).notna()).sum()),
             "rows_newly_populated_vs_B2": int((B2.isna() & adj_N.reindex(B2.index).notna()).sum()),
             "nHuber_B2": int(B2[~sc["ens_outlier_v2"]].notna().sum()), "nHuber_B1": int(adj_B1[~sc.loc[adj_B1.index, "ens_outlier_v2"]].notna().sum()),
             "nHuber_new": int(adj_N[~sc.loc[adj_N.index, "ens_outlier_v2"]].notna().sum())}
out["M3"] = {"B1": coef_B1, "new": coef_N}
# M4 (i): pipeline slope with the M19 bootstrap CI, via the single-source function
_, info_B1 = v6.m19b_huber_adjust(dm, "ens_outlier")
_, info_N = v6.m19b_huber_adjust(dm, "ens_outlier_v2")
clean_rows = sc[~sc["ens_outlier_v2"]].copy()
sl_B1, gB1, mB1 = huber_slope(adj_B1, clean_rows)
sl_N, gN, mN = huber_slope(adj_N, clean_rows)
sl_B2, gB2, mB2 = huber_slope(dm.loc[sc.index, COL], clean_rows)
ciB1, fB1 = boot_huber_slope(gB1, mB1)
ciN, fN = boot_huber_slope(gN, mN)
ciB2, fB2 = boot_huber_slope(gB2, mB2)
out["M4"] = {"i_slope_hub_mv_per_month": {"B1": info_B1, "new": info_N},
             "ii_huberSlopeMvPerMo": {"B1": {"slope": sl_B1, "n": int(len(gB1)), "ci95": ciB1, "failed_draws": fB1},
                                      "B2": {"slope": sl_B2, "n": int(len(gB2)), "ci95": ciB2, "failed_draws": fB2},
                                      "new": {"slope": sl_N, "n": int(len(gN)), "ci95": ciN, "failed_draws": fN}}}
cB1, cN = boot_coef_ci(keep_old), None
out["M5"] = {"B1_fit_bootstrap": cB1}
# criteria
hw = lambda ci: (ci[1] - ci[0]) / 2.0
incl0 = lambda ci: bool(ci[0] <= 0 <= ci[1])


def criteria(base_adj, base_slope_blk, base_label):
    d = delta_stats(adj_N, base_adj)
    r = {"baseline": base_label,
         "median_abs_delta_le_0.5": d["median"] <= MED, "p95_abs_delta_le_2.0": d["p95"] <= P95}
    npop = out["M2"]["rows_newly_populated_vs_B2"] if base_label == "B2" else len(only_new)
    r["newly_populated_share_le_10pct"] = bool(npop / len(sc) <= NEWPOP)
    nb = out["M2"]["nHuber_B2"] if base_label == "B2" else out["M2"]["nHuber_B1"]
    r["abs_delta_nHuber_share_le_10pct"] = bool(abs(out["M2"]["nHuber_new"] - nb) / max(nb, 1) <= NHUB)
    # slope (i): pipeline slope vs its M19 CI (baseline = B1 only; B2's pipeline report was not stored)
    if base_label == "B1":
        s0, s1 = info_B1["slope_hub_mv_per_month"], info_N["slope_hub_mv_per_month"]
        c0 = info_B1["boot_ci95_mv_per_month"]
        r["slope_i_shift_le_0.25_halfwidth"] = bool(abs(s1 - s0) <= SLOPE_F * hw(c0))
        r["slope_i_zero_inclusion_unchanged"] = bool(incl0(c0) == incl0(info_N["boot_ci95_mv_per_month"]))
    sb = out["M4"]["ii_huberSlopeMvPerMo"][base_label]
    r["slope_ii_shift_le_0.25_halfwidth"] = bool(abs(sl_N - sb["slope"]) <= SLOPE_F * hw(sb["ci95"]))
    r["slope_ii_zero_inclusion_unchanged"] = bool(incl0(sb["ci95"]) == incl0(ciN))
    if base_label == "B1":
        r["bT_shift_le_0.25_halfwidth"] = bool(abs(coef_N["bT"] - coef_B1["bT"]) <= COEF_F * hw(cB1["bT"]))
        r["bI_shift_le_0.25_halfwidth"] = bool(abs(coef_N["bI"] - coef_B1["bI"]) <= COEF_F * hw(cB1["bI"]))
        r["coef_ci_inconclusive_if_failed_draws_gt_1pct"] = bool(cB1["failed_draws"] > 0.01 * NB)
    r["ALL_PASS"] = bool(all(v for k, v in r.items() if k not in ("baseline", "coef_ci_inconclusive_if_failed_draws_gt_1pct")) and not r.get("coef_ci_inconclusive_if_failed_draws_gt_1pct", False))
    return r


out["criteria"] = {"vs_B1_exclusion_effect": criteria(adj_B1, None, "B1"), "vs_B2_published_change": criteria(B2, None, "B2"),
                   "refit_drift_B2_vs_B1_alone": {"median": out["M2"]["refit_drift_B2_vs_B1"]["median"], "p95": out["M2"]["refit_drift_B2_vs_B1"]["p95"],
                                                  "median_le_0.5": out["M2"]["refit_drift_B2_vs_B1"]["median"] <= MED, "p95_le_2.0": out["M2"]["refit_drift_B2_vs_B1"]["p95"] <= P95}}
# sensitivities
s1c, s1a = fit(sc)
last8 = sorted(keep_new["day"].unique())[-8:]
s2c, s2a = fit(keep_new[~keep_new["day"].isin(last8)])
out["sensitivity"] = {"S1_no_exclusion": {"coef": s1c, "n": int(len(sc)), "delta_vs_new": delta_stats(s1a, adj_N)},
                      "S2_leave_last_8_days_out_E_new": {"coef": s2c, "left_out_days": last8, "delta_vs_new_on_common_rows": delta_stats(s2a, adj_N)},
                      "S3_epsilon": {str(e): {"coef": fit(keep_new, e)[0], "delta_vs_new": delta_stats(fit(keep_new, e)[1], adj_N)} for e in (1.2, 1.5)},
                      "S4_reported_in_M2": True}
json.dump(out, open("analyses/M312_results.json", "w", encoding="utf-8"), indent=1)
c = out["criteria"]
print(json.dumps({"M1": out["M1"], "M2_new_vs_B1": out["M2"]["new_vs_B1"], "M2_new_vs_B2": out["M2"]["new_vs_B2"], "M2_refit_drift": out["M2"]["refit_drift_B2_vs_B1"],
                  "ALL_PASS_vs_B1": c["vs_B1_exclusion_effect"]["ALL_PASS"], "ALL_PASS_vs_B2": c["vs_B2_published_change"]["ALL_PASS"]}, indent=1))
