#!/usr/bin/env python3
"""M734: cloud thermal forcing as a sensitivity of Q1, Q2, Q3 and the parked-pack model (auxiliary, report-only).
Spec: analyses/M734_spec.md Rev 2. Nothing published is changed: no payload, dashboard, seasonalFits or frozen winter file is written.
Writes analyses/M734_thermal_forcing.json, M734_ambient_drives.csv, M734_park_gaps.csv.
Usage: python tools/mynissan_thermal.py [--store DIR] [--out-dir analyses] [--raw-dir DIR] [--cache-dir DIR] [--nb 4000]"""
import argparse, bisect, csv, glob, hashlib, json, math, os, re, sys
from datetime import datetime
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mynissan_import as mi
import mynissan_coverage as mc

ROOT = mi.ROOT
PINNED_MD5 = "d514d6009d6d9a0a168ad4fb09b9bb98"
F_EPOCH = datetime(2026, 11, 17, 19, 1, 29, tzinfo=mc.KYIV).timestamp()
GAP35, PAD, MIN_N, MIN_COV = 35.0, 60.0, 5, 0.70
CUTOFFS = (120.0, 180.0, 300.0)
SEED, NB_DEFAULT = 42, 4000
MIN_DRIVES, MIN_DAYS = 10, 5
COOL_COL = "охолодної рідини"


# ------------------------------------------------------------------ pure cloud-series functions (known-answer tested)
def trap(samples):
    """samples [(t, v)] sorted -> (mean, covered_s, span_s, n): duration-weighted trapezoidal mean over adjacent samples at most 35 s apart."""
    area = cov = 0.0
    for (t0, v0), (t1, v1) in zip(samples, samples[1:]):
        dt = t1 - t0
        if 0 < dt <= GAP35:
            area += 0.5 * (v0 + v1) * dt; cov += dt
    span = samples[-1][0] - samples[0][0] if len(samples) > 1 else 0.0
    return (area / cov if cov > 0 else None), cov, span, len(samples)


def movement_start(speed, thr=0.0):
    """first time of a run of >= 3 consecutive samples (gap <= 35 s) with speed above thr; None if absent."""
    for i in range(len(speed) - 2):
        a, b, c = speed[i], speed[i + 1], speed[i + 2]
        if a[1] > thr and b[1] > thr and c[1] > thr and b[0] - a[0] <= GAP35 and c[0] - b[0] <= GAP35:
            return a[0]
    return None


def screened_mean(amb, m0, t_end, cutoff, quantum=1.0):
    """in-drive ambient after m0 + cutoff: needs >= 5 samples and >= 70 % of (t_end - (m0 + cutoff)) represented; drift flag-only."""
    if m0 is None or t_end <= m0 + cutoff:
        return None
    s = [x for x in amb if m0 + cutoff <= x[0] <= t_end + PAD]
    if len(s) < MIN_N:
        return None
    mean, cov, span, n = trap(s)
    if mean is None or cov / (t_end - (m0 + cutoff)) < MIN_COV:
        return None
    last = [v for t, v in s if t >= s[-1][0] - 60.0]
    return {"mean": mean, "n": n, "represented": cov / (t_end - (m0 + cutoff)), "drift": bool(max(last) - min(last) > max(1.0, quantum))}


def baseline_mean(amb, lo, hi):
    """handoff baseline: >= 5 samples in the window, >= 70 % of the sample span represented by adjacent samples <= 35 s apart."""
    s = [x for x in amb if lo <= x[0] <= hi]
    if len(s) < MIN_N:
        return None
    mean, cov, span, n = trap(s)
    if mean is None or span <= 0 or cov / span < MIN_COV:
        return None
    return {"mean": mean, "n": n, "represented": cov / span}


def endpoint_mean(amb, lo, hi):
    """ten-minute endpoint ambient used for gaps (T3): same rule as the baseline on the selected window."""
    return baseline_mean(amb, lo, hi)


def f3_pred(T0, A0, A1, g, tau):
    """exact solution of dT/dt = -k (T - A(t)), A(t) = A0 + b t, b = (A1 - A0)/g, k = 1/tau."""
    b = (A1 - A0) / g
    k = 1.0 / tau
    return A0 + b * g - b / k + (T0 - A0 + b / k) * np.exp(-k * g)


def f_const_pred(T0, A, g, tau):
    return A + (T0 - A) * np.exp(-g / tau)


def conformal_q(abs_resid, alpha):
    r = np.sort(np.asarray(abs_resid, float))
    n = len(r)
    k = int(math.ceil((n + 1) * (1 - alpha)))
    return float("inf") if k > n or n == 0 else float(r[k - 1])


def fit_tau(predmat, y, lo=0.2, hi=200.0):
    """L1 tau on a log grid then local refinement (as n02_seasonal_fits.l1_tau); predmat(taus) -> n x m."""
    grid = np.exp(np.linspace(np.log(lo), np.log(hi), 200))
    L = np.abs(predmat(grid) - y[:, None]).sum(0)
    i = int(np.argmin(L))
    a, b = grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)]
    fine = np.exp(np.linspace(np.log(a), np.log(b), 80))
    return float(fine[int(np.argmin(np.abs(predmat(fine) - y[:, None]).sum(0)))])


