#!/usr/bin/env python3
"""M738: exposure of the driving seen only by the cloud export (unlogged), with masked-drive validation (auxiliary, report-only).
Spec: analyses/M738_spec.md Rev 2. Nothing published is changed: no payload, dashboard, summary, drive_master.csv or frozen winter file is written.
Writes analyses/M738_unlogged_exposure.json (aggregates only: no coordinates, no per-drive tracks).
Usage: python tools/mynissan_unlogged.py [--store DIR] [--out-dir analyses] [--raw-dir DIR] [--nb 4000]"""
import argparse, bisect, csv, glob, json, math, os, re, sys
from datetime import datetime
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mynissan_import as mi
import mynissan_coverage as mc
import mynissan_thermal as th

ROOT = mi.ROOT
PINNED_MD5 = "d514d6009d6d9a0a168ad4fb09b9bb98"
STEP_MAX_S, STEP_MAX_KMH, JOIN_S, PAD = 35.0, 180.0, 120.0, 60.0
UNLOGGED_MAX, MATCHED_MIN = 0.10, 0.90
CLASSES = ((0.0, 30.0), (30.0, 80.0), (80.0, 1e9))
CLASS_NAMES = ("below30", "30to80", "above80")
MIN_STRATUM, MIN_DRIVES, MIN_DAYS = 30, 100, 30
SEED, NB_DEFAULT = 42, 4000
SPD_COLS = ("Швидкість автомобіля (km/h)", "[VCM] Vehicle Speed (km/h)")


# ------------------------------------------------------------------ pure functions (known-answer tested)
def accepted_steps(odo, spd, near=20.0):
    """Cloud steps per the M729 rule, restored in full: successive odometer samples at most 35 s apart, positive increment, implied speed at most
    180 km/h, displayed speed above zero at one end (nearest speed sample within `near` s). odo, spd: lists of (t, value), sorted."""
    st = [t for t, _ in spd]

    def nearest(t):
        i = bisect.bisect_left(st, t)
        c = [k for k in (i - 1, i) if 0 <= k < len(st) and abs(st[k] - t) <= near]
        return spd[min(c, key=lambda k: abs(st[k] - t))][1] if c else None

    out = []
    for (t1, o1), (t2, o2) in zip(odo, odo[1:]):
        dt, dk = t2 - t1, o2 - o1
        if 0 < dt <= STEP_MAX_S and 0 < dk <= dt * STEP_MAX_KMH / 3600.0:
            v = [nearest(t1), nearest(t2)]
            if any(x is not None and x > 0 for x in v):
                out.append((t1, t2, dk))
    return out


def join_units(steps, gap=JOIN_S):
    """Units: consecutive accepted steps joined while the pause between them is at most `gap` s."""
    units, cur = [], []
    for s in steps:
        if cur and s[0] - cur[-1][1] > gap:
            units.append(cur); cur = []
        cur.append(s)
    if cur:
        units.append(cur)
    return units


def is_strict(unit):
    """M729 strict burst: at least two accepted steps and at least 1 km."""
    return len(unit) >= 2 and sum(s[2] for s in unit) >= 1.0


def class_of_speed(v):
    for k, (lo, hi) in enumerate(CLASSES):
        if lo <= v < hi:
            return k
    return None


def time_shares(speed, t0, t1, max_gap=STEP_MAX_S):
    """Time-weighted shares of the three speed classes over [t0, t1]: intervals between successive speed samples at most max_gap s apart,
    class of the interval mean speed. Returns (shares[3], covered_s) or (None, 0)."""
    w = np.zeros(3)
    s = [x for x in speed if t0 <= x[0] <= t1]
    for (a, va), (b, vb) in zip(s, s[1:]):
        if 0 < b - a <= max_gap:
            w[class_of_speed(0.5 * (va + vb))] += b - a
    tot = float(w.sum())
    return (w / tot, tot) if tot > 0 else (None, 0.0)


