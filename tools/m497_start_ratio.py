#!/usr/bin/env python3
"""M497 (spec analyses/M497_spec.md Rev 2): SoC-standardised (Mantel-Haenszel) per-second engine-start hazard ratio, high speed versus stationary, with
calendar-day and ISO-week clustered percentile bootstraps (seed 42, 4000 draws) and a day-cluster-robust Poisson regression. Replaces the max-over-bins
headline (audit PB-01, ST-08). Data definition = the released `_soc_hysteresis_transitions` (unchanged). Hard stop: pooled cell k/n equal the published
socHysteresis.startProbBySocSpeed. Usage: python tools/m497_start_ratio.py [--out analyses/M497_result.json] [--limit N]
Read-only: never writes drive_master.csv or the payload."""
import datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

SEED, B, MIN_N = 42, 4000, 30
BINS = np.arange(35, 91, 5, dtype=float)             # soc // 5 * 5 clipped to [35, 90]
NB = len(BINS)
# last axis of every count array: (k, n). band axis: 0 stationary (<5 km/h), 1 high (>=60), 2 stationary (<2 km/h), 3 stationary (<5) without the drive's first start, 4 high without it
ST, HI, ST2, STX, HIX = 0, 1, 2, 3, 4


def eligible(pooled, hi=HI, st=ST, n_min=MIN_N):
    """Bins with n >= n_min in both strata of the POOLED counts; computed once and then frozen (spec: Eligible bins)."""
    return (pooled[:, hi, 1] >= n_min) & (pooled[:, st, 1] >= n_min)


def mh(c, ok, hi=HI, st=ST):
    """Mantel-Haenszel common rate ratio high/stationary on the frozen bin mask `ok`. +inf when the denominator is 0 and the numerator > 0; nan when both are 0."""
    k_hi, n_hi, k_st, n_st = c[:, hi, 0], c[:, hi, 1], c[:, st, 0], c[:, st, 1]
    N = n_hi + n_st
    with np.errstate(divide="ignore", invalid="ignore"):
        num = np.where(ok & (N > 0), k_hi * n_st / N, 0.0).sum()
        den = np.where(ok & (N > 0), k_st * n_hi / N, 0.0).sum()
    if den > 0:
        return float(num / den)
    return float("inf") if num > 0 else float("nan")


def crude(c, hi=HI, st=ST):
    k_hi, n_hi, k_st, n_st = c[:, hi, 0].sum(), c[:, hi, 1].sum(), c[:, st, 0].sum(), c[:, st, 1].sum()
    return (k_hi / n_hi) / (k_st / n_st) if k_st > 0 and n_hi > 0 else float("nan")


def boot(cl, ok, hi=HI, st=ST, B=B, seed=SEED):
    """Cluster bootstrap of R over the clusters of cl [cluster, bin, band, 2]; eligible bins frozen."""
    rng = np.random.default_rng(seed)
    G = cl.shape[0]
    return np.array([mh(cl[rng.integers(0, G, G)].sum(axis=0), ok, hi, st) for _ in range(B)])


def order_ci(d, lo_q=0.025, hi_q=0.975):
    """Percentile interval by order statistics over ALL non-undefined draws (+inf kept)."""
    d = np.sort(d)
    n = len(d)
    return d[int(np.floor(lo_q * (n - 1)))], d[int(np.ceil(hi_q * (n - 1)))]


def summarize(draws):
    und = np.isnan(draws)
    d = draws[~und]
    res = {"nDraws": int(len(draws)), "nUndefined": int(und.sum()), "nInfinite": int(np.isinf(d).sum())}
    if not len(d):
        return {**res, "intervalReported": False}
    lo, hi = order_ci(d)
    inf_share = float(np.isinf(d).mean())
    res.update({"infiniteShare": round(inf_share, 4), "lo": round(float(lo), 2), "median": round(float(np.median(d)), 2),
                "hi": None if (inf_share > 0.025 or np.isinf(hi)) else round(float(hi), 2), "upperUnbounded": bool(inf_share > 0.025 or np.isinf(hi)),
                "intervalReported": True, "method": "percentile by order statistics over all non-undefined draws (+inf kept)"})
    return res