def audit_case(c):
    """closed list of alternative explanations (spec T3); each criterion is script-written. None = not assessable."""
    out = {}
    out["A1_ambient_rise_ge_2C"] = None if c.get("dA") is None else bool(c["dA"] >= 2.0)
    out["A2_first_probe_after_60s"] = bool(c.get("first_probe_lag_s", 0) > 60.0) if c.get("first_probe_lag_s") is not None else None
    out["A3_probe_spread_gt_2C"] = None if c.get("spread") is None else bool(c["spread"] > 2.0)
    out["A4_cloud_speed_in_gap"] = None if c.get("gap_speed_max") is None else bool(c["gap_speed_max"] > 0)
    out["unexplained"] = bool(all(v is False for v in out.values()))
    return out


# ------------------------------------------------------------------ helpers
def band_of(x):
    import n02_seasonal_fits as n02
    for nm, lo, hi in n02.BANDS:
        if lo <= x < hi:
            return nm
    return None


def ci(a):
    a = np.asarray([x for x in a if np.isfinite(x)], float)
    return None if len(a) == 0 else [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]


def kyiv_hour(epoch):
    d = datetime.fromtimestamp(epoch, mc.KYIV)
    return d.hour + d.minute / 60.0 + d.second / 3600.0


def raw_index(raw_dir):
    return {re.sub(r"\D", "", os.path.basename(q)): q for q in glob.glob(os.path.join(raw_dir, "*.csv"))}


def obd_coolant(path, t0_epoch):
    """OBD engine-coolant samples (epoch, value): clock time-of-day anchored to the master start time; midnight rollover handled."""
    try:
        df = pd.read_csv(path, usecols=lambda c: c == "time" or COOL_COL in c, low_memory=False)
    except Exception:
        return []
    cc = [c for c in df.columns if COOL_COL in c and "HV" not in c]
    if not cc:
        return []
    ts = pd.to_datetime(df["time"].astype(str), format="mixed", errors="coerce")
    sec = (ts.dt.hour * 3600 + ts.dt.minute * 60 + ts.dt.second + ts.dt.microsecond / 1e6).values
    if len(sec) == 0 or np.isnan(sec[0]):
        return []
    v = pd.to_numeric(df[cc[0]], errors="coerce").values
    out = []
    for s, x in zip(sec, v):
        if np.isfinite(x) and np.isfinite(s):
            out.append((t0_epoch + ((s - sec[0]) % 86400.0), float(x)))
    return out


def probe_boundary(path):
    """first/last valid reading of each pack probe T1..T4 (first/last value, and lag in s of the first reading from the first timestamp)."""
    import compute_summary_arrays as C
    import compute_drive_summary_v6 as v6
    df_raw = pd.read_csv(path, low_memory=False)
    df = df_raw.rename(columns={k: v for k, v in v6.COL_MAP.items() if k in df_raw.columns})
    tt = pd.Series(C._ft(df["time"], mixed=True)).reset_index(drop=True)
    ok = tt.notna()
    if not ok.any():
        return None
    t0 = tt[ok].min()
    firsts, lasts, lag = [], [], []
    for c in ("T1", "T2", "T3", "T4"):
        if c not in df.columns:
            continue
        x = pd.to_numeric(df[c], errors="coerce").reset_index(drop=True)
        m = x.notna() & (x >= -40) & (x <= 90) & ok
        if not m.any():
            continue
        tm = tt[m]
        firsts.append(float(x[tm.idxmin()])); lasts.append(float(x[tm.idxmax()])); lag.append((tm.min() - t0).total_seconds())
    return {"first": firsts, "last": lasts, "lag": max(lag) if lag else None}


# ------------------------------------------------------------------ T2 helpers
def make_c(d):
    """the Q1/Q2 analysis frame exactly as n02_seasonal_fits.q1_q2 builds it."""
    c = d[d.clean & (d.distance_km > 0.5) & d.ah_throughput.notna() & (d.ah_throughput > 0) & d.ambient_time_mean_c.notna() & d.pack_temp_time_mean_c.notna()].copy()
    c["cold"] = np.clip(15.0 - c.ambient_time_mean_c, 0, None)
    c["lahkm"] = np.log(c.ah_throughput / c.distance_km)
    c["ld"] = np.log(c.distance_km)
    c["ldur"] = np.log(c.duration_s / 60.0)
    return c.reset_index(drop=True)


def xy(c, kind):
    import n02_seasonal_fits as n02
    if kind == "Q1":
        return n02.design(c, ["class", "ld"], "cold"), c["lahkm"].astype(float).values
    return n02.design(c, ["class", "ldur"], "ambient_time_mean_c"), c["pack_temp_time_mean_c"].astype(float).values


def paired(cs, kind, nb):
    """arms in cs share rows (same files, same order); one set of day draws for all arms."""
    import n02_seasonal_fits as n02
    XY = [xy(c, kind) for c in cs]
    groups, _ = n02.day_index(cs[0]["date"].values)
    est = [n02.ols_slope(X, y) for X, y in XY]
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(nb):
        ix = n02.boot_idx(groups, rng)
        try:
            draws.append([n02.ols_slope(X[ix], y[ix]) for X, y in XY])
        except Exception:
            draws.append([np.nan] * len(XY))
    D = np.array(draws)
    return est, D


