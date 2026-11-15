#!/usr/bin/env python3
"""M674 (N-03 part A, spec analyses/M673_spec.md Rev 1.1): reference-free exposure vector from the logged current.
Per drive, ONE raw pass computes sufficient statistics (Ah, hours, I^2 h by pack-temperature bin; charge-Ah screens; charge-current histogram) for the primary variant (sensor T1, offset 0) and the pre-registered
sensitivities (minimum over pack sensors; current offset -0.5 / +0.5 A), cached per drive in exposure_vector_cache/ keyed by raw sha256 + method version. Aggregation never rereads raw.
Integration is the tools/ah_throughput.py loop (same pairs, same M229 zero-crossing split); each interval is attributed to the temperature bin of the sample nearest its END within 10 s (both sides, tie to the earlier sample).
Estimated from logged BMS current, offset-uncorrected: exposure of the logged driving window, not lifetime exposure, not damage. Writes the additive block `exposureVector` (+ stamp) to summary_arrays.json.
Usage: python tools/exposure_vector.py [--raw-dir DIR] [--out FILE] [--limit N]"""
import copy, datetime, hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd

METHOD_VERSION = 1
CACHE_DIR = os.path.join(ROOT, "exposure_vector_cache")
EDGES = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]            # pack temperature, deg C; a value on an edge goes to the upper bin
BIN_LABELS = ["<0", "0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30-35", "35-40", ">=40"]
NB = len(BIN_LABELS)
UNASSIGNED = NB                                                          # index of the unassigned bucket
TOL_S = 10.0                                                             # temperature / SOC attribution tolerance
HI_A = 25.0                                                              # screen: mean charge current of the interval >= 25 A
SOC_HI = 70.0
CUR_EDGES = [0.0, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 75.0, 100.0, 150.0, 200.0, 1e9]       # A, histogram of interval mean charge current
OFFSETS = (0.0, -0.5, 0.5)
SENSORS = ("T1", "Tmin")
SEED, NBOOT = 42, 4000
FIELDS = ["ahDis", "ahChg", "hours", "absAh", "i2Dis", "i2Chg", "chgGe25", "chgSoc70", "chgSocMissing", "chgMax"] + ["h%d" % i for i in range(len(CUR_EDGES) - 1)]


def interval_arrays(dt_h, x):
    """The M229 rule on a discharge-positive quantity, per interval (arrays, the same expressions as tools/ah_throughput._split)."""
    p0 = np.nan_to_num(np.concatenate([[np.nan], x[:-1]]), nan=0.0)
    cross = (p0 * x) < 0
    absum = np.abs(p0) + np.abs(x)
    den = np.where(absum > 0, 2.0 * absum, 1.0)
    disc_c = dt_h * ((p0 > 0) * p0 ** 2 + (x > 0) * x ** 2) / den
    chg_c = dt_h * ((p0 < 0) * p0 ** 2 + (x < 0) * x ** 2) / den
    signed = dt_h * (p0 + x) / 2.0
    disc = np.where(cross, disc_c, np.where(signed > 0, signed, 0.0))
    chg = np.where(cross, chg_c, np.where(signed < 0, -signed, 0.0))
    return p0, cross, disc, chg


def i2_arrays(dt_h, p0, x, cross):
    """Spec Rev 1.1 item 4: integral of I^2 dt for piecewise-linear current, split at a zero crossing; returns (discharge A^2 h, charge A^2 h) per interval."""
    same = dt_h * (p0 ** 2 + p0 * x + x ** 2) / 3.0
    s = np.where(np.abs(p0) + np.abs(x) > 0, np.abs(p0) / np.where(np.abs(p0) + np.abs(x) > 0, np.abs(p0) + np.abs(x), 1.0), 0.0)
    side_a = s * dt_h * p0 ** 2 / 3.0                                    # on the p0 side
    side_b = (1.0 - s) * dt_h * x ** 2 / 3.0
    d_same = np.where((p0 >= 0) & (x >= 0), same, 0.0)
    c_same = np.where((p0 <= 0) & (x <= 0) & ~((p0 == 0) & (x == 0)), same, 0.0)
    d = np.where(cross, np.where(p0 > 0, side_a, 0.0) + np.where(x > 0, side_b, 0.0), d_same)
    c = np.where(cross, np.where(p0 < 0, side_a, 0.0) + np.where(x < 0, side_b, 0.0), c_same)
    return d, c


