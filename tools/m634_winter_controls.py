#!/usr/bin/env python3
"""M634 (implements analyses/M622_spec.md Rev 1, registered at M622; sha256 prefix 2e1c61ddd8ed67d7): temperature-control specifications for the resistance-proxy and the cell-spread months coefficients,
a day-blocked cross-validation with the pre-registered retention rule, and the per-look attainability gate. Additive payload block `powerFadeTemperatureControls`.

Specifications (spec section 3), on the SAME rows as the released S0 / S1 fits (clean complete cases; months = days / 30.44 from the minimum date):
  T-lin  linear pack temperature (the released control)         T-quad  linear + squared (temperature centred)
  T-arr  Arrhenius: ln(y) on 1 / T(K); the slope is the marginal monthly slope on the ORIGINAL scale at the reference covariates, Duan smearing for the back-transformation
  T-spl  natural cubic spline in pack temperature, knots at 10, 20 and 30 C (absolute), boundary knots at the observed min and max; reportable only where the temperature support holds
The headline estimator and the equivalence test (locked bound, mOhm per month) are NOT touched: these are TREND / SENSITIVITY specifications.
Intervals: day-clustered percentile bootstrap (calendar day = cluster, seed 42, 4000 draws) for every specification; cluster-robust (CR1, t(G-1)) interval for the specifications linear in the months coefficient.
Cross-validation (R4): K = min(10, number of days) day-blocked folds, fold assignment by a seeded permutation of the days; error on the original scale (smearing for T-arr; held-out temperatures clipped to the training range for every specification); comparison = mean of the PAIRED fold-wise
RMSE difference versus the primary and its standard error across folds; the primary (T-arr) is retained unless another specification has a lower error by more than that standard error on two consecutive ingestions.
Usage: python tools/m634_winter_controls.py [--out analyses/M634_result.json] [--nb 4000] | --splice"""
import datetime, hashlib, json, math, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
from scipy import stats

SEED, NB_DEFAULT, MONTH_DAYS = 42, 4000, 30.44
KNOTS_C = (10.0, 20.0, 30.0)                 # spec R5: absolute degrees C, frozen
CELL_EDGES = list(range(-10, 55, 5))         # 5 C pack-temperature cells
MIN_CELL_DRIVES, MIN_CELL_DAYS = 10, 5       # the project cohort floor
SPECS = ("T-lin", "T-quad", "T-arr", "T-spl")
PRIMARY = "T-arr"
LOOKS = {"month9": {"cutoff": "2027-02-11", "alpha": None, "role": "descriptive only (spec Rev 1, alpha option A)"},
         "month12": {"cutoff": "2027-05-11", "alpha": 0.05, "role": "formal look: full alpha"}}
SPEC_PATH = "analyses/M622_spec.md"


def months_from(dates, t0):
    return ((pd.to_datetime(dates) - t0).dt.days / MONTH_DAYS).to_numpy(float)


def ns_basis(T, lo, hi):
    """Natural cubic spline basis (Hastie, Tibshirani, Friedman, ESL 5.2.1) with the boundary knots lo, hi and the frozen interior knots KNOTS_C; T clipped to [lo, hi] (not extrapolated).
    Columns: T and the K-2 nonlinear terms d_k(T) - d_{K-1}(T); the intercept is added by the caller."""
    T = np.clip(np.asarray(T, float), lo, hi)
    xi = [lo] + [k for k in KNOTS_C if lo < k < hi] + [hi]
    K = len(xi)
    def d(k):
        return (np.maximum(T - xi[k], 0) ** 3 - np.maximum(T - xi[K - 1], 0) ** 3) / (xi[K - 1] - xi[k])
    cols = [T] + [d(k) - d(K - 2) for k in range(K - 2)]
    return cols


