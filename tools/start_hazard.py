#!/usr/bin/env python3
"""M701 (spec analyses/M701_spec.md Rev 1 + errata 13): demand-aware hazard of RPM onsets (> 300 rpm, run >= 2 s) during engine-off spells.
Discrete-time cloglog hazard on 2 s intervals (log-width offset), time-since-spell-start spline, covariates up to second t-1 (LOCF <= 15 s), pedal D 2 s maximum primary.
Primary quantity: day-blocked cross-validated per-day log-likelihood gain of M1 (with pedal) over M0 (without), identical rows. Sign condition: log hazard ratio P75 vs P25 (scalar).
Modes:  python tools/start_hazard.py --pilot N | --study OUT.json [--workers W] | --sim OUT.json [--reps R]"""
import os, sys, json, hashlib, time, warnings
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from patsy import build_design_matrices
warnings.filterwarnings("ignore")
SEED = 42; NBOOT = 4000; FOLDS = 5; DF = 4
PED = "Положення педалі акселератора D (%)"
LINK = sm.families.links.CLogLog()
BASE = "cr(soc, df=4, constraints='center') + cr(speed, df=4, constraints='center') + cr(dur, df=4, constraints='center') + C(cls)"
F0 = "y ~ " + BASE
F1 = F0 + " + cr(ped, df=4, constraints='center')"
F2 = F0 + " + cr(tt, df=4, constraints='center')"
F3 = F1 + " + cr(tt, df=4, constraints='center')"


# ---------------------------------------------------------------- data
def build_grid(df, lim=15):
    import compute_summary_arrays as C
    from drive_raw_cache import fast_time as _ft
    df, _ = C._apply_speed_priority(df)
    df = df.rename(columns={k: v for k, v in C.RAW_MAP.items() if k in df.columns})
    if "time" not in df:
        return None
    t = _ft(df["time"], mixed=True)
    g = pd.DataFrame({"t": t})
    for nm, src, lo, hi, rawff in (("rpm", "eng_rpm", 0, None, True), ("cool", "T_coolant", -40, 150, True), ("speed", "speed", 0, None, False), ("soc", "soc", None, None, False),
                                   ("tt", "target_torque", None, None, False), ("ped", PED, 0, 100, False)):
        if src not in df:
            g[nm] = np.nan; continue
        s = pd.to_numeric(df[src], errors="coerce")
        if rawff:
            s = s.ffill(limit=lim)
        if lo is not None:
            s = s.where(s >= lo)
        if hi is not None:
            s = s.where(s <= hi)
        g[nm] = s.values
    g = g.dropna(subset=["t"]).set_index("t")
    r = g.resample("1s").mean()
    seen = r[["ped", "tt"]].notna()
    out = r.ffill(limit=lim)
    for c in ("ped", "tt"):                       # age of the carried sample (s since the last logged value on the 1 s grid)
        idx = np.where(seen[c].values, np.arange(len(r)), -1)
        last = np.maximum.accumulate(idx)
        out[c + "_age"] = np.where(last >= 0, np.arange(len(r)) - last, 9999)
    return out


def onset_idx(on, thr_len=2):
    edges = np.diff(np.concatenate([[0], on.astype(int), [0]]))
    s = np.where(edges == 1)[0]; ln = np.where(edges == -1)[0] - s
    return s[ln >= thr_len]


def rollmax(x, L):
    s = pd.Series(x).rolling(L, min_periods=1).max().shift(1)      # window ends at k-1
    return s.values


