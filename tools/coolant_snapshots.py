#!/usr/bin/env python3
"""M754 (spec analyses/M754_spec.md Rev 2): engine-coolant snapshots of the cloud export. REPORT-ONLY; ENGINE coolant only (the cloud has no pack-temperature channel).

K1 key-off cross-check of the cloud snapshot against the OBD coolant at the end of logged drives; K2 cloud-reported engine coolant shortly after the estimated end of unlogged trips (descriptive; different driver);
K3 engine cooling with three anchors: S_obd (previous logged drive, OBD last coolant sample), S_cloud (same gaps, cloud snapshot near the drive end) and D_cloud (gaps with estimated unlogged movement, cloud snapshot near
the end of the unlogged trip); K4 coverage and selection. A difference between the unlogged-anchored and the logged-anchored sets is NOT an 'unlogged effect' (spec 9.1). Values are cloud-reported, estimated; never measured.
Usage: python tools/coolant_snapshots.py [--store DIR] [--raw-dir DIR] [--out-dir analyses] [--nb 4000]   (no cloud store -> skipped, exit 0)"""
import argparse, bisect, csv, hashlib, json, os, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_import as mi
import mynissan_coverage as mc
import mynissan_thermal as th
import mynissan_unlogged as u

REGISTERED_MASTER = "d514d6009d6d9a0a168ad4fb09b9bb98"
GAPS_PIN = "d1d3f8e9da732e7c58212c3bcf5718e05304a186df4f45e567d8799c704d159f"
SEED, NB_DEFAULT = 42, 4000
WIN_LO_S, WIN_HI_S, WIN_HI_WIDE_S = 120.0, 120.0, 600.0
PARK_MIN_H, PARK_MAX_H, PARK_MAX_WIDE_H = 0.25, 6.0, 24.0
EA_MIN, EB_MIN, EB_MIN_WIDE = 10.0, 1.0, 3.0
N_MIN, DAYS_MIN = 20, 10
K_BAND = (0.80, 1.25)
K1_MED_ABS, K1_P90_ABS, K1_MED_CI = 2.0, 5.0, 1.0
D_CLASSES = ("driving_observed", "odometer_increase_only")
KYIV_CHECK = {"2026-07-15": 10800.0, "2026-11-15": 7200.0}


class Stop(Exception):
    pass


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


# ---------------------------------------------------------------------------- snapshots
def ambient_mean(entry):
    """Manual ambient of a drive from an ambientByDrive entry. Rev 2.1 (spec 10): a list [start, interim..., end] gives its mean (as in the heat-soak block); a plain number (66 drives of 11-22 September 2026 store the
    ambient this way) is a valid single reading and is used as it is; the published heat-soak code skips such entries silently (disclosed, not copied). None when nothing numeric is available."""
    try:
        if isinstance(entry, (list, tuple)):
            vals = [float(x) for x in entry]
            return sum(vals) / len(vals) if vals else None
        return float(entry)
    except (TypeError, ValueError):
        return None


def snapshot_near(ts, vs, t, lo=WIN_LO_S, hi=WIN_HI_S):
    """Cloud coolant row nearest to t inside [t - lo, t + hi]; returns (value, time, age_s = row time - t) or None."""
    i0, i1 = int(np.searchsorted(ts, t - lo, side="left")), int(np.searchsorted(ts, t + hi, side="right"))
    if i1 <= i0:
        return None
    j = i0 + int(np.argmin(np.abs(ts[i0:i1] - t)))
    return float(vs[j]), float(ts[j]), float(ts[j] - t)


def obd_ends(samples):
    """OBD coolant samples [(t, value)] -> (first value, first time, last value, last time) or None."""
    if not samples:
        return None
    return float(samples[0][1]), float(samples[0][0]), float(samples[-1][1]), float(samples[-1][0])


