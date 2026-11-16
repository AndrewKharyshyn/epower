#!/usr/bin/env python3
"""M676 (N-07, spec analyses/M675_spec.md Rev 1.1): exploratory change-point detection on per-drive series. Reads drive_master.csv and four existing sidecars (read-only), writes the additive payload block
summary_arrays.json['changePoints'] (+ stamp). Segment-neighbourhood (Auger-Lawrence) exact dynamic programme, mean-shift squared-error cost, K = 0..5, minimum segment 8 drives and 3 calendar days,
BIC(K) = n ln(RSS_K/n) + (2K+1) ln n (fixed, not tuned). Location intervals: day-clustered wild (Rademacher) residual bootstrap, seed 42, 4000 draws, conditional on K.
The detection code holds no reference dates; compare_reference() is a separate step run after the primary results are hashed (primarySha256).
Usage: python tools/changepoints.py [--out PATH] [--nboot N] [--coverage OUT.json [--reps N]]"""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
KEY = "changePoints"
KMAX = 5
MIN_DRIVES = 8
MIN_DAYS = 3
SEED = 42
_COV = None            # empirical coverage of the nominal 95 % location interval (read from analyses/M676_coverage.json in build)
NBOOT = 4000
FLOOR_DRIVES, FLOOR_DAYS = 100, 30
SERIES = {  # id -> (label, source)
    "X1": ("implied current offset (A, estimated)", "master:implied_offset_A_drive"),
    "X2": ("loaded p95 cell spread (mV)", "master:cell_spread_loaded_p95_mv"),
    "X3": ("cap_ah_est (2.1 kWh divided by the median pack voltage: a voltage proxy scaled by an assumed energy, not a capacity or an Ah-per-SOC measurement)", "master:cap_ah_est"),
    "X4": ("resistance proxy a1_R (model-derived), a1_n >= 600", "resistance_joint_sidecar.csv:a1_R"),
    "X5": ("logged current sample period (s)", "cadence_regime.csv:I_sample_period_s"),
}
LOG_SERIES = ("X2", "X4")
UPDATE_DATE = "2026-08-25"      # owner-reported; used ONLY in compare_reference()


# ---------------------------------------------------------------- exact DP
def _cost_matrix(y):
    """cost[i, j] = sum of squared deviations of y[i:j] around its mean (i < j), else +inf. Cumulative-sum form."""
    n = len(y)
    S = np.concatenate([[0.0], np.cumsum(y)])
    Q = np.concatenate([[0.0], np.cumsum(y * y)])
    i = np.arange(n + 1)[:, None]
    j = np.arange(n + 1)[None, :]
    ln = (j - i).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = (Q[j] - Q[i]) - (S[j] - S[i]) ** 2 / ln
    c = np.where(ln > 0, np.maximum(c, 0.0), np.inf)
    return c


def _feasible(dayidx, min_drives=MIN_DRIVES, min_days=MIN_DAYS):
    """feas[i, j]: segment y[i:j] has >= min_drives drives and >= min_days calendar days (days are contiguous in time order)."""
    n = len(dayidx)
    i = np.arange(n + 1)[:, None]
    j = np.arange(n + 1)[None, :]
    ok = (j - i) >= min_drives
    jj = np.clip(j - 1, 0, n - 1)
    ii = np.clip(i, 0, n - 1)
    days = dayidx[jj] - dayidx[ii] + 1
    return ok & (days >= min_days)


def partition(y, feas, kmax=KMAX):
    """Exact optimal partitions for K = 0..kmax change points. Returns (rss[k], locs[k]) with locs = start indices of segments 2..K+1; rss = inf and locs None when infeasible."""
    n = len(y)
    c = _cost_matrix(y)
    c = np.where(feas, c, np.inf)
    f = c[0, :].copy()                       # f[j] = best cost of y[0:j] in one segment
    best = [f.copy()]
    arg = []
    for k in range(1, kmax + 1):
        tot = best[-1][:, None] + c          # tot[i, j] = best_{k-1}[i] + cost(i, j)
        a = np.argmin(tot, axis=0)
        f2 = tot[a, np.arange(n + 1)]
        arg.append(a)
        best.append(f2)
    rss, locs = [], []
    for k in range(kmax + 1):
        v = best[k][n]
        if not np.isfinite(v):
            rss.append(np.inf); locs.append(None); continue
        pos, j = [], n
        for kk in range(k, 0, -1):
            i = int(arg[kk - 1][j]); pos.append(i); j = i
        rss.append(float(v)); locs.append(sorted(pos))
    return rss, locs


def bic_table(rss, n):
    out = []
    for k, r in enumerate(rss):
        if not np.isfinite(r) or r <= 0:
            out.append(None)
        else:
            out.append(float(n * np.log(r / n) + (2 * k + 1) * np.log(n)))
    return out


def choose_k(bics):
    ok = [(b, k) for k, b in enumerate(bics) if b is not None]
    return min(ok)[1] if ok else None


