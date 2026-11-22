#!/usr/bin/env python3
"""M736 stage G0 (offline feasibility): cloud-versus-OBD position agreement, cloud track geometry, support of the P2 validation set,
reference noise of the OBD-altitude grade, and the G0 gate. Spec: analyses/M736_spec.md Rev 2. Auxiliary, report-only, offline: no DEM or road
network is read or fetched. Stages G1 to G3 are not implemented here (they need Andrii's approval of the downloads).
Writes analyses/M736_g0.json: aggregates only (public repository, RC7): no coordinates, tracks or per-drive route geometry.
Usage: python tools/mynissan_grade.py [--store DIR] [--out-dir analyses] [--raw-dir DIR] [--nb 4000]"""
import argparse, bisect, glob, json, math, os, re, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mynissan_import as mi
import mynissan_coverage as mc

ROOT = mi.ROOT
PINNED_MD5 = "d514d6009d6d9a0a168ad4fb09b9bb98"
SEG_M, SEG_MIN_M, ALT_GAP_S, MIN_ALT_PTS = 500.0, 400.0, 5.0, 5
SHIFTS = (-16.0, 0.0, 16.0)
SPEED_CLASSES = ((0, 30, "below30"), (30, 80, "30to80"), (80, 1e9, "above80"))
RATIO_LO, RATIO_HI = 0.8, 1.25
CELL_DEG, MIN_DAYS, MIN_KM, MIN_PAIRS = 0.001, 30, 100.0, 5
SEED, NB_DEFAULT = 42, 4000
ALT_COL, LAT_COL, LON_COL = "Висота (GPS) (m)", "Latitude", "Longtitude"
SPD_COLS = ("Швидкість автомобіля (km/h)", "[VCM] Vehicle Speed (km/h)")   # OBD vehicle speed (older files lack the VCM column)


# ------------------------------------------------------------------ pure functions (known-answer tested)
def hav_arr(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(h))