def temp_terms(spec, T, bounds=None):
    """Columns of the temperature control for one specification (T in deg C)."""
    T = np.asarray(T, float)
    if spec == "T-lin":
        return [T]
    if spec == "T-quad":
        return [T, T ** 2]
    if spec == "T-arr":
        return [1.0 / (T + 273.15)]
    if spec == "T-spl":
        lo, hi = bounds if bounds is not None else (float(T.min()), float(T.max()))
        return ns_basis(T, lo, hi)
    raise ValueError(spec)


def design(spec, t, T, extra, bounds=None):
    """const, months, temperature terms, then the extra covariates (current, de, dc). The months coefficient is column 1."""
    return np.column_stack([np.ones(len(t)), t] + temp_terms(spec, T, bounds) + [np.asarray(e, float) for e in extra])


def fit_spec(spec, y, t, T, extra, ref=None):
    """Return dict(b, X, smear, slope, bounds) for one specification. The slope is the months effect on the ORIGINAL scale at the reference covariates (column means of X)."""
    T = np.asarray(T, float)
    bounds = (float(T.min()), float(T.max())) if spec == "T-spl" else None
    X = design(spec, t, T, extra, bounds)
    if spec == "T-arr":
        if np.any(y <= 0):
            raise ValueError("T-arr needs a positive response")
        z = np.log(y)
        b = np.linalg.lstsq(X, z, rcond=None)[0]
        resid = z - X @ b
        smear = float(np.mean(np.exp(resid)))                    # Duan smearing factor
        xr = X.mean(axis=0) if ref is None else ref
        yref = smear * float(np.exp(xr @ b))
        return {"b": b, "X": X, "smear": smear, "slope": yref * float(b[1]), "xref": xr, "bounds": bounds}   # d E[y] / d months at the reference covariates
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    return {"b": b, "X": X, "smear": 1.0, "slope": float(b[1]), "xref": X.mean(axis=0), "bounds": bounds}


def predict(spec, fit, Xnew):
    eta = Xnew @ fit["b"]
    return fit["smear"] * np.exp(eta) if spec == "T-arr" else eta


def day_boot(spec, y, t, T, extra, days, nb=NB_DEFAULT, seed=SEED):
    """Day-clustered percentile bootstrap of the original-scale months slope (whole refit per draw, including the smearing factor and the reference point of T-arr)."""
    uniq, di = np.unique(np.asarray(days), return_inverse=True)
    G = len(uniq)
    idx = [np.where(di == g)[0] for g in range(G)]
    rng = np.random.default_rng(seed)
    out, dropped = [], 0
    for _ in range(nb):
        pick = rng.integers(0, G, G)
        if len(set(pick.tolist())) < 3:
            dropped += 1
            continue
        rows = np.concatenate([idx[g] for g in pick])
        try:
            f = fit_spec(spec, y[rows], t[rows], T[rows], [e[rows] for e in extra])
            if not np.isfinite(f["slope"]):
                raise ValueError
            out.append(f["slope"])
        except (ValueError, np.linalg.LinAlgError):
            dropped += 1
    out = np.asarray(out)
    q = np.percentile(out, [2.5, 97.5]) if len(out) else np.array([np.nan, np.nan])
    return {"ci95": [float(q[0]), float(q[1])], "drawsUsed": int(len(out)), "drawsDropped": int(dropped), "seed": seed, "cluster": "calendar day"}


def cr1_ci(spec, y, t, T, extra, days):
    """Cluster-robust (CR1, day clusters) interval with the t(G-1) reference for the specifications linear in the months coefficient (not for T-arr, whose slope is a nonlinear function)."""
    if spec == "T-arr":
        return None
    import statsmodels.api as sm
    X = design(spec, t, T, extra)
    res = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": np.asarray(days)})
    G = len(np.unique(days))
    tc = float(stats.t.ppf(0.975, G - 1))
    b, se = float(res.params[1]), float(res.bse[1])
    return {"slope": b, "se": se, "ci95": [b - tc * se, b + tc * se], "reference": "t(G-1), G=%d" % G}