def fitted(y, locs):
    edges = [0] + list(locs) + [len(y)]
    f = np.empty(len(y))
    for a, b in zip(edges[:-1], edges[1:]):
        f[a:b] = y[a:b].mean()
    return f, edges


# ------------------------------------------------------------- bootstrap
def _day_groups(dayidx):
    u, inv = np.unique(dayidx, return_inverse=True)
    return len(u), inv


def wild_bootstrap(y, dayidx, feas, K, locs, nboot=NBOOT, seed=SEED):
    """Day-clustered Rademacher residual bootstrap at fixed K. Returns (locations[nboot, K], share of draws whose free BIC refit selects K)."""
    n = len(y)
    f, _ = fitted(y, locs)
    res = y - f
    nd, inv = _day_groups(dayidx)
    rng = np.random.default_rng(seed)
    out = np.zeros((nboot, K), dtype=int)
    same = 0
    for b in range(nboot):
        sg = rng.choice([-1.0, 1.0], size=nd)[inv]
        yb = f + res * sg
        rss_all, lc_all = partition(yb, feas, KMAX)
        kb = choose_k(bic_table(rss_all, n))
        same += int(kb == K)
        out[b] = lc_all[K] if lc_all[K] is not None else locs
    return out, same / nboot


def day_cluster_ci(values, dayidx, nboot=NBOOT, seed=SEED, stat=None):
    """Percentile CI of a mean (or stat(values_subset)) with calendar day as the resampling cluster."""
    nd, inv = _day_groups(dayidx)
    rng = np.random.default_rng(seed)
    sums = np.bincount(inv, weights=values, minlength=nd)
    cnt = np.bincount(inv, minlength=nd).astype(float)
    draws = rng.integers(0, nd, size=(nboot, nd))
    s = sums[draws].sum(1); c = cnt[draws].sum(1)
    est = s / c
    return float(values.mean()), [float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))]


def _segment_means(y, edges, dayidx, nboot, seed):
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        m, ci = day_cluster_ci(y[a:b], dayidx[a:b], nboot=nboot, seed=seed)
        out.append({"start": int(a), "end": int(b), "nDrives": int(b - a), "nDays": int(len(np.unique(dayidx[a:b]))), "mean": m, "ci95": ci})
    return out


# ----------------------------------------------------- covariate control
def _ols_step(y, edges, temp, tfun=None):
    """OLS y = segment means (+ beta * temp). Returns steps (adjacent mean differences) and beta."""
    n = len(y); k = len(edges) - 1
    X = np.zeros((n, k + (0 if temp is None else 1)))
    for s, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        X[a:b, s] = 1.0
    if temp is not None:
        X[:, k] = temp
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    steps = [float(coef[s + 1] - coef[s]) for s in range(k - 1)]
    return steps, (None if temp is None else float(coef[k]))


def control_A(y, dayidx, edges, temp, nboot, seed, tf=None):
    """Section 4 A: primary locations fixed; step with and without the temperature term, day-cluster pairs bootstrap."""
    ok = np.isfinite(temp)
    if ok.sum() < len(y) * 0.8:
        return {"status": "not estimable", "reason": "pack_min missing for more than 20 % of drives"}
    t = temp.copy(); t[~ok] = np.nanmean(temp)           # ordering is kept; missing temp imputed at the mean for the OLS only
    if tf is not None:
        t = tf(t)
    s0, _ = _ols_step(y, edges, None)
    s1, beta = _ols_step(y, edges, t)
    nd, inv = _day_groups(dayidx)
    rng = np.random.default_rng(seed)
    byday = [np.where(inv == d)[0] for d in range(nd)]
    B0, B1 = [], []
    for _ in range(nboot):
        pick = rng.integers(0, nd, size=nd)
        idx = np.concatenate([byday[d] for d in pick])
        # keep segment membership: positions keep their original segment through the edges
        seg = np.searchsorted(np.array(edges[1:-1]), idx, side="right")
        X0 = np.zeros((len(idx), len(edges) - 1)); X0[np.arange(len(idx)), seg] = 1.0
        X1 = np.column_stack([X0, t[idx]])
        yy = y[idx]
        if (X0.sum(0) == 0).any():
            continue
        c0, *_ = np.linalg.lstsq(X0, yy, rcond=None); c1, *_ = np.linalg.lstsq(X1, yy, rcond=None)
        B0.append([c0[s + 1] - c0[s] for s in range(len(edges) - 2)]); B1.append([c1[s + 1] - c1[s] for s in range(len(edges) - 2)])
    B0 = np.array(B0); B1 = np.array(B1)
    rows = []
    for s in range(len(edges) - 2):
        rows.append({"step": s + 1, "withoutBeta": {"est": s0[s], "ci95": [float(np.percentile(B0[:, s], 2.5)), float(np.percentile(B0[:, s], 97.5))]},
                     "withBeta": {"est": s1[s], "ci95": [float(np.percentile(B1[:, s], 2.5)), float(np.percentile(B1[:, s], 97.5))]}})
    return {"status": "computed", "beta": beta, "steps": rows, "nDraws": int(len(B0))}