def cum_dist(lat, lon):
    """Cumulative along-track distance (m) from latitude/longitude arrays."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    if len(lat) == 0:
        return np.zeros(0)
    return np.concatenate([[0.0], np.cumsum(hav_arr(lat[:-1], lon[:-1], lat[1:], lon[1:]))])


def altitude_runs(t, has_alt, max_gap=ALT_GAP_S):
    """Index runs [i0, i1] of consecutive altitude samples whose successive time gaps are at most max_gap seconds."""
    idx = [i for i in range(len(t)) if has_alt[i]]
    runs, cur = [], []
    for i in idx:
        if cur and t[i] - t[cur[-1]] > max_gap:
            runs.append(cur); cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    return runs


def chunk_run(d, seg=SEG_M, min_len=SEG_MIN_M):
    """Non-overlapping chunks of a run by along-track distance d (ascending, metres); a chunk qualifies when it spans at least min_len."""
    d = np.asarray(d, float)
    if len(d) < 2:
        return []
    out, start = [], d[0]
    while start + min_len <= d[-1] + 1e-9:
        end = min(start + seg, d[-1])
        i0, i1 = int(np.searchsorted(d, start - 1e-9)), int(np.searchsorted(d, end + 1e-9))
        if d[min(i1, len(d)) - 1] - d[i0] >= min_len - 1e-9:
            out.append((i0, min(i1, len(d))))
        start += seg
    return out


def ols_grade(d, z):
    """Grade in percent: slope of the least-squares line of altitude z on along-track distance d."""
    d, z = np.asarray(d, float), np.asarray(z, float)
    if len(d) < 2 or np.ptp(d) <= 0:
        return None
    x = d - d.mean()
    return float(100.0 * (x * (z - z.mean())).sum() / (x * x).sum())


def cell_set(lat, lon, deg=CELL_DEG):
    return {(int(math.floor(a / deg)), int(math.floor(b / deg))) for a, b in zip(lat, lon)}


def heading_vec(lat, lon):
    return (float(lon[-1] - lon[0]) * math.cos(math.radians(float(np.mean(lat)))), float(lat[-1] - lat[0]))


def interp_track(tq, t, lat, lon, max_span=5.0):
    """Linear interpolation of a track at times tq; NaN where the bracketing samples are further apart than max_span seconds."""
    t = np.asarray(t, float)
    out = np.full((len(tq), 2), np.nan)
    j = np.searchsorted(t, tq)
    for k, (q, jj) in enumerate(zip(tq, j)):
        if 0 < jj < len(t) and t[jj] - t[jj - 1] <= max_span:
            w = 0.0 if t[jj] == t[jj - 1] else (q - t[jj - 1]) / (t[jj] - t[jj - 1])
            out[k] = (lat[jj - 1] + w * (lat[jj] - lat[jj - 1]), lon[jj - 1] + w * (lon[jj] - lon[jj - 1]))
    return out


def path_ratio(t, lat, lon, spd):
    """GPS path length divided by the integral of OBD vehicle speed over the same samples (screen for a frozen or jumping logged GPS fix).
    Returns None when the speed integral is below 200 m."""
    t, lat, lon, spd = (np.asarray(x, float) for x in (t, lat, lon, spd))
    ok = np.isfinite(spd)
    t, lat, lon, spd = t[ok], lat[ok], lon[ok], spd[ok]      # speed is logged at about 1 Hz: use the rows that carry it
    if len(t) < 2:
        return None
    dt = np.diff(t)
    keep = (dt > 0) & (dt <= 5.0)
    odo = float((0.5 * (spd[:-1] + spd[1:]) / 3.6 * dt)[keep].sum())
    if odo < 200.0:
        return None
    gps = float(hav_arr(lat[:-1], lon[:-1], lat[1:], lon[1:])[keep].sum())
    return gps / odo


def window_ok(t, lat, lon, spd, w=60.0, lo=None, hi=None):
    """Per-row flag: True when the row lies in a w-second window whose GPS path / speed-integral ratio is inside [lo, hi]
    (a frozen or jumping logged GPS fails locally even if the whole drive passes). Windows without enough speed integral are False."""
    lo = RATIO_LO if lo is None else lo
    hi = RATIO_HI if hi is None else hi
    t = np.asarray(t, float)
    out = np.zeros(len(t), bool)
    if len(t) == 0:
        return out
    wi = np.floor((t - t[0]) / w).astype(int)
    for k in np.unique(wi):
        m = wi == k
        r = path_ratio(t[m], np.asarray(lat)[m], np.asarray(lon)[m], np.asarray(spd)[m])
        out[m] = r is not None and lo <= r <= hi
    return out


def noise_floor(diffs):
    """Noise of a single-traversal grade from between-traversal differences: SD(diff) / sqrt(2)."""
    d = np.asarray(diffs, float)
    return float(np.std(d, ddof=1) / math.sqrt(2.0)) if len(d) >= 2 else None


def speed_class(v):
    for lo, hi, name in SPEED_CLASSES:
        if lo <= v < hi:
            return name
    return None


def boot_median(vals, days, nb, seed=SEED):
    """Day-clustered percentile bootstrap interval of the median (days resampled with replacement)."""
    vals, days = np.asarray(vals, float), np.asarray(days)
    ud = np.unique(days)
    if len(ud) < 2 or len(vals) == 0:
        return [None, None]
    groups = [vals[days == u] for u in ud]
    rng = np.random.default_rng(seed)
    meds = np.empty(nb)
    for b in range(nb):
        pick = rng.integers(0, len(ud), len(ud))
        meds[b] = np.median(np.concatenate([groups[i] for i in pick]))
    return [float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))]


def g0_decision(days, unique_km, n_pairs, floor):
    """R1/RC3 gate: support floor (30 days, 100 unique km, 5 repeat pairs); floor above 1 pp reads 'not testable' at the later stage."""
    reasons = []
    if days < MIN_DAYS:
        reasons.append("days %d < %d" % (days, MIN_DAYS))
    if unique_km < MIN_KM:
        reasons.append("unique km %.1f < %.0f" % (unique_km, MIN_KM))
    if n_pairs < MIN_PAIRS:
        reasons.append("repeat pairs %d < %d" % (n_pairs, MIN_PAIRS))
    ok = not reasons
    return {"proceed_to_downloads": ok, "reasons": reasons,
            "outcome": "G0 passed: request the DEM and road-network downloads" if ok else "not testable at G0: milestone ends, no download requested"}


# ------------------------------------------------------------------ I/O
def raw_index(raw_dir):
    return {re.sub(r"\D", "", os.path.basename(q)): q for q in glob.glob(os.path.join(raw_dir, "*.csv"))}


def read_obd(path, t0_epoch):
    """OBD columns as arrays on an epoch axis anchored to the master start time (clock time-of-day, midnight rollover handled)."""
    try:
        df = pd.read_csv(path, usecols=lambda c: c in ("time", ALT_COL, LAT_COL, LON_COL) or c in SPD_COLS, low_memory=False)
    except Exception:
        return None
    if LAT_COL not in df.columns or LON_COL not in df.columns:
        return None
    ts = pd.to_datetime(df["time"].astype(str), format="mixed", errors="coerce")
    sec = (ts.dt.hour * 3600 + ts.dt.minute * 60 + ts.dt.second + ts.dt.microsecond / 1e6).values
    if len(sec) == 0 or np.isnan(sec[0]):
        return None
    t = t0_epoch + ((sec - sec[0]) % 86400.0)
    num = lambda c: pd.to_numeric(df[c], errors="coerce").values if c in df.columns else np.full(len(df), np.nan)
    lat, lon, alt = num(LAT_COL), num(LON_COL), num(ALT_COL)
    spd = np.full(len(df), np.nan)
    for c in SPD_COLS:                                   # first available channel fills the rows; later ones fill remaining gaps
        v = num(c)
        spd = np.where(np.isfinite(spd), spd, v)
    ok = np.isfinite(t) & np.isfinite(lat) & np.isfinite(lon) & ~((lat == 0) & (lon == 0))
    return {"t": t[ok], "lat": lat[ok], "lon": lon[ok], "alt": alt[ok], "spd": spd[ok]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store())
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")) or not os.path.isdir(a.raw_dir):
        print("mynissan_grade: no cloud store or raw directory, skipped (optional)"); return 0
    sys.stdout.reconfigure(encoding="utf-8")
    md5 = mc.md5(a.master)
    res = {"milestone": "M736", "stage": "G0", "spec": "analyses/M736_spec.md Rev 2", "role": "auxiliary", "masterMd5": md5, "pinnedMd5": PINNED_MD5,
           "external_inputs_used": [], "privacy": "aggregates only; no coordinates or tracks"}
    if md5 != PINNED_MD5:
        res["stopped"] = "master md5 differs from the pin"
        os.makedirs(a.out_dir, exist_ok=True)
        json.dump(res, open(os.path.join(a.out_dir, "M736_g0.json"), "w", encoding="utf-8"), indent=1)
        print("mynissan_grade: master pin failed"); return 1
    master = mc.load_master(a.master)
    idx = raw_index(a.raw_dir)
    geo = mi.load_stream(a.store, "Geolocation")
    cpos = []
    for t, x in geo:
        la, lo = mc.fnum(x["LocationLatitude"]), mc.fnum(x["LocationLongitude"])
        if la is None or lo is None or (la == 0 and lo == 0):
            continue
        if mc.BOX[0] <= la <= mc.BOX[1] and mc.BOX[2] <= lo <= mc.BOX[3]:
            cpos.append((t, la, lo))
    ct = np.array([c[0] for c in cpos]); cla = np.array([c[1] for c in cpos]); clo = np.array([c[2] for c in cpos])
    res["cloud_positions_screened"] = len(cpos)
    res["cloud_sample_interval_s_median"] = float(np.median(np.diff(ct))) if len(ct) > 1 else None

    p1 = {s: {c[2]: {"err": [], "day": [], "drive": set()} for c in SPEED_CLASSES} for s in SHIFTS}
    geom = {c[2]: {"spacing_m": [], "n": 0} for c in SPEED_CLASSES}
    segs = []   # per qualifying segment: day, drive, grade, cells, heading, km
    n_files = n_pos = n_alt = 0
    n_track_ok = n_track_rej = 0
    alt_pts_total = 0
    for m in master:
        key = re.sub(r"\D", "", os.path.basename(m["file"]))
        path = idx.get(key)
        if not path:
            continue
        o = read_obd(path, m["t0"])
        if o is None or len(o["t"]) < 3:
            continue
        n_files += 1
        n_pos += 1
        # cloud fixes inside the padded window
        i0, i1 = bisect.bisect_left(ct, m["t0"] - 60.0), bisect.bisect_right(ct, m["t1"] + 60.0)
        has_cloud = (i1 - i0) >= 2
        pr = path_ratio(o["t"], o["lat"], o["lon"], o["spd"])
        track_ok = pr is not None and RATIO_LO <= pr <= RATIO_HI
        n_track_ok += int(track_ok); n_track_rej += int(not track_ok)
        if not track_ok:
            has_cloud = False
        okrow = window_ok(o["t"], o["lat"], o["lon"], o["spd"]) if track_ok else np.zeros(len(o["t"]), bool)
        if has_cloud:
            tq = ct[i0:i1]
            vs = np.isfinite(o["spd"])
            ospd = np.interp(tq, o["t"][vs], o["spd"][vs]) if vs.sum() >= 2 else np.zeros(len(tq))   # interpolate over the rows that carry speed
            sp_c = [speed_class(v) for v in ospd]
            for s in SHIFTS:
                tr = interp_track(tq + s, o["t"], o["lat"], o["lon"])
                jj = np.clip(np.searchsorted(o["t"], tq + s), 1, len(o["t"]) - 1)
                ok = np.isfinite(tr[:, 0]) & okrow[jj] & okrow[jj - 1]
                if not ok.any():
                    continue
                err = hav_arr(cla[i0:i1][ok], clo[i0:i1][ok], tr[ok, 0], tr[ok, 1])
                for e, c in zip(err, np.array(sp_c, dtype=object)[ok]):
                    if c is None:
                        continue
                    p1[s][c]["err"].append(float(e)); p1[s][c]["day"].append(m["date"]); p1[s][c]["drive"].add(m["file"])
            d_c = hav_arr(cla[i0:i1][:-1], clo[i0:i1][:-1], cla[i0:i1][1:], clo[i0:i1][1:])
            for dm, dt, c in zip(d_c, np.diff(tq), sp_c[:-1]):
                if c is not None and dt <= 120.0:
                    geom[c]["spacing_m"].append(float(dm)); geom[c]["n"] += 1
        has_alt = np.isfinite(o["alt"])
        if has_alt.any():
            n_alt += 1
            alt_pts_total += int(has_alt.sum())
        cd = cum_dist(o["lat"], o["lon"])
        for run in (altitude_runs(o["t"], has_alt) if track_ok else []):
            if len(run) < 2:
                continue
            dr = cd[run] - cd[run[0]]
            for c0, c1 in chunk_run(dr):
                ii = run[c0:c1]
                if len(ii) < MIN_ALT_PTS:
                    continue
                seg_pr = path_ratio(o["t"][run[c0]:run[c1 - 1] + 1], o["lat"][run[c0]:run[c1 - 1] + 1], o["lon"][run[c0]:run[c1 - 1] + 1], o["spd"][run[c0]:run[c1 - 1] + 1])
                if seg_pr is None or not RATIO_LO <= seg_pr <= RATIO_HI:
                    continue
                g = ols_grade(cd[ii], o["alt"][ii])
                if g is None:
                    continue
                seg_run = slice(run[c0], run[c1 - 1] + 1)
                segs.append({"day": m["date"], "drive": m["file"], "grade": g, "cloud": has_cloud, "len_m": float(cd[ii[-1]] - cd[ii[0]]),
                             "cells": cell_set(o["lat"][seg_run], o["lon"][seg_run]), "head": heading_vec(o["lat"][seg_run], o["lon"][seg_run])})

    res["obd_files_with_position"] = n_files
    res["obd_files_with_altitude"] = n_alt
    res["obd_altitude_samples"] = alt_pts_total
    res["obd_track_screen"] = {"rule": "GPS path length / integral of OBD speed in [%.2f, %.2f] per drive, per 60 s window for position agreement and per segment for grade (frozen or jumping logged GPS fails)" % (RATIO_LO, RATIO_HI), "drives_passing": n_track_ok, "drives_failing_or_untestable": n_track_rej}
    # P1
    p1o = {}
    for s in SHIFTS:
        p1o["shift_%+.0fs" % s] = {}
        for _, _, cn in SPEED_CLASSES:
            e = np.array(p1[s][cn]["err"])
            p1o["shift_%+.0fs" % s][cn] = (
                {"n_fixes": int(len(e)), "n_drives": len(p1[s][cn]["drive"]), "n_days": len(set(p1[s][cn]["day"])),
                 "median_m": float(np.median(e)), "p90_m": float(np.percentile(e, 90)), "share_within_150m": float((e <= 150).mean()),
                 "median_ci95_m": boot_median(e, p1[s][cn]["day"], a.nb)} if len(e) else {"n_fixes": 0})
    res["P1_position_agreement"] = p1o
    res["cloud_track_geometry"] = {cn: ({"n_steps": g["n"], "spacing_m_median": float(np.median(g["spacing_m"])), "spacing_m_p90": float(np.percentile(g["spacing_m"], 90))}
                                        if g["n"] else {"n_steps": 0}) for cn, g in geom.items()}
    # support of the P2 validation set (segments with a cloud track)
    qual = [s_ for s_ in segs if s_["cloud"]]
    all_cells = set().union(*[s_["cells"] for s_ in qual]) if qual else set()
    days = sorted({s_["day"] for s_ in qual})
    unique_km = len(all_cells) * 0.1   # one 0.001-degree cell is about 0.1 km of road (approximation, stated in the output)
    gr = np.array([s_["grade"] for s_ in qual]) if qual else np.zeros(0)
    # repeat traversals: same direction, different days, cell Jaccard >= 0.6
    diffs, n_pairs = [], 0
    for i in range(len(qual)):
        for j in range(i + 1, len(qual)):
            A, B = qual[i], qual[j]
            if A["day"] == B["day"]:
                continue
            inter = len(A["cells"] & B["cells"])
            if inter == 0 or inter / len(A["cells"] | B["cells"]) < 0.6:
                continue
            ha, hb = A["head"], B["head"]
            if ha[0] * hb[0] + ha[1] * hb[1] <= 0:
                continue
            diffs.append(A["grade"] - B["grade"]); n_pairs += 1
    floor = noise_floor(diffs)
    res["P2_validation_support"] = {
        "qualifying_segments_all": len(segs), "qualifying_segments_with_cloud_track": len(qual), "drives": len({s_["drive"] for s_ in qual}),
        "days": len(days), "total_km": float(sum(s_["len_m"] for s_ in qual) / 1000.0), "unique_km_approx_100m_cells": float(unique_km),
        "grade_sd_pp": float(np.std(gr, ddof=1)) if len(gr) > 1 else None,
        "class_shares_below-2_flat_above2": ([float((gr < -2).mean()), float(((gr >= -2) & (gr <= 2)).mean()), float((gr > 2).mean())] if len(gr) else None),
        "repeat_traversal_pairs": n_pairs, "reference_noise_floor_pp_L500": floor,
        "reverse_movement_screen": "not available (no gear channel, speed unsigned); not applied at G0",
        "note": "OBD altitude is sparse: files with altitude carry few altitude samples, so qualifying 500 m segments are counted, not assumed"}
    res["G0_gate"] = g0_decision(len(days), unique_km, n_pairs, floor)
    if mc.md5(a.master) != PINNED_MD5:
        print("mynissan_grade: master changed during the run"); return 1
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(res, open(os.path.join(a.out_dir, "M736_g0.json"), "w", encoding="utf-8"), indent=1)
    print("mynissan_grade G0:", json.dumps(res["G0_gate"]), "| segments", len(qual), "days", len(days), "unique km %.1f" % unique_km, "pairs", n_pairs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