def drive_rows(hz, thr=300, lag=2, excl="first60", rev=None, age_max=None, width=2):
    """Person-period blocks of `width` s for one drive. Covariates for a block starting at grid second k use samples <= k-1."""
    n = len(hz)
    rpm = hz["rpm"].values; nanr = ~np.isfinite(rpm); on = np.nan_to_num(rpm) > thr
    ev = np.zeros(n, bool); ev[onset_idx(on)] = True
    prev_off = np.concatenate([[True], ~on[:-1] & ~nanr[:-1]])      # key-on spell: at risk from second 1
    atrisk = prev_off & ~nanr
    atrisk[0] = False
    k = np.arange(n)
    if excl == "first60":
        atrisk &= k >= 60
    elif excl == "cool60":
        cool_prev = np.concatenate([[np.nan], hz["cool"].values[:-1]])
        atrisk &= np.isfinite(cool_prev) & (cool_prev >= 60)
    if rev is not None:
        for a, b in rev:
            atrisk[max(0, int(a)):int(b) + 1] = False
    ev &= atrisk
    last_on = np.maximum.accumulate(np.where(on, k, -1))
    dur = np.where(last_on >= 0, k - 1 - last_on, k - 1).astype(float)
    pad = (-n) % width
    def blk(x, f):
        x = np.concatenate([x, np.zeros(pad, x.dtype)]) if pad else x
        return f(x.reshape(-1, width))
    w = blk(atrisk.astype(int), lambda m: m.sum(1)); y = blk(ev.astype(int), lambda m: m.max(1))
    b0 = np.arange(0, n + pad, width)
    def at_start(a):
        a = np.concatenate([a, np.full(pad, np.nan)]) if pad else a
        return np.concatenate([[np.nan], a])[b0]       # sample at k-1
    out = pd.DataFrame({"w": w, "y": y, "k": b0, "soc": at_start(hz["soc"].values), "speed": at_start(hz["speed"].values),
                        "dur": at_start(dur), "cool": at_start(hz["cool"].values), "ped": np.nan, "tt": np.nan, "ped_age": np.nan, "tt_age": np.nan})
    for c in ("ped", "tt"):
        v = hz[c].values.astype(float)
        rm = rollmax(v, lag) if lag > 0 else np.concatenate([[np.nan], v[:-1]])
        rm = np.concatenate([rm, np.full(pad, np.nan)]) if pad else rm
        out[c] = rm[b0]
        out[c + "_age"] = at_start(hz[c + "_age"].values.astype(float))
    out = out[out["w"] > 0]
    if age_max is not None:
        out = out[(out["ped_age"] <= age_max) | ~np.isfinite(out["ped_age"])]
    return out


def load_rev_mask():
    import reverse_mask as R
    import ah_throughput as AH
    tau0 = R.load_tau0(); sha_by = AH.manifest_sha_lookup(); res = {}
    import glob
    cache = {os.path.basename(p).split("_v")[0]: p for p in glob.glob(os.path.join(ROOT, "reverse_mask_cache", "*.json"))}
    return sha_by, cache


_RAWIDX = {}


def raw_pedal(fn):
    """Pedal D from the raw CSV (the pipeline frame cache does not carry it); attached by row position (row counts verified equal)."""
    import re
    root = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    if not _RAWIDX:
        for n in os.listdir(root):
            _RAWIDX.setdefault(re.sub(r"\D", "", n)[-14:], os.path.join(root, n))
    p = _RAWIDX.get(re.sub(r"\D", "", fn)[-14:])
    if not p:
        return None
    r = pd.read_csv(p, usecols=lambda c: c == PED)
    return pd.to_numeric(r[PED], errors="coerce").values if PED in r else None


def collect(files=None, variants=None, workers=1):
    """Build the person-period tables for every variant for each eligible drive. Variants: name -> kwargs of drive_rows."""
    import drive_raw_cache as drc
    variants = variants or {"primary": {}}
    m = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "date", "ens_outlier_v2"], low_memory=False)
    m = m[m["ens_outlier_v2"].astype(str) == "False"]
    reg = pd.read_csv(os.path.join(ROOT, "seasonal_drive_master.csv"), usecols=["file", "thermal_regime"]); cls = dict(zip(reg.file, reg.thermal_regime))
    cad = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv")); cadm = {r.file: (r.regime if isinstance(r.regime, str) else "unknown") for r in cad.itertuples()}
    sha_by, cache = load_rev_mask()
    fl = drc.make_frame_loader()
    tabs = {v: [] for v in variants}; cov = []
    for _, r in m.iterrows():
        fn = r["file"]
        if files is not None and fn not in files:
            continue
        df = fl(fn)
        if df is None:
            continue
        pv = raw_pedal(fn)
        if pv is not None and len(pv) == len(df):
            df = df.copy(); df[PED] = pv
        hz = build_grid(df)
        if hz is None or hz["rpm"].notna().sum() == 0:
            continue
        rpm = hz["rpm"].values; off = ~(np.nan_to_num(rpm) > 300)
        pc = float(np.isfinite(hz["ped"].values[off]).mean()) if off.any() else 0.0
        tc = float(np.isfinite(hz["tt"].values[off]).mean()) if off.any() else 0.0
        sha = sha_by(fn); rev = None
        if sha and sha in cache:
            rec = json.load(open(cache[sha], encoding="utf-8")); rev = [(e["tStart"], e["tStart"] + e["duration"]) for e in (rec.get("episodes") or [])]
        cov.append({"file": fn, "date": str(r["date"])[:10], "pedCov": pc, "ttCov": tc})
        for name, kw in variants.items():
            kw = dict(kw)
            use_rev = kw.pop("rev", True)
            t = drive_rows(hz, rev=(rev if use_rev else None), **kw)
            t["file"] = fn; t["date"] = str(r["date"])[:10]; t["cls"] = cls.get(fn, "warm"); t["cad"] = cadm.get(fn, "unknown"); t["pedEl"] = pc > 0.9; t["ttEl"] = tc > 0.9
            tabs[name].append(t)
    return {k: (pd.concat(v, ignore_index=True) if v else pd.DataFrame()) for k, v in tabs.items()}, pd.DataFrame(cov)