def unit_vector(unit, speed, amb):
    """Exposure vector of a unit from the cloud alone (spec section 3). Ambient: M734 screened rule with a 180 s cutoff (reuse, not redefinition)."""
    t0, t1 = unit[0][0], unit[-1][1]
    dist = float(sum(s[2] for s in unit))
    moving = float(sum(s[1] - s[0] for s in unit))
    sh, cov = time_shares(speed, t0, t1)
    spd_in = [x for x in speed if t0 <= x[0] <= t1]
    zeros = sum(1 for _, v in spd_in if v == 0)
    sc = None
    m0 = th.movement_start(spd_in, 0.0)
    if m0 is not None:
        sc = th.screened_mean([x for x in amb if t0 - 1 <= x[0] <= t1 + th.PAD], m0, t1, 180.0)
    return {"t0": t0, "t1": t1, "km": dist, "duration_s": t1 - t0, "moving_s": moving, "mean_moving_kmh": dist / (moving / 3600.0) if moving > 0 else None,
            "shares": None if sh is None else [float(x) for x in sh], "stopgo_per_km": zeros / dist if dist > 0 else None,
            "ambient": None if sc is None else float(sc["mean"]), "n_steps": len(unit)}


def overlap_fraction(t0, t1, windows):
    """Share of [t0, t1] covered by the union of the windows [(a, b)] (sorted by a); also the indices of the overlapping windows."""
    if t1 <= t0:
        return 0.0, []
    cov, hit, last = 0.0, [], t0
    for k, (a, b) in enumerate(windows):
        if b <= t0 or a >= t1:
            continue
        hit.append(k)
        lo, hi = max(a, t0, last), min(b, t1)
        if hi > lo:
            cov += hi - lo
        last = max(last, hi)
    return cov / (t1 - t0), hit


def classify_unit(frac):
    return "unlogged" if frac < UNLOGGED_MAX else ("matched" if frac >= MATCHED_MIN else "boundary")


def tv_distance(p, q):
    return 0.5 * float(np.abs(np.asarray(p, float) - np.asarray(q, float)).sum())


def tercile_cuts(vals):
    v = np.asarray(vals, float)
    return float(np.percentile(v, 100 / 3)), float(np.percentile(v, 200 / 3))


def length_tercile(km, cuts):
    return 0 if km < cuts[0] else (1 if km < cuts[1] else 2)


def day_type(epoch):
    return "weekend" if datetime.fromtimestamp(epoch, mc.KYIV).weekday() >= 5 else "weekday"


def hour_class(epoch):
    h = datetime.fromtimestamp(epoch, mc.KYIV).hour
    return "night" if (h >= 22 or h < 6) else "day"


def boot_days(groups, stat, nb, seed=SEED):
    """Day-clustered percentile bootstrap. groups: list (one per day) of row-index arrays into whatever `stat` closes over; stat(index_array) -> float."""
    if len(groups) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    out = np.empty(nb)
    for b in range(nb):
        pick = rng.integers(0, len(groups), len(groups))
        out[b] = stat(np.concatenate([groups[i] for i in pick]))
    out = out[np.isfinite(out)]
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))] if len(out) else [None, None]


def within_day_permutation_p(values, labels, days, stat, nperm, seed=SEED):
    """Permutation p-value of stat(values, labels) with labels shuffled WITHIN each day (day structure conditioned on)."""
    values, labels, days = np.asarray(values, float), np.asarray(labels), np.asarray(days)
    obs = stat(values, labels)
    rng = np.random.default_rng(seed)
    idx_by_day = [np.where(days == d)[0] for d in np.unique(days)]
    ge = 0
    for _ in range(nperm):
        lab = labels.copy()
        for ix in idx_by_day:
            lab[ix] = rng.permutation(lab[ix])
        ge += stat(values, lab) >= obs - 1e-12
    return obs, (ge + 1) / (nperm + 1)


def decompose_km(total, parts):
    """Disjoint and exhaustive km partition: the named parts plus a remainder equal to the total; gate: parts non-negative and remainder >= -1e-6."""
    rem = total - sum(parts.values())
    return {**parts, "remainder": rem, "partition_exhaustive": abs(sum(parts.values()) + rem - total) < 1e-6, "remainder_nonnegative": rem >= -1e-6}