def nearest_idx(t_s, tq, tol=TOL_S):
    """Index of the sample of t_s (sorted seconds) nearest to each tq, within tol, both sides, tie to the earlier sample; -1 if none."""
    if len(t_s) == 0:
        return np.full(len(tq), -1)
    j = np.searchsorted(t_s, tq)
    lo = np.clip(j - 1, 0, len(t_s) - 1)
    hi = np.clip(j, 0, len(t_s) - 1)
    dlo = np.abs(tq - t_s[lo]); dhi = np.abs(t_s[hi] - tq)
    pick = np.where(dlo <= dhi, lo, hi)                                  # tie -> earlier
    d = np.minimum(dlo, dhi)
    return np.where(d <= tol, pick, -1)


def bin_of(T):
    return np.digitize(T, EDGES)                                         # edges[i-1] <= x < edges[i]


def bin_drive(t, Id, tT, T, tS=None, soc=None, dt_cap_h=None):
    """Pure function on arrays. t: seconds of the I/V pairs (sorted), Id: discharge-positive current (A) at the pairs (offset already applied), tT/T: temperature samples,
    tS/soc: SOC samples. Returns {field: array(NB+1)} (last entry = unassigned) plus bookkeeping."""
    dt_h = np.diff(t, prepend=t[0] if len(t) else 0.0)
    dt_h = np.clip(dt_h, 0, dt_cap_h * 3600.0 if dt_cap_h is not None else 5.0) / 3600.0
    dt_h[0:1] = 0.0
    p0, cross, disc, chg = interval_arrays(dt_h, Id)
    i2d, i2c = i2_arrays(dt_h, p0, Id, cross)
    ti = nearest_idx(np.asarray(tT, dtype=float), t) if tT is not None and len(tT) else np.full(len(t), -1)
    b = np.where(ti >= 0, bin_of(np.asarray(T, dtype=float)[np.clip(ti, 0, max(len(T) - 1, 0))]) if len(T) else 0, UNASSIGNED)
    if soc is not None and tS is not None and len(soc):
        si = nearest_idx(np.asarray(tS, dtype=float), t)
        sv = np.where(si >= 0, np.asarray(soc, dtype=float)[np.clip(si, 0, len(soc) - 1)], np.nan)
    else:
        sv = np.full(len(t), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_chg_a = np.where(dt_h > 0, chg / dt_h, 0.0)
    ge25 = np.round(mean_chg_a, 9) >= HI_A                                # M674: rounded to 9 decimals so a mean of exactly 25 A is not decided by floating-point noise
    out = {f: np.zeros(NB + 1) for f in FIELDS}
    np.add.at(out["ahDis"], b, disc); np.add.at(out["ahChg"], b, chg); np.add.at(out["hours"], b, dt_h)
    np.add.at(out["absAh"], b, (disc + chg)); np.add.at(out["i2Dis"], b, i2d); np.add.at(out["i2Chg"], b, i2c)
    np.add.at(out["chgGe25"], b, np.where(ge25, chg, 0.0))
    np.add.at(out["chgSoc70"], b, np.where(sv >= SOC_HI, chg, 0.0))
    np.add.at(out["chgSocMissing"], b, np.where(np.isnan(sv), chg, 0.0))
    has_chg = chg > 0
    for k in range(len(CUR_EDGES) - 1):
        m = has_chg & (mean_chg_a >= CUR_EDGES[k]) & (mean_chg_a < CUR_EDGES[k + 1])
        np.add.at(out["h%d" % k], b, np.where(m, dt_h, 0.0))
    for q in range(NB + 1):
        m = has_chg & (b == q)
        out["chgMax"][q] = float(mean_chg_a[m].max()) if m.any() else 0.0
    return out


def load_drive(csv_bytes):
    """Raw bytes -> arrays for bin_drive for every variant; also the unrounded ah_from_bytes control. Returns None-valued dict with a reason if no integrable I/V pairs."""
    import compute_drive_summary_v6 as D
    import ah_throughput as AH
    res = {"reason": None, "variants": {}, "t1ResolutionC": None}
    df, t = D._prep_bytes(csv_bytes)
    I = D._series(df, t, 'I')
    if I is not None:
        I = I[I['v'].abs() < 900]
    V = D._series(df, t, 'V', lo=AH.V_BAND[0], hi=AH.V_BAND[1])
    if I is None or V is None or len(I) <= 2:
        res["reason"] = "no_iv_series"
        return res
    e = D._asof(I.copy(), V, 'V', D.V_ALIGN_TOL).dropna(subset=['V'])
    if len(e) < 2:
        res["reason"] = "no_integrable_iv_pairs"
        return res
    t0 = e['t'].iloc[0]
    ts = (e['t'] - t0).dt.total_seconds().to_numpy(dtype=float)
    Iv = e['v'].to_numpy(dtype=float)
    temps = {}
    for c in ("T1", "T2", "T3", "T4"):
        s = D._series(df, t, c, lo=-40, hi=90)
        if s is not None:
            temps[c] = ((s['t'] - t0).dt.total_seconds().to_numpy(dtype=float), s['v'].to_numpy(dtype=float))
    if "T1" in temps:
        v = np.unique(np.round(temps["T1"][1], 6)); dv = np.diff(v); dv = dv[dv > 1e-9]
        res["t1ResolutionC"] = float(dv.min()) if len(dv) else None
    # minimum over the available sensors on the union of their timestamps (each sensor carried as-of, nearest within tolerance)
    tmin = None
    if temps:
        tt = np.unique(np.concatenate([x[0] for x in temps.values()]))
        cols = []
        for (xs, xv) in temps.values():
            idx = nearest_idx(xs, tt)
            cols.append(np.where(idx >= 0, xv[np.clip(idx, 0, len(xv) - 1)], np.nan))
        with np.errstate(all="ignore"):
            tmin = (tt, np.nanmin(np.vstack(cols), axis=0))
        ok = ~np.isnan(tmin[1]); tmin = (tmin[0][ok], tmin[1][ok])
    soc = D._series(df, t, 'soc')
    tS = (soc['t'] - t0).dt.total_seconds().to_numpy(dtype=float) if soc is not None else None
    sv = soc['v'].to_numpy(dtype=float) if soc is not None else None
    for sens in SENSORS:
        src = temps.get("T1") if sens == "T1" else tmin
        for off in OFFSETS:
            Id = -(Iv + off)
            res["variants"][("%s|%+.1f" % (sens, off))] = bin_drive(ts, Id, src[0] if src else None, src[1] if src else None, tS, sv, dt_cap_h=D.DT_CAP_S / 3600.0)
    ctrl = AH.ah_from_bytes(csv_bytes)
    res["control"] = {"ahDis": ctrl["ah_discharge"], "ahChg": ctrl["ah_charge"]}
    return res


CODE_TAG = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:8]            # a change of this file invalidates the cache