# ---------------------------------------------------------------- model
def winsor(df, cols, bounds=None):
    bounds = bounds or {c: (float(np.nanpercentile(df[c], 1)), float(np.nanpercentile(df[c], 99))) for c in cols}
    for c in cols:
        df[c] = df[c].clip(*bounds[c])
    return bounds


def fit(df, formula, cluster=False):
    mod = smf.glm(formula, df, family=sm.families.Binomial(link=LINK), offset=np.log(df["w"].values))
    return mod.fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(df["date"])[0]}) if cluster else mod.fit()


def predict_p(res, df):
    return res.predict(df, offset=np.log(df["w"].values))


def loglik(y, p):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return y * np.log(p) + (1 - y) * np.log(1 - p)


def design_row(res, ref):
    return np.asarray(build_design_matrices([res.model.data.orig_exog.design_info], ref)[0])


def hr_scalar(res, df, var="ped", draws=NBOOT, seed=SEED, score_boot=True):
    """log hazard ratio of `var` at its 75th vs 25th percentile, other covariates at median (cls warm); sandwich (needs a clustered fit) and day-cluster score bootstrap."""
    q25, q75 = float(np.nanpercentile(df[var], 25)), float(np.nanpercentile(df[var], 75))
    base = {c: [float(np.nanmedian(df[c]))] for c in ("soc", "speed", "dur", "ped", "tt")}
    base["cls"] = ["warm"]; base["w"] = [1.0]; base["y"] = [0]
    a = pd.DataFrame(base); b = pd.DataFrame(base); a[var] = q25; b[var] = q75
    d = (design_row(res, b) - design_row(res, a))[0]
    beta = np.asarray(res.params); est = float(d @ beta)
    se = float(np.sqrt(d @ np.asarray(res.cov_params()) @ d))
    out = {"q25": q25, "q75": q75, "logHR": est, "hr": float(np.exp(est)), "sandwichSE": se, "sandwichCi95": [float(np.exp(est - 1.96 * se)), float(np.exp(est + 1.96 * se))]}
    if score_boot:
        S = res.model.score_obs(beta)
        g = pd.factorize(df["date"])[0]
        Sd = np.zeros((g.max() + 1, S.shape[1])); np.add.at(Sd, g, S)
        V = np.linalg.inv(-res.model.hessian(beta))
        rng = np.random.default_rng(seed)
        xi = rng.choice([-1.0, 1.0], size=(draws, Sd.shape[0]))
        bs = beta[None, :] + (xi @ Sd) @ V.T
        lh = bs @ d
        out["scoreBootCi95"] = [float(np.exp(np.percentile(lh, 2.5))), float(np.exp(np.percentile(lh, 97.5)))]
        out["draws"] = draws
    return out


def monotone(res, df, var="ped"):
    lo, hi = float(np.nanpercentile(df[var], 10)), float(np.nanpercentile(df[var], 90))
    g = np.linspace(lo, hi, 25)
    base = {c: [float(np.nanmedian(df[c]))] * len(g) for c in ("soc", "speed", "dur", "ped", "tt")}
    base["cls"] = ["warm"] * len(g); base["w"] = [1.0] * len(g); base["y"] = [0] * len(g)
    a = pd.DataFrame(base); a[var] = g
    eta = design_row(res, a) @ np.asarray(res.params)
    inc = np.diff(eta)
    return {"nondecreasing": bool((inc >= -1e-9).all()), "shareIncreasing": float((inc > 0).mean())}