def fold_assignment(days, K, seed=SEED):
    uniq = np.unique(np.asarray(days))
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(uniq))
    fold_of_day = {uniq[i]: int(r % K) for r, i in enumerate(perm)}
    return np.array([fold_of_day[d] for d in np.asarray(days)])


def cv_errors(y, t, T, extra, days, K=None, seed=SEED, clip=True):
    """Per specification: fold-wise RMSE on the original scale (smearing for T-arr). Returns {spec: [rmse_k]} and K."""
    ndays = len(np.unique(days))
    K = min(10, ndays) if K is None else K
    fold = fold_assignment(days, K, seed)
    out = {s: [] for s in SPECS}
    for k in range(K):
        te, tr = fold == k, fold != k
        if te.sum() == 0 or tr.sum() < 10:
            continue
        for s in SPECS:
            try:
                f = fit_spec(s, y[tr], t[tr], T[tr], [e[tr] for e in extra])
                Tte = np.clip(T[te], T[tr].min(), T[tr].max()) if (clip or s == "T-spl") else T[te]   # like-for-like: held-out temperatures are clipped to the training range for EVERY specification (the spline cannot extrapolate)
                Xte = design(s, t[te], Tte, [e[te] for e in extra], f['bounds'])
                err = y[te] - predict(s, f, Xte)
                out[s].append(float(np.sqrt(np.mean(err ** 2))))
            except (ValueError, np.linalg.LinAlgError):
                out[s].append(float("nan"))
    return out, K


def retention(cv, prev=None, eligible=None, master_md5=None):
    """R4: the primary stays unless another specification has a lower error by more than the standard error of the paired fold-wise RMSE difference, on two consecutive ingestions."""
    arr = np.asarray(cv[PRIMARY], float)
    rows = {}
    challenger, best = None, None
    for s in SPECS:
        if s == PRIMARY:
            continue
        x = np.asarray(cv[s], float)
        if eligible is not None and not eligible.get(s, True):
            m0 = np.isfinite(x) & np.isfinite(arr)
            d0 = x[m0] - arr[m0]
            rows[s] = {"meanRmseDifferenceVsPrimary": None, "seDifference": None, "beatsPrimary": False, "nFolds": 0, "eligible": False, "reason": "not reportable (temperature support)",
                       "descriptiveMeanRmseDifference": float(np.mean(d0)) if m0.sum() >= 3 else None,
                       "descriptiveSeDifference": float(np.std(d0, ddof=1) / math.sqrt(len(d0))) if m0.sum() >= 3 else None}
            continue
        m = np.isfinite(x) & np.isfinite(arr)
        if m.sum() < 3:
            rows[s] = {"meanRmseDifferenceVsPrimary": None, "seDifference": None, "beatsPrimary": False, "nFolds": int(m.sum())}
            continue
        d = x[m] - arr[m]                                  # spec minus primary: negative = the spec predicts better
        se = float(np.std(d, ddof=1) / math.sqrt(len(d)))
        beats = bool(np.mean(d) < 0 and abs(np.mean(d)) > se)
        rows[s] = {"meanRmseDifferenceVsPrimary": float(np.mean(d)), "seDifference": se, "beatsPrimary": beats, "nFolds": int(m.sum())}
        if beats and (best is None or np.mean(d) < best):
            challenger, best = s, float(np.mean(d))
    prev_c = (prev or {}).get("challenger")
    same_corpus = bool(prev and master_md5 and prev.get("masterMd5") == master_md5)       # a re-run on the SAME corpus is not a new ingestion: the count is carried, never incremented
    if same_corpus:
        consecutive = int(prev.get("consecutive", 0)) if challenger == prev_c else (1 if challenger else 0)
    else:
        consecutive = (int((prev or {}).get("consecutive", 0)) + 1) if (challenger and challenger == prev_c) else (1 if challenger else 0)
    return {"primary": PRIMARY, "masterMd5": master_md5, "bySpec": rows, "challenger": challenger, "consecutive": consecutive, "switchTriggered": bool(consecutive >= 2),
            "rule": "the primary is retained unless another specification has a lower paired fold-wise RMSE by more than its standard error on two consecutive ingestions; any switch is a recorded deviation and is not applied retroactively"}


