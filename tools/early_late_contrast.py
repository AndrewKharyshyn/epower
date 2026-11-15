#!/usr/bin/env python3
"""M678 (N-04, spec analyses/M677_spec.md Rev 1.1 and 1.2): exploratory early-versus-late contrast of three outcomes inside matched state cells. Reads drive_master.csv and two sidecars (read-only), writes the
additive payload block summary_arrays.json['earlyLateContrast'] (+ stamp). Path A: coarsened exact matching (covariate-only granularity ladder), late-count-weighted difference, day-clustered bootstrap with fixed cells
(seed 42, 4000 draws). Path B: OLS with day-cluster CR1 errors and t(G-1). Descriptive, not an M622 look, no equivalence verdict, no alpha spent.
Usage: python tools/early_late_contrast.py [--out PATH] [--nboot N]"""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
KEY = "earlyLateContrast"
SEED, NBOOT = 42, 4000
MIN_CELL, MIN_CELL_DAYS = 3, 2
SHOW_DRIVES, SHOW_DAYS = 10, 5
UPDATE_DATE = "2026-08-25"
LEVELS = [{"name": "5x5x4x2", "nT": 5, "nI": 5, "nS": 4}, {"name": "3x3x3x2", "nT": 3, "nI": 3, "nS": 3}]
DIST_EDGES = [-1, 5, 25, 9999]
ALPHA_BONF = 0.05 / 3
OUTCOMES = {
    "Y1": ("resistance proxy a1_R (model-derived), drives with a1_n >= 600", "resistance_joint_sidecar.csv:a1_R"),
    "Y2": ("loaded p95 cell spread (mV)", "master:cell_spread_loaded_p95_mv"),
    "Y3": ("median pack voltage V_pack_median (V); cap_ah_est is 2.1 kWh divided by this value, a voltage proxy and not a capacity", "master:V_pack_median"),
}
FROZEN_PATH = os.path.join(ROOT, "analyses", "M678_frozen_windows.json")