def cache_path(sha):
    return os.path.join(CACHE_DIR, "%s_v%d_%s.json" % (sha, METHOD_VERSION, CODE_TAG))


def drive_stats(csv_bytes, sha):
    p = cache_path(sha)
    if os.path.isfile(p):
        return json.load(open(p, encoding="utf-8"))
    r = load_drive(csv_bytes)
    out = {"sha": sha, "reason": r["reason"], "t1ResolutionC": r["t1ResolutionC"] if r["reason"] is None else None, "control": r.get("control"), "variants": {}}
    for k, v in r["variants"].items():
        out["variants"][k] = {f: [float(x) for x in v[f]] for f in FIELDS}
    os.makedirs(CACHE_DIR, exist_ok=True)
    json.dump(out, open(p, "w", encoding="utf-8"))
    return out


def corpus_stats(raw_dir, master, limit=None):
    import ah_throughput as AH
    sha_by = AH.manifest_sha_lookup()
    loader = AH.raw_loader(raw_dir)
    rows = {}
    for n, f in enumerate(sorted(master["file"])):
        if limit and n >= limit:
            break
        b = loader(f)
        if b is None:
            rows[f] = {"reason": "raw_missing", "variants": {}}
            continue
        sha = sha_by(f) or hashlib.sha256(b).hexdigest()
        rows[f] = drive_stats(b, sha)
    return rows


# ---------------------------------------------------------------- aggregation (no raw access)
PRIMARY = "T1|+0.0"


def _vec(rec, variant, field):
    v = (rec.get("variants") or {}).get(variant)
    return np.array(v[field]) if v else None