def control_B(y, dayidx, loc, temp, nboot, seed):
    """Section 4 B: restrict to drives inside the central 95 % pack_min range of the drives before the first change point."""
    ok = np.isfinite(temp)
    pre = np.arange(len(y)) < loc
    if (pre & ok).sum() < 10:
        return {"status": "not estimable", "reason": "fewer than 10 pre-change drives with pack_min"}
    lo, hi = np.percentile(temp[pre & ok], [2.5, 97.5])
    keep = ok & (temp >= lo) & (temp <= hi)
    post = ~pre
    kpost = keep & post
    kpre = keep & pre
    ndays_post = len(np.unique(dayidx[kpost]))
    rec = {"rangeC": [float(lo), float(hi)], "postDrives": int(post.sum()), "postRetained": int(kpost.sum()), "postRetainedShare": float(kpost.sum() / max(post.sum(), 1)),
           "postRetainedDays": int(ndays_post)}
    if kpost.sum() < 30 or ndays_post < 5:
        rec["status"] = "not estimable"; rec["reason"] = "fewer than 30 post-change drives or 5 days after the restriction"
        return rec
    d = y[kpost].mean() - y[kpre].mean()
    nd, inv = _day_groups(dayidx)
    rng = np.random.default_rng(seed)
    sp = np.bincount(inv[kpost], weights=y[kpost], minlength=nd); cp = np.bincount(inv[kpost], minlength=nd).astype(float)
    sq = np.bincount(inv[kpre], weights=y[kpre], minlength=nd); cq = np.bincount(inv[kpre], minlength=nd).astype(float)
    dr = rng.integers(0, nd, size=(nboot, nd))
    with np.errstate(invalid="ignore", divide="ignore"):
        est = sp[dr].sum(1) / cp[dr].sum(1) - sq[dr].sum(1) / cq[dr].sum(1)
    est = est[np.isfinite(est)]
    rec.update(status="computed", step=float(d), ci95=[float(np.percentile(est, 2.5)), float(np.percentile(est, 97.5))], nPre=int(kpre.sum()))
    return rec


# ------------------------------------------------------------- per series
def analyse(sid, df, nboot=NBOOT, seed=SEED):
    """df: columns date (datetime64), file, y, temp, ordered in time. Returns the series record."""
    df = df[np.isfinite(df["y"].values)].reset_index(drop=True)
    n = len(df)
    dates = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d").values
    dayidx = pd.factorize(dates)[0]
    nd = int(dayidx.max() + 1) if n else 0
    base = {"label": SERIES[sid][0], "source": SERIES[sid][1], "nDrives": int(n), "nDays": nd}
    if n < FLOOR_DRIVES or nd < FLOOR_DAYS:
        base.update(status="not analysed", reason="fewer than %d drives or %d days" % (FLOOR_DRIVES, FLOOR_DAYS)); return base
    y = df["y"].values.astype(float)
    if sid == "X5":
        # deviation from spec section 9.2 (recorded in Rev 1.2): the per-drive sample period is a continuous mean, so "distinct-value transitions" would list nearly every drive;
        # the exact transitions of the categorical cadence regime (fast / slow, regime_reader rule via cadence_regime.csv) are listed instead, beside the distribution of the period.
        rg = df["regime"].astype(str).values
        ch = [i for i in range(1, n) if rg[i] != rg[i - 1]]
        v = np.round(y, 3)
        base.update(status="listed", method="exact transitions of the categorical cadence regime in time order (no BIC; the sample period itself is continuous)",
                    nDistinctPeriodValues=int(len(set(v.tolist()))), periodQuantiles={q: float(np.percentile(y, q)) for q in (5, 25, 50, 75, 95)},
                    regimeCounts={str(k): int(c) for k, c in pd.Series(rg).value_counts().items()}, nTransitions=len(ch),
                    transitions=[{"date": str(dates[i]), "driveIndex": int(i), "from": rg[i - 1], "to": rg[i]} for i in ch])
        return base
    feas = _feasible(dayidx)
    rss, locs = partition(y, feas)
    bics = bic_table(rss, n)
    K = choose_k(bics)
    var0 = float(np.var(y))
    trend = _trend(y, df["date"])
    base.update(status="computed", method="segment-neighbourhood exact DP, mean shift, BIC (2K+1) ln n", minSegmentDrives=MIN_DRIVES, minSegmentDays=MIN_DAYS,
                bic=[None if b is None else round(b, 3) for b in bics], rss=[None if not np.isfinite(r) else float(r) for r in rss],
                selectedK=int(K), rss0PopVarianceCheck=float(n * var0), trend=trend)
    edges = [0] + list(locs[K]) + [n]
    base["segments"] = _segment_means(y, edges, dayidx, nboot, seed)
    if K == 0:
        base["changePoints"] = []
        return base
    bl, same = wild_bootstrap(y, dayidx, feas, K, locs[K], nboot=nboot, seed=seed)
    base["sameKShare"] = float(same)
    dts = pd.to_datetime(dates)
    cps = []
    for j in range(K):
        loc = int(locs[K][j])
        d0 = dts[loc]
        bd = np.array([(dts[int(x)] - d0).days for x in bl[:, j]])
        lo, hi = np.percentile(bd, [2.5, 97.5])
        share7 = float((np.abs(bd) <= 7).mean())
        gain = (bics[0] - bics[K]) if bics[0] is not None else None
        weak = bool((gain is not None and gain < 10) or share7 < 0.5)
        cps.append({"driveIndex": loc, "date": str(dates[loc]), "nominal95IntervalDaysUncalibrated": [int(lo), int(hi)], "nominal95IntervalUncalibrated": [str((d0 + pd.Timedelta(days=int(lo))).date()), str((d0 + pd.Timedelta(days=int(hi))).date())],
                    "intervalCalibrated": False, "empiricalCoverage": _COV,
                    "within7dShare": share7, "poorlyLocalised": bool(hi - lo > 60), "weaklySupported": weak, "bicGainVsK0": None if gain is None else round(float(gain), 3),
                    "conditionalOnK": True})
    base["changePoints"] = cps
    return base


