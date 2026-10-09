#!/usr/bin/env python3
"""M393 (read-only study, script-written JSON analyses/M393_resistance_cadence.json): is the pack-resistance proxy slope (powerFade, +0.552 mOhm/month) correct, and does the
logger PID-cadence change influence it?  Proxy = vreg_R_pack_mohm (Huber V ~ soc + Id per drive); model = R ~ 1 + months + T_pack_mean_avg + vreg_I_p95_A [+ cadence covariates]
on the v2-clean set, day-clustered percentile bootstrap (seed 42, 4000 draws), exactly as compute_drive_summary_v6._powerfade_trend.
Part A  reproduction: the pipeline function on the live master vs the stored arrays value; an INDEPENDENT own implementation of the same OLS; cluster-robust (day) OLS CI (method disagreement reported).
Part B  specification sensitivity (same clean set unless stated): M0 no cadence covariate; M1 published (median interval + coverage of the HV-current channel); M2 regime dummies
        (fast1 = 2026-08-14..09-06, fast2 = from 2026-10-01) instead of the density covariates; M3 density + dummies; M4 published model on drives up to 2026-09-30 (before the latest change);
        M5 slow-regime drives only, no cadence covariate; M6 slow-regime + fast1 only (everything before the latest change) with a fast1 dummy.
Part C  proxy-level emulation (tools/cadence_emulate.py, M379b method): every fast-regime clean drive is thinned to the slow-regime interval distribution (seeded pools from slow drives),
        analyze_bytes is re-run, vreg_R_pack_mohm recomputed (mean over seeds); per-drive paired difference (emulated - original) by era with a day-clustered CI; slope re-estimated with the
        emulated values for the fast drives ('slow-equivalent').  Emulated sampling sensitivity, NOT a causal cadence effect (PID order, I-V co-timing, jitter are not emulated).
Nothing is written to the master. Usage: python analyses/M393_resistance_cadence.py [--seeds 3] [--skip-emulation]"""
import argparse, json, os, sys, time
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import compute_drive_summary_v6 as V
import cadence_emulate as CE

ap = argparse.ArgumentParser(); ap.add_argument("--seeds", type=int, default=3); ap.add_argument("--skip-emulation", action="store_true"); a = ap.parse_args()
STAGE = os.path.join(ROOT, "raw_only")
loader = lambda fn: open(os.path.join(STAGE, fn), "rb").read()
dm = pd.read_csv("drive_master.csv", low_memory=False)
reg = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
NB, SEED = V.N_BOOT, 42
FAST2_FROM, FAST1 = "2026-10-01", ("2026-08-14", "2026-09-06")
out = {"seed": SEED, "n_boot": NB, "model": "R ~ 1 + months + T_pack_mean_avg + vreg_I_p95_A [+ covariates]; day-clustered percentile bootstrap"}

# ---------------- clean set (as _powerfade_trend) ----------------
keep = ~dm["ens_outlier_v2"].fillna(False).astype(bool)
rcol, icol = "vreg_R_pack_mohm", "vreg_I_p95_A"
cc = dm[keep].dropna(subset=[rcol, "T_pack_mean_avg", icol, "date"]).copy()
cc["regime"] = cc["file"].map(reg)
cc["era"] = np.where(cc["regime"] == "fast", np.where(cc["date"].astype(str) >= FAST2_FROM, "fast2", "fast1"), np.where(cc["regime"] == "slow", "slow", "unknown"))
print("clean n", len(cc), cc["era"].value_counts().to_dict(), flush=True)


def slope(df, cols, y=None, boot=True):
    dt = pd.to_datetime(df["date"]); t = ((dt - pd.to_datetime(cc["date"]).min()).dt.days / 30.44).values
    X = np.column_stack([np.ones(len(df)), t, df["T_pack_mean_avg"].values, df[icol].values] + [df[c].values.astype(float) for c in cols])
    yy = (df[rcol] if y is None else y).values.astype(float)
    b = np.linalg.lstsq(X, yy, rcond=None)[0]
    res = {"slope": round(float(b[1]), 4), "n": int(len(df)), "n_days": int(dt.dt.date.nunique())}
    if boot:
        days = dt.dt.date.values; uniq = np.unique(days); grp = {d: np.where(days == d)[0] for d in uniq}
        rng = np.random.default_rng(SEED); bs = []
        for _ in range(NB):
            idx = np.concatenate([grp[d] for d in rng.choice(uniq, size=len(uniq), replace=True)])
            if len(np.unique(t[idx])) < 3:
                continue
            try:
                bs.append(float(np.linalg.lstsq(X[idx], yy[idx], rcond=None)[0][1]))
            except Exception:
                pass
        bs = np.array(bs); lo, hi = np.percentile(bs, [2.5, 97.5])
        res.update(ci95=[round(float(lo), 3), round(float(hi), 3)], p_slope_gt0=round(float((bs > 0).mean()), 3), n_boot=int(len(bs)))
    return res