def _status(n_drives, n_days, ess):
    if n_drives < 10 or n_days < 5:
        return "not shown"
    return "exploratory" if ess < 10 else "supported"


def _ess(w):
    w = np.asarray(w, dtype=float)
    return float(w.sum() ** 2 / (w ** 2).sum()) if (w ** 2).sum() > 0 else 0.0


def day_ratio(nums, dens, dates, nboot=NBOOT, seed=SEED):
    """Ratio of sums with the day-clustered percentile bootstrap (calendar day = cluster)."""
    df = pd.DataFrame({"d": dates, "n": nums, "m": dens}).groupby("d")[["n", "m"]].sum()
    n, m = df["n"].to_numpy(), df["m"].to_numpy()
    if len(n) == 0 or m.sum() <= 0:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(n), size=(nboot, len(n)))
    den = m[idx].sum(axis=1)
    ok = den > 0
    r = n[idx].sum(axis=1)[ok] / den[ok]
    return {"est": float(n.sum() / m.sum()), "ci95": [float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))], "nDays": int(len(n)), "essDays": _ess(n), "essDaysDenominator": _ess(m)}


SCREEN_DEF = {"S1": "charge Ah in bins below 10 C", "S2": "charge Ah in bins below 15 C", "S3": "charge Ah at a mean interval charge current of 25 A or more",
              "S4": "charge Ah at SOC of 70 % or more", "S5": "charge Ah below 10 C at a mean interval charge current of 25 A or more"}


def screens(recs, variant, nboot=NBOOT):
    """S1-S5 on the given records (already restricted to the population)."""
    data = []
    for r in recs:
        chg = _vec(r, variant, "ahChg")
        if chg is None:
            continue
        data.append((r["date"], chg, _vec(r, variant, "chgGe25"), _vec(r, variant, "chgSoc70"), _vec(r, variant, "chgSocMissing")))
    den = np.array([d[1].sum() for d in data]); dates = [d[0] for d in data]
    nums = {"S1": np.array([d[1][:3].sum() for d in data]), "S2": np.array([d[1][:4].sum() for d in data]), "S3": np.array([d[2].sum() for d in data]),
            "S4": np.array([d[3].sum() for d in data]), "S5": np.array([d[2][:3].sum() for d in data])}
    out = {}
    for sid, num in nums.items():
        pos = num > 1e-12
        nd = int(len(set(np.array(dates)[pos]))) if pos.any() else 0
        nr = int(pos.sum())
        ratio = day_ratio(num, den, dates, nboot)
        st = _status(nr, nd, ratio["essDays"] if ratio else 0.0)
        out[sid] = {"definition": SCREEN_DEF[sid], "ah": round(float(num.sum()), 6), "cleanChargeAh": round(float(den.sum()), 6), "nDrives": nr, "nDays": nd, "status": st,
                    "share": round(ratio["est"], 8) if ratio else None, "shareCi95": [round(x, 8) for x in ratio["ci95"]] if (ratio and st != "not shown") else None,
                    "essDays": round(ratio["essDays"], 3) if ratio else None}
    out["S4"]["socMissingAh"] = round(float(sum(d[4].sum() for d in data)), 6)
    return out


def bins_table(recs, variant):
    tot = {f: np.zeros(NB + 1) for f in FIELDS}
    nd = np.zeros(NB + 1)
    days = [set() for _ in range(NB + 1)]
    perday = [dict() for _ in range(NB + 1)]
    for r in recs:
        a = _vec(r, variant, "ahDis")
        c = _vec(r, variant, "ahChg")
        if a is None:
            continue
        for f in FIELDS:
            v = _vec(r, variant, f)
            if f == "chgMax":
                tot[f] = np.maximum(tot[f], v)
            else:
                tot[f] += v
        for q in range(NB + 1):
            if a[q] + c[q] > 0:
                nd[q] += 1
                days[q].add(r["date"])
                perday[q][r["date"]] = perday[q].get(r["date"], 0.0) + float(a[q] + c[q])
    thr = tot["ahDis"] + tot["ahChg"]
    total = float(thr.sum())
    rows = []
    for q in range(NB + 1):
        rows.append({"bin": (BIN_LABELS[q] if q < NB else "unassigned"), "ahDischarge": round(float(tot["ahDis"][q]), 6), "ahCharge": round(float(tot["ahChg"][q]), 6),
                     "ahThroughput": round(float(thr[q]), 6), "shareOfThroughput": round(float(thr[q] / total), 8) if total > 0 else None,
                     "hours": round(float(tot["hours"][q]), 6), "meanAbsCurrentA": round(float(tot["absAh"][q] / tot["hours"][q]), 4) if tot["hours"][q] > 0 else None,
                     "i2hDischarge": round(float(tot["i2Dis"][q]), 4), "i2hCharge": round(float(tot["i2Chg"][q]), 4),
                     "nDrives": int(nd[q]), "nDays": len(days[q]), "status": _status(int(nd[q]), len(days[q]), _ess(list(perday[q].values())) if perday[q] else 0.0) if q < NB else "n/a",
                     "essDays": round(_ess(list(perday[q].values())), 3) if (q < NB and perday[q]) else None})
    return rows, tot