def _trend(y, dates):
    t = (pd.to_datetime(dates) - pd.to_datetime(dates).min()).dt.days.values.astype(float)
    n = len(y)
    X = np.column_stack([np.ones(n), t])
    c, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = float(((y - X @ c) ** 2).sum())
    return {"slopePerDay": float(c[1]), "rss": r, "bic": float(n * np.log(r / n) + 2 * np.log(n)) if r > 0 else None, "note": "linear-trend comparison; no verdict wording"}


def sensitivities(sid, df, rec, nboot, seed):
    out = {}
    if rec.get("status") != "computed":
        return out
    d = df[np.isfinite(df["y"].values)].reset_index(drop=True)
    dates = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d").values
    dayidx = pd.factorize(dates)[0]
    y = d["y"].values.astype(float)
    temp = d["temp"].values.astype(float)
    n = len(y)
    K = rec["selectedK"]
    feas = _feasible(dayidx)
    edges = [0] + [c["driveIndex"] for c in rec["changePoints"]] + [n]
    if sid in LOG_SERIES and (y > 0).all():
        r, l = partition(np.log(y), feas); b = bic_table(r, n); k2 = choose_k(b)
        out["logScale"] = {"selectedK": int(k2), "locations": [str(dates[i]) for i in l[k2]]}
    if sid in ("X2", "X4") and K >= 1:
        tf = (lambda t: 1000.0 / (t + 273.15)) if sid == "X4" else None
        out["A_fixedLocations"] = control_A(y, dayidx, edges, temp, min(nboot, 2000), seed)
        if sid == "X4":
            out["A_fixedLocations_lnR_arrhenius"] = control_A(np.log(y), dayidx, edges, temp, min(nboot, 2000), seed, tf=tf)
        out["B_restrictedRange"] = control_B(y, dayidx, edges[1], temp, min(nboot, 2000), seed)
        okt = np.isfinite(temp)
        if okt.sum() > 50:
            X = np.column_stack([np.ones(okt.sum()), temp[okt]])
            c, *_ = np.linalg.lstsq(X, y[okt], rcond=None)
            res = y.copy(); res[okt] = y[okt] - X @ c
            dd = dayidx
            r, l = partition(res, feas); b = bic_table(r, n); k3 = choose_k(b)
            out["C_residualSearch"] = {"selectedK": int(k3), "locations": [str(dates[i]) for i in l[k3]], "beta": float(c[1]), "status": "secondary"}
        # persists: same sign and CI excludes 0 in both A (with beta) and B, first step
        pst = None
        A = out.get("A_fixedLocations", {}); B = out.get("B_restrictedRange", {})
        if A.get("status") == "computed" and B.get("status") == "computed":
            sa = A["steps"][0]["withBeta"]; sb = B
            same = np.sign(sa["est"]) == np.sign(sb["step"]) == np.sign(A["steps"][0]["withoutBeta"]["est"])
            ex = (sa["ci95"][0] > 0 or sa["ci95"][1] < 0) and (sb["ci95"][0] > 0 or sb["ci95"][1] < 0)
            pst = "persists under the pack-temperature control" if (same and ex) else "not separable from the temperature range"
        out["verdict"] = pst or "not estimable"
    return out


