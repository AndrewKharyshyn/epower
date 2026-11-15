"""M667 (N-02, spec analyses/M666_spec.md Rev 1.1, deviations in section 9): fitted seasonal quantities beside the M28 priors. Exploratory payload block `seasonalFits`, no display, no year output.

Q1 throughput cold slope, Q2 pack-ambient coupling, Q3 temperature-scale cool-down constant (owner decision D-05) with day-blocked held-out skill against persistence AND full relaxation,
Q4 Arrhenius-weighted temperature exposure index relative to constant 25 C (assumed Ea, verified:false). Every interval: day-clustered percentile bootstrap, calendar day cluster, seed 42, 4000 draws.
Inputs: drive_master.csv, seasonal_drive_master.csv, ah_throughput.csv and the end-of-drive pack temperatures from the raw files (per-drive cache keyed by the raw sha256 and the extractor version).
Run: python tools/n02_seasonal_fits.py [--raw-dir DIR] [--out FILE | --dry-run]"""
import copy, datetime, hashlib, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd

EXTRACTOR_VERSION = "n02-r1"
CACHE_DIR = os.path.join(ROOT, "seasonal_fits_cache")
SPEC = "analyses/M666_spec.md"
SEED, NB = 42, 4000
KB = 8.617333e-5
MIN_DRIVES, MIN_DAYS, ESS_FLOOR = 10, 5, 10.0
TOL_ENDPOINT_S = 60.0            # a probe's first / last valid reading must lie within 60 s of the drive's first / last timestamp
MIN_PROBES = 3
GAP_LO_H, GAP_HI_H = 0.02, 36.0
UNLOGGED_KM = 1.0                # a pair is flagged when the next drive's estimated unlogged distance exceeds the whole-km odometer resolution
DIURNAL_C = 4.0                  # assumption, as in the self-audit scenario code
COOL_CAP_H = 18.0
FOLDS = 10
BANDS = (("below 5 C", -99.0, 5.0), ("5 to 15 C", 5.0, 15.0), ("15 C or warmer", 15.0, 99.0))


# ------------------------------------------------------------------------------------------------ raw extractor
def extract_drive(csv_bytes, filename):
    """End-of-drive and start-of-drive pack temperature (mean over probes T1..T4 of each probe's first / last valid reading within 60 s of the drive's first / last timestamp)."""
    import compute_summary_arrays as C
    import compute_drive_summary_v6 as v6
    df_raw = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    df = df_raw.rename(columns={k: v for k, v in v6.COL_MAP.items() if k in df_raw.columns})
    t = C._ft(df["time"], mixed=True)
    tt = pd.Series(t).reset_index(drop=True)
    ok_t = tt.notna()
    if not ok_t.any():
        return {"file": filename, "tFirst": None, "tLast": None, "nFirst": 0, "nLast": 0}
    t0, t1 = tt[ok_t].min(), tt[ok_t].max()
    firsts, lasts = [], []
    for c in ("T1", "T2", "T3", "T4"):
        if c not in df.columns:
            continue
        x = pd.to_numeric(df[c], errors="coerce").reset_index(drop=True)
        m = x.notna() & (x >= -40) & (x <= 90) & ok_t
        if not m.any():
            continue
        tm = tt[m]
        i0, i1 = tm.idxmin(), tm.idxmax()
        if (tm[i0] - t0).total_seconds() <= TOL_ENDPOINT_S:
            firsts.append(float(x[i0]))
        if (t1 - tm[i1]).total_seconds() <= TOL_ENDPOINT_S:
            lasts.append(float(x[i1]))
    return {"file": filename, "tFirst": float(np.mean(firsts)) if len(firsts) >= MIN_PROBES else None,
            "tLast": float(np.mean(lasts)) if len(lasts) >= MIN_PROBES else None, "nFirst": len(firsts), "nLast": len(lasts)}


def _file_sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _cache_path(sha):
    return os.path.join(CACHE_DIR, "%s_%s.json" % (sha, EXTRACTOR_VERSION))