def poisson_cluster(cd_days, ok, day_index):
    """Poisson regression on (day, bin, band) cells: log rate = bin fixed effects + beta*high, offset log n, CR1 covariance clustered by calendar day."""
    import statsmodels.api as sm
    rows = []
    for g in range(cd_days.shape[0]):
        for j in np.where(ok)[0]:
            for band, h in ((ST, 0), (HI, 1)):
                k, n = cd_days[g, j, band]
                if n > 0:
                    rows.append((g, j, h, k, n))
    a = np.array(rows)
    X = np.zeros((len(a), 1 + int(ok.sum())))
    X[:, 0] = a[:, 2]
    bins_ok = list(np.where(ok)[0])
    for r, j in enumerate(a[:, 1].astype(int)):
        X[r, 1 + bins_ok.index(j)] = 1.0
    m = sm.GLM(a[:, 3], X, family=sm.families.Poisson(), offset=np.log(a[:, 4])).fit(cov_type="cluster", cov_kwds={"groups": a[:, 0].astype(int), "use_correction": True})
    b, se = float(m.params[0]), float(m.bse[0])
    return {"ratio": round(float(np.exp(b)), 2), "lo": round(float(np.exp(b - 1.96 * se)), 2), "hi": round(float(np.exp(b + 1.96 * se)), 2), "logSE": round(se, 4),
            "nClusters": int(cd_days.shape[0]), "nCells": int(len(a)), "method": "Poisson, SoC-bin fixed effects, offset log n, CR1 by calendar day, Wald on log scale"}