def cv_gain(df, f_big, f_small, seed=SEED, boot=NBOOT):
    days = df.groupby("date").size().index.values
    mon = {d: d[:7] for d in days}
    rng = np.random.default_rng(seed)
    fold = {}
    for mth in sorted(set(mon.values())):
        ds = [d for d in days if mon[d] == mth]; rng.shuffle(ds)
        for i, d in enumerate(ds):
            fold[d] = i % FOLDS
    df = df.assign(fold=df["date"].map(fold))
    p1 = np.zeros(len(df)); p0 = np.zeros(len(df))
    for f in range(FOLDS):
        tr, te = df[df["fold"] != f], df[df["fold"] == f]
        r1, r0 = fit(tr, f_big), fit(tr, f_small)
        p1[te.index] = predict_p(r1, te).values; p0[te.index] = predict_p(r0, te).values
    d1 = loglik(df["y"].values, p1) - loglik(df["y"].values, p0)
    per_day = pd.Series(d1).groupby(df["date"].values).sum()
    nd = len(per_day); rng = np.random.default_rng(seed)
    bs = np.array([per_day.values[rng.integers(0, nd, nd)].mean() for _ in range(boot)])
    from sklearn.metrics import roc_auc_score
    def auc(idx, p):
        return roc_auc_score(df["y"].values[idx], (p / df["w"].values)[idx])
    allidx = np.arange(len(df))
    out = {"gainPerDayMean": float(per_day.mean()), "gainPerDayCi95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], "gainTotal": float(per_day.sum()),
           "nDays": int(nd), "nBlocks": int(len(df)), "nEvents": int(df["y"].sum()), "draws": boot,
           "auc": {"M1": float(auc(allidx, p1)), "M0": float(auc(allidx, p0))}}
    out["auc"]["gain"] = out["auc"]["M1"] - out["auc"]["M0"]
    byday = {d: np.where(df["date"].values == d)[0] for d in days}
    ab = []
    for _ in range(300):
        pick = rng.integers(0, nd, nd)
        idx = np.concatenate([byday[days[i]] for i in pick])
        if df["y"].values[idx].sum() == 0:
            continue
        ab.append(auc(idx, p1) - auc(idx, p0))
    out["auc"]["gainCi95"] = [float(np.percentile(ab, 2.5)), float(np.percentile(ab, 97.5))]; out["auc"]["draws"] = 300
    return out


# ---------------------------------------------------------------- study
def supported(cv, hr):
    ok_cv = cv["gainPerDayCi95"][0] > 0
    ok_hr = hr["sandwichCi95"][0] > 1 and hr["scoreBootCi95"][0] > 1
    ok_auc = cv["auc"]["gainCi95"][0] > 0
    return bool(ok_cv and ok_hr and ok_auc), {"cvGainExcludesZero": bool(ok_cv), "hrBothIntervalsAboveOne": bool(ok_hr), "aucGainExcludesZero": bool(ok_auc)}


def eligible_ok(df, minD=10, minDays=5):
    return df["file"].nunique() >= minD and df["date"].nunique() >= minDays