# ---------------------------------------------------------------- data
def load(root=ROOT, master_path=None):
    mp = master_path or os.path.join(root, "drive_master.csv")
    m = pd.read_csv(mp, low_memory=False)
    m = m[m["ens_outlier_v2"] == False].copy()                           # noqa: E712
    m["_ts"] = m["time_start"].astype(str)
    m = m.sort_values(["date", "_ts", "file"], kind="mergesort").reset_index(drop=True)
    res = pd.read_csv(os.path.join(root, "resistance_joint_sidecar.csv")).set_index("file")
    cad = pd.read_csv(os.path.join(root, "cadence_regime.csv")).set_index("file")
    tmp = pd.read_csv(os.path.join(root, "battery_temp_extremes.csv")).set_index("file")
    temp = m["file"].map(tmp["pack_min"]).values.astype(float)
    ser = {}
    ser["X1"] = m["implied_offset_A_drive"].values.astype(float)
    ser["X2"] = m["cell_spread_loaded_p95_mv"].values.astype(float)
    ser["X3"] = m["cap_ah_est"].values.astype(float)
    r = m["file"].map(res["a1_R"]).values.astype(float); rn = m["file"].map(res["a1_n"]).values.astype(float)
    ser["X4"] = np.where(rn >= 600, r, np.nan)
    ser["X5"] = m["file"].map(cad["I_sample_period_s"]).values.astype(float)
    reg = m["file"].map(cad["regime"]).values
    frames = {sid: pd.DataFrame({"file": m["file"], "date": m["date"], "y": v, "temp": temp, "regime": reg}) for sid, v in ser.items()}
    return m, frames