def per_drive_counts(dm, limit=None):
    import drive_raw_cache as drc
    import compute_summary_arrays as C
    fl = drc.make_frame_loader()
    rows, n_cov = [], 0
    for i, r in dm.iterrows():
        if limit and i >= limit:
            break
        fr = fl(r["file"])
        if fr is None:
            continue
        res = C._soc_hysteresis_transitions(fr)
        if res is None:
            continue
        n_cov += 1
        ars = res[0]
        S = ars.dropna(subset=["speed"]) if "speed" in ars.columns else None
        c = np.zeros((NB, 5, 2))
        if S is not None and len(S):
            sb = ((S["soc"] // 5 * 5).clip(35, 90)).values
            sp, st = S["speed"].values, S["isStart"].values.astype(bool)
            first = np.zeros(len(S), bool)                         # the drive's first engine start (key-on warm-up), S7
            if st.any():
                first[int(np.argmax(st))] = True
            for band, m in ((ST, sp < 5), (HI, sp >= 60), (ST2, sp < 2), (STX, (sp < 5) & ~first), (HIX, (sp >= 60) & ~first)):
                for j, b in enumerate(BINS):
                    s = m & (sb == b)
                    c[j, band, 0], c[j, band, 1] = (s & st).sum(), s.sum()
        rows.append((r["file"], r["date"], c))
    return rows, n_cov


def main():
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M497_result.json"
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    rows, n_cov = per_drive_counts(dm, limit)
    dates = pd.to_datetime(pd.Series([r[1] for r in rows]))
    cnt = np.stack([r[2] for r in rows])                       # [drive, bin, band, 2]
    pooled = cnt.sum(axis=0)
    mism = []
    if limit is None:                                          # hard fidelity stop
        for cell in A["socHysteresis"]["startProbBySocSpeed"]:
            band = {"stationary": ST, "high": HI}.get(cell["speedBand"])
            if band is None:
                continue
            j = int(np.where(BINS == cell["socBin"])[0][0])
            if int(pooled[j, band, 0]) != cell["k"] or int(pooled[j, band, 1]) != cell["n"]:
                mism.append({"socBin": cell["socBin"], "band": cell["speedBand"], "published": [cell["k"], cell["n"]], "mine": [int(pooled[j, band, 0]), int(pooled[j, band, 1])]})
        if mism:
            print(json.dumps({"STOP": "fidelity", "mismatches": mism[:10]}))
            sys.exit(2)
    day = dates.dt.strftime("%Y-%m-%d").values
    wk = dates.dt.strftime("%G-W%V").values

    def cluster(keys):
        keys = np.array(keys)
        u = sorted(set(keys))
        return u, np.stack([cnt[keys == k].sum(axis=0) for k in u])
    days, cd = cluster(day)
    weeks, cw = cluster(wk)
    ok = eligible(pooled)                                      # frozen
    R = mh(pooled, ok)
    st_by_day, st_by_wk = cd[:, :, ST, 0][:, ok].sum(axis=1), cw[:, :, ST, 0][:, ok].sum(axis=1)
    k_st, k_hi = int(pooled[ok, ST, 0].sum()), int(pooled[ok, HI, 0].sum())
    top3 = float(np.sort(st_by_day)[::-1][:3].sum() / max(st_by_day.sum(), 1))
    week_ok = len(weeks) >= 20 and int((st_by_wk > 0).sum()) >= 8
    res = {"spec": "analyses/M497_spec.md",
           "provenance": {"masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
                          "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
                          "specSha256": hashlib.sha256(open("analyses/M497_spec.md", "rb").read()).hexdigest(),
                          "seed": SEED, "B": B, "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "limit": limit},
           "fidelity": {"checked": limit is None, "mismatches": mism},
           "nDrivesCovered": n_cov, "nDays": len(days), "nWeeks": len(weeks),
           "frozenBins": [float(b) for b in BINS[ok]]}
    prim = {"R": round(R, 2), "kStationary": k_st, "kHigh": k_hi, "nAtRiskStationary": int(pooled[ok, ST, 1].sum()), "nAtRiskHigh": int(pooled[ok, HI, 1].sum()),
            "daysWithStationaryStart": int((st_by_day > 0).sum()), "weeksWithStationaryStart": int((st_by_wk > 0).sum()), "top3DayShareOfStationaryStarts": round(top3, 3),
            "dayBootstrap": summarize(boot(cd, ok)), "weekBootstrap": {**summarize(boot(cw, ok)), "coPrimary": bool(week_ok)}, "poissonClusterByDay": poisson_cluster(cd, ok, days)}
    res["primary"] = prim
    # wording ladder (spec): L = min lower bound over the co-primary intervals; widest = larger log(UB/LB), unbounded widest
    cands = [("dayBootstrap", prim["dayBootstrap"]), ("poissonClusterByDay", prim["poissonClusterByDay"])] + ([("weekBootstrap", prim["weekBootstrap"])] if week_ok else [])
    cands = [(n, c) for n, c in cands if c.get("lo") is not None]
    L = min(c["lo"] for _, c in cands)
    def width(c):
        return float("inf") if (c.get("upperUnbounded") or c.get("hi") is None) else float(np.log(c["hi"] / max(c["lo"], 1e-12)))
    widest = max(cands, key=lambda x: width(x[1]))
    ladder = "roughly two orders of magnitude higher" if L >= 50 else ("at least an order of magnitude higher" if L >= 10 else "higher; the ratio is poorly determined")
    res["decision"] = {"L": L, "widestInterval": widest[0], "widest": {k: widest[1].get(k) for k in ("lo", "hi", "upperUnbounded")}, "wording": ladder,
                       "thinSupport": bool(k_st < 20 or prim["daysWithStationaryStart"] < 10)}
    # per-bin display: stratum ratio with its own day-clustered interval; bins with k_st = 0 are lower-bound-only
    perbin, excluded = [], 0
    for j, b in enumerate(BINS):
        if not ok[j]:
            continue
        c = pooled[j]
        draws = []
        rng = np.random.default_rng(SEED); G = cd.shape[0]
        for _ in range(B):
            s = cd[rng.integers(0, G, G), j].sum(axis=0)
            if s[ST, 0] > 0 and s[ST, 1] > 0 and s[HI, 1] > 0:
                draws.append((s[HI, 0] / s[HI, 1]) / (s[ST, 0] / s[ST, 1]))
            elif s[HI, 0] > 0:
                draws.append(float("inf"))
            else:
                draws.append(float("nan"))
        entry = {"socBin": float(b), "kStationary": int(c[ST, 0]), "kHigh": int(c[HI, 0]), **summarize(np.array(draws))}
        if c[ST, 0] > 0:
            entry["ratio"] = round(float((c[HI, 0] / c[HI, 1]) / (c[ST, 0] / c[ST, 1])), 1)
        else:
            entry["note"] = "lower bound only (no stationary start)"
            excluded += 1
        perbin.append(entry)
    res["perBin"] = perbin
    rs = [p["ratio"] for p in perbin if "ratio" in p]
    res["perBinRange"] = {"min": min(rs), "max": max(rs), "binsWithStationaryStart": len(rs), "eligibleBinsExcluded": excluded} if rs else None
    sens = {"S1_crudeRatio": round(crude(pooled), 2), "S2_driveBootstrap": summarize(boot(cnt, ok))}
    loo = [mh(cd.sum(axis=0) - cd[i], ok) for i in range(cd.shape[0])]
    fin = [x for x in loo if np.isfinite(x)]
    sens["S3_leaveOneDayOut"] = {"min": round(min(fin), 2), "max": round(max(fin), 2), "nInfinite": int(sum(np.isinf(loo)))}
    imax = int(np.argmax(st_by_day)); sens["S3_dayWithMostStationaryStarts"] = {"day": days[imax], "kStationary": int(st_by_day[imax]), "R_without": round(float(loo[imax]), 2)}
    sens["S4_leaveOneBinOut"] = {str(float(BINS[j])): round(mh(pooled, ok & (np.arange(NB) != j)), 2) for j in np.where(ok)[0]}
    ok2 = eligible(pooled, HI, ST2)
    sens["S5_stationaryBelow2kmh"] = {"frozenBins": [float(b) for b in BINS[ok2]], "R": round(mh(pooled, ok2, HI, ST2), 2), "kStationary": int(pooled[ok2, ST2, 0].sum()), "dayBootstrap": summarize(boot(cd, ok2, HI, ST2))}
    j60 = int(np.where(BINS == 60)[0][0]); c = pooled[j60]
    if c[ST, 0] > 0:
        r60 = (c[HI, 0] / c[HI, 1]) / (c[ST, 0] / c[ST, 1]); se = np.sqrt(1 / c[HI, 0] - 1 / c[HI, 1] + 1 / c[ST, 0] - 1 / c[ST, 1])
        sens["S6_iidKatzOldHeadlineCell"] = {"socBin": 60.0, "ratio": round(float(r60), 1), "lo": round(float(r60 * np.exp(-1.96 * se)), 1), "hi": round(float(r60 * np.exp(1.96 * se)), 1), "label": "iid per-second; anti-conservative; comparison only"}
    okx = eligible(pooled, HIX, STX)
    sens["S7_firstStartPerDriveRemoved"] = {"frozenBins": [float(b) for b in BINS[okx]], "R": round(mh(pooled, okx, HIX, STX), 2), "kStationary": int(pooled[okx, STX, 0].sum()), "dayBootstrap": summarize(boot(cd, okx, HIX, STX))}
    res["sensitivities"] = sens
    res["dayCells"] = {"days": days, "binsLower": [float(b) for b in BINS], "layout": "[day][bin][band: stationary<5, high>=60, stationary<2, stationary<5 ex-first-start, high ex-first-start][k, n]", "counts": cd.astype(int).tolist()}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: res[k] for k in ("nDrivesCovered", "nDays", "nWeeks", "frozenBins", "primary", "decision", "perBinRange")}, indent=1))


if __name__ == "__main__":
    main()