def hist_quantiles(tot_h, tot_max, qs=(0.5, 0.95, 0.99)):
    h = np.array(tot_h, dtype=float)
    if h.sum() <= 0:
        return None
    c = np.cumsum(h) / h.sum()
    out = {}
    for q in qs:
        k = min(int(np.searchsorted(c, q)), len(h) - 1)
        lo, hi = CUR_EDGES[k], (CUR_EDGES[k + 1] if CUR_EDGES[k + 1] < 1e8 else tot_max)
        prev = c[k - 1] if k > 0 else 0.0
        frac = (q - prev) / (c[k] - prev) if c[k] > prev else 0.0
        out["p%d" % round(q * 100)] = round(float(lo + frac * (hi - lo)), 3)
    out["max"] = round(float(tot_max), 3)
    return out


def q3_table(recs, variant):
    nh = len(CUR_EDGES) - 1
    hs = [np.zeros(NB + 1) for _ in range(nh)]
    mx = np.zeros(NB + 1)
    for r in recs:
        m = _vec(r, variant, "chgMax")
        if m is None:
            continue
        mx = np.maximum(mx, m)
        for k in range(nh):
            hs[k] += _vec(r, variant, "h%d" % k)
    rows = []
    for q in range(NB):
        qq = hist_quantiles([hs[k][q] for k in range(nh)], mx[q])
        rows.append({"bin": BIN_LABELS[q], "chargeHours": round(float(sum(hs[k][q] for k in range(nh))), 6), "currentA": qq,
                     "cRateOnRated5Ah": ({k: round(v / 5.0, 4) for k, v in qq.items()} if qq else None)})
    return rows