# ------------------------------------------------------------------ I/O
def read_obd_speed_shares(path):
    """OBD time shares in the three classes from vehicle-speed rows (rows carrying speed, successive gaps at most 5 s) and the speed-integral distance."""
    try:
        df = pd.read_csv(path, usecols=lambda c: c == "time" or c in SPD_COLS, low_memory=False)
    except Exception:
        return None
    ts = pd.to_datetime(df["time"].astype(str), format="mixed", errors="coerce")
    sec = (ts.dt.hour * 3600 + ts.dt.minute * 60 + ts.dt.second + ts.dt.microsecond / 1e6).values
    v = np.full(len(df), np.nan)
    for c in SPD_COLS:
        if c in df.columns:
            x = pd.to_numeric(df[c], errors="coerce").values
            v = np.where(np.isfinite(v), v, x)
    ok = np.isfinite(sec) & np.isfinite(v)
    sec, v = sec[ok], v[ok]
    if len(sec) < 3:
        return None
    dt = np.diff(sec) % 86400.0
    keep = (dt > 0) & (dt <= 5.0)
    mid = 0.5 * (v[:-1] + v[1:])
    w = np.zeros(3)
    for k, (lo, hi) in enumerate(CLASSES):
        w[k] = dt[keep & (mid >= lo) & (mid < hi)].sum()
    return (w / w.sum()).tolist() if w.sum() > 0 else None