# ---------------------------------------------------------------------------- statistics
def cluster_stats(vals, days, nb, seed=SEED):
    """Day-clustered percentile bootstrap of the median, the mean, the median |value| and the 90th percentile |value|."""
    vals = np.asarray(vals, float)
    codes, uniq = pd.factorize(np.asarray(days))
    groups = [np.where(codes == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    draws = {"median": [], "mean": [], "medianAbs": [], "p90Abs": []}
    for _ in range(nb):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        v = vals[idx]
        draws["median"].append(np.median(v))
        draws["mean"].append(v.mean())
        draws["medianAbs"].append(np.median(np.abs(v)))
        draws["p90Abs"].append(np.percentile(np.abs(v), 90))
    pt = {"median": float(np.median(vals)), "mean": float(vals.mean()), "medianAbs": float(np.median(np.abs(vals))), "p90Abs": float(np.percentile(np.abs(vals), 90))}
    return {k: {"est": round(pt[k], 3), "ci95": [round(float(np.percentile(draws[k], 2.5)), 3), round(float(np.percentile(draws[k], 97.5)), 3)]} for k in draws}


def summarise(values, days, nb):
    n, nd = int(len(values)), int(len(set(days)))
    if n < N_MIN or nd < DAYS_MIN:
        return {"nDrives": n, "nDays": nd, "status": "not estimable at this support (counts only)"}
    return {"nDrives": n, "nDays": nd, **cluster_stats(values, days, nb)}


def k1_wording(s):
    """Spec 4 and 9.6: consistent at key-off, else a stated offset."""
    if "median" not in s:
        return "not estimable at this support"
    lo, hi = s["median"]["ci95"]
    if s["medianAbs"]["est"] <= K1_MED_ABS and s["p90Abs"]["est"] <= K1_P90_ABS and lo >= -K1_MED_CI and hi <= K1_MED_CI:
        return "consistent at key-off (median |d| <= 2 C, 90th percentile <= 5 C, median within +-1 C)"
    return "offset of %.1f C [%.1f, %.1f] (median |d| %.1f C, 90th percentile %.1f C); mean %.2f C" % (s["median"]["est"], lo, hi, s["medianAbs"]["est"], s["p90Abs"]["est"], s["mean"]["est"])


def age_slope(d, age_s, days):
    """OLS slope of the difference on the snapshot age (C per minute) with a day-clustered robust standard error."""
    y, x = np.asarray(d, float), np.asarray(age_s, float) / 60.0
    if len(y) < 10 or np.ptp(x) == 0:
        return None
    X = np.column_stack([np.ones(len(y)), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    res = y - X @ beta
    codes, uniq = pd.factorize(np.asarray(days))
    G, n = len(uniq), len(y)
    XtXi = np.linalg.pinv(X.T @ X)
    meat = np.zeros((2, 2))
    for g in range(G):
        s_ = X[codes == g].T @ res[codes == g]
        meat += np.outer(s_, s_)
    V = XtXi @ meat @ XtXi * (G / max(G - 1, 1)) * ((n - 1) / max(n - 2, 1))
    se = float(np.sqrt(V[1, 1]))
    return {"slopeCPerMin": round(float(beta[1]), 4), "ci95": [round(float(beta[1] - 1.96 * se), 4), round(float(beta[1] + 1.96 * se), 4)], "nDrives": int(n), "nDays": int(G)}


# ---------------------------------------------------------------------------- cooling fits
def sen_slope(x, y):
    """Classical Theil-Sen slope (median of the pairwise slopes), the estimator of the published soak fit."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    i, j = np.triu_indices(len(x), 1)
    dx = x[j] - x[i]
    ok = dx != 0
    return float(np.median((y[j] - y[i])[ok] / dx[ok])) if ok.any() else float("nan")


def ratio_origin_slope(x, y):
    """Through-origin slope as the median of y / x (the Sen-through-origin of the registered spec text; the auditor's estimator): k = -median(y / x)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = x != 0
    return float(np.median(y[ok] / x[ok])) if ok.any() else float("nan")


def ls_origin_slope(x, y):
    """Least-squares slope through the origin (sensitivity)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    return float((x * y).sum() / (x * x).sum()) if (x * x).sum() > 0 else float("nan")


def pair_table(rows, ea_min=EA_MIN, eb_min=EB_MIN, park_max=PARK_MAX_H):
    """rows: dicts with anchorT, arrivalT, ambient, parkedH, day. Returns the filtered table with the excess values and the log ratio, plus the exclusion counts."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df, {"input": 0}
    df = df.assign(ea=df["anchorT"] - df["ambient"], eb=df["arrivalT"] - df["ambient"])
    ex = {"input": int(len(df))}
    keep = (df["parkedH"] >= PARK_MIN_H) & (df["parkedH"] <= park_max)
    ex["outsideParkedRange"] = int((~keep).sum())
    k2 = keep & (df["ea"] > ea_min)
    ex["eaNotAbove%g" % ea_min] = int((keep & ~(df["ea"] > ea_min)).sum())
    k3 = k2 & (df["eb"] > eb_min)
    ex["ebNotAbove%g" % eb_min] = int((k2 & ~(df["eb"] > eb_min)).sum())
    out = df[k3].copy()
    out["y"] = np.log(out["eb"] / out["ea"])
    ex["kept"] = int(len(out))
    return out, ex


def fit_k(tab):
    """Decay rate k (per hour) of the pooled pairs: primary the pairwise Sen slope (the published family; intercept reported as the through-origin check), sensitivity the least-squares slope through the origin."""
    n = int(len(tab))
    res = {"nPairs": n, "nDays": int(tab["day"].nunique()) if n else 0}
    if n < 8:
        res["status"] = "not estimable (fewer than 8 pairs)"
        return res
    x, y = tab["parkedH"].to_numpy(float), tab["y"].to_numpy(float)
    s = sen_slope(x, y)
    res.update({"kSen": round(-s, 5), "interceptSen": round(float(np.median(y - s * x)), 4), "kThroughOriginLS": round(-ls_origin_slope(x, y), 5), "kMedianRatioOrigin": round(-ratio_origin_slope(x, y), 5), "tauSenH": round(-1.0 / s, 2) if s < 0 else None})
    return res


def supported(tab):
    return len(tab) >= N_MIN and tab["day"].nunique() >= DAYS_MIN


def joint_boot(sets, nb, seed=SEED, est="sen"):
    """Joint day-clustered bootstrap: days are resampled from the union of the days of all sets; each set's pairs of the resampled days enter its own fit. sets: {name: table with day, parkedH, y}.
    Returns per-set k draws (k = -Sen slope) so differences are computed within the same resample (a true pair for sets that share gaps, a joint resample for disjoint sets)."""
    days = sorted(set().union(*[set(t["day"]) for t in sets.values() if len(t)]))
    by = {n: {d_: np.where(t["day"].to_numpy() == d_)[0] for d_ in days} for n, t in sets.items()}
    arr = {n: (t["parkedH"].to_numpy(float), t["y"].to_numpy(float)) for n, t in sets.items()}
    rng = np.random.default_rng(seed)
    out = {n: [] for n in sets}
    for _ in range(nb):
        pick = [days[i] for i in rng.integers(0, len(days), len(days))]
        for n in sets:
            idx = [by[n][d_] for d_ in pick if len(by[n][d_])]
            if not idx:
                out[n].append(np.nan)
                continue
            ii = np.concatenate(idx)
            slope_fn = sen_slope if est == "sen" else ratio_origin_slope
            out[n].append(-slope_fn(arr[n][0][ii], arr[n][1][ii]) if len(ii) >= 8 else np.nan)
    return {n: np.array(v) for n, v in out.items()}


def median_diff_ci(a_vals, a_days, b_vals, b_days, nb, seed=SEED):
    """Median(a) - median(b) of two independent sets with a joint day-clustered percentile bootstrap (days resampled from the union)."""
    a_vals, b_vals = np.asarray(a_vals, float), np.asarray(b_vals, float)
    a_days, b_days = np.asarray(a_days), np.asarray(b_days)
    days = sorted(set(a_days) | set(b_days))
    ia = {d_: np.where(a_days == d_)[0] for d_ in days}
    ib = {d_: np.where(b_days == d_)[0] for d_ in days}
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(nb):
        pick = [days[i] for i in rng.integers(0, len(days), len(days))]
        xa = np.concatenate([ia[d_] for d_ in pick if len(ia[d_])] or [np.array([], int)])
        xb = np.concatenate([ib[d_] for d_ in pick if len(ib[d_])] or [np.array([], int)])
        if len(xa) and len(xb):
            out.append(np.median(a_vals[xa]) - np.median(b_vals[xb]))
    est = float(np.median(a_vals) - np.median(b_vals))
    return {"difference": round(est, 2), "ci95": [round(float(np.percentile(out, 2.5)), 2), round(float(np.percentile(out, 97.5)), 2)], "nDays": len(days)}


def diff_wording(k_a, k_b, lo, hi, supported_both):
    """Spec 4 / 9.1: difference between two sets (a - b): material when the interval excludes zero and the ratio is outside the band."""
    if not supported_both or k_a is None or k_b is None or k_a == 0:
        return "not estimable at this support (counts only)"
    ratio = k_b / k_a
    excl = lo > 0 or hi < 0
    if excl and (ratio < K_BAND[0] or ratio > K_BAND[1]):
        return "material"
    return "small" if excl else "not distinguishable"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store())
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--gaps", default=os.path.join(ROOT, "analyses", "M729_cloud_gaps.csv"))
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")) or not os.path.isdir(a.raw_dir) or not os.path.exists(a.gaps):
        print("coolant_snapshots: no cloud store, raw directory or gap table, skipped (optional)")
        return 0
    t_start = time.time()
    try:
        if sha256(a.gaps) != GAPS_PIN:
            raise Stop("the M729 gap table differs from its pinned sha256")
        m0 = md5(a.master)
        if m0 != REGISTERED_MASTER:
            raise Stop("master MD5 %s differs from the registered master (a rerun on a larger corpus needs its own addendum)" % m0)
        for d_, off in KYIV_CHECK.items():
            from datetime import datetime
            got = datetime.strptime(d_ + " 12:00:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=mc.KYIV).utcoffset().total_seconds()
            if got != off:
                raise Stop("local-to-UTC conversion check failed for %s: %s" % (d_, got))
        master = mc.load_master(a.master)
        mdf = pd.read_csv(a.master, usecols=["file", "ens_outlier_v2"], low_memory=False).set_index("file")
        clean = {f: (str(v) == "False") for f, v in mdf["ens_outlier_v2"].items()}
        cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))
        amb = {}
        for fn, pair in (cfg.get("ambientByDrive") or {}).items():
            v = ambient_mean(pair)
            if v is not None:
                amb[fn] = v
        V = mi.load_stream(a.store, "Vehicle_Information")
        ct = np.array([t for t, r in V if r.get("EngineCoolantTemp", "") != ""], float)
        cv = np.array([float(r["EngineCoolantTemp"]) for t, r in V if r.get("EngineCoolantTemp", "") != ""], float)
        raw = th.raw_index(a.raw_dir)
        import re
        info = {}
        for m in master:
            p = raw.get(re.sub(r"\D", "", m["file"]))
            ends = obd_ends(th.obd_coolant(p, m["t0"])) if p else None
            info[m["file"]] = {"m": m, "obd": ends}
        # unlogged strict units (M739 definition) and accepted steps
        odo, spd, _amb = u.load_streams(a.store)
        steps = u.accepted_steps(odo, spd)
        units = u.join_units(steps)
        wins = [(m["t0"] - u.PAD, m["t1"] + u.PAD) for m in master]
        unl = []
        for x in units:
            if not u.is_strict(x):
                continue
            fr, _h = u.overlap_fraction(x[0][0], x[-1][1], wins)
            if u.classify_unit(fr) == "unlogged":
                unl.append(x)
        gaps = pd.read_csv(a.gaps)
        n_d = int(gaps["class"].isin(D_CLASSES).sum())
        if len(unl) != 331 or n_d != 98:
            raise Stop("control V0: %d unlogged strict units (registered 331) and %d D gaps (registered 98)" % (len(unl), n_d))
        res = {"milestone": "M754", "spec": "analyses/M754_spec.md Rev 2", "role": "report-only; ENGINE coolant, cloud-reported, estimated; no pack-temperature channel in the cloud",
               "masterMd5": m0, "registeredMasterMd5": REGISTERED_MASTER, "m729GapsSha256": GAPS_PIN, "storeManifestSha256": sha256(os.path.join(a.store, "manifest.json")), "seed": SEED, "nBoot": a.nb,
               "toolSha256": sha256(os.path.abspath(__file__)), "control_V0": {"unloggedStrictUnits": len(unl), "dGaps": n_d, "kyivUtcOffsetsS": KYIV_CHECK, "status": "reproduced"},
               "cloudCoolantRows": int(len(ct)), "drivesWithoutObdCoolant": int(sum(1 for v in info.values() if v["obd"] is None))}
        # ---- K1
        rows = []
        for f, v in info.items():
            if v["obd"] is None or not clean.get(f, False):
                continue
            _fv, _ft, lv, lt = v["obd"]
            sn = snapshot_near(ct, cv, v["m"]["t1"], WIN_LO_S, WIN_HI_S)
            snw = snapshot_near(ct, cv, v["m"]["t1"], WIN_LO_S, WIN_HI_WIDE_S)
            sn16 = snapshot_near(ct, cv, v["m"]["t1"] - 16.0, WIN_LO_S, WIN_HI_S)
            rows.append({"file": f, "day": v["m"]["date"], "obdEnd": lv, "tLast": lt, "snap": sn, "snapWide": snw, "snap16": sn16})
        def k1(sel, key="snap", tier=None):
            vals = [(r[key][0] - r["obdEnd"], r[key][1] - r["tLast"], r["day"], r["obdEnd"]) for r in rows if r[key] is not None and (tier is None or tier(r))]
            return vals
        def k1_block(vals):
            if not vals:
                return {"nDrives": 0}
            d_ = [x[0] for x in vals]
            out = summarise(d_, [x[2] for x in vals], a.nb)
            out["wording"] = k1_wording(out)
            return out
        v1 = k1(None)
        res["K1_keyoff_crosscheck"] = {"primary_pm120s": k1_block(v1), "ageSlope": age_slope([x[0] for x in v1], [x[1] for x in v1], [x[2] for x in v1]),
                                       "obdEndBelow60C": k1_block([x for x in v1 if x[3] < 60.0]), "obdEnd60CAndAbove": k1_block([x for x in v1 if x[3] >= 60.0]),
                                       "snapshotAfterEnd0to60s": k1_block([x for x in v1 if 0 <= x[1] <= 60.0]), "snapshotAfterEnd60to120s": k1_block([x for x in v1 if 60.0 < x[1] <= 120.0]),
                                       "snapshotBeforeEnd": k1_block([x for x in v1 if x[1] < 0]),
                                       "sensitivity_window_to_600s": k1_block(k1(None, "snapWide")), "sensitivity_shift16s": k1_block(k1(None, "snap16")),
                                       "definition": "difference = cloud snapshot nearest the drive end (within +-120 s) minus the last valid OBD coolant sample; age = snapshot time minus the time of that sample"}
        # ---- K2 (cloud vs cloud; tercile cuts fixed on the cloud kilometres of the logged drives)
        step_end = np.array([s_[1] for s_ in steps]); step_km = np.array([s_[2] for s_ in steps])
        def cloud_km(t0, t1):
            i0, i1 = int(np.searchsorted(step_end, t0)), int(np.searchsorted(step_end, t1, side="right"))
            return float(step_km[i0:i1].sum())
        lg = [(f, cloud_km(v["m"]["t0"], v["m"]["t1"]), snapshot_near(ct, cv, v["m"]["t1"]), v["m"]["date"]) for f, v in info.items() if clean.get(f, False)]
        lg = [x for x in lg if x[2] is not None]
        cuts = np.percentile([x[1] for x in lg], [100.0 / 3, 200.0 / 3]) if len(lg) >= 3 else [0, 0]
        terc = lambda km: 0 if km < cuts[0] else (1 if km < cuts[1] else 2)
        un = []
        for x in unl:
            sn = snapshot_near(ct, cv, x[-1][1])
            km = sum(s_[2] for s_ in x)
            un.append((km, sn, pd.Timestamp(x[0][0], unit="s", tz="UTC").tz_convert("Europe/Kyiv").strftime("%Y-%m-%d")))
        un_s = [x for x in un if x[1] is not None]
        k2 = {"unlogged": {"units": len(un), "withSnapshot": len(un_s), "cloudCoolant": summarise([x[1][0] for x in un_s], [x[2] for x in un_s], a.nb) if un_s else {"nDrives": 0}},
              "logged": {"drives": len(lg), "cloudCoolant": summarise([x[2][0] for x in lg], [x[3] for x in lg], a.nb)},
              "tercileCutsCloudKm": [round(float(c), 2) for c in cuts], "byTercile": {}}
        for tcl in (0, 1, 2):
            ul = [x for x in un_s if terc(x[0]) == tcl]
            ll = [x for x in lg if terc(x[1]) == tcl]
            row = {"unloggedUnits": len(ul), "loggedDrives": len(ll)}
            if len(ul) >= N_MIN and len(ll) >= N_MIN:
                row["medianUnlogged"] = float(np.median([x[1][0] for x in ul]))
                row["medianLogged"] = float(np.median([x[2][0] for x in ll]))
                row["medianDifferenceUnloggedMinusLogged"] = median_diff_ci([x[1][0] for x in ul], [x[2] for x in ul], [x[2][0] for x in ll], [x[3] for x in ll], a.nb)
            else:
                row["status"] = "counts only"
            k2["byTercile"][["shortest", "middle", "longest"][tcl]] = row
        k2["wording"] = "cloud-reported engine coolant shortly after the estimated end of unlogged trips (different driver; not comparable as a driving-style effect)"
        res["K2_unlogged_end_of_trip"] = k2
        # ---- K3
        last_step_end = lambda lo, hi: max([s_[1] for s_ in steps if lo < s_[1] <= hi], default=None)
        recs = {"S_obd": [], "S_cloud": [], "D_cloud": [], "D_cloud_m729": [], "D1_cloud": []}
        diag = {"D_anchor_time_diff_s_max": 0.0, "gapsWithoutSnapshotD": 0, "gapsWithSnapshotD": 0}
        for g in gaps.itertuples():
            pa, nb_ = info.get(g.prev), info.get(g.next)
            if pa is None or nb_ is None or nb_["obd"] is None or not clean.get(g.prev, False) or not clean.get(g.next, False) or g.next not in amb:
                continue
            tb = nb_["obd"][1]
            base = {"arrivalT": nb_["obd"][0], "ambient": amb[g.next], "day": nb_["m"]["date"]}
            cls = getattr(g, "_9", None) if False else gaps.loc[g.Index, "class"]
            if cls == "stationary_consistent":
                if pa["obd"] is not None:
                    recs["S_obd"].append({**base, "anchorT": pa["obd"][2], "parkedH": (tb - pa["obd"][3]) / 3600.0})
                sn = snapshot_near(ct, cv, pa["m"]["t1"])
                if sn is not None:
                    recs["S_cloud"].append({**base, "anchorT": sn[0], "parkedH": (tb - sn[1]) / 3600.0})
            elif cls in D_CLASSES:
                tu = last_step_end(pa["m"]["t1"], nb_["m"]["t0"])
                tu29 = tb - float(g.last_move_to_next_h) * 3600.0
                if tu is not None:
                    diag["D_anchor_time_diff_s_max"] = max(diag["D_anchor_time_diff_s_max"], abs(tu - tu29))
                sn = snapshot_near(ct, cv, tu) if tu is not None else None
                sn29 = snapshot_near(ct, cv, tu29)
                diag["gapsWithSnapshotD" if sn is not None else "gapsWithoutSnapshotD"] += 1
                if sn is not None:
                    recs["D_cloud"].append({**base, "anchorT": sn[0], "parkedH": (tb - sn[1]) / 3600.0})
                    if float(g.moved_km) >= 1.0:
                        recs["D1_cloud"].append({**base, "anchorT": sn[0], "parkedH": (tb - sn[1]) / 3600.0})
                if sn29 is not None:
                    recs["D_cloud_m729"].append({**base, "anchorT": sn29[0], "parkedH": (tb - sn29[1]) / 3600.0})
        k3 = {"anchorDiagnostics": diag, "sets": {}}
        tabs = {}
        for name, rr in recs.items():
            tab, ex = pair_table(rr)
            tabs[name] = tab
            tab_b, ex_b = pair_table(rr, eb_min=EB_MIN_WIDE)
            tab_w, ex_w = pair_table(rr, park_max=PARK_MAX_WIDE_H)
            k3["sets"][name] = {"primary": {**fit_k(tab), "exclusions": ex, "supported": bool(len(tab) and supported(tab))}, "sensitivity_eb_above_3C": {**fit_k(tab_b), "exclusions": ex_b},
                                "sensitivity_parked_to_24h": {**fit_k(tab_w), "exclusions": ex_w},
                                "note": "the e_b > 1 C filter keeps the slow coolers and biases k downward, differently in sets with different parked-time mixes"}
        main_sets = {n: tabs[n] for n in ("S_obd", "S_cloud", "D_cloud") if len(tabs[n]) >= 8}
        if len(main_sets) >= 2:
            for est, key, field, lab_est in (("sen", "comparisons", "kSen", "pairwise Sen slope (headline)"), ("ratio", "comparisonsMedianRatioOrigin", "kMedianRatioOrigin", "median of ratios through the origin (registered spec text; the auditor's estimator)")):
                dr = joint_boot(main_sets, a.nb, est=est)
                if est == "sen":
                    for n, v in dr.items():
                        k3["sets"][n]["primary"]["kCI95"] = [round(float(np.nanpercentile(v, 2.5)), 5), round(float(np.nanpercentile(v, 97.5)), 5)]
                else:
                    for n, v in dr.items():
                        k3["sets"][n]["primary"]["kMedianRatioOriginCI95"] = [round(float(np.nanpercentile(v, 2.5)), 5), round(float(np.nanpercentile(v, 97.5)), 5)]
                comp = {}
                for lab, (x, y) in {"S_cloud_minus_S_obd": ("S_cloud", "S_obd"), "D_cloud_minus_S_cloud": ("D_cloud", "S_cloud")}.items():
                    if x in dr and y in dr:
                        dd = dr[x] - dr[y]
                        lo, hi = float(np.nanpercentile(dd, 2.5)), float(np.nanpercentile(dd, 97.5))
                        kx, ky = k3["sets"][x]["primary"].get(field), k3["sets"][y]["primary"].get(field)
                        sup = k3["sets"][x]["primary"].get("supported") and k3["sets"][y]["primary"].get("supported")
                        comp[lab] = {"estimator": lab_est, "difference": round((kx or 0) - (ky or 0), 5), "ci95": [round(lo, 5), round(hi, 5)], "mde": round(2.8016 * float(np.nanstd(dd, ddof=1)), 5), "wording": diff_wording(kx, ky, lo, hi, bool(sup)),
                                     "bootstrap": "paired (same gaps)" if lab.startswith("S_cloud_minus") else "joint day-clustered resample of disjoint gap sets",
                                     "label": "difference between the sets, confounded by driver, time of day, parking place and a possibly two-time-constant engine; not an unlogged effect"}
                k3[key] = comp
        res["K3_cooling"] = k3
        # ---- K4 coverage
        cov = {"loggedDrivesWithSnapshotNearEnd": int(sum(1 for v in info.values() if snapshot_near(ct, cv, v["m"]["t1"]) is not None)), "loggedDrives": len(info),
               "unloggedUnitsWithSnapshotNearEnd": len(un_s), "unloggedUnits": len(un)}
        res["K4_coverage"] = cov
        res["deviations_from_spec"] = ["the primary fit is the published pairwise Sen slope (with the through-origin check reported as the intercept) and the least-squares through-origin slope is the sensitivity, because the published estimator family (M242) is the Sen slope; the Theil-Sen-with-intercept of 9.3 coincides with it for the slope",
                                       "OBD coolant is read directly from the raw files (thermal.obd_coolant), not through _battery_temp_traj, so drives without pack-sensor columns are kept; drives without an OBD coolant channel are counted"]
        res["scope"] = "report-only: no payload, dashboard or master change; never a pack-temperature statement"
        res["seconds"] = round(time.time() - t_start, 1)
        if md5(a.master) != m0:
            raise Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        json.dump(res, open(os.path.join(a.out_dir, "M754_coolant_snapshots.json"), "w", encoding="utf-8", newline="\n"), indent=1, default=float)
        out_rows = []
        for name, tab in tabs.items():
            for r in tab.itertuples():
                out_rows.append({"set": name, "day": r.day, "parkedH": round(r.parkedH, 3), "anchorT": r.anchorT, "arrivalT": r.arrivalT, "ambient": round(r.ambient, 2)})
        pd.DataFrame(out_rows).to_csv(os.path.join(a.out_dir, "M754_coolant_pairs.csv"), index=False, lineterminator="\n")
        print("coolant_snapshots: K1 %s; K3 pairs %s; %.0f s" % (res["K1_keyoff_crosscheck"]["primary_pm120s"].get("nDrives"), {n: v["primary"]["nPairs"] for n, v in k3["sets"].items()}, res["seconds"]))
        return 0
    except Stop as e:
        print("coolant_snapshots: STOP (%s); nothing written" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