def aggregate(stats, master, regimes, ah_side, cap_kwh, cap_ah, ah_per100, md5, nboot=NBOOT):
    recs = []
    for _, m in master.iterrows():
        f = str(m["file"])
        r = dict(stats.get(f) or {"reason": "raw_missing", "variants": {}})
        r.update(file=f, date=str(m["date"]), clean=(str(m.get("ens_outlier_v2")) == "False"), regime=regimes.get(f))
        recs.append(r)
    have = [r for r in recs if r.get("variants")]
    clean = [r for r in have if r["clean"]]
    block = {"label": "Exposure vector of the logged driving window from the logged BMS current (estimated, offset-uncorrected; not lifetime exposure, not an ageing estimate)",
             "spec": "analyses/M673_spec.md Rev 1.1", "status": "descriptive; screens carry a support ladder",
             "reading": ["Exposure of the logged driving window only (logged drives; the logged share of the odometer is below 1), not lifetime exposure and not an ageing estimate.",
                         "Ampere-hours are integrated from the logged current (estimated, offset-uncorrected), never measured at the cell; charging here is regeneration and generator charging (no plug).",
                         "The screen thresholds (10 C, 15 C, 25 A, SOC 70 %) were adopted from an external review; they are not identified BMS limits.",
                         "The 25 A screen and the upper charge-current quantiles depend on the logging cadence (piecewise-linear sampling cuts peaks; the cadence-invariance check B6 stays FAILED); the cold charge Ah share is open to the uncorrected current offset.",
                         "Regeneration charging is concentrated in short high-current bursts, so a large share of charge Ah at 25 A or more describes regeneration, not a charger-type load.",
                         "|I| / 5 A is a ratio to the rated reference (verified:false), not a reference-free quantity. No annualisation is made."],
             "binEdgesC": EDGES, "binLabels": BIN_LABELS,
             "attribution": "interval Ah to the bin of the T1 sample nearest the interval end within 10 s (both sides, tie to the earlier sample); no sample -> unassigned; a value on an edge goes to the upper bin"}
    block["t1ResolutionC"] = min([r["t1ResolutionC"] for r in have if r.get("t1ResolutionC")], default=None)
    all_rows, all_tot = bins_table(have, PRIMARY)
    cl_rows, cl_tot = bins_table(clean, PRIMARY)
    block["population"] = {"nMasterDrives": len(recs), "nWithIvPairs": len(have), "nCanonicalClean": len(clean), "nDaysAll": len({r["date"] for r in have}), "nDaysClean": len({r["date"] for r in clean}),
                           "noIvDrives": [{"file": r["file"], "reason": r.get("reason")} for r in recs if not r.get("variants")][:60],
                           "lowestObservedPackTempBinClean": next((cl_rows[q]["bin"] for q in range(NB) if cl_rows[q]["nDrives"] > 0), None)}
    block["Q1_Q2_Q4_all"] = {"bins": all_rows}
    block["Q1_Q2_Q4_clean"] = {"bins": cl_rows}
    block["Q3_chargeCurrentByTemperature_clean"] = {"unit": "A (time-weighted over intervals with charge; histogram resolution of the current classes)", "rows": q3_table(clean, PRIMARY),
                                                    "cRateReference": "|I| / 5 A rated (verified:false)"}
    scr = {"primary": screens(clean, PRIMARY, nboot)}
    scr["sensitivityTmin"] = {k: v for k, v in screens(clean, "Tmin|+0.0", nboot).items() if k in ("S1", "S2", "S5")}
    scr["sensitivityOffset"] = {("%+.1f A" % off): screens(clean, "T1|%+.1f" % off, nboot) for off in (-0.5, 0.5)}
    scr["sensitivityCadence"] = {}
    nh = len(CUR_EDGES) - 1
    for reg in ("fast", "slow"):
        sub = [r for r in clean if r.get("regime") == reg]
        ent = {"nDrives": len(sub), "S3": screens(sub, PRIMARY, nboot)["S3"] if sub else None, "Q3_p95_A_all_bins": None}
        if sub:
            hist = np.zeros(nh)
            mxv = 0.0
            for r in sub:
                for k in range(nh):
                    hist[k] += _vec(r, PRIMARY, "h%d" % k)[:NB].sum()
                mxv = max(mxv, float(_vec(r, PRIMARY, "chgMax")[:NB].max()))
            qq = hist_quantiles(hist, mxv)
            ent["Q3_p95_A_all_bins"] = qq["p95"] if qq else None
        scr["sensitivityCadence"][reg] = ent
    scr["offsetNote"] = "current offset of -0.5 and +0.5 A applied to every sample (assumed, verified:false); the primary is offset 0"
    scr["limits"] = ["Splitting an interval at a bin crossing instead of end-sample attribution is not run (named limit).", "Screens count exposure; they make no assessment of the effect on the pack."]
    block["Q5_screens_clean"] = scr
    dd = {r["date"] for r in have}
    tot_thr = float((all_tot["ahDis"] + all_tot["ahChg"]).sum())
    block["Q6_totals"] = {"ahThroughputAll": round(tot_thr, 4), "nDrivingDays": len(dd), "ahThroughputPerDrivingDay": round(tot_thr / len(dd), 4) if dd else None,
                          "note": "window totals and per driving day; not annualised (the window is one season-cycle fragment)"}
    gk = float((ah_side["kwh_discharge"].fillna(0) + ah_side["kwh_charge"].fillna(0)).sum())
    ga = float(ah_side["ah_throughput"].fillna(0).sum())
    block["Q7_gtcBesideReferences"] = {"sumThroughputAh": round(ga, 4), "sumGrossThroughputKwh": round(gk, 4), "referenceAhRated": cap_ah, "referenceKwhLegacy": cap_kwh, "apparentScaleAhPer100": ah_per100,
                                       "gtcRatedBasis": round(ga / cap_ah, 3), "gtcLegacyBasis": round(gk / cap_kwh, 3), "gtcApparentScaleBasis": round(ga / ah_per100, 3) if ah_per100 else None,
                                       "ratioRatedOverLegacy": round((ga / cap_ah) / (gk / cap_kwh), 4),
                                       "note": "sums over the drives with an Ah value in ah_throughput.csv; the references (5 Ah rated, 2.1 kWh legacy, apparent SoC-scale) are verified:false and the 20,000 GTC scenario threshold stays a labelled multiplier, not a life estimate"}
    v = {}
    ctrl_ok, csv_ok, n_ctrl = True, True, 0
    side_idx = ah_side.set_index("file")
    for r in have:
        c = r.get("control")
        vd, vc = _vec(r, PRIMARY, "ahDis"), _vec(r, PRIMARY, "ahChg")
        if c and c.get("ahDis") is not None:
            n_ctrl += 1
            ctrl_ok &= abs(vd.sum() - c["ahDis"]) < 1e-9 and abs(vc.sum() - c["ahChg"]) < 1e-9
            if r["file"] in side_idx.index and pd.notna(side_idx.loc[r["file"], "ah_discharge"]):
                csv_ok &= abs(vd.sum() - float(side_idx.loc[r["file"], "ah_discharge"])) < 5e-7 and abs(vc.sum() - float(side_idx.loc[r["file"], "ah_charge"])) < 5e-7
    v["V1_perDriveInMemory1e-9"] = bool(ctrl_ok)
    v["V1_perDriveCsv5e-7"] = bool(csv_ok)
    v["V2_totalMatchesSidecar"] = abs(tot_thr - ga) < 5e-7 * max(len(have), 1) + 1e-6
    v["V3_everyMasterDriveAccounted"] = len(have) + len([r for r in recs if not r.get("variants")]) == len(recs)
    p = scr["primary"]
    v["V5_screenOrdering"] = bool(p["S1"]["ah"] <= p["S2"]["ah"] + 1e-9 and p["S5"]["ah"] <= min(p["S1"]["ah"], p["S3"]["ah"]) + 1e-9)
    v["V5_binSharesSumToOne"] = abs(sum(x["shareOfThroughput"] or 0 for x in all_rows) - 1.0) < 1e-6
    block["validity"] = dict(v, V1_nDrivesChecked=n_ctrl)
    assert all(v.values()), "validity rule failed: %s" % v
    block["provenance"] = {"masterMd5": md5, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "methodVersion": METHOD_VERSION, "seed": SEED, "nBoot": nboot, "toleranceS": TOL_S}
    return block


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get("exposureVector")
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M674: derived by tools/exposure_vector.py from raw drive CSVs (cached by sha256), drive_master.csv and ah_throughput.csv (spec analyses/M673_spec.md Rev 1.1); descriptive")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["exposureVector"] = _sc.carry_declared(old, st)