def load_streams(store):
    st = {s: [(t, x) for t, x in mi.load_stream(store, s)] for s in ("Odometer", "Trip_Information", "Vehicle_Information")}
    conf = set()
    cp = os.path.join(store, "conflicts.csv")
    if os.path.exists(cp):
        for r in csv.DictReader(open(cp, encoding="utf-8", newline="")):
            if r["stream"] == "Odometer":
                conf.add(mi.to_epoch(r["timestamp_utc"]))
    odo = [(t, mc.fnum(x.get("StatusDistanceTotalizerComputed", ""))) for t, x in st["Odometer"] if x.get("StatusDistanceTotalizerComputed", "") != "" and t not in conf]
    odo = [(t, v) for t, v in odo if v is not None]
    spd = [(t, mc.fnum(x.get("SpeedDisplayedValueinkmh", ""))) for t, x in st["Trip_Information"] if x.get("SpeedDisplayedValueinkmh", "") != ""]
    spd = [(t, v) for t, v in spd if v is not None]
    amb = [(t, mc.fnum(x.get("ExternalTempDisplayValue", ""))) for t, x in st["Vehicle_Information"] if x.get("ExternalTempDisplayValue", "") != ""]
    amb = [(t, v) for t, v in amb if v is not None]
    return odo, spd, amb


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store())
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--seasonal", default=os.path.join(ROOT, "seasonal_drive_master.csv"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")):
        print("mynissan_unlogged: no cloud store, skipped (optional)"); return 0
    sys.stdout.reconfigure(encoding="utf-8")
    md5 = mc.md5(a.master)
    res = {"milestone": "M738", "spec": "analyses/M738_spec.md Rev 2", "role": "auxiliary", "masterMd5": md5, "pinnedMd5": PINNED_MD5,
           "privacy": "aggregates only; no coordinates or per-drive tracks", "external_inputs_used": []}
    if md5 != PINNED_MD5:
        res["stopped"] = "master md5 differs from the pin"
        os.makedirs(a.out_dir, exist_ok=True)
        json.dump(res, open(os.path.join(a.out_dir, "M738_unlogged_exposure.json"), "w", encoding="utf-8"), indent=1)
        print("mynissan_unlogged: master pin failed"); return 1
    frozen = [os.path.join(ROOT, "analyses", "M717_winter_predictions.json")]
    frozen_before = {p: mc.md5(p) for p in frozen if os.path.exists(p)}
    odo, spd, amb = load_streams(a.store)
    exp_t0, exp_t1 = odo[0][0], odo[-1][0]
    steps = accepted_steps(odo, spd)
    units = join_units(steps)
    # drives (aligned to the export span) and the OBD reference
    mdf = pd.read_csv(a.master, usecols=["file", "date", "time_start", "duration_s", "distance_km", "speed_mean_moving", "ens_outlier_v2"], low_memory=False)
    master = mc.load_master(a.master)
    byf = mdf.set_index("file")
    sdf = pd.read_csv(a.seasonal, usecols=["file", "ambient_time_mean_c"], low_memory=False).drop_duplicates("file").set_index("file") if os.path.exists(a.seasonal) else None
    win_all = [(m["t0"] - PAD, m["t1"] + PAD) for m in master]
    in_span = [k for k, m in enumerate(master) if m["t0"] - PAD >= exp_t0 and m["t1"] + PAD <= exp_t1]
    res["alignment"] = {"drives_in_master": len(master), "drives_in_export_span": len(in_span), "export_range_kyiv": [datetime.fromtimestamp(exp_t0, mc.KYIV).isoformat(), datetime.fromtimestamp(exp_t1, mc.KYIV).isoformat()],
                        "cloud_odometer_gain_km": float(odo[-1][1] - odo[0][1]), "accepted_steps": len(steps), "units": len(units), "strict_units": sum(is_strict(u) for u in units)}
    order = sorted(range(len(master)), key=lambda k: win_all[k][0])
    wins = [win_all[k] for k in order]

    def assign(shift, pad):
        w = [(master[k]["t0"] - pad, master[k]["t1"] + pad) for k in order]
        out = []
        for u in units:
            f, hit = overlap_fraction(u[0][0] + shift, u[-1][1] + shift, w)
            out.append((classify_unit(f), f, [order[h] for h in hit]))
        return out

    asg = assign(0.0, PAD)
    vecs = [unit_vector(u, spd, amb) for u in units]
    # drive vectors from matched units
    per_drive = {}
    for u, v, (c, f, hit) in zip(units, vecs, asg):
        if c != "matched" or not hit:
            continue
        k = max(hit, key=lambda h: min(master[h]["t1"], v["t1"]) - max(master[h]["t0"], v["t0"]))
        per_drive.setdefault(k, []).append(v)

    def combine(vs):
        km = sum(v["km"] for v in vs)
        mv = sum(v["moving_s"] for v in vs)
        tot_t = sum(v["duration_s"] for v in vs)
        sh = [sum((v["shares"] or [0, 0, 0])[i] * v["duration_s"] for v in vs if v["shares"]) for i in range(3)]
        ss = sum(sh)
        am = [v["ambient"] for v in vs if v["ambient"] is not None]
        return {"km": km, "duration_s": tot_t, "moving_s": mv, "shares": [x / ss for x in sh] if ss > 0 else None,
                "ambient": float(np.mean(am)) if am else None, "mean_moving_kmh": km / (mv / 3600.0) if mv > 0 else None}

    dv = {k: combine(vs) for k, vs in per_drive.items()}
    # V2 recall and precision
    def covered(k):
        lo, hi = win_all[k]
        return bisect.bisect_right([t for t, _ in odo], hi) - bisect.bisect_left([t for t, _ in odo], lo) >= 2
    ref_rows = []
    for k in in_span:
        m = master[k]
        r = byf.loc[m["file"]] if m["file"] in byf.index else None
        if r is None:
            continue
        ref_rows.append(k)
    rec_all = [k for k in ref_rows if k in dv and dv[k]["km"] >= 0.9 * float(byf.loc[master[k]["file"], "distance_km"])]
    cov_k = [k for k in ref_rows if covered(k)]
    n_inwin = sum(1 for c, f, h in asg if f >= UNLOGGED_MAX)
    res["V2_detection"] = {"drives_in_span": len(ref_rows), "recall_all_in_span": len(rec_all) / max(1, len(ref_rows)), "recall_n": len(rec_all),
                           "drives_with_cloud_coverage": len(cov_k), "recall_among_covered": sum(1 for k in cov_k if k in rec_all) / max(1, len(cov_k)),
                           "units_in_window_overlap_ge_10pct": n_inwin, "precision_in_window_units_matched_ge_90pct": sum(1 for c, f, h in asg if c == "matched") / max(1, n_inwin),
                           "precision_note": "an in-window unit always overlaps a drive by construction; precision is the share of in-window units whose overlap is at least 90 % (the rest are boundary cases)",
                           "boundary_units": sum(1 for c, _, _ in asg if c == "boundary")}
    # OBD reference and V1
    canon = [k for k in ref_rows if k in dv and not bool(byf.loc[master[k]["file"], "ens_outlier_v2"])]
    raw_idx = th.raw_index(a.raw_dir) if os.path.isdir(a.raw_dir) else {}
    rows = []
    for k in canon:
        m = master[k]
        f = m["file"]
        refkm, refdur = float(byf.loc[f, "distance_km"]), float(byf.loc[f, "duration_s"])
        p = raw_idx.get(re.sub(r"\D", "", f))
        osh = read_obd_speed_shares(p) if p else None
        man = None
        if sdf is not None and f in sdf.index and pd.notna(sdf.loc[f, "ambient_time_mean_c"]):
            man = float(sdf.loc[f, "ambient_time_mean_c"])
        c = dv[k]
        rows.append({"k": k, "date": m["date"], "ref_km": refkm, "ref_dur": refdur, "c_km": c["km"], "c_dur": c["duration_s"], "ref_sh": osh, "c_sh": c["shares"],
                     "man": man, "c_amb": c["ambient"], "t0": m["t0"], "ref_v": float(byf.loc[f, "speed_mean_moving"]) if pd.notna(byf.loc[f, "speed_mean_moving"]) else None, "c_v": c["mean_moving_kmh"]})
    R = pd.DataFrame(rows)
    res["V1_n"] = {"validation_drives": int(len(R)), "days": int(R.date.nunique()) if len(R) else 0, "ref_km": float(R.ref_km.sum()) if len(R) else 0.0}
    v1 = {}
    if len(R) >= 5:
        days = R.date.values
        ud = list(dict.fromkeys(days))
        groups = [np.where(days == d)[0] for d in ud]
        rel = ((R.c_km - R.ref_km) / R.ref_km).values
        err_dur = (R.c_dur - R.ref_dur).values
        v1["distance"] = {"median_abs_rel_err": float(np.median(np.abs(rel))), "ci95_day": boot_days(groups, lambda ix: float(np.median(np.abs(rel[ix]))), a.nb),
                          "aggregate_signed_bias": float((R.c_km.sum() - R.ref_km.sum()) / R.ref_km.sum()),
                          "bias_ci95_day": boot_days(groups, lambda ix: float((R.c_km.values[ix].sum() - R.ref_km.values[ix].sum()) / R.ref_km.values[ix].sum()), a.nb)}
        v1["duration"] = {"median_abs_err_s": float(np.median(np.abs(err_dur))), "ci95_day": boot_days(groups, lambda ix: float(np.median(np.abs(err_dur[ix]))), a.nb),
                          "aggregate_signed_bias": float((R.c_dur.sum() - R.ref_dur.sum()) / R.ref_dur.sum()),
                          "bias_ci95_day": boot_days(groups, lambda ix: float((R.c_dur.values[ix].sum() - R.ref_dur.values[ix].sum()) / R.ref_dur.values[ix].sum()), a.nb),
                          "note": "cloud duration runs from the first to the last accepted step; the OBD duration includes stationary lead-in and lead-out, so a negative bias is expected"}
        sh = R.dropna(subset=["ref_sh", "c_sh"])
        if len(sh) >= 5:
            tvs = np.array([tv_distance(a_, b_) for a_, b_ in zip(sh.ref_sh, sh.c_sh)])
            sd = sh.date.values
            sg = [np.where(sd == d)[0] for d in list(dict.fromkeys(sd))]
            sgn = np.array([np.asarray(b_) - np.asarray(a_) for a_, b_ in zip(sh.ref_sh, sh.c_sh)])
            v1["time_shares"] = {"n_drives": int(len(sh)), "median_tv": float(np.median(tvs)), "ci95_day": boot_days(sg, lambda ix: float(np.median(tvs[ix])), a.nb),
                                 "signed_mean_error_by_class": {CLASS_NAMES[i]: float(sgn[:, i].mean()) for i in range(3)}}
        am = R.dropna(subset=["man", "c_amb"])
        if len(am) >= 5:
            dd = (am.c_amb - am.man).abs().values
            ad = am.date.values
            ag = [np.where(ad == d)[0] for d in list(dict.fromkeys(ad))]
            v1["ambient"] = {"n_drives": int(len(am)), "median_abs_diff_C": float(np.median(dd)), "ci95_day": boot_days(ag, lambda ix: float(np.median(dd[ix])), a.nb),
                             "note": "reference is the driver-recorded ambient; the M734 screening rules were tuned on the same drives (in-sample)"}
        vv = R.dropna(subset=["ref_v", "c_v"])
        v1["mean_speed_descriptive"] = {"n_drives": int(len(vv)), "median_abs_err_kmh": float((vv.c_v - vv.ref_v).abs().median()) if len(vv) else None}
    res["V1_reconstruction_error"] = v1
    # R1 verdicts
    def verdict(est, ci_hi, thr):
        if est is None or ci_hi is None:
            return "not testable"
        return "met" if ci_hi <= thr else ("marginal" if ci_hi <= 1.5 * thr else "not met")
    r1 = {}
    support_ok = len(R) >= MIN_DRIVES and (R.date.nunique() if len(R) else 0) >= MIN_DAYS
    r1["support_floor_met"] = bool(support_ok)
    if "distance" in v1:
        d = v1["distance"]
        r1["distance"] = {"median_rel": verdict(d["median_abs_rel_err"], d["ci95_day"][1], 0.10), "aggregate_bias": verdict(abs(d["aggregate_signed_bias"]), max(abs(x) for x in d["bias_ci95_day"] if x is not None) if d["bias_ci95_day"][0] is not None else None, 0.05)}
        du = v1["duration"]
        r1["duration"] = {"median_abs_err_s": verdict(du["median_abs_err_s"], du["ci95_day"][1], 90.0), "aggregate_bias": verdict(abs(du["aggregate_signed_bias"]), max(abs(x) for x in du["bias_ci95_day"] if x is not None) if du["bias_ci95_day"][0] is not None else None, 0.05)}
        if "time_shares" in v1:
            r1["time_shares"] = verdict(v1["time_shares"]["median_tv"], v1["time_shares"]["ci95_day"][1], 0.15)
        if "ambient" in v1:
            r1["ambient"] = verdict(v1["ambient"]["median_abs_diff_C"], v1["ambient"]["ci95_day"][1], 1.0)
    res["R1_verdicts"] = r1

    def carried(q):
        v = r1.get(q)
        if not support_ok or v is None:
            return False
        vals = list(v.values()) if isinstance(v, dict) else [v]
        return all(x in ("met", "marginal") for x in vals)
    res["R1_carried_to_U"] = {q: carried(q) for q in ("distance", "duration", "time_shares", "ambient")}

    # strata (length tercile x day type); cuts from the validation reference km
    cuts = tercile_cuts(R.ref_km.values) if len(R) >= 9 else (0.0, 0.0)
    R["stratum"] = [(length_tercile(x, cuts), day_type(t)) for x, t in zip(R.c_km, R.t0)]
    strata_v = {}
    for key, g in R.groupby("stratum"):
        sk = "%d/%s" % key
        gd = g.date.values
        gg = [np.where(gd == d)[0] for d in list(dict.fromkeys(gd))]
        ck, rk = g.c_km.values, g.ref_km.values
        strata_v[sk] = {"n_drives": int(len(g)), "n_days": int(g.date.nunique()), "agg_bias": float((ck.sum() - rk.sum()) / rk.sum()),
                        "bias_ci95_day": boot_days(gg, lambda ix: float((ck[ix].sum() - rk[ix].sum()) / rk[ix].sum()), a.nb), "supported": bool(len(g) >= MIN_STRATUM)}
    res["V1_strata"] = {"length_tercile_cuts_km_cloud": list(cuts), "strata": strata_v}

    # U1, U2, U3 sensitivities
    def unlogged_units(assignment, strict_only=True):
        return [i for i, (c, f, h) in enumerate(assignment) if c == "unlogged" and (is_strict(units[i]) or not strict_only)]
    ui = unlogged_units(asg)
    um = pd.DataFrame([{"i": i, "km": vecs[i]["km"], "dur": vecs[i]["duration_s"], "date": datetime.fromtimestamp(vecs[i]["t0"], mc.KYIV).date().isoformat(), "t0": vecs[i]["t0"],
                        "sh": vecs[i]["shares"], "amb": vecs[i]["ambient"]} for i in ui])
    u1 = {"strict_units": len(ui), "days": int(um.date.nunique()) if len(um) else 0, "total_km_cloud": float(um.km.sum()) if len(um) else 0.0,
          "total_hours_cloud": float(um.dur.sum() / 3600.0) if len(um) else 0.0, "crude_units_all": len(unlogged_units(asg, False)),
          "crude_total_km_cloud": float(sum(vecs[i]["km"] for i in unlogged_units(asg, False))),
          "mean_unit_km": float(um.km.mean()) if len(um) else None, "median_unit_km": float(um.km.median()) if len(um) else None,
          "mean_logged_drive_km_master": float(R.ref_km.mean()) if len(R) else None}
    if len(um):
        um["stratum"] = ["%d/%s" % (length_tercile(k, cuts), day_type(t)) for k, t in zip(um.km, um.t0)]
        sup = {sk for sk, v in strata_v.items() if v["supported"]}
        ins = um[um.stratum.isin(sup)]
        out = um[~um.stratum.isin(sup)]
        u1["in_support"] = {"units": int(len(ins)), "km_cloud": float(ins.km.sum())}
        u1["outside_validation_support"] = {"units": int(len(out)), "km_cloud": float(out.km.sum()), "days": int(out.date.nunique()) if len(out) else 0, "note": "count, km and days only; no exposure statement"}
        if carried("distance") and len(ins):
            lo = hi = 0.0
            for sk, g in ins.groupby("stratum"):
                b = strata_v[sk]["bias_ci95_day"]
                if b[0] is None:
                    continue
                hi += g.km.sum() / (1.0 + b[0]); lo += g.km.sum() / (1.0 + b[1])
            u1["in_support_km_bias_bracket_V1_stratum"] = [float(lo), float(hi)]
            u1["interval_covers"] = "measurement error only (a census of the export); V1 stratum bias interval propagated"
        if carried("time_shares"):
            w = ins.dropna(subset=["sh"])
            if len(w):
                tot = w.km.values
                u1["time_share_km_weighted"] = {CLASS_NAMES[i]: float(np.average([s[i] for s in w.sh], weights=tot)) for i in range(3)}
    res["U1_unlogged"] = u1
    # U2: signed differences, km-weighted, comparator = cloud-reconstructed vector of logged drives
    u2 = {"carried": bool(carried("time_shares") and len(um) > 0)}
    if u2["carried"] and len(R.dropna(subset=["c_sh"])):
        L = R.dropna(subset=["c_sh"])
        Um = um.dropna(subset=["sh"])
        vals_sh = np.array(list(L.c_sh) + list(Um.sh), float)
        wts = np.array(list(L.c_km) + list(Um.km), float)
        lab = np.array([0] * len(L) + [1] * len(Um))
        dys = np.array(list(L.date) + list(Um.date))

        def diff(vs, lb, wt=wts):
            return np.array([np.average(vs[lb == 1][:, i], weights=wt[lb == 1]) - np.average(vs[lb == 0][:, i], weights=wt[lb == 0]) for i in range(3)])
        obs = diff(vals_sh, lab)
        ud = list(dict.fromkeys(dys))
        gps = [np.where(dys == d)[0] for d in ud]
        rng = np.random.default_rng(SEED)
        bs = []
        for _ in range(a.nb):
            ix = np.concatenate([gps[j] for j in rng.integers(0, len(gps), len(gps))])
            if (lab[ix] == 1).any() and (lab[ix] == 0).any():
                bs.append(diff(vals_sh[ix], lab[ix], wts[ix]))
        bs = np.array(bs)
        u2["signed_diff_unlogged_minus_logged_cloud"] = {CLASS_NAMES[i]: {"estimate": float(obs[i]), "ci95_day": [float(np.percentile(bs[:, i], 2.5)), float(np.percentile(bs[:, i], 97.5))],
                                                                           "mde_80pct_power": float(2.8 * bs[:, i].std())} for i in range(3)}
        tv_stat = lambda vs, lb: tv_distance(*[np.average(vs[lb == g], axis=0, weights=wts[lb == g]) for g in (1, 0)])
        tv, p = within_day_permutation_p(vals_sh, lab, dys, tv_stat, 1000)
        u2["tv_km_weighted_mean_shares"] = {"observed": float(tv), "permutation_p_within_day_labels": float(p), "note": "labels shuffled within each day; TV is non-negative and biased upward, so only the permutation p is read"}
        u2["n"] = {"logged_cloud_vectors": int(len(L)), "unlogged_units": int(len(Um)), "days": len(ud)}
    res["U2_representativeness"] = u2
    # U3 km decomposition
    km_by = {"matched": 0.0, "unlogged": 0.0, "boundary": 0.0}
    for u, (c, f, h) in zip(units, asg):
        km_by[c] += sum(s[2] for s in u)
    res["U3_km_decomposition"] = decompose_km(float(odo[-1][1] - odo[0][1]), {"matched_units": km_by["matched"], "unlogged_units": km_by["unlogged"], "boundary_units": km_by["boundary"]})
    # sensitivities: unpadded overlap, +16 s clock shift, boundary km bracket
    sens = {}
    for name, sh_, pad_ in (("unpadded", 0.0, 0.0), ("shift_plus16s", 16.0, PAD), ("shift_minus16s", -16.0, PAD)):
        alt = assign(sh_, pad_)
        sens[name] = {"units_changing_class": sum(1 for x, y in zip(asg, alt) if x[0] != y[0]),
                      "unlogged_strict_units": len(unlogged_units(alt)), "unlogged_km_cloud": float(sum(vecs[i]["km"] for i in unlogged_units(alt)))}
    bk = sum(sum(s[2] for s in u) for u, (c, f, h) in zip(units, asg) if c == "boundary")
    bk_out = sum(sum(s[2] for s in u) * (1 - f) for u, (c, f, h) in zip(units, asg) if c == "boundary")
    sens["boundary_km_bracket"] = {"lower_excludes": float(res["U1_unlogged"]["total_km_cloud"]), "upper_adds_non_overlap": float(res["U1_unlogged"]["total_km_cloud"] + bk_out), "boundary_km": float(bk)}
    res["sensitivities"] = sens
    # missingness stratum
    iso = lambda t: datetime.fromtimestamp(t, mc.KYIV).date().isoformat()
    holes = [(b - a_, a_, b) for (a_, _), (b, _) in zip(odo, odo[1:]) if b - a_ >= 24 * 3600]
    res["cloud_missingness"] = {"holes_ge_24h": [{"hours": round(h[0] / 3600, 1), "from": iso(h[1]), "to": iso(h[2])} for h in holes],
                                "note": "unlogged driving inside these holes and on dates without export rows is unobservable here; listed, not modelled"}
    res["scope"] = "M726: no U1/U2 output feeds the winter session; no winter prediction is scored or extended"
    if mc.md5(a.master) != PINNED_MD5 or any(mc.md5(p) != v for p, v in frozen_before.items()):
        print("mynissan_unlogged: master or frozen file changed during the run"); return 1
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(res, open(os.path.join(a.out_dir, "M738_unlogged_exposure.json"), "w", encoding="utf-8"), indent=1)
    print("mynissan_unlogged: units %d (strict %d), unlogged strict %d (%.0f km), validation drives %d, R1 %s" % (len(units), res["alignment"]["strict_units"], u1["strict_units"], u1["total_km_cloud"], len(R), json.dumps(res["R1_carried_to_U"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