def support_cells(T, days):
    """5 C pack-temperature cells with the support floor (>= 10 drives on >= 5 calendar days): count and listing."""
    T = np.asarray(T, float)
    cells = []
    for lo in CELL_EDGES[:-1]:
        m = (T >= lo) & (T < lo + 5)
        n, d = int(m.sum()), int(len(set(np.asarray(days)[m].tolist())))
        cells.append({"cellC": [lo, lo + 5], "nDrives": n, "nDays": d, "supported": bool(n >= MIN_CELL_DRIVES and d >= MIN_CELL_DAYS)})
    return cells


def attainability(delta, df, se_now):
    """Per look: the ceiling on the standard error at which the TOST can succeed for ANY slope, delta / t(1 - alpha, df), for the alpha spent at that look (None for a descriptive look)."""
    out = {}
    for name, L in LOOKS.items():
        a = L["alpha"]
        ceil = None if a is None else float(delta / stats.t.ppf(1 - a, df))
        out[name] = {"cutoff": L["cutoff"], "alpha": a, "role": L["role"], "seCeiling": None if ceil is None else round(ceil, 4),
                     "currentSe": round(float(se_now), 4), "attainableNow": None if ceil is None else bool(se_now <= ceil)}
    return out


class FidelityError(SystemExit):
    pass


def analyse_metric(label, d, ycol, icol, extra_names, nb, prev_cv=None, delta=None, se_now=None, unit="mOhm", released_slope=None, master_md5=None):
    """One metric. `d` has columns y, date, T, I (+ extras). Returns the block for this metric."""
    d = d.sort_values(["date"], kind="stable").reset_index(drop=True)
    t0 = pd.to_datetime(d["date"]).min()
    t = months_from(d["date"], t0)
    y = d["y"].to_numpy(float)
    T = d["T"].to_numpy(float)
    extra = [d[c].to_numpy(float) for c in extra_names]
    days = d["date"].astype(str).to_numpy()
    G = len(np.unique(days))
    rows = {}
    f_lin = fit_spec("T-lin", y, t, T, extra)
    import degradation_trends as _DT
    if released_slope is not None:
        released_slope = released_slope * (MONTH_DAYS / _DT.MONTH_DAYS)          # the released slopes are per (days / 30.4375); this script uses days / 30.44 (M578 convention)
    if released_slope is not None and abs(f_lin["slope"] - released_slope) > 1.1e-4:           # fidelity stop: T-lin is the released control and must reproduce the released slope
        raise FidelityError("STOP fidelity (%s): T-lin slope %.5f != released %.5f" % (label, f_lin["slope"], released_slope))
    for s in SPECS:
        f = fit_spec(s, y, t, T, extra)
        b = day_boot(s, y, t, T, extra, days, nb=nb)
        cr = cr1_ci(s, y, t, T, extra, days)
        rows[s] = {"slope": round(f["slope"], 4), "dayBootstrap": {"ci95": [round(x, 4) for x in b["ci95"]], "drawsUsed": b["drawsUsed"], "drawsDropped": b["drawsDropped"]},
                   "includesZero": bool(b["ci95"][0] <= 0 <= b["ci95"][1]), "cr1": None if cr is None else {"ci95": [round(x, 4) for x in cr["ci95"]], "se": round(cr["se"], 4), "reference": cr["reference"]},
                   "smearingFactor": round(f["smear"], 5) if s == "T-arr" else None, "temperatureTerms": design_names(s)}
    cv, K = cv_errors(y, t, T, extra, days)
    cells = support_cells(T, days)
    n_sup = sum(1 for c in cells if c["supported"])
    n_sup_below10 = sum(1 for c in cells if c["supported"] and c["cellC"][1] <= 10)
    rows["T-spl"]["reportable"] = bool(n_sup >= 4 and all(any(c["supported"] for c in cells if lo <= c["cellC"][0] < hi) for lo, hi in ((-10, 10), (10, 20), (20, 30))))
    rows["T-spl"]["supportReason"] = "%d supported 5 C cells (%d below 10 C); reportable needs at least 4 and a supported cell in each of <10, 10-20 and 20-30 C" % (n_sup, n_sup_below10)
    ret = retention(cv, prev_cv, eligible={"T-spl": rows["T-spl"]["reportable"]}, master_md5=master_md5)
    cv_unc, _ = cv_errors(y, t, T, extra, days, clip=False)
    block = {"metric": label, "unit": unit + " per month", "nDrives": int(len(d)), "nDays": int(G), "monthsScale": "days / 30.44 from the minimum date of the rows", "specs": rows,
             "crossValidation": {"K": int(K), "seed": SEED, "foldRmse": {s: [None if not np.isfinite(x) else round(x, 4) for x in cv[s]] for s in SPECS},
                                 "meanRmse": {s: (None if not np.isfinite(np.nanmean(cv[s])) else round(float(np.nanmean(cv[s])), 4)) for s in SPECS},
                                 "meanRmseUnclippedDescriptive": {s: (None if not np.isfinite(np.nanmean(cv_unc[s])) else round(float(np.nanmean(cv_unc[s])), 4)) for s in SPECS},
                                 "clipping": "held-out temperatures are clipped to the training range for every specification (like-for-like; the spline cannot extrapolate); the unclipped figures are descriptive", "retention": ret},
             "temperatureSupport": {"cells": cells, "supportedCells": n_sup, "supportedBelow10C": n_sup_below10, "floor": "%d drives on %d days" % (MIN_CELL_DRIVES, MIN_CELL_DAYS)}}
    if delta is not None and se_now is not None:
        block["attainability"] = attainability(delta, G - 1, se_now)
    return block