def run_study(out, files=None):
    t0 = time.time()
    variants = {"primary": {}, "lag0": {"lag": 0}, "lag5": {"lag": 5}, "thr400": {"thr": 400}, "cool60": {"excl": "cool60"}, "withStart": {"excl": "none"},
                "revIncluded": {"rev": False}, "age5": {"age_max": 5}, "everySecond": {"width": 1}}
    tabs, cov = collect(files, variants)
    res = {"spec": "analyses/M701_spec.md Rev 1 + errata 13", "seed": SEED, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest()}
    prim = tabs["primary"]
    P = prim[prim["pedEl"] & np.isfinite(prim[["soc", "speed", "dur", "ped"]]).all(axis=1)].reset_index(drop=True)
    bounds = winsor(P, ["soc", "speed", "dur", "ped"])
    res["fingerprint"] = {"nDrives": int(P["file"].nunique()), "nDays": int(P["date"].nunique()), "nBlocks": int(len(P)), "nEvents": int(P["y"].sum()), "winsorBounds": bounds,
                          "pedEligibleDrives": int((cov["pedCov"] > 0.9).sum()), "cleanDrivesRead": int(len(cov))}
    if not eligible_ok(P):
        res["status"] = "not estimable: fewer than 10 pedal-eligible drives on 5 days"
        json.dump(res, open(out, "w", encoding="utf-8"), indent=1, default=str); return res
    r1 = fit(P, F1, cluster=True)
    hr = hr_scalar(r1, P)
    cv = cv_gain(P, F1, F0)
    ok, parts = supported(cv, hr)
    res["primary"] = {"hazardRatioP75vsP25": hr, "monotonicity": monotone(r1, P), "cvGain": cv, "supported": ok, "supportParts": parts,
                      "nonSupportNote": "supported = consistent with the OEM statement that start depends on demand; otherwise not established"}
    res["sensitivities"] = {}
    for name in ("lag0", "lag5", "thr400", "cool60", "withStart", "revIncluded", "age5", "everySecond"):
        T = tabs[name]; Q = T[T["pedEl"] & np.isfinite(T[["soc", "speed", "dur", "ped"]]).all(axis=1)].reset_index(drop=True)
        if not eligible_ok(Q):
            res["sensitivities"][name] = {"status": "not estimable"}; continue
        winsor(Q, ["soc", "speed", "dur", "ped"], bounds)
        rr = fit(Q, F1, cluster=True)
        res["sensitivities"][name] = {"nDrives": int(Q["file"].nunique()), "nDays": int(Q["date"].nunique()), "nEvents": int(Q["y"].sum()), "hazardRatioP75vsP25": hr_scalar(rr, Q, draws=1000)}
    res["cadenceStrata"] = {}
    for c in ("fast", "slow"):
        Q = P[P["cad"] == c].reset_index(drop=True)
        if not eligible_ok(Q):
            res["cadenceStrata"][c] = {"status": "not estimable", "nDrives": int(Q["file"].nunique()), "nDays": int(Q["date"].nunique())}; continue
        rr = fit(Q, F1, cluster=True)
        res["cadenceStrata"][c] = {"nDrives": int(Q["file"].nunique()), "nDays": int(Q["date"].nunique()), "hazardRatioP75vsP25": hr_scalar(rr, Q, draws=1000)}
    TT = P[P["ttEl"] & np.isfinite(P["tt"])].reset_index(drop=True)
    if eligible_ok(TT):
        tb = winsor(TT, ["tt"])
        m1, m2 = fit(TT, F1, cluster=True), fit(TT, F2, cluster=True)
        m3 = fit(TT, F3, cluster=True)
        c0 = np.corrcoef(TT["ped"], TT["tt"])[0, 1]
        res["targetTorque"] = {"nDrives": int(TT["file"].nunique()), "nDays": int(TT["date"].nunique()), "intersectionSetOnly": True, "pedalTorqueCorrelation": float(c0),
                               "M1pedal": hr_scalar(m1, TT, "ped", 1000), "M2torque": hr_scalar(m2, TT, "tt", 1000), "M3bothPedal": hr_scalar(m3, TT, "ped", 1000), "M3bothTorque": hr_scalar(m3, TT, "tt", 1000),
                               "reverseCausality": "target torque is a VCM output (the controller computes it from the pedal): possible reverse causality"}
    else:
        res["targetTorque"] = {"status": "not estimable"}
    res["runtimeSeconds"] = round(time.time() - t0)
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1, default=str)
    return res