def corpus_endpoints(raw_dir, files, verbose=False):
    """Per-drive endpoint temperatures; the file is found in raw_only/ (staged master-key view) first, else in raw/ by the digits of the name (as tools/ah_throughput.py)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    out, nnew = {}, 0
    import glob, re
    idx = {re.sub(r"\D", "", os.path.basename(q)): q for q in glob.glob(os.path.join(raw_dir, "*.csv"))}      # raw/ files carry a space separator; the master key uses an underscore
    stage = os.path.join(ROOT, "raw_only")
    for f in files:
        p = os.path.join(stage, f)
        if not os.path.isfile(p):
            p = idx.get(re.sub(r"\D", "", f))
        if not p or not os.path.isfile(p):
            continue
        sha = _file_sha(p)
        cp = _cache_path(sha)
        if os.path.isfile(cp):
            r = json.load(open(cp, encoding="utf-8"))
        else:
            r = extract_drive(open(p, "rb").read(), f)
            json.dump(r, open(cp, "w", encoding="utf-8"), separators=(",", ":"))
            nnew += 1
        out[f] = r
    if verbose:
        print(json.dumps({"extractedNew": nnew, "files": len(out)}))
    return out


# ------------------------------------------------------------------------------------------------ data
def load_drives(endpoints):
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    sm = pd.read_csv(os.path.join(ROOT, "seasonal_drive_master.csv"), low_memory=False)
    ah = pd.read_csv(os.path.join(ROOT, "ah_throughput.csv"), low_memory=False)
    keep = ["file", "ambient_start_c", "ambient_end_c", "ambient_time_mean_c", "pack_temp_time_mean_c", "pack_temp_max_c", "pack_temp_start_c", "local_iso", "unlogged_distance_est_km"]
    d = dm.merge(sm[keep], on="file", how="left", suffixes=("", "_sm"))
    d = d.merge(ah[["file", "ah_throughput"]], on="file", how="left")
    for c in ("ambient_start_c", "ambient_end_c", "ambient_time_mean_c", "pack_temp_time_mean_c", "pack_temp_max_c", "pack_temp_start_c", "unlogged_distance_est_km"):
        if c + "_sm" in d.columns:
            d[c] = d[c + "_sm"]
    d["t0"] = pd.to_datetime(d["local_iso"].astype(str).str.slice(0, 19))
    d["t1"] = d["t0"] + pd.to_timedelta(d["duration_s"], unit="s")
    d = d.sort_values("t0").reset_index(drop=True)
    d["gap_h"] = (d["t0"] - d["t1"].shift(1)).dt.total_seconds() / 3600.0
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    clean = lambda c: ~d[c].map(lambda x: x is True or x == "True")
    d["clean"] = clean("ens_outlier_v2") & clean("ens_invalid")
    d["dclass"] = d["drive_type"]                                       # the four master drive types (urban, mixed, mixed_highway, highway; one unknown)
    d["dclassMerged"] = d["drive_type"].replace({"mixed_highway": "highway"})   # sensitivity coding
    d["tFirst"] = d["file"].map(lambda f: (endpoints.get(f) or {}).get("tFirst")).astype(float)
    d["tLast"] = d["file"].map(lambda f: (endpoints.get(f) or {}).get("tLast")).astype(float)
    return d


# ------------------------------------------------------------------------------------------------ helpers
def ess_days(day_weights):
    w = np.asarray(day_weights, float)
    s = w / w.sum()
    return float(1.0 / np.sum(s ** 2)) if w.sum() > 0 else 0.0


def support(days, weights):
    n_d = len(set(days))
    ess = ess_days(pd.Series(weights).groupby(pd.Series(days).values).sum().values) if len(weights) else 0.0
    return n_d, ess


def ladder(n, days, ess):
    if n < MIN_DRIVES or days < MIN_DAYS:
        return "not shown"
    return "supported" if ess >= ESS_FLOOR else "exploratory"


def day_index(days):
    codes, uniq = pd.factorize(pd.Series(days))
    return [np.where(codes == i)[0] for i in range(len(uniq))], list(uniq)


def boot_idx(groups, rng):
    pick = rng.integers(0, len(groups), len(groups))
    return np.concatenate([groups[i] for i in pick])


def pct(a):
    a = np.asarray([x for x in a if np.isfinite(x)], float)
    return None if len(a) == 0 else [round(float(np.percentile(a, 2.5)), 5), round(float(np.percentile(a, 97.5)), 5)], len(a)


def design(df, controls, target, cls_col="dclass"):
    cols = [np.ones(len(df))]
    for c in controls:
        if c == "class":
            for k in sorted(df[cls_col].unique())[1:]:
                cols.append((df[cls_col] == k).astype(float).values)
        else:
            cols.append(df[c].astype(float).values)
    cols.append(df[target].astype(float).values)
    return np.column_stack(cols)


def ols_slope(X, y):
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(b[-1])


def fit_with_ci(df, controls, target, yname, nb, cls_col="dclass"):
    """OLS coefficient of `target` with a day-clustered percentile bootstrap."""
    X, y = design(df, controls, target, cls_col), df[yname].astype(float).values
    est = ols_slope(X, y)
    groups, _ = day_index(df["date"].values)
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(nb):
        ix = boot_idx(groups, rng)
        try:
            vals.append(ols_slope(X[ix], y[ix]))
        except Exception:
            vals.append(np.nan)
    ci, ok = pct(vals)
    drop = 1.0 - ok / nb
    return {"estimate": round(est, 5), "ci95": ci, "droppedDrawShare": round(drop, 4), "notEstimable": bool(drop > 0.01 or ci is None)}


def support_block(df):
    n_d, ess = support(df["date"].values, df["distance_km"].values)
    return {"nDrives": int(len(df)), "nDays": int(n_d), "essDays": round(ess, 2),
            "largestDayShare": round(float(df.groupby("date")["distance_km"].sum().max() / df["distance_km"].sum()), 3) if len(df) else None,
            "status": ladder(len(df), n_d, ess)}


# ------------------------------------------------------------------------------------------------ Q1 and Q2
def q1_q2(d, nb):
    c = d[d.clean & (d.distance_km > 0.5) & d.ah_throughput.notna() & (d.ah_throughput > 0) & d.ambient_time_mean_c.notna() & d.pack_temp_time_mean_c.notna()].copy()
    c["cold"] = np.clip(15.0 - c.ambient_time_mean_c, 0, None)
    c["lahkm"] = np.log(c.ah_throughput / c.distance_km)
    c["ld"] = np.log(c.distance_km)
    c["ldur"] = np.log(c.duration_s / 60.0)
    c["rise"] = c.pack_temp_time_mean_c - c.ambient_time_mean_c
    out = {"essBasis": "Q1 and Q2 effective days use distance-weighted day shares (inverse of the sum of squared day shares of the logged km); Q3 effective days use pair-count day shares", "support": support_block(c), "lowestAmbientC": round(float(c.ambient_time_mean_c.min()), 2)}
    out["bandSupport"] = {nm: dict(support_block(c[(c.ambient_time_mean_c >= lo) & (c.ambient_time_mean_c < hi)]) if ((c.ambient_time_mean_c >= lo) & (c.ambient_time_mean_c < hi)).any() else {"nDrives": 0, "nDays": 0, "essDays": 0.0, "status": "not shown"}) for nm, lo, hi in BANDS}
    out["drivesBelow5C"] = int((c.ambient_time_mean_c < 5).sum())
    out["drivesBelow0C"] = int((c.ambient_time_mean_c < 0).sum())
    out["daysBelow5C"] = int(c[c.ambient_time_mean_c < 5].date.nunique())
    out["daysBelow0C"] = int(c[c.ambient_time_mean_c < 0].date.nunique())
    q1 = {"definition": "d ln(Ah per km) per C below 15 C drive-time ambient (driver-recorded), OLS, drive-class dummies and log distance; association by thermal class, not a temperature effect",
          "primary": fit_with_ci(c, ["class", "ld"], "cold", "lahkm", nb), "sensitivityClassOnly": fit_with_ci(c, ["class"], "cold", "lahkm", max(nb // 4, 400)),
          "sensitivityMergedClasses": fit_with_ci(c, ["class", "ld"], "cold", "lahkm", max(nb // 4, 400), "dclassMerged")}
    g = q1["primary"]["estimate"]
    q1["fractionalSlopePerC"] = {"estimate": round(float(np.expm1(g)), 5), "ci95": None if q1["primary"]["ci95"] is None else [round(float(np.expm1(x)), 5) for x in q1["primary"]["ci95"]],
                                 "conversion": "exp(g) - 1, to compare with the M28 prior consumptionSlopePerC (fractional consumption slope)"}
    spread = [q1["primary"]["estimate"], q1["sensitivityClassOnly"]["estimate"], q1["sensitivityMergedClasses"]["estimate"]]
    hw = (q1["primary"]["ci95"][1] - q1["primary"]["ci95"][0]) / 2.0 if q1["primary"]["ci95"] else None
    q1["spread"] = {"maxMinusMin": round(max(spread) - min(spread), 5), "definitionDependent": bool(hw is not None and (max(spread) - min(spread)) > hw)}
    q1["reading"] = "not resolved at this support" if (q1["primary"]["ci95"] is None or (q1["primary"]["ci95"][0] <= 0 <= q1["primary"]["ci95"][1])) else ("positive association by thermal class" if q1["primary"]["estimate"] > 0 else "negative association by thermal class")
    cb = c[c.ambient_time_mean_c < 5]
    sb = out["bandSupport"]["below 5 C"]
    q1["belowFiveC"] = fit_with_ci(cb, ["class"], "cold", "lahkm", nb) if sb["status"] in ("exploratory", "supported") and cb["dclass"].nunique() >= 1 and cb["cold"].nunique() > 3 else "not observed at this support"
    out["Q1"] = q1
    # Q2
    beta = fit_with_ci(c, ["class", "ldur"], "ambient_time_mean_c", "pack_temp_time_mean_c", nb)
    q2 = {"definition": "d(pack time-mean temperature) / d(driver-recorded ambient), OLS, drive-class dummies and log duration; association by thermal class",
          "primary": beta, "sensitivityRiseOnCold": fit_with_ci(c, ["class", "ldur"], "cold", "rise", max(nb // 4, 400)),
          "sensitivityMergedClasses": fit_with_ci(c, ["class", "ldur"], "ambient_time_mean_c", "pack_temp_time_mean_c", max(nb // 4, 400), "dclassMerged")}
    cs = c.dropna(subset=["pack_temp_start_c", "ambient_start_c"])
    q2["sensitivityStartOnStart"] = fit_with_ci(cs, [], "ambient_start_c", "pack_temp_start_c", max(nb // 4, 400))
    spread2 = [beta["estimate"], q2["sensitivityStartOnStart"]["estimate"], q2["sensitivityMergedClasses"]["estimate"]]
    hw2 = (beta["ci95"][1] - beta["ci95"][0]) / 2.0 if beta["ci95"] else None
    q2["spread"] = {"maxMinusMin": round(max(spread2) - min(spread2), 5), "definitionDependent": bool(hw2 is not None and (max(spread2) - min(spread2)) > hw2)}
    # errors-in-variables bracket: partial ambient variance after the controls; assumed reading-error SD (labelled assumption)
    X0 = design(c, ["class", "ldur"], "ambient_time_mean_c")[:, :-1]
    a = c.ambient_time_mean_c.values
    resid = a - X0 @ np.linalg.lstsq(X0, a, rcond=None)[0]
    var_a = float(np.var(resid))
    q2["errorsInVariablesBracket"] = {"assumption": "the dashboard ambient is hand-entered and quantised to whole degrees; the reading-error SD below is an assumed value, not an estimate", "partialAmbientVariance": round(var_a, 4),
                                      "corrected": {str(sd): round(float(beta["estimate"] * (var_a + sd ** 2) / var_a), 4) for sd in (1.0, 2.0)}}
    q2["flags"] = {"outsidePhysicalRange0to1p5": bool(beta["estimate"] < 0 or beta["estimate"] > 1.5)}
    q2["priorM28"] = "none: M28 has no pack-ambient coupling coefficient (it assumes a rise shrinkage and 1.0 for highway), so nothing is compared"
    out["Q2"] = q2
    out["_c"] = c
    return out


# ------------------------------------------------------------------------------------------------ Q3
def l1_tau(e0, e1, gap, loss="l1", amb_shift=0.0):
    """tau minimising sum |e0 exp(-gap/tau) - e1| (L1) or the squared version (L2): log grid then local refinement; no outcome filter."""
    def loss_at(taus):
        pred = e0[:, None] * np.exp(-gap[:, None] / taus[None, :])
        r = pred - e1[:, None]
        return np.abs(r).sum(0) if loss == "l1" else (r ** 2).sum(0)
    grid = np.exp(np.linspace(np.log(0.2), np.log(200.0), 200))
    L = loss_at(grid)
    i = int(np.argmin(L))
    lo, hi = grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)]
    fine = np.exp(np.linspace(np.log(lo), np.log(hi), 80))
    return float(fine[int(np.argmin(loss_at(fine)))])


def build_pairs(d):
    prev = d.shift(1)
    ok = d.clean & prev.clean.fillna(False).astype(bool) & (d.gap_h >= GAP_LO_H) & (d.gap_h <= GAP_HI_H)
    p = pd.DataFrame({"date": d["date"], "prevDate": prev["date"], "gap_h": d["gap_h"], "prevEnd": prev["tLast"], "nextStart": d["tFirst"], "prevMax": prev["pack_temp_max_c"], "nextStartMaster": d["pack_temp_start_c"],
                      "ambPrevEnd": prev["ambient_end_c"], "ambNextStart": d["ambient_start_c"], "unlogged": d["unlogged_distance_est_km"], "distPrev": prev["distance_km"]})[ok]
    p["amb"] = (p.ambPrevEnd + p.ambNextStart) / 2.0
    p["flagUnlogged"] = p["unlogged"].fillna(0) > UNLOGGED_KM
    p["crossDay"] = p["date"] != p["prevDate"]
    return p.reset_index(drop=True)


def fit_variant(p, endcol, startcol, loss="l1", shift=0.0, minexc=None, resid=None):
    q = p.dropna(subset=[endcol, startcol, "amb"]).copy()
    q["e0"] = q[endcol] - (q.amb + shift)
    q["e1"] = q[startcol] - (q.amb + shift)
    if minexc is not None:
        q = q[q.e0 > minexc]
    if resid is not None:
        q = q[q.e1 > resid]
    if len(q) < 20:
        return {"n": int(len(q)), "tauH": None}
    return {"n": int(len(q)), "tauH": round(l1_tau(q.e0.values, q.e1.values, q.gap_h.values, loss), 3)}


def project_tau(p):
    """Project-like definition (outcome filter e1 > 0.5 C): log-scale through-origin Sen slope; known to be selected on the outcome, shown for comparison only."""
    q = p.dropna(subset=["prevEnd", "nextStart", "amb"]).copy()
    q["e0"] = q.prevEnd - q.amb
    q["e1"] = q.nextStart - q.amb
    q = q[(q.e0 > 0) & (q.e1 > 0.5)]
    y = np.log(q.e1 / q.e0)
    sl = np.median(y / q.gap_h)
    return {"n": int(len(q)), "tauH": round(float(-1.0 / sl), 3) if sl < 0 else None}


def q3(d, nb):
    p = build_pairs(d)
    base = p.dropna(subset=["prevEnd", "nextStart", "amb"]).copy()
    base["e0"] = base.prevEnd - base.amb
    base["e1"] = base.nextStart - base.amb
    out = {"definition": "e1 = e0 exp(-gap/tau) on the temperature scale: e0 = previous drive's last pack temperature minus ambient_ref, e1 = next drive's first pack temperature minus ambient_ref, ambient_ref = mean of the previous end ambient and the next start ambient; L1 loss, no outcome-based filter; consecutive canonical-clean drives, gap 0.02 to 36 h",
           "nPairsEligible": int(len(p)), "nPairsFit": int(len(base)), "pairsDropped": {"missingEndpointOrAmbient": int(len(p) - len(base))}}
    n_d, ess = support(base["date"].values, np.ones(len(base)))
    out["support"] = {"nPairs": int(len(base)), "nDays": int(n_d), "essDays": round(ess, 2), "status": ladder(len(base), n_d, ess)}
    out["byGapStratum"] = {nm: int(((base.gap_h >= lo) & (base.gap_h < hi)).sum()) for nm, lo, hi in (("below 1 h", 0, 1), ("1 to 4 h", 1, 4), ("4 to 12 h", 4, 12), ("12 h or longer", 12, 1e9))}
    out["byAmbientBand"] = {nm: int(((base.amb >= lo) & (base.amb < hi)).sum()) for nm, lo, hi in BANDS}
    out["unloggedDrivingFlag"] = {"rule": "next drive's estimated unlogged distance above the whole-km odometer resolution (%.1f km); unlogged driving between a pair biases tau downward" % UNLOGGED_KM, "nFlagged": int(base.flagUnlogged.sum()),
                                  "crossDayPairs": int(base.crossDay.sum()), "clustering": "each pair is clustered on its arrival day (the next drive's calendar day)"}
    if len(base) < 20:
        out["primary"] = {"tauH": None, "notEstimable": True}
        return out, base
    tau = l1_tau(base.e0.values, base.e1.values, base.gap_h.values)
    groups, _ = day_index(base["date"].values)
    rng = np.random.default_rng(SEED)
    vals = []
    e0, e1, gp = base.e0.values, base.e1.values, base.gap_h.values
    for _ in range(nb):
        ix = boot_idx(groups, rng)
        try:
            vals.append(l1_tau(e0[ix], e1[ix], gp[ix]))
        except Exception:
            vals.append(np.nan)
    ci, ok = pct(vals)
    out["primary"] = {"tauH": round(tau, 3), "ci95": ci, "droppedDrawShare": round(1 - ok / nb, 4), "notEstimable": bool(1 - ok / nb > 0.01 or ci is None)}
    # sensitivities (point estimates only)
    sens = {"projectDefinitionOutcomeFiltered": project_tau(p), "previousDriveMaxProxy": fit_variant(p, "prevMax", "nextStartMaster"), "L2Loss": fit_variant(p, "prevEnd", "nextStart", "l2"),
            "excludingFlaggedUnloggedPairs": fit_variant(p[~p.flagUnlogged], "prevEnd", "nextStart"),
            "gapBelow1h": fit_variant(p[p.gap_h < 1], "prevEnd", "nextStart"), "gap1hOrLonger": fit_variant(p[p.gap_h >= 1], "prevEnd", "nextStart"), "gap4hOrLonger": fit_variant(p[p.gap_h >= 4], "prevEnd", "nextStart")}
    for sh in (-2.0, -1.0, 1.0, 2.0):
        sens["ambientRefShift%+.0fC" % sh] = fit_variant(p, "prevEnd", "nextStart", shift=sh)
    out["sensitivities"] = sens
    pts = [v["tauH"] for k, v in sens.items() if v.get("tauH") is not None and k != "projectDefinitionOutcomeFiltered"] + [round(tau, 3)]
    hw = (out["primary"]["ci95"][1] - out["primary"]["ci95"][0]) / 2.0 if out["primary"]["ci95"] else None
    out["spread"] = {"definition": "max minus min of tau over the primary and its sensitivities, the outcome-filtered project variant excluded", "maxMinusMinH": round(max(pts) - min(pts), 3), "definitionDependent": bool(hw is not None and (max(pts) - min(pts)) > hw)}
    # held-out skill: day-blocked contiguous folds over arrival days
    days = np.array(sorted(base["date"].unique()))
    blocks = np.array_split(days, min(FOLDS, len(days)))
    pred = np.full(len(base), np.nan)
    for blk in blocks:
        test = base["date"].isin(blk).values
        if (~test).sum() < 20 or test.sum() == 0:
            continue
        t_k = l1_tau(e0[~test], e1[~test], gp[~test])
        pred[test] = e1[test] * 0 + e0[test] * np.exp(-gp[test] / t_k)
    sc = ~np.isnan(pred)
    err_m = np.abs(pred - e1)[sc]
    err_p = np.abs(e0 - e1)[sc]           # persistence: no decay
    err_r = np.abs(0.0 - e1)[sc]          # full relaxation to ambient_ref
    dd = base["date"].values[sc]
    g2, _ = day_index(dd)

    def skill(ix):
        m, a, b = err_m[ix].sum(), err_p[ix].sum(), err_r[ix].sum()
        return 1 - m / a, 1 - m / b, 1 - m / min(a, b)
    point = skill(np.arange(sc.sum()))
    rng = np.random.default_rng(SEED)
    bs = np.array([skill(boot_idx(g2, rng)) for _ in range(nb)])
    ciP, ciR, ciB = [pct(bs[:, i])[0] for i in range(3)]
    n_sc_d = len(set(dd))
    gate = bool(ciB is not None and ciB[0] > 0)
    out["heldOut"] = {"cv": "day-blocked contiguous folds over arrival days (k=%d), tau fitted on the other folds; MAE of the predicted next-start temperature on the temperature scale (C)" % len(blocks),
                      "nScoredPairs": int(sc.sum()), "nScoredDays": int(n_sc_d), "maeModelC": round(float(err_m.mean()), 3), "maePersistenceC": round(float(err_p.mean()), 3), "maeFullRelaxationC": round(float(err_r.mean()), 3),
                      "skillVsPersistence": {"estimate": round(float(point[0]), 4), "ci95": ciP}, "skillVsFullRelaxation": {"estimate": round(float(point[1]), 4), "ci95": ciR},
                      "skillVsBetterReference": {"estimate": round(float(point[2]), 4), "ci95": ciB},
                      "gate": "tau is useful only if the skill against the better of the two references has an interval above zero", "gatePassed": gate}
    out["d05"] = {"decision": "owner decision D-05 (2026-11-12): temperature-scale definition is the forecast basis", "support": "supported" if gate else "not supported",
                  "ifNotSupported": "Q4 is shown as a 3-tau grid with no primary value and Andrii is told that D-05 lacks support so he can re-decide it; no silent switch" if not gate else None}
    # comparison with the M28 prior (retained fraction at the pair-gap distribution)
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))["seasonalAssumptions"]
    qs = np.percentile(base.gap_h.values, [25, 50, 75])
    out["priorM28CompareColdSoakRetention"] = {"prior": cfg["coldSoakRetention"], "pairGapQuartilesH": [round(float(x), 2) for x in qs],
                                               "impliedRetainedFractionAtGapQuartiles": [round(float(np.exp(-x / tau)), 3) for x in qs],
                                               "note": "the prior is a band (lo, mid, hi) for an inter-drive pack cooling pattern; the implied fraction is exp(-gap/tau) at the corpus pair gaps; printed side by side, no test"}
    return out, base


# ------------------------------------------------------------------------------------------------ Q4
def af(tc, ea, ref=25.0):
    return np.exp(-ea / KB * (1.0 / (np.asarray(tc, float) + 273.15) - 1.0 / (ref + 273.15)))


def q4(d, c, q2blk, taus, base, ea_list=(0.3, 0.5, 0.7), parks=(0.0, -3.0, 3.0)):
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))["seasonalAssumptions"]
    clim = np.array([float(x) for x in cfg["monthlyTempC"]])
    dim = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
    cl = d[d.clean]
    span_d = (pd.to_datetime(cl.date).max() - pd.to_datetime(cl.date).min()).days + 1
    drive_h_per_day = float(cl.duration_s.sum() / 3600.0) / span_d
    n_per_day = len(cl) / span_d
    lowest = float(c.ambient_time_mean_c.min())
    beta = q2blk["primary"]["estimate"]
    cc = c.copy()
    # drive-time pack temperature at ambient a: class-averaged Q2 line through the time-weighted mean point (observed corpus)
    w = cc.duration_s.values
    a_bar, p_bar = float(np.average(cc.ambient_time_mean_c, weights=w)), float(np.average(cc.pack_temp_time_mean_c, weights=w))
    e0_med = float((base.prevEnd - base.amb).median()) if len(base) else 8.0
    gaps = np.minimum(base.gap_h.values, COOL_CAP_H) if len(base) else np.array([6.0])
    gq = np.quantile(gaps, np.linspace(0.025, 0.975, 20))       # empirical gap distribution (20 quantiles)
    hrs = np.arange(24)
    dd = DIURNAL_C * np.sin(2 * np.pi * (hrs - 9) / 24.0)
    tt = np.linspace(0, COOL_CAP_H, 181)

    def index(tau, ea, park):
        tot, parts = 0.0, {"parked": 0.0, "drive": 0.0, "coolDown": 0.0}
        extr = 0.0
        for m in range(12):
            h_m = 24.0 * dim[m]
            tpark = clim[m] + park
            drive_h = drive_h_per_day * dim[m]
            n_m = n_per_day * dim[m]
            cool_h = float(np.mean(np.minimum(gq, COOL_CAP_H))) * n_m
            park_h = max(h_m - drive_h - cool_h, 0.0)
            f_park = float(np.mean(af(tpark + dd, ea)))
            tp = p_bar + beta * (clim[m] - a_bar)
            f_drive = float(af(tp, ea))
            ex = np.array([float(np.trapezoid(af(tpark + e0_med * np.exp(-tt[tt <= g] / tau), ea), tt[tt <= g])) / g for g in gq if g > 0])
            f_cool = float(np.mean(ex)) if len(ex) else f_park
            v = {"parked": park_h * f_park, "drive": drive_h * f_drive, "coolDown": cool_h * f_cool}
            for k, x in v.items():
                parts[k] += x
            tot += sum(v.values())
            if clim[m] < lowest:
                extr += sum(v.values())
        return tot / (24.0 * dim.sum()), {k: round(v / tot, 4) for k, v in parts.items()}, round(extr / tot, 4)

    out = {"label": "Arrhenius-weighted temperature exposure index relative to constant 25 C (assumed Ea, verified:false); a dimensionless index, not a life, not a rate",
           "climatologySource": "summary_config.json seasonalAssumptions.monthlyTempC (external, user-supplied assumption)", "lowestObservedAmbientC": round(lowest, 2),
           "monthsBelowLowestObservedAmbient": [m + 1 for m in range(12) if clim[m] < lowest],
           "assignment": "drive-time pack temperature in each month = the time-weighted corpus mean point moved along the Q2 coupling line to the climatology; months below the lowest observed ambient are extrapolated via Q2 and their share of the index is printed",
           "inputsFromCorpus": {"driveHoursPerDay": round(drive_h_per_day, 3), "drivesPerCalendarDay": round(n_per_day, 3), "coolDownInitialExcessMedianC": round(e0_med, 2), "coolDownWindowCapH": COOL_CAP_H, "diurnalAmplitudeC": DIURNAL_C},
           "grid": []}
    for tn, tv in taus:
        if tv is None:
            continue
        for ea in ea_list:
            for pk in parks:
                if (ea != 0.5 and pk != 0.0):
                    continue
                ix, parts, extr = index(tv, ea, pk)
                out["grid"].append({"tauLabel": tn, "tauH": round(tv, 3), "eaEv": ea, "parkedOffsetC": pk, "index": round(float(ix), 4), "shareOfIndex": parts, "extrapolatedShareOfIndex": extr})
    return out


# ------------------------------------------------------------------------------------------------ block
def aggregate(d, nb=NB):
    r = q1_q2(d, nb)
    c = r.pop("_c")
    q3blk, base = q3(d, nb)
    block = {"label": "fitted seasonal quantities beside the M28 priors (exploratory; estimated, never measured; no year output)", "spec": SPEC, "status": "exploratory",
             "reading": ["Q1 and Q2 are associations by thermal class (season, route, load and period move together), never temperature effects",
                         "the ambient is the driver-recorded dashboard reading entered by hand; it carries reading error and whole-degree quantisation",
                         "the estimators of Q1 to Q3 were run on this corpus in the self-audit, so the current estimates are post hoc; 'supported' in the ladder means support only, not confirmatory status",
                         "a winter statement is allowed only for ambient bands that reach 'supported'; below that the block prints 'not observed at this support'",
                         "the Q3 interval covers sampling variability only; quote tau together with its sensitivity bracket, which is set mostly by the ambient-reference shifts; the held-out skill against persistence does not choose between the tau definitions",
                         "Q4 has no interval: the whole grid is its bracket; because its reproduction was partial, index differences below about 0.015 are not resolvable and tau-driven differences fall below that; it rests on an assumed climatology, an assumed 4 C diurnal amplitude and the corpus median initial excess, the cool-down windows carry most of the index, and the months below the lowest observed ambient are extrapolated; show the whole grid or nothing",
                         "the held-out skill is the skill of a model on a temperature scale whose ambient reference is built from the same pairs; it is not a validation of a battery property, and its interval resamples fixed held-out errors, so it excludes the variance of the fitted tau",
                         "the sensitivities are reported, not tuned, and carry no multiplicity control across the many Q1 to Q3 variants; a Q1 interval that includes 0 reads 'not resolved at this support', never 'no effect'",
                         "the exposure index is not a life and not a rate; every year output stays retracted (M114); the M28 block is unchanged"],
             "data": {k: r[k] for k in ("essBasis", "support", "lowestAmbientC", "bandSupport", "drivesBelow5C", "drivesBelow0C", "daysBelow5C", "daysBelow0C")},
             "Q1": r["Q1"], "Q2": r["Q2"], "Q3": q3blk}
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))["seasonalAssumptions"]
    pr = cfg["consumptionSlopePerC"]
    f = r["Q1"]["fractionalSlopePerC"]
    block["Q1"]["belowFiveCLabel"] = "exploratory: few effective days and a large largest-day share in this band (see data.bandSupport)"
    block["Q1"]["priorM28CompareConsumptionSlope"] = {"label": "exploratory", "prior": pr, "fractionalEstimate": f["estimate"], "differenceToPriorMid": round(f["estimate"] - pr["mid"], 5),
                                                      "intervalOverlapsPriorBand": None if f["ci95"] is None else bool(f["ci95"][0] <= pr["hi"] and f["ci95"][1] >= pr["lo"]),
                                                      "note": "the prior is a band (lo, mid, hi), not an interval"}
    taus = []
    if q3blk.get("heldOut", {}).get("gatePassed"):
        taus.append(("primary L1 temperature scale", q3blk["primary"]["tauH"]))
    sens = q3blk.get("sensitivities", {})
    for k, lab in (("projectDefinitionOutcomeFiltered", "project definition (outcome-filtered)"), ("previousDriveMaxProxy", "previous-drive-maximum proxy")):
        if sens.get(k, {}).get("tauH") is not None:
            taus.append((lab, sens[k]["tauH"]))
    if q3blk.get("primary", {}).get("tauH") is not None and not q3blk.get("heldOut", {}).get("gatePassed"):
        taus.insert(0, ("L1 temperature scale (no primary: held-out gate not passed)", q3blk["primary"]["tauH"]))
    block["Q4"] = q4(d, c, r["Q2"], taus, base)
    block["disclosures"] = ["the sensitivity tau values in the Q4 grid (project definition, previous-drive maximum) are refitted on the live corpus at every run, not the earlier cited constants (no snapshot constants)",
                            "owner decision D-05 fixes the primary tau as the Q4 basis; the held-out gate supports using it; the fallback is pre-registered",
                            "Q1 below 5 C and the comparison with the M28 consumption-slope prior are exploratory (few effective days, a large largest-day share); allowed reading: the fitted association does not overlap the prior band; never that the prior is refuted",
                            "spec analyses/M666_spec.md Rev 1.2 (sections 8 to 10: Director review, implementation record, blind-audit reconciliation); no article use without the Opus audit and Andrii's sign-off"]
    block["Q4"]["primaryTau"] = "primary" if q3blk.get("heldOut", {}).get("gatePassed") else "none (D-05 not supported at the held-out gate; grid only)"
    return block


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get("seasonalFits")
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M667: derived by tools/n02_seasonal_fits.py from drive_master.csv, seasonal_drive_master.csv, ah_throughput.csv and end-of-drive pack temperatures from raw (spec analyses/M666_spec.md Rev 1.2); exploratory")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["seasonalFits"] = _sc.carry_declared(old, st)


def main(argv):
    raw_dir = argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else (os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file"])
    eps = corpus_endpoints(raw_dir, sorted(dm["file"]), verbose=True)
    d = load_drives(eps)
    nb = 400 if "--dry-run" in argv else NB
    block = aggregate(d, nb)
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    block["provenance"] = {"masterMd5": md5, "nCanonicalCleanDrives": int(d.clean.sum()), "nEndpointFilesRead": len(eps), "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "seed": SEED, "nBoot": nb}
    if "--out" in argv:
        json.dump(block, open(argv[argv.index("--out") + 1], "w", encoding="utf-8"), indent=1)
        print("wrote block")
        return
    if "--dry-run" in argv:
        print(json.dumps({"Q1": block["Q1"]["primary"], "Q2": block["Q2"]["primary"], "Q3": block["Q3"].get("primary"), "gate": block["Q3"].get("heldOut", {}).get("gatePassed")}))
        return
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    old = copy.deepcopy(A)
    A["seasonalFits"] = block
    stamp(A, md5)
    chk = copy.deepcopy(A); chk.pop("seasonalFits"); chk["_artifactStamps"].pop("seasonalFits")
    o2 = copy.deepcopy(old); o2.pop("seasonalFits", None); o2["_artifactStamps"].pop("seasonalFits", None)
    assert chk == o2, "unexpected change outside /seasonalFits"
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    main(sys.argv[1:])