def design_names(spec):
    return {"T-lin": ["T"], "T-quad": ["T", "T2"], "T-arr": ["1/T(K)"], "T-spl": ["natural cubic spline, knots %s C" % (list(KNOTS_C),)]}[spec]


def main(argv):
    import powerfade_equivalence as PE
    import degradation_trends as DT
    nb = int(argv[argv.index("--nb") + 1]) if "--nb" in argv else NB_DEFAULT
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else "analyses/M634_result.json"
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    side = PE._read(PE.SIDECAR)
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in side.to_dict("records")}
    prev = (A.get("powerFadeTemperatureControls") or {})
    res = {"spec": SPEC_PATH, "provenance": {"masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
                                             "specSha256": hashlib.sha256(open(SPEC_PATH, "rb").read()).hexdigest(), "seed": SEED, "nBoot": nb,
                                             "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}}
    # resistance proxy: the released S0 / S1 rows (clean complete cases with the sidecar density)
    cc, have_d = PE.s1_rows(dm, dens)
    rv = A["degradationTrends"]["resistanceVreg"]; cs = A["degradationTrends"]["cellSpread"]
    delta_r, delta_c = rv["releasedEquivalence"]["delta"], cs["releasedEquivalence"]["delta"]
    t0_all = pd.to_datetime(cc["date"]).min()
    r = have_d.copy(); r["y"] = r[PE.RCOL].astype(float); r["T"] = r["T_pack_mean_avg"].astype(float); r["I"] = r[PE.ICOL].astype(float)
    # the M622 months origin is the minimum date of the rows of each metric (the released fits use the same convention per metric)
    blocks = {}
    blocks["resistanceProxyS0"] = analyse_metric("resistance proxy, S0 design y ~ months + T-control + I", r, PE.RCOL, PE.ICOL, ["I"], nb, (prev.get("resistanceProxyS0") or {}).get("crossValidation", {}).get("retention"),
                                                 delta_r, A["powerFadeEquivalence"]["s0Control"]["se"], "mOhm", A["powerFadeEquivalence"]["s0Control"]["slope"], res["provenance"]["masterMd5"])
    blocks["resistanceProxyS1"] = analyse_metric("resistance proxy, S1 design y ~ months + T-control + I + de + dc", r, PE.RCOL, PE.ICOL, ["I", "_de", "_dc"], nb, (prev.get("resistanceProxyS1") or {}).get("crossValidation", {}).get("retention"),
                                                 delta_r, A["powerFadeEquivalence"]["s1"]["se"], "mOhm", A["powerFadeEquivalence"]["s1"]["slope"], res["provenance"]["masterMd5"])
    # cell spread: the released design y ~ months + T + I on drive_master rows (DT._prep)
    dcs = DT._prep(dm, "cell_spread_loaded_p95_mv", icol="peak_I_discharge")
    dcs = dcs.dropna(subset=["T", "I"]).copy()
    dcs["date"] = dcs["date"].dt.date.astype(str)
    blocks["cellSpread"] = analyse_metric("cell spread (loaded p95), design y ~ months + T-control + I", dcs, "cell_spread_loaded_p95_mv", "peak_I_discharge", ["I"], nb,
                                          (prev.get("cellSpread") or {}).get("crossValidation", {}).get("retention"), delta_c, cs["tostSeUsed"], "mV", cs["tostSlopeUsed"], res["provenance"]["masterMd5"])
    res["blocks"] = blocks
    res["looks"] = LOOKS
    res["label"] = ("temperature-control specifications of the resistance-proxy and cell-spread months coefficients (M622 spec Rev 1): trend / sensitivity specifications; the headline and the "
                    "equivalence test are unchanged; a proxy trend, never measured resistance; the study is 12 months, every figure before the month-12 look is provisional")
    if "--splice" in argv:
        return splice(res)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: {"n": v["nDrives"], "days": v["nDays"], "slopes": {s: [v["specs"][s]["slope"], v["specs"][s]["dayBootstrap"]["ci95"]] for s in SPECS}, "retention": v["crossValidation"]["retention"]["challenger"]} for k, v in blocks.items()}, indent=1))
    return 0