def build(root=ROOT, master_path=None, nboot=NBOOT, seed=SEED):
    global _COV
    cp0 = os.path.join(root, "analyses", "M676_coverage.json")
    _COV = json.load(open(cp0, encoding="utf-8"))["coverage95"] if os.path.exists(cp0) else None
    m, frames = load(root, master_path)
    md5 = hashlib.md5(open(master_path or os.path.join(root, "drive_master.csv"), "rb").read()).hexdigest()
    block = {"method": "segment-neighbourhood exact DP (Auger-Lawrence), mean shift, fixed BIC; day-clustered wild residual bootstrap for location intervals (conditional on K)",
             "spec": "analyses/M675_spec.md Rev 1.1", "exploratory": True, "articleUse": False, "seed": seed, "nBoot": nboot, "corpusHash": md5,
             "eligibility": "canonical-clean drives (ens_outlier_v2 == False), ordered by date, time_start, file", "nCleanDrives": int(len(m)), "series": {}}
    for sid in SERIES:
        rec = analyse(sid, frames[sid], nboot=nboot, seed=seed)
        rec["sensitivities"] = sensitivities(sid, frames[sid], rec, nboot, seed)
        block["series"][sid] = rec
    block["reading"] = [
        "A location is a statistical break in a per-drive summary, not a cause; season, route mix, load, logger configuration and the software update move together (one vehicle, one May-to-November window).",
        "Location intervals are conditional on the selected K and approximate; slow drift versus step is not identifiable here (linear-trend BIC is shown beside).",
        "X3 is cap_ah_est = 2.1 kWh / median pack voltage in the master (corrected labelling, M678): a voltage proxy and not a capacity, so its breaks are shifts in the median pack voltage (SOC-level driven); X1 and X4 are estimated / model-derived. X5 is a logger quantity.",
        "poorlyLocalised, within7dShare, the +-7 d leg of weaklySupported and the reference comparison all come from the same uncalibrated draws and are lower bounds on location uncertainty.",
        "The detection holds no reference dates; the reference comparison is a separate step run after the primary results were hashed.",
    ]
    cp = os.path.join(root, "analyses", "M676_coverage.json")
    if os.path.exists(cp):
        cv = json.load(open(cp, encoding="utf-8"))
        block["intervalCoverageStudy"] = {"file": "analyses/M676_coverage.json", "plantedStepSd": 1.5, "reps": cv["reps"], "nBoot": cv["nBoot"], "nObs": cv["n"], "kEqualsOneRate": cv["kEqualsOneRate"],
                                          "empiricalCoverageOf95Interval": cv["coverage95"], "flaggedBelow0.85": cv["flag"]}
        block["reading"].append(f"Planted-step study at the real drives-per-day structure: the nominal 95 % location interval covered the planted location in {100 * cv['coverage95']:.0f} % of replicates; read every interval as optimistic (too narrow), not as a 95 % interval.")
    block["validity"] = validate(block, m, frames)
    block["primarySha256"] = hashlib.sha256(json.dumps(block, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    block["referenceComparison"] = compare_reference(block, m)
    block["locationSetStudy"] = _location_set_study(root, frames)          # M694: after the primary hash, additive (spec analyses/M693_spec.md Rev 1.1)
    block["kSelectionStudy"] = _k_selection_study(root, frames)            # M700: after the primary hash, additive (spec analyses/M700_spec.md Rev 1)
    return block


def _location_set_study(root, frames):
    """Record of the offline M693/M694 coverage study of candidate location sets. No set is attached to any break unless the pre-registered gate admitted a construction."""
    cp = os.path.join(root, "analyses", "M693_coverage.json")
    if not os.path.exists(cp):
        return {"status": "not run", "spec": "analyses/M693_spec.md Rev 1.1"}
    cv = json.load(open(cp, encoding="utf-8"))
    df = frames["X2"]; df = df[np.isfinite(df["y"].values)].reset_index(drop=True)
    dayidx = pd.factorize(pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d").values)[0]
    cnt = np.bincount(dayidx)
    fp = cv["fingerprint"]
    stale = bool(fp["n"] != len(df) or fp["nDays"] != len(cnt) or fp["drivesPerDayHash"] != hashlib.sha256(cnt.astype(np.int64).tobytes()).hexdigest()[:16])
    rec = {"spec": cv["spec"] + " Rev 1.1", "file": "analyses/M693_coverage.json", "reps": cv["reps"], "descriptiveReps": cv["descriptiveReps"], "B": cv["B"], "fingerprint": fp, "studyStale": stale,
           "selectedConstruction": cv["selected"], "scriptSha256": cv["scriptSha256"], "constructions": {}, "coreScenarios": {}}
    for c, a in cv["admissibility"].items():
        rec["constructions"][c] = {"admissible": a["admissible"], "reasons": a["reasons"], "meanOverCoreOfMedianWidthDays": a["meanOverCoreOfMedianWidthDays"]}
    for nm in ("S1", "S2", "S3", "S4", "S5", "S5effect"):
        sc = cv["scenarios"][nm]
        rec["coreScenarios"][nm] = {"kTrue": sc["kTrue"], "kHatEqualsKTrueRate": sc["kHatEqualsKTrueRate"], "falseBreakRate": sc["falseBreakRate"],
                                    **{c: {"coverageUnconditional": sc["constructions"][c]["coverageUnconditional"], "coverageConditional": sc["constructions"][c]["coverageConditional"], "nCorrectK": sc["constructions"][c]["nCorrectK"],
                                           "medianWidthDrives": sc["constructions"][c]["medianWidthDrives"], "medianWidthDays": sc["constructions"][c]["medianWidthDays"],
                                           "adjacentOverlapShare": sc["constructions"][c]["adjacentOverlapShare"]} for c in ("C0", "C1", "C2")}}
    if cv["selected"] is None:
        near = min(cv["admissibility"], key=lambda c: (len(cv["admissibility"][c]["reasons"]), c))
        rec["status"] = "no construction admitted by the pre-registered gate; no location set is attached to any break"
        rec["closestConstruction"] = {"construction": near, "label": "not admissible, reference only", "reasons": cv["admissibility"][near]["reasons"]}
        rec["f1Status"] = "F1 stays open: no admissible construction (M693); a new pre-registered spec addressing the selection of the number of breaks is warranted (it is not a subset or a re-gate of M693)"
        rec["kSelectionNote"] = "BIC at the drive level does not account for day-level dependence: the planted number of breaks is recovered in 0.68 (AR(1), one step), 0.56 (AR(1), three steps) and 0.23 (day random effect, one step) of replicates; coverage in those scenarios is inflated by over-segmentation"
        rec["robustnessNote"] = "blind audit: an independent reproduction with other random draws obtained 56 replicates with the planted number of breaks in the day-effect scenario (46 in the pre-registered seed-42 run; the binomial standard deviation is about 6), so the pre-registered cut of 50 is seed-sensitive; the verdict as pre-registered (seed 42) stands and is not re-gated; the weakness of the selection of the number of breaks (planted number recovered in a minority of replicates, false-break rate 0.72 to 0.77) is independent of that threshold"
        rec["overlapBoundReading"] = "the adjacent-set overlap bound of the gate is applied to the three-step scenarios S3 and S4 only (a defensible reading of the spec); under the wider reading the likelihood-ratio set would also fail the day-effect scenario on overlap"
        rec["reading"] = ["the nominal 95 % wild-bootstrap location interval (C0) and the unconditional bootstrap (C1) did not reach the pre-registered coverage in the core scenarios; the likelihood-ratio set (C2) covered the planted breaks in 91 to 99 % of replicates in every core scenario but failed one pre-registered condition (fewer than 50 replicates with the planted number of breaks in the day-effect scenario, where BIC over-selects breaks)",
                          "the study is simulated coverage at the real X2 structure with planted steps, not fitted ones; a subset admission would need a new spec revision and is post hoc; the M676 labels (uncalibrated, not for display) stay unchanged"]
    else:
        rec["status"] = "a construction was admitted; the per-break sets are a separate step"
    return rec


def _k_selection_study(root, frames):
    """Record of the offline M700 study of rules for the number of breaks. Negative or positive, nothing is applied to the real series and the primary block is untouched."""
    cp = os.path.join(root, "analyses", "M700_study.json")
    if not os.path.exists(cp):
        return {"status": "not run", "spec": "analyses/M700_spec.md Rev 1"}
    cv = json.load(open(cp, encoding="utf-8"))
    df = frames["X2"]; df = df[np.isfinite(df["y"].values)].reset_index(drop=True)
    dayidx = pd.factorize(pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d").values)[0]
    cnt = np.bincount(dayidx)
    fp = cv["fingerprint"]
    stale = bool(fp["n"] != len(df) or fp["nDays"] != len(cnt) or fp["drivesPerDayHash"] != hashlib.sha256(cnt.astype(np.int64).tobytes()).hexdigest()[:16])
    rec = {"spec": cv["spec"], "file": "analyses/M700_study.json", "reps": cv["reps"], "descriptiveReps": cv["descriptiveReps"], "seed": cv["seed"], "fingerprint": fp, "studyStale": stale,
           "scriptSha256": cv["scriptSha256"], "K3": cv["K3"], "selectedRule": cv["selected"], "rules": {}, "coreScenarios": {}}
    for r, a in cv["admissibility"].items():
        rec["rules"][r] = {"admissible": a["admissible"], "failedCriteria": a["reasons"], "minCoreRecovery": a["minCoreRecovery"]}
    for nm in ("S1", "S2", "S3", "S4", "S5", "D5a", "D5b", "AI", "N0", "N5", "S5null"):
        sc = cv["scenarios"][nm]
        rec["coreScenarios"][nm] = {"kTrue": sc["kTrue"], "rules": {r: {k: v for k, v in sc["rules"][r].items() if k in ("recovery", "recoveryWilson95", "overSegmentation", "overSegWilson95", "falseBreakRate", "falseBreakWilson95", "shareAtKmax")} for r in sc["rules"]}}
    if cv["selected"] is None:
        near = max(cv["admissibility"], key=lambda r: (cv["admissibility"][r]["minCoreRecovery"] if r != "K0" else -1.0))
        rec["status"] = "no admissible rule for the number of breaks at this series structure (n = 633 drives, 126 days), in the stated scenarios, 200 replicates; number of breaks not established"
        rec["closestRule"] = {"rule": near, "label": "reference only, not selected; failed criteria within Monte Carlo error of the 0.10 over-segmentation threshold", "failedCriteria": cv["admissibility"][near]["reasons"]}
        rec["applicationToRealSeries"] = "none (no rule admitted); the primary block and every exploratory label stay unchanged; K0 (BIC) stays the reference and carries the M693 false-break rate 0.72 to 0.77 under the day-effect null"
        rec["f1Status"] = "F1 closed for this series length by the pre-registered gate: the open question is more data, not a different method; any rule adopted from these results is post hoc and needs a new spec revision"
        rec["rerunTrigger"] = "re-run under a new spec revision when the clean-drive series reaches at least 180 days (126 at the time of the study) with a larger pre-registered replicate count and a fixed K2 BIC form"
        rec["disclosures"] = ["blind audit (analyses/M700_audit.json) reproduced K0/K1/K2 in S1, S2, S4, D5a, N0, N5 and K1/K2/K3 in D5b, S5 and the semi-synthetic null within Wilson overlap; K4 is author-only",
                              "Monte Carlo error: at 200 replicates a rate near 0.10 has a standard deviation of about 0.02; K1's S4 over-segmentation is 0.135 in the study and 0.09 on the audit stream",
                              "K3 deviations: the statistic is an RSS ratio (spec text: RSS reduction); the 120 s per-replicate cap is wall-clock under parallel workers and capped replicates return K = 0",
                              "K2 day-level BIC form is under-specified in the spec (penalty n and likelihood weighting); Kmax = 5 binds for K0, so its over-segmentation is a lower bound; planted noise is not the real noise"]
    else:
        rec["status"] = "a rule was admitted; application to X2 is a separate step"
    return rec


def validate(block, m, frames):
    v = {}
    for sid, rec in block["series"].items():
        if rec.get("status") == "not analysed":
            continue
        n = int(np.isfinite(frames[sid]["y"].values).sum())
        assert rec["nDrives"] == n, (sid, "V2 n drives")
        if rec.get("status") == "computed":
            r = [x for x in rec["rss"] if x is not None]
            assert abs(rec["rss0PopVarianceCheck"] - rec["rss"][0]) <= 1e-6 * max(1.0, rec["rss"][0]), (sid, "V3 RSS0")
            assert rec["rss"][rec["selectedK"]] <= rec["rss"][0] + 1e-9, (sid, "V3 chosen RSS")
            idx = [c["driveIndex"] for c in rec["changePoints"]]
            assert idx == sorted(set(idx)), (sid, "V4 order")
            for s in rec["segments"]:
                assert s["nDrives"] >= MIN_DRIVES and s["nDays"] >= MIN_DAYS, (sid, "V4 segment")
    v["V2_V3_V4"] = True
    return v


# ------------------------------------------------- reference comparison
def compare_reference(block, m, root=ROOT):
    """Section 5, run after the primary results exist: signed day difference to the owner-reported update date and to the PID-class transitions; chance rate = share of the window covered."""
    pid = pd.read_csv(os.path.join(root, "pid_epoch.csv")).set_index("file")
    cls = m["file"].map(pid["pidSetClass"]).values
    dts = pd.to_datetime(m["date"]).values
    trans = [{"date": str(pd.Timestamp(dts[i]).date()), "from": str(cls[i - 1]), "to": str(cls[i])} for i in range(1, len(cls)) if cls[i] != cls[i - 1]]
    refs = [{"kind": "softwareUpdate", "date": UPDATE_DATE, "provenance": "owner-reported around 2026-08-25; intake-air channel empty from 2026-08-24 10:46"}] + \
           [{"kind": "pidClassTransition", "date": t["date"], "from": t["from"], "to": t["to"]} for t in trans]
    w0, w1 = pd.Timestamp(m["date"].min()), pd.Timestamp(m["date"].max())
    window = max((w1 - w0).days, 1)
    out = {"referenceDates": refs, "windowDays": int(window), "series": {}, "coincidesRule": "reference date inside the UNCALIBRATED nominal 95 % location interval AND |difference| <= 7 days", "chanceRateNote": "intervalCoverageOfWindow uses the same uncalibrated intervals (a lower bound on the chance rate)"}
    for sid, rec in block["series"].items():
        if rec.get("status") == "listed":
            out["series"][sid] = {"transitions": rec["transitions"]}
            continue
        cps = rec.get("changePoints") or []
        rows, cov = [], []
        for c in cps:
            d0 = pd.Timestamp(c["date"]); lo, hi = c["nominal95IntervalDaysUncalibrated"]
            cov.append((d0 + pd.Timedelta(days=lo), d0 + pd.Timedelta(days=hi)))
            for r in refs:
                diff = (d0 - pd.Timestamp(r["date"])).days
                inside = bool(d0 + pd.Timedelta(days=lo) <= pd.Timestamp(r["date"]) <= d0 + pd.Timedelta(days=hi))
                rows.append({"location": c["date"], "reference": r["kind"], "referenceDate": r["date"], "diffDays": int(diff), "insideUncalibratedInterval": inside, "coincidesAgainstUncalibratedInterval": bool(inside and abs(diff) <= 7)})
        covered = 0
        if cov:
            segs = sorted(cov); cur_a, cur_b = segs[0]
            for a, b in segs[1:]:
                if a <= cur_b: cur_b = max(cur_b, b)
                else: covered += (cur_b - cur_a).days; cur_a, cur_b = a, b
            covered += (cur_b - cur_a).days
        out["series"][sid] = {"comparisons": rows, "intervalCoverageOfWindow": float(min(covered, window) / window)}
    return out


# ------------------------------------------------------ coverage study
def coverage_study(reps=200, nboot=400, seed=SEED, root=ROOT):
    """Planted-step replicates at the real drives-per-day structure (X2 clean drives): coverage of the 95 % location interval and K-selection rate. Offline study, not part of the stage."""
    m, frames = load(root)
    df = frames["X2"]; df = df[np.isfinite(df["y"].values)].reset_index(drop=True)
    dates = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d").values
    dayidx = pd.factorize(dates)[0]; n = len(df)
    feas = _feasible(dayidx)
    rng = np.random.default_rng(seed)
    sd = float(np.std(df["y"].values))
    hit, kk, nrep = 0, 0, 0
    true_loc = n // 2
    for r in range(reps):
        step = 1.5 * sd
        y = rng.normal(0, sd, n) + np.where(np.arange(n) >= true_loc, step, 0.0)
        rss, lc = partition(y, feas); K = choose_k(bic_table(rss, n))
        kk += int(K == 1)
        if K != 1:
            continue
        bl, _ = wild_bootstrap(y, dayidx, feas, 1, lc[1], nboot=nboot, seed=seed + r)
        lo, hi = np.percentile(bl[:, 0], [2.5, 97.5])
        hit += int(lo <= true_loc <= hi); nrep += 1
    return {"reps": reps, "nBoot": nboot, "n": int(n), "kEqualsOneRate": kk / reps, "coverage95": (hit / nrep) if nrep else None, "nIntervals": nrep, "flag": bool(nrep and hit / nrep < 0.85)}


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get(KEY)
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M676: derived by tools/changepoints.py from drive_master.csv and four existing sidecars (spec analyses/M675_spec.md Rev 1.1); exploratory")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"][KEY] = _sc.carry_declared(old, st)


def main(argv):
    sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
    nboot = int(argv[argv.index("--nboot") + 1]) if "--nboot" in argv else NBOOT
    if "--coverage" in argv:
        reps = int(argv[argv.index("--reps") + 1]) if "--reps" in argv else 200
        res = coverage_study(reps=reps)
        json.dump(res, open(argv[argv.index("--coverage") + 1], "w", encoding="utf-8"), indent=1)
        print(json.dumps(res)); return
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