# ------------------------------------------------------------ data
def load(root=ROOT, master_path=None):
    m = pd.read_csv(master_path or os.path.join(root, "drive_master.csv"), low_memory=False)
    m = m[m["ens_outlier_v2"] == False].copy()                                 # noqa: E712
    res = pd.read_csv(os.path.join(root, "resistance_joint_sidecar.csv")).set_index("file")
    cad = pd.read_csv(os.path.join(root, "cadence_regime.csv")).set_index("file")
    d = pd.DataFrame({"file": m["file"].values, "date": pd.to_datetime(m["date"]).values, "T": m["T_pack_mean_avg"].astype(float).values,
                      "I": m["peak_I_discharge"].astype(float).values, "S": m["rf_socmean_wtd_pct"].astype(float).values,
                      "dist": m["distance_km"].astype(float).values})
    d["reg"] = m["file"].map(cad["regime"]).values
    r = m["file"].map(res["a1_R"]).values.astype(float); rn = m["file"].map(res["a1_n"]).values.astype(float)
    d["Y1"] = np.where(rn >= 600, r, np.nan)
    d["Y2"] = m["cell_spread_loaded_p95_mv"].astype(float).values
    d["Y3"] = m["V_pack_median"].astype(float).values
    d["day"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    return d.reset_index(drop=True), hashlib.md5(open(master_path or os.path.join(root, "drive_master.csv"), "rb").read()).hexdigest()


def windows(d, frozen_path=FROZEN_PATH, write=True):
    """Frozen primary windows (thirds of the span first..last clean-drive date); the first run writes the frozen file."""
    d0, d1 = pd.Timestamp(d["date"].min()).normalize(), pd.Timestamp(d["date"].max()).normalize()
    span = (d1 - d0).days
    derived = {"spanFirst": str(d0.date()), "spanLast": str(d1.date()), "earlyEnd": str((d0 + pd.Timedelta(days=span // 3)).date()), "lateStart": str((d1 - pd.Timedelta(days=span // 3)).date())}
    if os.path.exists(frozen_path):
        fz = json.load(open(frozen_path, encoding="utf-8"))
    else:
        fz = {"frozenAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "spec": "analyses/M677_spec.md Rev 1.1", **derived}
        if write:
            json.dump(fz, open(frozen_path, "w", encoding="utf-8"), indent=1)
    return fz, derived


# -------------------------------------------------- cells (covariates only)
def make_edges(T, I, S, level):
    """Quantile edges computed from the covariates ONLY (V5: no outcome column reaches this function). Right-closed, lowest bin closed, duplicates merged."""
    def q(x, n):
        e = np.unique(np.quantile(x, np.linspace(0, 1, n + 1)))
        return e if len(e) >= 2 else np.array([x.min(), x.min() + 1.0])
    return {"T": q(T, level["nT"]), "I": q(I, level["nI"]), "S": q(S, level["nS"])}


def assign(df, edges, level, with_dist=False):
    cols = []
    for v in ("T", "I", "S"):
        e = edges[v]
        c = pd.cut(df[v], bins=e, labels=False, include_lowest=True)
        c = np.where(df[v].values < e[0], 0, np.where(df[v].values > e[-1], len(e) - 2, c)).astype(int)
        cols.append(c)
    cols.append((df["reg"].astype(str).values == "fast").astype(int))          # fixed coding (fast = 1, slow = 0) so the early and late frames use the same cell keys
    if with_dist:
        cols.append(pd.cut(df["dist"], DIST_EDGES, labels=False).fillna(0).astype(int).values)
    key = np.zeros(len(df), dtype=np.int64)
    for c in cols:
        key = key * 100 + c
    return key


def used_cells(key_e, day_e, key_l, day_l):
    ce = pd.DataFrame({"k": key_e, "d": day_e}).groupby("k").agg(n=("d", "size"), nd=("d", "nunique"))
    cl = pd.DataFrame({"k": key_l, "d": day_l}).groupby("k").agg(n=("d", "size"), nd=("d", "nunique"))
    j = ce.join(cl, lsuffix="_e", rsuffix="_l", how="inner")
    ok = j[(j["n_e"] >= MIN_CELL) & (j["n_l"] >= MIN_CELL) & (j["nd_e"] >= MIN_CELL_DAYS) & (j["nd_l"] >= MIN_CELL_DAYS)]
    return list(ok.index)


def choose_level(early, late, with_dist=False):
    """Covariate-only ladder (no outcome read): first level that matches at least 50 % of the late drives."""
    pool = pd.concat([early, late])
    best = None
    for lv in LEVELS:
        ed = make_edges(pool["T"].values, pool["I"].values, pool["S"].values, lv)
        ke, kl = assign(early, ed, lv, with_dist), assign(late, ed, lv, with_dist)
        cells = used_cells(ke, early["day"].values, kl, late["day"].values)
        share = float(np.isin(kl, cells).mean()) if len(late) else 0.0
        best = (lv, ed, ke, kl, cells, share)
        if share >= 0.5:
            return best, True
    return best, False


# ---------------------------------------------------------------- path A
def _day_tables(y, key, day, cells):
    """Per-day sums and counts for each used cell: arrays [n_days, n_cells]."""
    ud, inv = np.unique(day, return_inverse=True)
    ci = {c: i for i, c in enumerate(cells)}
    S = np.zeros((len(ud), len(cells))); N = np.zeros((len(ud), len(cells)))
    for r, (k, v) in enumerate(zip(key, y)):
        if k in ci:
            S[inv[r], ci[k]] += v; N[inv[r], ci[k]] += 1
    return S, N


def path_a(early, late, ycol, with_dist=False, nboot=NBOOT, seed=SEED):
    ey = early.dropna(subset=[ycol]).reset_index(drop=True); ly = late.dropna(subset=[ycol]).reset_index(drop=True)
    if len(ey) < 10 or len(ly) < 10:
        return {"status": "not shown", "reason": "fewer than 10 drives in a window", "nEarly": int(len(ey)), "nLate": int(len(ly))}
    (lv, ed, ke, kl, cells, share), reached = choose_level(ey, ly, with_dist)
    out = {"level": lv["name"], "levelReachedFiftyPercent": bool(reached), "nEarlyDrives": int(len(ey)), "nLateDrives": int(len(ly)),
           "nEarlyDays": int(ey["day"].nunique()), "nLateDays": int(ly["day"].nunique()), "nCellsUsed": int(len(cells)), "matchedLateShare": share,
           "edges": {k: [float(x) for x in v] for k, v in ed.items()}}
    mask_l = np.isin(kl, cells); mask_e = np.isin(ke, cells)
    out["matchedLateDrives"] = int(mask_l.sum()); out["matchedLateDays"] = int(ly.loc[mask_l, "day"].nunique())
    out["matchedEarlyDrives"] = int(mask_e.sum()); out["matchedEarlyDays"] = int(ey.loc[mask_e, "day"].nunique())
    if not cells or out["matchedLateDrives"] < SHOW_DRIVES or out["matchedLateDays"] < SHOW_DAYS:
        out.update(status="not shown", reason="fewer than %d matched late drives or %d matched late days" % (SHOW_DRIVES, SHOW_DAYS)); return out
    Se, Ne = _day_tables(ey[ycol].values, ke, ey["day"].values, cells)
    Sl, Nl = _day_tables(ly[ycol].values, kl, ly["day"].values, cells)
    w = Nl.sum(0); w = w / w.sum()
    me, ml = Se.sum(0) / Ne.sum(0), Sl.sum(0) / Nl.sum(0)
    est = float(((ml - me) * w).sum()); ebar = float((me * w).sum())
    rng = np.random.default_rng(seed)
    nde, ndl = len(Se), len(Sl)
    B, dropped = [], 0
    ie = rng.integers(0, nde, size=(nboot, nde)); il = rng.integers(0, ndl, size=(nboot, ndl))
    for b in range(nboot):
        ne = Ne[ie[b]].sum(0); nl = Nl[il[b]].sum(0)
        if (ne == 0).any() or (nl == 0).any():
            dropped += 1; continue
        B.append((((Sl[il[b]].sum(0) / nl) - (Se[ie[b]].sum(0) / ne)) * w).sum())
    B = np.array(B)
    se = float(B.std(ddof=1)) if len(B) > 1 else float("nan")
    out.update(status="computed" if share >= 0.5 else "weakly overlapping", estimate=est, pctOfEarlyMatchedMean=float(100 * est / ebar) if ebar else None,
               ci95=[float(np.percentile(B, 2.5)), float(np.percentile(B, 97.5))],
               ci98_33=[float(np.percentile(B, 100 * ALPHA_BONF / 2)), float(np.percentile(B, 100 * (1 - ALPHA_BONF / 2)))],
               bootstrapSe=se, twoPointEightSe=float(2.8 * se), nDraws=int(len(B)), droppedDraws=int(dropped), droppedShare=float(dropped / nboot), unstable=bool(dropped / nboot > 0.05),
               unadjustedLateMinusEarly=float(ly[ycol].mean() - ey[ycol].mean()))
    out["_cellsMask"] = (mask_e, mask_l)           # internal (removed before output)
    return out


# ---------------------------------------------------------------- path B
def path_b(early, late, ycol, matched_masks=None, arrhenius=False):
    """OLS y ~ late + T term + I + S + regime; day-cluster CR1 SE; t(G-1) intervals (95 % and 98.33 %). matched_masks=(mask_early, mask_late) restricts to the matched-support drives."""
    e = early.dropna(subset=[ycol]).reset_index(drop=True); l = late.dropna(subset=[ycol]).reset_index(drop=True)
    if matched_masks is not None:
        e, l = e[matched_masks[0]], l[matched_masks[1]]
    df = pd.concat([e.assign(late=0.0), l.assign(late=1.0)], ignore_index=True)
    if len(df) < 20 or df["late"].nunique() < 2:
        return {"status": "not estimable"}
    tv = 1000.0 / (df["T"].values + 273.15) if arrhenius else df["T"].values
    X = np.column_stack([np.ones(len(df)), df["late"].values, tv, df["I"].values, df["S"].values, (df["reg"].astype(str) == "fast").astype(float).values])
    y = df[ycol].values
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtXi = np.linalg.pinv(X.T @ X)
    ud, inv = np.unique(df["day"].values, return_inverse=True)
    G = len(ud); n, k = X.shape
    meat = np.zeros((k, k))
    for g in range(G):
        xg = X[inv == g].T @ resid[inv == g]
        meat += np.outer(xg, xg)
    V = XtXi @ meat @ XtXi * (G / (G - 1)) * ((n - 1) / (n - k))
    se = float(np.sqrt(V[1, 1]))
    out = {"status": "computed", "estimate": float(beta[1]), "se": se, "nDrives": int(n), "nDays": int(G), "df": int(G - 1)}
    for nm, a in (("ci95", 0.05), ("ci98_33", ALPHA_BONF)):
        tq = stats.t.ppf(1 - a / 2, G - 1)
        out[nm] = [float(beta[1] - tq * se), float(beta[1] + tq * se)]
    return out


def excl0(ci):
    return bool(ci[0] > 0 or ci[1] < 0)


# --------------------------------------------------------------- per outcome
def split(d, early_end, late_start):
    e = d[d["date"] <= pd.Timestamp(early_end) + pd.Timedelta(hours=23, minutes=59)]
    l = d[d["date"] >= pd.Timestamp(late_start)]
    return e, l


def clean_cov(d):
    return d.dropna(subset=["T", "I", "S", "reg"]).reset_index(drop=True)


def outcome_block(oid, d, fz, derived, nboot):
    ycol = oid
    dd = clean_cov(d.dropna(subset=[ycol]))
    e, l = split(dd, fz["earlyEnd"], fz["lateStart"])
    rec = {"label": OUTCOMES[oid][0], "source": OUTCOMES[oid][1], "windows": {"earlyEnd": fz["earlyEnd"], "lateStart": fz["lateStart"]}}
    pa = path_a(e, l, ycol, nboot=nboot)
    masks = pa.pop("_cellsMask", None)
    rec["pathA"] = pa
    arr = (oid == "Y1")
    pb_p = path_b(e, l, ycol, masks, arrhenius=arr) if masks else {"status": "not estimable"}
    pb_s = path_b(e, l, ycol, None, arrhenius=arr)
    rec["pathB"] = {"primaryMatchedSupport": pb_p, "secondaryAllDrives": pb_s, "temperatureTerm": "1000/(T+273.15)" if arr else "linear"}
    shown = pa.get("status") in ("computed", "weakly overlapping")
    sameSign = shown and pb_p.get("status") == "computed" and np.sign(pa["estimate"]) == np.sign(pb_p["estimate"])
    rec["agreement"] = {"sameSign": bool(sameSign) if shown else None,
                        "pathAExcludesZero95": excl0(pa["ci95"]) if shown else None, "pathBExcludesZero95": excl0(pb_p["ci95"]) if pb_p.get("status") == "computed" else None}
    rec["persists"] = bool(pa.get("status") == "computed" and not pa.get("unstable") and pb_p.get("status") == "computed" and sameSign and excl0(pa["ci98_33"]) and excl0(pb_p["ci98_33"]))
    rec["persistsRev11"] = bool(shown and pb_p.get("status") == "computed" and sameSign and excl0(pa["ci98_33"]) and excl0(pb_p["ci98_33"]))
    if shown:
        pa["intervalStatus"] = "unstable, not for display (drop-conditioned bootstrap)" if pa.get("unstable") else "stable under the 5 % drop rule"
        pa["widthAboveEstimate"] = bool(pa["twoPointEightSe"] > abs(pa["estimate"]))
    rec["persistsRule"] = ("same sign and both Path A and Path B (matched-support) 98.33 % intervals exclude zero (Bonferroni over three outcomes); sensitivities never upgrade a result. "
                           "Rev 1.2 (stricter than Rev 1.1, added after the first run was seen): also requires a matched late share of at least 50 % (status computed, not weakly overlapping) and a stable interval (at most 5 % of draws dropped). persistsRev11 is the Rev 1.1 rule alone, shown beside")
    rec["sensitivities"] = sens(oid, dd, fz, derived, pa, nboot)
    return rec


def _brief(pa):
    if pa.get("status") in ("computed", "weakly overlapping"):
        return {"status": pa["status"], "estimate": pa["estimate"], "ci95": pa["ci95"], "level": pa["level"], "matchedLateShare": pa["matchedLateShare"], "matchedLateDrives": pa["matchedLateDrives"], "matchedLateDays": pa["matchedLateDays"],
                "nDraws": pa["nDraws"], "droppedShare": pa["droppedShare"], "unstable": pa["unstable"]}
    return {"status": pa.get("status"), "reason": pa.get("reason")}


def sens(oid, dd, fz, derived, primary, nboot):
    ycol = oid
    out = {}
    nb = min(nboot, 2000)

    def run(e, l, **kw):
        p = path_a(e, l, ycol, nboot=nb, **kw); p.pop("_cellsMask", None); return _brief(p)
    lo, hi = pd.Timestamp(derived["spanFirst"]), pd.Timestamp(derived["spanLast"])
    half = lo + (hi - lo) / 2
    eh = dd[dd["date"] <= half]; lh = dd[dd["date"] > half]
    out["a_halves"] = run(eh, lh)
    # b cadence strata
    e, l = split(dd, fz["earlyEnd"], fz["lateStart"])
    for r in ("fast", "slow"):
        out["b_cadence_" + r] = run(e[e["reg"] == r], l[l["reg"] == r])
    out["c_wider_late_narrower_early"] = run(dd[dd["date"] < pd.Timestamp("2026-07-01")], dd[dd["date"] >= pd.Timestamp("2026-09-01")])
    u = pd.Timestamp(UPDATE_DATE)
    keep = (dd["date"] < u - pd.Timedelta(days=7)) | (dd["date"] > u + pd.Timedelta(days=7))
    dk = dd[keep]
    out["d_halves_excluding_update_pm7d"] = run(dk[dk["date"] <= half], dk[dk["date"] > half])
    # e leave-one-week-out of the primary
    wk = e["date"].dt.isocalendar().week.astype(int); wl = l["date"].dt.isocalendar().week.astype(int)
    ests = []
    for w in sorted(set(wk) | set(wl)):
        p = path_a(e[wk != w], l[wl != w], ycol, nboot=200)
        if p.get("estimate") is not None:
            ests.append(p["estimate"])
    out["e_leave_one_week_out"] = {"n": len(ests), "min": float(min(ests)) if ests else None, "max": float(max(ests)) if ests else None}
    out["f_with_distance_class"] = run(e, l, with_dist=True)
    # re-derived thirds (differs from the frozen windows only after later ingestions)
    e2, l2 = split(dd, derived["earlyEnd"], derived["lateStart"])
    out["reDerivedThirds"] = {"windows": {"earlyEnd": derived["earlyEnd"], "lateStart": derived["lateStart"]}, **run(e2, l2)}
    return out


# ---------------------------------------------------------------- block
def build(root=ROOT, master_path=None, nboot=NBOOT, frozen_path=None, write_frozen=True):
    d, md5 = load(root, master_path)
    fz, derived = windows(d, frozen_path or FROZEN_PATH, write=write_frozen)
    u = pd.Timestamp(UPDATE_DATE)
    inMiddle = bool(pd.Timestamp(fz["earlyEnd"]) < u < pd.Timestamp(fz["lateStart"]))
    block = {"spec": "analyses/M677_spec.md Rev 1.1, 1.2", "exploratory": True, "articleUse": False, "descriptiveNotALook": "descriptive, not a look, no equivalence verdict, no alpha spent; never feeds the month-9 or month-12 looks",
             "estimand": "late-drive-weighted matched difference on the matched late subset (late minus early), in the outcome units",
             "seed": SEED, "nBoot": nboot, "corpusHash": md5, "frozenWindows": fz, "updateDateInExcludedMiddle": inMiddle, "outcomes": {}}
    if not inMiddle:
        block["flag"] = "2026-08-25 is not in the excluded middle third: results are not shown"
    else:
        for oid in OUTCOMES:
            block["outcomes"][oid] = outcome_block(oid, d, fz, derived, nboot)
    block["deviations"] = ["Y3 is the median pack voltage V_pack_median, not cap_ah_est: cap_ah_est (2.1 kWh divided by the median pack voltage) was already known to be a voltage proxy (M413), so this is a spec omission, not a new finding; the SOC-swing eligibility of Director change 8 has no object.",
                           "persists additionally requires status computed and a stable interval (Rev 1.2, added after the first run); persistsRev11 shown beside."]
    block["reading"] = [
        "A difference between early and late drives in matched state bins; time, season, route mix, load, logger configuration and the HV-battery software update (owner-reported around 2026-08-25, in the excluded middle third) move together on one vehicle. Not an ageing estimate; a same-season comparison is not available in a 12-month study.",
        "The estimand covers only the matched late subset (overlap is partial; the matched late share is reported). Drive-mean pack temperature does not describe the thermal state.",
        "Y3 is the median pack voltage: cap_ah_est in the master is 2.1 kWh divided by the median pack voltage (a voltage proxy scaled by an assumed energy, not a capacity or an Ah-per-SOC measurement); SOC level is a matching variable.",
        "Cadence is part of the cell key and all early drives of the window are slow-polled, so fast-polled late drives cannot match: the matched late share has a structural ceiling (the share of slow-polled late drives) and 'weakly overlapping' is structural, not a tuning outcome. When no ladder level reaches 50 % the coarsest level is used and the status stays 'weakly overlapping'. Path B on the matched support uses the early and late drives in the used cells.",
        "Coarse cells (the ladder falls back to 3 temperature classes of roughly 10 deg C width) leave within-cell covariate differences; Path B adjusts linearly beside it and the two are compared, never tuned to agree. Many bootstrap draws can be dropped when a used cell loses a side (droppedShare); an interval with more than 5 % dropped is flagged unstable.",
        "'persists' (Rev 1.2) needs the same sign, both paths' 98.33 % intervals excluding zero, a matched late share of at least 50 % and at most 5 % of bootstrap draws dropped; persistsRev11 applies the first two conditions only and is shown beside, the stricter rule having been added after the first run was seen. persists = false is not 'no difference'. Every other statement is descriptive and unadjusted.",
        "Path A intervals with more than 5 % of draws dropped are selected on cell survival and are not valid confidence intervals: unstable, not for display. Path B (CR1) may be shown beside. A cell-by-side stratified day resampling must be pre-registered and audited before any display.",
        "Where 2.8 times the bootstrap standard error (twoPointEightSe, a bootstrap-width quantity, not a power calculation) exceeds the estimate (widthAboveEstimate), the contrast cannot be distinguished from zero at this support.",
    ]
    block["validity"] = validate(block, d)
    return block


def validate(block, d):
    for oid, rec in block["outcomes"].items():
        pa = rec["pathA"]
        if pa.get("status") in ("computed", "weakly overlapping"):
            assert pa["matchedLateDrives"] <= pa["nLateDrives"] and pa["matchedEarlyDrives"] <= pa["nEarlyDrives"], (oid, "V3")
            assert pa["nCellsUsed"] >= 1, (oid, "V3 cells")
    e_end, l_start = pd.Timestamp(block["frozenWindows"]["earlyEnd"]), pd.Timestamp(block["frozenWindows"]["lateStart"])
    assert e_end < l_start, "V2 early and late windows overlap"
    return {"V2_V3_V4_V5": True}


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get(KEY)
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M678: derived by tools/early_late_contrast.py from drive_master.csv and two sidecars (spec analyses/M677_spec.md Rev 1.1, 1.2); exploratory")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"][KEY] = _sc.carry_declared(old, st)


def main(argv):
    sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
    nboot = int(argv[argv.index("--nboot") + 1]) if "--nboot" in argv else NBOOT
    block = build(nboot=nboot)
    md5 = block["corpusHash"]
    if "--out" in argv:
        json.dump(block, open(argv[argv.index("--out") + 1], "w", encoding="utf-8"), indent=1, default=str)
        print("wrote block"); return
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    old = copy.deepcopy(A)
    A[KEY] = json.loads(json.dumps(block, default=str))
    stamp(A, md5)
    chk = copy.deepcopy(A); chk.pop(KEY); chk["_artifactStamps"].pop(KEY)
    o2 = copy.deepcopy(old); o2.pop(KEY, None); o2["_artifactStamps"].pop(KEY, None)
    assert chk == o2, "unexpected change outside /" + KEY
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    main(sys.argv[1:])