# ---------------------------------------------------------------- simulation (known answer)
def sim_one(args):
    seed, log_hr_iqr, confound = args
    rng = np.random.default_rng(seed)
    nd, per, nb = 44, 5, 200
    rows = []
    for d in range(nd):
        u = rng.normal(0, 0.3); month = d * 4 // nd
        for j in range(per):
            v = rng.normal(0, 0.3)
            soc = np.cumsum(rng.normal(0, 0.15, nb)) % 6 + 40; speed = np.abs(np.cumsum(rng.normal(0, 3, nb))) % 90
            ar = np.zeros(nb); z = rng.normal()
            for i in range(nb):
                z = 0.8 * z + 0.6 * rng.normal(); ar[i] = z
            ped = np.clip(18 + 8 * ar + (4 * month if confound else 0), 0, 100)
            dur = np.arange(nb) * 2.0
            iqr = 10.8
            eta = -4.6 + 0.02 * (soc - 43) - 0.004 * (speed - 40) - 0.0005 * dur + u + v + log_hr_iqr * (ped - 18) / iqr + (0.25 * month if confound else 0)
            y = (rng.random(nb) < 1 - np.exp(-2 * np.exp(eta))).astype(int)
            hit = np.where(y == 1)[0]
            m = nb if len(hit) == 0 else hit[0] + 1                   # spell ends at the event
            rows.append(pd.DataFrame({"w": 2, "y": y[:m], "soc": soc[:m], "speed": speed[:m], "dur": dur[:m], "ped": ped[:m], "tt": ped[:m], "cls": "warm", "date": f"d{d:02d}", "file": f"f{d}_{j}"}))
    df = pd.concat(rows, ignore_index=True)
    r = fit(df, F1, cluster=True)
    h = hr_scalar(r, df, "ped", score_boot=False)
    truth = float(np.exp(log_hr_iqr))                           # IQR of the planted pedal is ~10.8 (nominal)
    return {"hr": h["hr"], "lo": h["sandwichCi95"][0], "hi": h["sandwichCi95"][1], "truth": truth, "events": int(df["y"].sum())}


def run_sim(out, reps=500, workers=6):
    from multiprocessing import Pool
    res = {"spec": "analyses/M701_spec.md Rev 1 item 12 + errata 13", "reps": reps}
    with Pool(workers) as pool:
        for name, lhr, conf in (("null", 0.0, False), ("planted_HR1.5", float(np.log(1.5)), False), ("epoch_confound_null", 0.0, True)):
            rs = pool.map(sim_one, [(SEED * 1000 + i, lhr, conf) for i in range(reps)])
            R = pd.DataFrame(rs)
            nan_share = float(R["lo"].isna().mean()); excl = (R["lo"] > 1) | (R["hi"] < 1)
            if name == "null":
                res[name] = {"falsePositiveRate": float(excl.mean()), "undefinedIntervalShare": nan_share, "criterion": "<= 0.075 and undefined share <= 0.02", "pass": bool(excl.mean() <= 0.075 and nan_share <= 0.02), "medianHr": float(R["hr"].median())}
            elif name == "planted_HR1.5":
                cov = ((R["lo"] <= R["truth"]) & (R["hi"] >= R["truth"])).mean()
                res[name] = {"coverage95": float(cov), "undefinedIntervalShare": nan_share, "criterion": ">= 0.90 and undefined share <= 0.02", "pass": bool(cov >= 0.90 and nan_share <= 0.02), "power": float(((R["lo"] > 1)).mean()), "medianHr": float(R["hr"].median()), "note": "truth uses the nominal IQR 10.8 of the planted pedal; the realised IQR differs slightly"}
            else:
                res[name] = {"falsePositiveRate": float(excl.mean()), "undefinedIntervalShare": nan_share, "diagnostic": True, "caveatIfAbove": 0.075, "epochConfoundedCaveat": bool(excl.mean() > 0.075)}
    res["allGatedCriteriaPass"] = bool(res["null"]["pass"] and res["planted_HR1.5"]["pass"])
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1)
    return res


def main(argv):
    if "--pilot" in argv:
        n = int(argv[argv.index("--pilot") + 1])
        m = pd.read_csv(os.path.join(ROOT, "analyses", "M701_feasibility_perdrive.csv"))
        files = set(m[m["pedEligible"]]["file"].head(n))
        r = run_study(os.path.join(os.environ.get("TEMP", "."), "m701_pilot.json"), files=files)
        print(json.dumps({k: r.get(k) for k in ("fingerprint", "status", "runtimeSeconds")}, default=str)); print(json.dumps(r.get("primary"), default=str)[:1500]); return
    if "--study" in argv:
        run_study(argv[argv.index("--study") + 1]); print("done"); return
    if "--sim" in argv:
        reps = int(argv[argv.index("--reps") + 1]) if "--reps" in argv else 500
        w = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 6
        print(json.dumps(run_sim(argv[argv.index("--sim") + 1], reps, w))); return


if __name__ == "__main__":
    main(sys.argv[1:])