def splice(res):
    import copy
    P = "summary_arrays.json"
    raw = open(P, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    blk = json.loads(json.dumps({"label": res["label"], "spec": res["spec"], "specSha256": res["provenance"]["specSha256"], "scriptSha256": res["provenance"]["scriptSha256"], "masterMd5": res["provenance"]["masterMd5"],
                                 "seed": SEED, "nBoot": res["provenance"]["nBoot"], "looks": res["looks"], **res["blocks"]}))
    md5 = res["provenance"]["masterMd5"]
    old = (A.get("_artifactStamps") or {}).get("powerFadeTemperatureControls")
    coherent = old and old.get("includedInReleaseAt") == old.get("computedAt") == old.get("generatedAt")
    if A.get("powerFadeTemperatureControls") == blk and coherent and old.get("corpusHash") == md5:
        print(json.dumps({"changed": False}))
        return 0
    A["powerFadeTemperatureControls"] = blk
    st = copy.deepcopy(A["_artifactStamps"]["powerFadeTemperatureSpecs"])
    st.update(corpusHash=md5, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M634: derived by tools/m634_winter_controls.py from drive_master.csv and the tracked powerfade_density.csv (spec analyses/M622_spec.md Rev 1)", upstreamHashes={"driveMasterMd5": md5})
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    import stamp_common as _sc
    A["_artifactStamps"]["powerFadeTemperatureControls"] = _sc.carry_declared(old, st)
    open(P, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True, "block": "powerFadeTemperatureControls"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