def main(argv):
    raw_dir = argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else (os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    master = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    master = master.sort_values("file").reset_index(drop=True)
    if limit:
        master = master.head(limit)
    stats = corpus_stats(raw_dir, master, None)
    cad = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv"), keep_default_na=False)
    regimes = {r["file"]: (r["regime"] or None) for r in cad.to_dict("records")}
    side = pd.read_csv(os.path.join(ROOT, "ah_throughput.csv"), dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])
    A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    cp = A["constantProvenance"]
    cap_kwh = float(cp["CAP_KWH"]["value"])
    cap_ah = float(cp["CAP_AH_RATED"]["value"])
    a100 = (A.get("capacityBasis") or {}).get("ahPer100", {}).get("point")
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    if limit:
        side = side[side["file"].isin(set(master["file"]))]
    block = aggregate(stats, master, regimes, side, cap_kwh, cap_ah, a100, md5, 400 if "--dry-run" in argv else NBOOT)
    if "--out" in argv:
        json.dump(block, open(argv[argv.index("--out") + 1], "w", encoding="utf-8"), indent=1)
        print("wrote block")
        return
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    old = copy.deepcopy(A)
    A["exposureVector"] = block
    stamp(A, md5)
    chk = copy.deepcopy(A)
    chk.pop("exposureVector")
    chk["_artifactStamps"].pop("exposureVector")
    o2 = copy.deepcopy(old)
    o2.pop("exposureVector", None)
    o2["_artifactStamps"].pop("exposureVector", None)
    assert chk == o2, "unexpected change outside /exposureVector"
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    main(sys.argv[1:])