def t2_variant(d, scr, nb, label):
    """arms: published (all drives, manual); matched control (screened subset, manual); screened (same drives, screened ambient)."""
    c_all = make_c(d)
    has = d.file.map(lambda f: f in scr)
    d_ctrl = d[has].copy()
    d_scr = d_ctrl.copy()
    d_scr["ambient_time_mean_c"] = d_scr.file.map(scr)
    c_ctrl, c_scr = make_c(d_ctrl), make_c(d_scr)
    keep = set(c_ctrl.file) & set(c_scr.file)
    c_ctrl = c_ctrl[c_ctrl.file.isin(keep)].reset_index(drop=True)
    c_scr = c_scr[c_scr.file.isin(keep)].reset_index(drop=True)
    assert list(c_ctrl.file) == list(c_scr.file)
    import n02_seasonal_fits as n02
    out = {"label": label, "published": {"nDrives": int(len(c_all)), "nDays": int(c_all.date.nunique())}, "subset": n02.support_block(c_ctrl) if len(c_ctrl) else None}
    if len(c_ctrl) < MIN_DRIVES or c_ctrl.date.nunique() < MIN_DAYS:
        out["status"] = "not evaluable"; return out, c_all, c_ctrl
    for kind in ("Q1", "Q2"):
        est_all = n02.ols_slope(*xy(c_all, kind))
        est, D = paired([c_ctrl, c_scr], kind, nb)
        diff = D[:, 1] - D[:, 0]
        ctrl_ci, scr_ci, diff_ci = ci(D[:, 0]), ci(D[:, 1]), ci(diff)
        out[kind] = {"published_all_drives_estimate": round(float(est_all), 5), "matched_control": {"estimate": round(float(est[0]), 5), "ci95": ctrl_ci},
                     "screened": {"estimate": round(float(est[1]), 5), "ci95": scr_ci},
                     "ambient_effect_screened_minus_control": {"estimate": round(float(est[1] - est[0]), 5), "ci95_paired": diff_ci},
                     "subset_effect_control_minus_published": round(float(est[0] - est_all), 5),
                     "ambient_effect_interval_excludes_zero": bool(diff_ci is not None and (diff_ci[0] > 0 or diff_ci[1] < 0)),
                     "screened_outside_control_interval": bool(ctrl_ci is not None and not (ctrl_ci[0] <= est[1] <= ctrl_ci[1]))}
    out["status"] = "evaluated"
    return out, c_all, c_ctrl


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store()); ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--cache-dir", default=os.path.join(ROOT, "seasonal_fits_cache"))
    ap.add_argument("--gaps", default=os.path.join(ROOT, "analyses", "M729_cloud_gaps.csv"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")):
        print("mynissan_thermal: no cloud store, skipped (optional)"); return 0
    sys.stdout.reconfigure(encoding="utf-8")
    import n02_seasonal_fits as n02
    n02.CACHE_DIR = a.cache_dir
    master_md5 = mc.md5(a.master)
    frozen = [os.path.join(ROOT, "analyses", "M717_winter_predictions.json")]
    frozen_before = {p: mc.md5(p) for p in frozen if os.path.exists(p)}
    res = {"milestone": "M734", "spec": "analyses/M734_spec.md Rev 2", "role": "auxiliary", "masterMd5": master_md5, "pinnedMd5": PINNED_MD5, "gates": {}}
    res["gates"]["R3_master_pinned"] = bool(master_md5 == PINNED_MD5)
    log = json.load(open(os.path.join(ROOT, "analyses", "M717_winter_exposure_log.json"), encoding="utf-8"))["records"][-1]
    h0 = sum((log.get(k) or {}).get("hours", {}).get("below0", 0.0) for k in ("frozenBasis", "postBasisPreFreeze", "scoringSet"))
    res["E1_stop_check"] = {"hours_below_0C_in_exposure_log": h0, "stop": bool(h0 > 0), "note": "M726 event E1 needs >= 10 grid samples below 0 C with a passing GateA2 check; any sub-zero hour stops the tool for a re-spec"}
    if h0 > 0 or master_md5 != PINNED_MD5:
        res["gates"]["stopped"] = True
        os.makedirs(a.out_dir, exist_ok=True)
        json.dump(res, open(os.path.join(a.out_dir, "M734_thermal_forcing.json"), "w", encoding="utf-8"), indent=1)
        print("mynissan_thermal: stop rule or pinned-master gate failed", res["gates"], res["E1_stop_check"]); return 1
    master = mc.load_master(a.master)
    win = {m["file"]: m for m in master}
    veh = mi.load_stream(a.store, "Vehicle_Information")
    trip = mi.load_stream(a.store, "Trip_Information")
    amb = [(t, mc.fnum(x["ExternalTempDisplayValue"])) for t, x in veh if x["ExternalTempDisplayValue"] != ""]
    amb = [(t, v) for t, v in amb if v is not None]
    cool = [(t, mc.fnum(x["EngineCoolantTemp"])) for t, x in veh if x["EngineCoolantTemp"] != ""]
    spd = [(t, mc.fnum(x["SpeedDisplayedValueinkmh"])) for t, x in trip if x["SpeedDisplayedValueinkmh"] != ""]
    spd = [(t, v) for t, v in spd if v is not None]
    at, st = [t for t, _ in amb], [t for t, _ in spd]
    vals = sorted({v for _, v in amb})
    quantum = min([b - a_ for a_, b in zip(vals, vals[1:])] or [1.0])
    res["resolution"] = {"ambient_quantum_C": quantum, "ambient_samples": len(amb), "ambient_min_max": [min(vals), max(vals)], "median_ambient_interval_s": float(np.median(np.diff(at))),
                         "median_speed_interval_s": float(np.median(np.diff(st))), "speed_samples": len(spd)}

    def win_of(series_t, series, lo, hi):
        i, j = bisect.bisect_left(series_t, lo), bisect.bisect_right(series_t, hi)
        return series[i:j]

    # ---- per-drive cloud ambient (T1)
    d = n02.load_drives(n02.corpus_endpoints(a.raw_dir, sorted(pd.read_csv(a.master, usecols=["file"])["file"])))
    byf = d.set_index("file")
    rows, scr = [], {c: {} for c in ("cut120", "cut180", "cut300", "cut180_speed5", "cut180_driftfree")}
    m0s = {}
    for f, m in win.items():
        lo, hi = m["t0"] - PAD, m["t1"] + PAD
        sa, aa = win_of(st, spd, lo, hi), win_of(at, amb, lo, hi)
        m0, m0_5 = movement_start(sa, 0.0), movement_start(sa, 5.0)
        m0s[f] = m0
        manual = float(byf.loc[f, "ambient_time_mean_c"]) if f in byf.index and pd.notna(byf.loc[f, "ambient_time_mean_c"]) else None
        base = baseline_mean(aa, lo, hi)
        r = {"file": f, "date": m["date"], "group": "post_F" if m["t0"] > F_EPOCH + 3600 else ("excluded_near_F" if abs(m["t0"] - F_EPOCH) <= 3600 else "primary"),
             "manual_c": manual, "baseline_c": None if base is None else round(base["mean"], 3), "m0_found": m0 is not None}
        for cut in CUTOFFS:
            s = screened_mean(aa, m0, m["t1"], cut, quantum)
            r["screened%d_c" % cut] = None if s is None else round(s["mean"], 3)
            if cut == 180.0:
                r["drift_flag"] = None if s is None else int(s["drift"]); r["represented_180"] = None if s is None else round(s["represented"], 3)
                if s is not None and r["group"] == "primary":
                    scr["cut180"][f] = s["mean"]
                    if not s["drift"]:
                        scr["cut180_driftfree"][f] = s["mean"]
            elif s is not None and r["group"] == "primary":
                scr["cut%d" % cut][f] = s["mean"]
        s5 = screened_mean(aa, m0_5, m["t1"], 180.0, quantum)
        r["screened180_speed5_c"] = None if s5 is None else round(s5["mean"], 3)
        if s5 is not None and r["group"] == "primary":
            scr["cut180_speed5"][f] = s5["mean"]
        rows.append(r)
    R = pd.DataFrame(rows)
    pr = R[R.group == "primary"]
    t1 = {"definition": "screened (180 s after sustained movement) minus manual ambient", "n_primary_drives": int(len(pr)), "n_post_F_drives": int((R.group == "post_F").sum()),
          "coverage": {"with_m0": int(pr.m0_found.sum()), **{"screened%d" % c: int(pr["screened%d_c" % c].notna().sum()) for c in CUTOFFS}, "screened180_speed5": int(pr.screened180_speed5_c.notna().sum()),
                       "drift_flagged": int((pr.drift_flag == 1).sum()), "with_manual": int(pr.manual_c.notna().sum())}}
    both = pr.dropna(subset=["manual_c", "screened180_c"]).copy() if "screened180_c" in pr else pr.iloc[0:0]
    both["diff"] = both.screened180_c - both.manual_c
    if len(both) >= MIN_DRIVES:
        groups, _ = n02.day_index(both["date"].values)
        rng = np.random.default_rng(SEED)
        meds = [np.median(both["diff"].values[n02.boot_idx(groups, rng)]) for _ in range(a.nb)]
        t1["screened_minus_manual"] = {"n_drives": int(len(both)), "n_days": int(both.date.nunique()), "median": float(both["diff"].median()), "ci95_day_bootstrap": ci(meds),
                                       "median_abs": float(both["diff"].abs().median()), "p90_abs": float(both["diff"].abs().quantile(0.9)), "share_abs_gt_3C": float((both["diff"].abs() > 3).mean())}
        both["band"] = both.manual_c.map(band_of); both["band_scr"] = both.screened180_c.map(band_of)
        t1["cohort_switches"] = {"n": int((both.band != both.band_scr).sum()), "files": both[both.band != both.band_scr].file.tolist()}
        t1["by_band"] = {nm: ({"n_drives": int(len(g)), "n_days": int(g.date.nunique()), "median_diff": float(g["diff"].median()),
                               "status": "not evaluable" if (len(g) < MIN_DRIVES or g.date.nunique() < MIN_DAYS) else "supported"}) for nm, g in both.groupby("band")}
        t1["by_month"] = {m_: {"n_drives": int(len(g)), "median_diff": float(g["diff"].median())} for m_, g in both.groupby(both.date.str[:7])}
    bb = pr.dropna(subset=["manual_c", "baseline_c"])
    if len(bb):
        e = (bb.baseline_c - bb.manual_c)
        t1["baseline_vs_manual"] = {"n_drives": int(len(bb)), "median_abs": float(e.abs().median()), "p90_abs": float(e.abs().quantile(0.9)), "n_abs_gt_3C": int((e.abs() > 3).sum()),
                                    "R1_note": "handoff targets (565 logs, median 0.28 C, P90 2.23 C) are unverified known-answer targets; the 565-log subset cannot be identified here, so R1 for T1 is not testable; live-set values are shown for comparison only"}
    res["T1_ambient"] = t1
    res["gates"]["R1_T1"] = "not testable (565-log subset not identifiable); live values reported"

    # ---- T2
    t2 = {}
    pri_files = set(pr.file)
    dP = d[d.file.isin(pri_files)].copy()
    import json as _j
    pub = _j.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["seasonalFits"]
    c_pub = make_c(dP)
    r2 = {k: round(float(n02.ols_slope(*xy(c_pub, k))), 5) for k in ("Q1", "Q2")}
    res["gates"]["R2_reproduce_published"] = {"Q1_replicated_primary_drives": r2["Q1"], "Q2_replicated_primary_drives": r2["Q2"], "Q1_published": pub["Q1"]["primary"]["estimate"], "Q2_published": pub["Q2"]["primary"]["estimate"]}
    c_full = make_c(d)
    ok2 = abs(round(float(n02.ols_slope(*xy(c_full, "Q1"))), 5) - pub["Q1"]["primary"]["estimate"]) <= 1e-5 and abs(round(float(n02.ols_slope(*xy(c_full, "Q2"))), 5) - pub["Q2"]["primary"]["estimate"]) <= 1e-5
    res["gates"]["R2_all_717_match_1e-5"] = bool(ok2)
    for lab, key in (("primary_180s", "cut180"), ("cutoff_120s", "cut120"), ("cutoff_300s", "cut300"), ("speed_gt_5_start", "cut180_speed5"), ("drift_free_only", "cut180_driftfree")):
        out, c_all, c_ctrl = t2_variant(dP, scr[key], a.nb, lab)
        if lab == "primary_180s" and len(c_ctrl):
            out["screened_subset_vs_published_set"] = {"median_distance_km": [float(c_ctrl.distance_km.median()), float(c_all.distance_km.median())], "median_duration_min": [float(c_ctrl.duration_s.median() / 60), float(c_all.duration_s.median() / 60)],
                                                       "class_share": {k: [float((c_ctrl.dclass == k).mean()), float((c_all.dclass == k).mean())] for k in sorted(c_all.dclass.unique())},
                                                       "note": "pairs are [screened subset, published set]"}
            out["escalate_to_Director"] = bool(out.get("status") == "evaluated" and any(out[k]["ambient_effect_interval_excludes_zero"] or out[k]["screened_outside_control_interval"] for k in ("Q1", "Q2")))
        t2[lab] = out
    t2["kept_unchanged"] = "ambient_start_c and ambient_end_c (Q2 start-on-start, Q3) keep their published values in T2; the cloud endpoint ambient enters only in T3"
    t2["reading"] = "associations by thermal class; a Q2 slope change is an errors-in-variables sensitivity, never a correction; verdict only on primary_180s"
    res["T2_Q1_Q2"] = t2

    # ---- T3
    gcls = {(r["prev"], r["next"]): r["class"] for r in csv.DictReader(open(a.gaps, encoding="utf-8"))} if os.path.exists(a.gaps) else {}
    dd = d.reset_index(drop=True)
    prev = dd.shift(1)
    ok = dd.clean & prev.clean.fillna(False).astype(bool) & (dd.gap_h >= n02.GAP_LO_H) & (dd.gap_h <= n02.GAP_HI_H)
    P = pd.DataFrame({"prev": prev.file, "next": dd.file, "date": dd["date"], "gap_h": dd.gap_h, "T0": prev.tLast, "T1": dd.tFirst, "ambPrevEnd": prev.ambient_end_c, "ambNextStart": dd.ambient_start_c,
                      "prevT0": prev.t0, "prevDur": prev.duration_s})[ok].reset_index(drop=True)
    P["A_man"] = (P.ambPrevEnd + P.ambNextStart) / 2.0
    P["cls"] = [gcls.get((a_, b_), "") for a_, b_ in zip(P.prev, P.next)]
    # cloud endpoint ambient
    def endpoints(f):
        m = win[f]; m0 = m0s.get(f)
        if m0 is None:
            return None, None
        aa = win_of(at, amb, m["t0"] - PAD, m["t1"] + PAD)
        s = endpoint_mean(aa, max(m0 + 180.0, m["t1"] + PAD - 600.0), m["t1"] + PAD)
        e = endpoint_mean(aa, m0 + 180.0, min(m0 + 180.0 + 600.0, m["t1"] + PAD))
        return (None if s is None else s["mean"]), (None if e is None else e["mean"])
    cache = {}
    for f in set(P.prev) | set(P.next):
        cache[f] = endpoints(f) if f in win else (None, None)
    P["A0c"] = P.prev.map(lambda f: cache[f][0]); P["A1c"] = P.next.map(lambda f: cache[f][1])
    primary_set = set(pr.file)
    P["primary"] = P.prev.isin(primary_set) & P.next.isin(primary_set)
    base = P.dropna(subset=["T0", "T1", "A_man"])
    base = base[base.primary]
    G = base.dropna(subset=["A0c", "A1c"])
    G = G[G.cls == "stationary_consistent"].reset_index(drop=True)
    t3 = {"n_pairs_eligible": int(len(P)), "n_primary_with_probe_endpoints_and_manual_ambient": int(len(base)), "n_cloud_stationary_subset": int(len(G)), "n_days": int(G.date.nunique()) if len(G) else 0,
          "note": "next-start ambient is observed together with the pack outcome: a consistency comparison, not a forecast; screened endpoints use samples after M0+180 s only"}
    if len(G) >= 20 and G.date.nunique() >= MIN_DAYS:
        G["Ac"] = (G.A0c + G.A1c) / 2.0
        G["Am"] = G.A_man
        # diurnal parameters for F4 from the screened cloud endpoints (no outcome used)
        drv = []
        for f, (s0, e0) in cache.items():
            if f in win and s0 is not None and e0 is not None and f in byf.index:
                dt0 = win[f]["t0"]
                drv.append({"day": win[f]["date"], "month": int(win[f]["date"][5:7]), "h0": kyiv_hour(dt0), "h1": kyiv_hour(dt0) + (win[f]["t1"] - dt0) / 3600.0, "A0": e0, "A1": s0})
        drv = pd.DataFrame(drv)
        import park_model as PM
        par = {}
        for seas, g in drv.groupby(np.where(drv.month <= 8, "summer", "autumn")):
            par[seas] = PM._fit_diurnal(g)
        W = PM.W
        G["month"] = G.date.str[5:7].astype(int)
        G["season"] = np.where(G.month <= 8, "summer", "autumn")
        G["amp"] = G.season.map(lambda s: par.get(s, par.get("autumn", (0, 0)))[0]); G["hpk"] = G.season.map(lambda s: par.get(s, par.get("autumn", (0, 0)))[1])
        G["clock0"] = [((pd.Timestamp(pt).hour + pd.Timestamp(pt).minute / 60 + pd.Timestamp(pt).second / 3600) + du / 3600.0) % 24 for pt, du in zip(G.prevT0, G.prevDur)]
        G["Abar_e"] = G.A0c - G.amp * np.cos(W * (G.clock0 - G.hpk))
        G["Abar_s"] = G.A1c - G.amp * np.cos(W * ((G.clock0 + G.gap_h) % 24 - G.hpk))
        G["slope"] = (G.Abar_s - G.Abar_e) / G.gap_h.clip(lower=1e-3)
        T0, T1v, g = G.T0.values, G.T1.values, G.gap_h.values
        days = np.array(sorted(G.date.unique()))
        blocks = np.array_split(days, min(n02.FOLDS, len(days)))
        names = ["F0_manual_const", "F2_cloud_const", "F3_cloud_linear", "F4_cloud_diurnal", "persistence", "full_relaxation"]
        err = {k: np.full(len(G), np.nan) for k in names}
        q80, q90 = {k: np.full(len(G), np.nan) for k in names}, {k: np.full(len(G), np.nan) for k in names}
        taus = {k: [] for k in names[:4]}
        from scipy.optimize import least_squares
        for blk in blocks:
            te = G.date.isin(blk).values; tr = ~te
            if tr.sum() < 20 or te.sum() == 0:
                continue
            fits = {}
            fits["F0_manual_const"] = fit_tau(lambda tt, ix=tr: f_const_pred(T0[ix][:, None], G.Am.values[ix][:, None], g[ix][:, None], tt[None, :]), T1v[tr])
            fits["F2_cloud_const"] = fit_tau(lambda tt, ix=tr: f_const_pred(T0[ix][:, None], G.Ac.values[ix][:, None], g[ix][:, None], tt[None, :]), T1v[tr])
            fits["F3_cloud_linear"] = fit_tau(lambda tt, ix=tr: f3_pred(T0[ix][:, None], G.A0c.values[ix][:, None], G.A1c.values[ix][:, None], g[ix][:, None], tt[None, :]), T1v[tr])
            f4 = lambda th, ix: PM.park_T(T0[ix], g[ix], G.clock0.values[ix], G.Abar_e.values[ix], G.slope.values[ix], G.amp.values[ix], G.hpk.values[ix], th[0], th[1])
            th = least_squares(lambda t_: f4(t_, tr) - T1v[tr], PM.X0, bounds=(PM.LO, PM.HI)).x
            fits["F4_cloud_diurnal"] = (th[0], th[1])
            def predict(k, ix):
                if k == "F0_manual_const": return f_const_pred(T0[ix], G.Am.values[ix], g[ix], fits[k])
                if k == "F2_cloud_const": return f_const_pred(T0[ix], G.Ac.values[ix], g[ix], fits[k])
                if k == "F3_cloud_linear": return f3_pred(T0[ix], G.A0c.values[ix], G.A1c.values[ix], g[ix], fits[k])
                if k == "F4_cloud_diurnal": return f4(fits[k], ix)
                if k == "persistence": return T0[ix]
                return G.Ac.values[ix]
            for k in names:
                if k in taus: taus[k].append(float(fits[k] if k != "F4_cloud_diurnal" else fits[k][0]))
                e_te = np.abs(predict(k, te) - T1v[te]); e_tr = np.abs(predict(k, tr) - T1v[tr])
                err[k][te] = e_te
                q80[k][te] = conformal_q(e_tr, 0.2); q90[k][te] = conformal_q(e_tr, 0.1)
        sc = ~np.isnan(err["F0_manual_const"])
        groups, _ = n02.day_index(G.date.values[sc])
        rng = np.random.default_rng(SEED)
        draws = [n02.boot_idx(groups, rng) for _ in range(a.nb)]
        summ = {}
        for k in names:
            e = err[k][sc]
            summ[k] = {"mae": float(e.mean()), "median_abs_error": float(np.median(e)), "p90_abs_error": float(np.percentile(e, 90)), "n_gaps": int(sc.sum()), "n_days": int(len(groups)),
                       "tau_per_fold_h": [round(x, 3) for x in taus.get(k, [])]}
        contrasts = {}
        for k in ("F2_cloud_const", "F3_cloud_linear", "F4_cloud_diurnal", "persistence", "full_relaxation"):
            diff = err[k][sc] - err["F0_manual_const"][sc]
            bs = [diff[ix].mean() for ix in draws]
            contrasts[k + "_minus_F0"] = {"mean_abs_error_difference": float(diff.mean()), "ci95_day_bootstrap": ci(bs), "interval_excludes_zero": bool(ci(bs)[0] > 0 or ci(bs)[1] < 0),
                                          "verdict": ("difference supported" if (ci(bs)[0] > 0 or ci(bs)[1] < 0) else "not established") if k == "F2_cloud_const" else "descriptive"}
        cal = {}
        bands = G.Ac.map(band_of).values
        terc = pd.qcut(G.gap_h, 3, labels=["short", "mid", "long"]).values
        for k in ("F0_manual_const", "F2_cloud_const"):
            cal[k] = {}
            for nm, mask in [("all", np.ones(len(G), bool))] + [(b, bands == b) for b in sorted(set(bands))] + [("gap_" + t, terc == t) for t in ("short", "mid", "long")]:
                m = mask & sc
                nd = G.date.values[m]
                if m.sum() < MIN_DRIVES or len(set(nd)) < MIN_DAYS:
                    cal[k][nm] = {"n_gaps": int(m.sum()), "status": "not evaluable"}; continue
                gg, _ = n02.day_index(nd)
                hit80, hit90 = (err[k][m] <= q80[k][m]).astype(float), (err[k][m] <= q90[k][m]).astype(float)
                rr = np.random.default_rng(SEED)
                b80 = [hit80[n02.boot_idx(gg, rr)].mean() for _ in range(a.nb)]
                rr = np.random.default_rng(SEED)
                b90 = [hit90[n02.boot_idx(gg, rr)].mean() for _ in range(a.nb)]
                eff = n02.support(nd, np.ones(len(nd)))[1]
                cal[k][nm] = {"n_gaps": int(m.sum()), "n_days": int(len(set(nd))), "coverage80": float(hit80.mean()), "ci80": ci(b80), "coverage90": float(hit90.mean()), "ci90": ci(b90),
                              "status": "exploratory (essDays < 10)" if eff < 10 else "supported"}
        mb = {}
        tr = (G.month <= 8).values; te = (G.month >= 9).values
        if tr.sum() >= 20 and te.sum() >= MIN_DRIVES:
            tF0 = fit_tau(lambda tt: f_const_pred(T0[tr][:, None], G.Am.values[tr][:, None], g[tr][:, None], tt[None, :]), T1v[tr])
            tF2 = fit_tau(lambda tt: f_const_pred(T0[tr][:, None], G.Ac.values[tr][:, None], g[tr][:, None], tt[None, :]), T1v[tr])
            mb = {"train_gaps": int(tr.sum()), "test_gaps": int(te.sum()), "test_days": int(G.date[te].nunique()),
                  "mae_F0": float(np.abs(f_const_pred(T0[te], G.Am.values[te], g[te], tF0) - T1v[te]).mean()), "mae_F2": float(np.abs(f_const_pred(T0[te], G.Ac.values[te], g[te], tF2) - T1v[te]).mean()),
                  "tau_F0_h": tF0, "tau_F2_h": tF2, "note": "transfer check that mixes season with the hold-out; not a clean hold-out"}
        t3.update({"folds": len(blocks), "models": summ, "contrasts": contrasts, "split_conformal_coverage": cal, "month_blocked_secondary": mb,
                   "published_tau_in_sample_h": pub["Q3"]["primary"]["tauH"], "diurnal_params_cloud": {k: {"amp": v[0], "hpk": v[1]} for k, v in par.items()},
                   "F3_closed_form": "T(g) = A0 + b g - b/k + (T0 - A0 + b/k) exp(-k g), b = (A1 - A0)/g, k = 1/tau"})
        G["fold_err_F0"] = err["F0_manual_const"]; G["fold_err_F2"] = err["F2_cloud_const"]; G["fold_err_F3"] = err["F3_cloud_linear"]; G["fold_err_F4"] = err["F4_cloud_diurnal"]
        os.makedirs(a.out_dir, exist_ok=True)
        G[["prev", "next", "date", "gap_h", "T0", "T1", "Am", "A0c", "A1c", "Ac", "cls", "fold_err_F0", "fold_err_F2", "fold_err_F3", "fold_err_F4"]].round(4).to_csv(os.path.join(a.out_dir, "M734_park_gaps.csv"), index=False, lineterminator="\n")
    else:
        t3["status"] = "not evaluable"
    # F1 control on the full base with the published fold construction (reference)
    if len(base) >= 20:
        bs_ = base.copy(); bs_["amb"] = bs_.A_man
        e0, e1, gp = (bs_.T0 - bs_.amb).values, (bs_.T1 - bs_.amb).values, bs_.gap_h.values
        dys = np.array(sorted(bs_.date.unique())); bl = np.array_split(dys, min(n02.FOLDS, len(dys)))
        pred = np.full(len(bs_), np.nan)
        for blk in bl:
            te = bs_.date.isin(blk).values
            if (~te).sum() < 20 or te.sum() == 0: continue
            tk = n02.l1_tau(e0[~te], e1[~te], gp[~te]); pred[te] = e0[te] * np.exp(-gp[te] / tk)
        s_ = ~np.isnan(pred)
        t3["F0_manual_full_primary_base"] = {"n_gaps": int(s_.sum()), "median_abs_error_C": float(np.median(np.abs(pred - e1)[s_])), "mae_C": float(np.abs(pred - e1)[s_].mean()),
                                              "R1_note": "handoff 223-gap rule (stationary-consistent, 0.5-36 h, four probes, both ambients) is not identifiable from the live data, so R1 for T3 is not testable; this is the live primary-base reference"}
    res["gates"]["R1_T3"] = "not testable (223-gap subset not identifiable); live reference reported"
    # warm-rise audit
    idx = raw_index(a.raw_dir)
    cand = P[(P.primary) & P.T0.notna() & P.T1.notna() & (P.gap_h >= 2 / 60.0) & (P.gap_h <= 6.0) & (P.cls == "stationary_consistent") & ((P.T1 - P.T0) > 1.0)]
    audit = []
    for _, r in cand.iterrows():
        c = {"dA": None if (r.A0c is None or r.A1c is None or pd.isna(r.A0c) or pd.isna(r.A1c)) else float(r.A1c - r.A0c)}
        for tag, f in (("prev", r.prev), ("next", r.next)):
            p_ = idx.get(re.sub(r"\D", "", f))
            b = probe_boundary(p_) if p_ else None
            if b:
                if tag == "prev": c["spread"] = (max(b["last"]) - min(b["last"])) if b["last"] else None
                else:
                    c["first_probe_lag_s"] = b["lag"]
                    c["spread"] = max(c.get("spread") or 0.0, (max(b["first"]) - min(b["first"])) if b["first"] else 0.0)
        ge = win_of(st, spd, win[r.prev]["t1"], win[r.next]["t0"]) if r.prev in win and r.next in win else []
        c["gap_speed_max"] = max([v for _, v in ge], default=None) if ge is not None and len(ge) else None
        audit.append({"prev": r.prev, "next": r.next, "date": r.date, "gap_h": round(float(r.gap_h), 3), "rise_C": round(float(r.T1 - r.T0), 2), **audit_case(c), "inputs": {k: (None if v is None else round(float(v), 2)) for k, v in c.items()}})
    nun = [x for x in audit if x["unexplained"]]
    t3["warm_rise_audit"] = {"n_cases": len(audit), "cases": audit, "n_unexplained": len(nun), "n_unexplained_days": len({x["date"] for x in nun}),
                             "second_state_milestone_triggered": bool(len(nun) >= 5 and len({x["date"] for x in nun}) >= 3),
                             "note": "A2 is false by construction when the endpoint extractor accepted the first reading (within 60 s); A4 is None when no cloud speed sample lies in the gap; None counts as not-explained-by that criterion"}
    res["T3_parked_forcing"] = t3

    # ---- T4 coolant
    cl_t = [t for t, _ in cool]
    idxr = raw_index(a.raw_dir)
    pairs = []
    for f, m in win.items():
        snaps = [(t, v) for t, v in win_of(cl_t, cool, m["t1"] - 30.0, m["t1"] + 60.0) if v is not None]
        if not snaps:
            continue
        tc, vc = snaps[-1]
        pth = idxr.get(re.sub(r"\D", "", f))
        obd = obd_coolant(pth, m["t0"]) if pth else []
        ot = [t for t, _ in obd]
        j = bisect.bisect_left(ot, tc)
        cand_ = [k for k in (j - 1, j) if 0 <= k < len(obd) and abs(ot[k] - tc) <= 15.0]
        if cand_:
            k = min(cand_, key=lambda k: abs(ot[k] - tc))
            pairs.append({"file": f, "date": m["date"], "age_s": tc - m["t1"], "res": vc - obd[k][1], "phase": "inside_log" if tc <= m["t1"] else "after_log_end"})
    PD = pd.DataFrame(pairs)
    t4 = {"drives_with_end_snapshot": int(sum(1 for f, m in win.items() if win_of(cl_t, cool, m["t1"] - 30.0, m["t1"] + 60.0))), "paired_within_15s": int(len(PD)),
          "note": "residual = cloud minus OBD engine coolant; no coolant model fitted"}
    for ph, g_ in (PD.groupby("phase") if len(PD) else []):
        t4[ph] = {"n": int(len(g_)), "n_days": int(g_.date.nunique()), "median": float(g_.res.median()), "p90_abs": float(g_.res.abs().quantile(0.9)), "median_age_s": float(g_.age_s.median())}
    res["T4_coolant"] = t4

    # ---- gates and outputs
    frozen_after = {p: mc.md5(p) for p in frozen if os.path.exists(p)}
    res["gates"]["R3_frozen_unchanged"] = bool(frozen_before == frozen_after)
    res["gates"]["R3_master_unchanged"] = bool(mc.md5(a.master) == master_md5)
    os.makedirs(a.out_dir, exist_ok=True)
    R.to_csv(os.path.join(a.out_dir, "M734_ambient_drives.csv"), index=False, lineterminator="\n")
    json.dump(res, open(os.path.join(a.out_dir, "M734_thermal_forcing.json"), "w", encoding="utf-8"), indent=1, default=float)
    print(json.dumps({k: res[k] for k in ("gates", "resolution", "E1_stop_check")}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