# ---------------- Part A ----------------
stored = json.load(open("summary_arrays.json", encoding="utf-8"))
def find_key(o, key):
    if isinstance(o, dict):
        if key in o:
            return o
        for v in o.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_key(v, key)
            if r is not None:
                return r
    return None


pf = find_key(stored, "slopeMohmPerMoTctrl") or {}
pipe = V._powerfade_trend(dm, raw_loader=loader)
A = {"stored_powerFade": {k: pf.get(k) for k in pf if not isinstance(pf.get(k), (dict, list)) or k.lower().startswith(("ci", "boot"))},
     "pipeline_function_now": pipe}
dens = V._i_channel_sampling_density(cc["file"].tolist(), loader)
cc["dens_eff"] = [dens.get(f, (np.nan, np.nan))[0] for f in cc["file"]]
cc["dens_cov"] = [dens.get(f, (np.nan, np.nan))[1] for f in cc["file"]]
ok = cc[np.isfinite(cc["dens_eff"]) & np.isfinite(cc["dens_cov"])]
A["own_M1_published_design"] = slope(ok, ["dens_eff", "dens_cov"])
A["own_matches_pipeline_slope"] = bool(abs(A["own_M1_published_design"]["slope"] - pipe.get("slope_mohm_per_month_Tctrl", 1e9)) < 1e-3)
try:
    import statsmodels.api as sm
    dt = pd.to_datetime(ok["date"]); t = ((dt - pd.to_datetime(cc["date"]).min()).dt.days / 30.44).values
    X = np.column_stack([np.ones(len(ok)), t, ok["T_pack_mean_avg"].values, ok[icol].values, ok["dens_eff"].values, ok["dens_cov"].values])
    fit = sm.OLS(ok[rcol].values, X).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(dt.dt.date)[0]})
    A["cluster_robust_ols_M1"] = {"slope": round(float(fit.params[1]), 4), "ci95": [round(float(x), 3) for x in fit.conf_int()[1]], "p": round(float(fit.pvalues[1]), 4), "n_clusters": int(len(np.unique(pd.factorize(dt.dt.date)[0])))}
except Exception as ex:
    A["cluster_robust_ols_M1"] = {"error": repr(ex)}
out["A_reproduction"] = A
print("A", json.dumps(A)[:900], flush=True)

# ---------------- Part B ----------------
cc["fast1"] = (cc["era"] == "fast1").astype(float); cc["fast2"] = (cc["era"] == "fast2").astype(float)
okd = cc[np.isfinite(cc["dens_eff"]) & np.isfinite(cc["dens_cov"])]
B = {"era_counts": cc["era"].value_counts().to_dict(),
     "era_R_median_mohm": {e: round(float(g[rcol].median()), 1) for e, g in cc.groupby("era")},
     "era_dens_eff_median_s": {e: round(float(g["dens_eff"].median()), 3) for e, g in cc.groupby("era")},
     "M0_no_cadence_covariate": slope(cc, []),
     "M1_published_density": slope(okd, ["dens_eff", "dens_cov"]),
     "M2_regime_dummies": slope(cc[cc["era"] != "unknown"], ["fast1", "fast2"]),
     "M3_density_plus_dummies": slope(okd[okd["era"] != "unknown"], ["dens_eff", "dens_cov", "fast1", "fast2"]),
     "M4_published_model_to_2026-09-30": slope(okd[okd["date"].astype(str) < FAST2_FROM], ["dens_eff", "dens_cov"]),
     "M5_slow_only_no_covariate": slope(cc[cc["era"] == "slow"], []),
     "M6_before_latest_change_fast1_dummy": slope(cc[cc["date"].astype(str) < FAST2_FROM], ["fast1"])}
out["B_specification_sensitivity"] = B
print("B", json.dumps({k: (v if not isinstance(v, dict) else {x: v[x] for x in ("slope", "ci95", "n") if x in v}) for k, v in B.items() if k.startswith("M")}), flush=True)

# ---------------- Part C ----------------
if not a.skip_emulation:
    fast = cc[cc["era"].isin(["fast1", "fast2"])]
    slow_files = cc[cc["era"] == "slow"]["file"].tolist()
    rs = np.random.default_rng(7)
    pool_files = [slow_files[i] for i in sorted(rs.choice(len(slow_files), size=min(40, len(slow_files)), replace=False))]
    pools = CE.build_pools([os.path.join(STAGE, f) for f in pool_files])
    emu = {}; t0 = time.time()
    first_bytes = {}
    for n, f in enumerate(fast["file"].tolist()):
        vals = []
        for s in range(a.seeds):
            rng = np.random.default_rng(s * 100003 + n)
            b, rep = CE.emulate(open(os.path.join(STAGE, f), "rb").read(), pools, rng)
            row = V.analyze_bytes(b, f)
            vals.append(row.get(rcol))
            if s == 0:
                first_bytes[f] = b
        v = [x for x in vals if x is not None and x == x]
        emu[f] = float(np.mean(v)) if v else np.nan
        if (n + 1) % 20 == 0:
            print(f"  emulated {n + 1}/{len(fast)} drives, {round(time.time() - t0)} s", flush=True)
    fast = fast.assign(R_emu=fast["file"].map(emu))
    fast_all = fast.copy()
    fast = fast[np.isfinite(fast["R_emu"])]
    fast = fast.assign(diff=fast["R_emu"] - fast[rcol])
    C = {"n_fast_clean": int(len(fast_all)), "n_fast_clean_emulated": int(len(fast)), "seeds": a.seeds, "slow_pool_drives": len(pool_files),
         "n_fast_lose_proxy_at_slow_sampling": int(len(fast_all) - len(fast)),
         "lose_proxy_by_era": {e: int((g["R_emu"].isna()).sum()) for e, g in fast_all.groupby("era")}}
    for era, g in fast.groupby("era"):
        dd = g.groupby(g["date"].astype(str))["diff"].mean(); rng = np.random.default_rng(SEED)
        bs = [dd.values[rng.integers(0, len(dd), len(dd))].mean() for _ in range(NB)]
        C[f"paired_diff_{era}"] = {"n": int(len(g)), "n_days": int(len(dd)), "mean_emulated_minus_original_mohm": round(float(g["diff"].mean()), 3), "median": round(float(g["diff"].median()), 3),
                                   "ci95_day_clustered": [round(float(x), 3) for x in np.percentile(bs, [2.5, 97.5])], "original_mean": round(float(g[rcol].mean()), 2)}
    # SAME-DRIVE comparison: slow drives + the fast drives whose proxy survives emulation (n identical on both sides)
    same = cc[(cc["era"] == "slow") | cc["file"].isin(fast["file"])].copy()
    same["R_emu"] = same["file"].map(emu).where(same["era"] != "slow", same[rcol])
    C["same_drive_set"] = {"n": int(len(same)), "original_M0": slope(same, []), "emulated_M0": slope(same, [], y=same["R_emu"])}
    # slow-equivalent slope: fast drives' R replaced by the emulated value, every drive now at slow cadence
    cc2 = cc.copy(); cc2["R_se"] = cc2[rcol]
    m = cc2["file"].isin(fast["file"]); cc2.loc[m, "R_se"] = cc2.loc[m, "file"].map(emu)
    cc2 = cc2[np.isfinite(cc2["R_se"])]
    C["slow_equivalent_M0_no_covariate"] = slope(cc2, [], y=cc2["R_se"])
    C["original_M0_same_drives"] = slope(cc2, [])
    # density covariates recomputed for the emulated drives (seed-0 emulated bytes)
    ld2 = lambda fn: first_bytes[fn] if fn in first_bytes else loader(fn)
    d2 = V._i_channel_sampling_density(cc2["file"].tolist(), ld2)
    s2 = same.copy()
    d3 = V._i_channel_sampling_density(s2["file"].tolist(), ld2); d0 = V._i_channel_sampling_density(s2["file"].tolist(), loader)
    s2["de"] = [d3.get(f, (np.nan, np.nan))[0] for f in s2["file"]]; s2["dc"] = [d3.get(f, (np.nan, np.nan))[1] for f in s2["file"]]
    s2["oe"] = [d0.get(f, (np.nan, np.nan))[0] for f in s2["file"]]; s2["oc"] = [d0.get(f, (np.nan, np.nan))[1] for f in s2["file"]]
    s2 = s2[np.isfinite(s2["de"]) & np.isfinite(s2["dc"]) & np.isfinite(s2["oe"]) & np.isfinite(s2["oc"])]
    C["same_drive_set"]["original_published_design"] = slope(s2, ["oe", "oc"])
    C["same_drive_set"]["emulated_published_design"] = slope(s2, ["de", "dc"], y=s2["R_emu"])
    cc2["de"] = [d2.get(f, (np.nan, np.nan))[0] for f in cc2["file"]]; cc2["dc"] = [d2.get(f, (np.nan, np.nan))[1] for f in cc2["file"]]
    c3 = cc2[np.isfinite(cc2["de"]) & np.isfinite(cc2["dc"])]
    C["slow_equivalent_published_design"] = slope(c3, ["de", "dc"], y=c3["R_se"])
    out["C_emulation"] = C
    print("C", json.dumps({k: v for k, v in C.items() if not k.startswith("paired")})[:700], flush=True)
    print("C paired", json.dumps({k: v for k, v in C.items() if k.startswith("paired")}), flush=True)
json.dump(out, open("analyses/M393_resistance_cadence.json", "w", encoding="utf-8", newline="\n"), indent=1, default=float)
print("written")
