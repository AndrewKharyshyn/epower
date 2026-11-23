#!/usr/bin/env python3
"""M752 (spec analyses/M752_spec.md Rev 2): cloud-reported odometer at both ends of every logged drive, and the difference between the cloud-reported distance and the logged distance.
REPORT-ONLY side table and statistics; no master column, payload, dashboard or published figure changes.

Estimators (spec 9.1): E_int (linear interpolation inside a bracket of at most 35 s, flat-bracket rule: rows differing by at most 0.05 km give an exact endpoint whatever the gap) is the primary
and is biased LOW at drive edges; E_br (last row at or before the start, first row at or after the end) extends the window and is biased HIGH; they are a lower and an upper bracket on the same drives.
E_near (nearest row within 30 s of each end, the M729 rule) and the +16 s clock shift (cloud time T-16 for OBD time T) are sensitivities. The cloud value is 'cloud-reported, interpolated'; the
difference to the logged distance is a 'difference', never an error or correction, and nothing here is substituted into distance_km or the logged-share KPI.
Usage: python tools/drive_odometer.py [--store DIR] [--out-dir analyses] [--nb 4000]   (no cloud store -> skipped, exit 0)"""
import argparse, bisect, csv, hashlib, json, os, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_import as mi
import mynissan_coverage as mc

REGISTERED_MASTER = "d514d6009d6d9a0a168ad4fb09b9bb98"
CAP_S, FLAT_KM, REGRESS_KM, NEAR_S, NEAR60_S, SHIFT_S = 35.0, 0.05, 0.05, 30.0, 60.0, 16.0
N_MIN, DAYS_MIN, SEED, NB_DEFAULT = 20, 10, 42, 4000
MARGIN_PRIMARY, MARGIN_WIDE, MEDIAN_ABS_KM, SHORT_KM, IDENT_KM = 0.01, 0.03, 0.25, 2.0, 0.05
GAIN_RAW_KM, GAIN_TOL_KM = 13285.0390625, 0.01
ANCHOR_TOL_KM = 1.0


class Stop(Exception):
    pass


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


# ---------------------------------------------------------------------------- odometer rows
def accepted_odo(rows, conflict_t=()):
    """rows: [(t, value)] sorted by t. Drops conflict rows and non-numeric values. Rev 2.1 (spec 10.1): NO global monotone filter (the cloud odometer has level excursions of tens of km that a running-maximum
    rule would turn into hundreds of discarded valid rows); jumps are handled locally per drive window by jump_in_window. Counts the negative steps and the level excursions for disclosure.
    Returns (ts, vs, counts)."""
    ts, vs, cnt = [], [], {"rows": len(rows), "conflict": 0, "nonnumeric": 0}
    cset = set(conflict_t)
    for t, v in rows:
        if t in cset:
            cnt["conflict"] += 1
            continue
        if v is None or not np.isfinite(v):
            cnt["nonnumeric"] += 1
            continue
        ts.append(t)
        vs.append(v)
    cnt["accepted"] = len(ts)
    ts, vs = np.asarray(ts, float), np.asarray(vs, float)
    if len(ts) > 1:
        dv = np.diff(vs)
        cnt["negativeSteps"] = int((dv < -REGRESS_KM).sum())
        run = np.maximum.accumulate(vs)
        below = vs < run - REGRESS_KM
        edges = np.diff(np.r_[0, below.astype(int)])
        cnt["levelExcursions"] = int((edges == 1).sum())
        cnt["maxExcursionKm"] = round(float((run - vs).max()), 2)
    return ts, vs, cnt


def jump_in_window(t_lo, t_hi, ts, vs):
    """True when consecutive rows inside [t_lo - CAP, t_hi + CAP] contain a negative step or a positive step that implies more than 180 km/h (an odometer level jump inside the drive)."""
    i0 = max(int(np.searchsorted(ts, t_lo - CAP_S, side="left")) - 1, 0)
    i1 = min(int(np.searchsorted(ts, t_hi + CAP_S, side="right")) + 1, len(ts))
    if i1 - i0 < 2:
        return False
    dv, dt = np.diff(vs[i0:i1]), np.diff(ts[i0:i1])
    if (dv < -REGRESS_KM).any():
        return True
    fast = (dv > REGRESS_KM) & (dt > 0) & (dv > dt * mc.PHYSICAL_MAX_KMH / 3600.0 + REGRESS_KM)
    return bool(fast.any())


def odo_at(t, ts, vs, mode, shift=0.0):
    """Cloud-reported odometer for OBD time t. mode: int | br_start | br_end | near | near60. Returns (value or None, age_s or None, reason).
    reason: ok | flat | outside_span | no_row_within_cap | hole (bracket gap of 24 h or more that is not flat)."""
    tq = t - shift
    i1 = int(np.searchsorted(ts, tq, side="left"))            # first row at or after tq
    i0 = int(np.searchsorted(ts, tq, side="right")) - 1       # last row at or before tq
    if mode in ("near", "near60"):
        lim = NEAR_S if mode == "near" else NEAR60_S
        best = None
        for j in (i0, i1):
            if 0 <= j < len(ts):
                d = abs(ts[j] - tq)
                if best is None or d < best[0]:
                    best = (d, j)
        if best is None or best[0] > lim:
            return None, None, "no_row_within_cap" if len(ts) and ts[0] <= tq <= ts[-1] else "outside_span"
        return float(vs[best[1]]), float(best[0]), "ok"
    if i0 < 0 or i1 >= len(ts):
        return None, None, "outside_span"
    gap = ts[i1] - ts[i0]
    flat = (vs[i1] - vs[i0]) <= FLAT_KM
    if not flat and gap > CAP_S:
        return None, None, "hole" if gap >= 86400.0 else "no_row_within_cap"
    age = float(min(tq - ts[i0], ts[i1] - tq))
    if mode == "br_start":
        return float(vs[i0]), float(tq - ts[i0]), "flat" if flat else "ok"
    if mode == "br_end":
        return float(vs[i1]), float(ts[i1] - tq), "flat" if flat else "ok"
    if flat:
        return float(vs[i0]), age, "flat"
    w = (tq - ts[i0]) / gap if gap > 0 else 0.0
    return float(vs[i0] + w * (vs[i1] - vs[i0])), age, "ok"


def drive_endpoints(t0, t1, ts, vs):
    """All estimators for one drive: {name: (odo_start, odo_end, dist, reasons)}."""
    out = {}
    if jump_in_window(t0, t1, ts, vs):
        return {n: {"start": None, "end": None, "ageStart": None, "ageEnd": None, "reasonStart": "odometer_jump", "reasonEnd": "odometer_jump", "dist": None}
                for n in ("E_int", "E_br", "E_near", "E_near60", "E_int_shift16")}
    specs = {"E_int": ("int", "int", 0.0), "E_br": ("br_start", "br_end", 0.0), "E_near": ("near", "near", 0.0), "E_near60": ("near60", "near60", 0.0), "E_int_shift16": ("int", "int", SHIFT_S)}
    for name, (ms, me, sh) in specs.items():
        a, aa, ra = odo_at(t0, ts, vs, ms, sh)
        b, ab, rb = odo_at(t1, ts, vs, me, sh)
        ok = a is not None and b is not None
        out[name] = {"start": a, "end": b, "ageStart": aa, "ageEnd": ab, "reasonStart": ra, "reasonEnd": rb, "dist": (b - a) if ok else None}
    return out


# ---------------------------------------------------------------------------- statistics
def boot_stats(delta, logged, days, nb, seed=SEED):
    """Day-clustered percentile bootstrap of: median difference, median |difference|, 90th percentile |difference|, aggregate relative difference (sum diff / sum logged)."""
    delta, logged, days = np.asarray(delta, float), np.asarray(logged, float), np.asarray(days)
    codes, uniq = pd.factorize(days)
    groups = [np.where(codes == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    draws = {"median": [], "medianAbs": [], "p90Abs": [], "relative": []}
    for _ in range(nb):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        d, l = delta[idx], logged[idx]
        draws["median"].append(np.median(d))
        draws["medianAbs"].append(np.median(np.abs(d)))
        draws["p90Abs"].append(np.percentile(np.abs(d), 90))
        draws["relative"].append(d.sum() / l.sum() if l.sum() > 0 else np.nan)
    out = {}
    pt = {"median": float(np.median(delta)), "medianAbs": float(np.median(np.abs(delta))), "p90Abs": float(np.percentile(np.abs(delta), 90)), "relative": float(delta.sum() / logged.sum())}
    for k, v in draws.items():
        a = np.array(v)
        a = a[np.isfinite(a)]
        out[k] = {"est": round(pt[k], 5), "ci95": [round(float(np.percentile(a, 2.5)), 5), round(float(np.percentile(a, 97.5)), 5)]}
    return out


def summarise(df, nb, seed=SEED):
    """df: rows with delta, logged, day. Support floor 20 drives and 10 days; below it only counts."""
    n, days = int(len(df)), int(df["day"].nunique()) if len(df) else 0
    res = {"nDrives": n, "nDays": days}
    if n < N_MIN or days < DAYS_MIN:
        res["status"] = "not estimable at this support (counts only)"
        return res
    res.update(boot_stats(df["delta"].to_numpy(), df["logged"].to_numpy(), df["day"].to_numpy(), nb, seed))
    return res


def verdict(summary, margin=MARGIN_PRIMARY):
    """Wording per spec 9.3: consistent within the margin when the interval of the aggregate relative difference lies inside it and the median |difference| is at most 0.25 km."""
    if "relative" not in summary:
        return "not estimable at this support"
    lo, hi = summary["relative"]["ci95"]
    parts = []
    if not (lo >= -margin and hi <= margin):
        parts.append("aggregate relative difference %.2f %% [%.2f, %.2f] reaches beyond +-%g %%" % (100 * summary["relative"]["est"], 100 * lo, 100 * hi, 100 * margin))
    if summary["medianAbs"]["est"] > MEDIAN_ABS_KM:
        parts.append("median |difference| %.2f km above %.2f km" % (summary["medianAbs"]["est"], MEDIAN_ABS_KM))
    return "; ".join(parts) if parts else "consistent within +-%g %%" % (100 * margin)


def stratum_of(km):
    return "below2km" if km < SHORT_KM else ("2to10km" if km < 10 else "10kmplus")


def anchor(dash_odo, cloud_last_odo, t_last, drives_after):
    """Single-point plausibility check: cloud ODO at the last accepted row plus the logged distance of the part of every drive after that row, against the dash reading (integer, probably truncated)."""
    add = 0.0
    for t0, t1, km in drives_after:
        if t1 <= t_last:
            continue
        frac = 1.0 if t0 >= t_last else (t1 - t_last) / (t1 - t0)
        add += km * frac
    est = cloud_last_odo + add
    return {"dashOdoKm": dash_odo, "cloudLastOdoKm": round(cloud_last_odo, 3), "loggedKmAfterLastRow": round(add, 3), "cloudPlusLogged": round(est, 3), "differenceKm": round(dash_odo - est, 3),
            "withinTolerance": bool(abs(dash_odo - est) <= ANCHOR_TOL_KM), "n": 1, "note": "single-point, one-sided plausibility check (no interval): the dash reading is an integer, probably truncated, and unlogged driving after the last row cannot be ruled out"}


def check_gain(ts, vs):
    gain = float(vs[-1] - vs[0])
    if abs(gain - GAIN_RAW_KM) > GAIN_TOL_KM:
        raise Stop("control V0: cloud odometer gain %.7f differs from the registered %.7f km" % (gain, GAIN_RAW_KM))
    return gain


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store())
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")):
        print("drive_odometer: no cloud store, skipped (optional)")
        return 0
    t_start = time.time()
    try:
        m0 = md5(a.master)
        if m0 != REGISTERED_MASTER:
            raise Stop("master MD5 %s differs from the registered master (a rerun on a larger corpus needs its own addendum)" % m0)
        rows = [(t, mc.fnum(x.get("StatusDistanceTotalizerComputed", ""))) for t, x in mi.load_stream(a.store, "Odometer")]
        conf = set()
        cp = os.path.join(a.store, "conflicts.csv")
        if os.path.exists(cp):
            for r in csv.DictReader(open(cp, encoding="utf-8", newline="")):
                if r["stream"] == "Odometer":
                    conf.add(mi.to_epoch(r["timestamp_utc"]))
        ts, vs, cnt = accepted_odo(rows, conf)
        gain = check_gain(ts, vs)
        master = mc.load_master(a.master)
        mdf = pd.read_csv(a.master, usecols=["file", "distance_km", "odo_start", "odo_end", "ens_outlier_v2", "distance_source"], low_memory=False).set_index("file")
        recs = []
        for m in master:
            r = mdf.loc[m["file"]]
            logged = float(r["distance_km"]) if pd.notna(r["distance_km"]) else None
            ident = (logged is not None and pd.notna(r["odo_end"]) and abs(logged - (float(r["odo_end"]) - float(r["odo_start"]))) <= IDENT_KM)
            clean = (r["ens_outlier_v2"] is False) or (str(r["ens_outlier_v2"]) == "False")
            ep = drive_endpoints(m["t0"], m["t1"], ts, vs)
            row = {"file": m["file"], "date": m["date"], "month": m["date"][:7], "t0": m["t0"], "t1": m["t1"], "logged": logged, "identity": bool(ident), "clean": bool(clean), "distance_source": str(r["distance_source"]) if pd.notna(r["distance_source"]) else ""}
            for name, e in ep.items():
                row[name + "_start"], row[name + "_end"] = e["start"], e["end"]
                row[name + "_dist"] = e["dist"]
                row[name + "_reason"] = e["reasonStart"] if e["reasonStart"] != "ok" and e["reasonStart"] != "flat" else e["reasonEnd"]
                row[name + "_ageStart"], row[name + "_ageEnd"] = e["ageStart"], e["ageEnd"]
            recs.append(row)
        df = pd.DataFrame(recs)
        df["stratum"] = df["logged"].map(lambda v: stratum_of(v) if v is not None and not pd.isna(v) else None)
        # P0 coverage
        cov = {"drives": int(len(df))}
        for name in ("E_int", "E_br", "E_near", "E_near60", "E_int_shift16"):
            av = df[name + "_dist"].notna()
            reasons = df.loc[~av, name + "_reason"].value_counts().to_dict()
            cov[name] = {"available": int(av.sum()), "unavailableByReason": {k: int(v) for k, v in reasons.items()}}
        avail = df["E_int_dist"].notna()
        sel = {"byStratum": {}, "byMonth": {}}
        for s in ("below2km", "2to10km", "10kmplus"):
            sub = df[df["stratum"] == s]
            sel["byStratum"][s] = {"drives": int(len(sub)), "available": int(sub["E_int_dist"].notna().sum())}
        for mth, sub in df.groupby("month"):
            sel["byMonth"][mth] = {"drives": int(len(sub)), "available": int(sub["E_int_dist"].notna().sum())}
        # P1 agreement
        elig = df[df["clean"] & df["logged"].notna()]
        p1, verdicts = {}, {}
        for name in ("E_int", "E_br", "E_near", "E_near60", "E_int_shift16"):
            sub = elig[elig[name + "_dist"].notna()].copy()
            sub["delta"] = sub[name + "_dist"] - sub["logged"]
            sub["day"] = sub["date"]
            block = {"identityClass": {}, "strata": {}}
            prim = sub[sub["identity"]]
            block["primary_identity_ge2km"] = summarise(prim[prim["logged"] >= SHORT_KM], a.nb)
            block["all_ge2km"] = summarise(sub[sub["logged"] >= SHORT_KM], a.nb)
            block["identityClass"]["identity"] = summarise(prim, a.nb)
            block["identityClass"]["notIdentity"] = {"nDrives": int((~sub["identity"]).sum()), "nDays": int(sub.loc[~sub["identity"], "day"].nunique()), "note": "sensitivity class (trip_meter, repaired or other non-identity drives): counts only unless the floor is met"}
            for s in ("below2km", "2to10km", "10kmplus"):
                ss = prim[prim["stratum"] == s]
                block["strata"][s] = ({"nDrives": int(len(ss)), "nDays": int(ss["day"].nunique()), "status": "counts only: no agreement verdict below 2 km (resolution)"} if s == "below2km" else summarise(ss, a.nb))
            p1[name] = block
            if name == "E_int":
                verdicts["primary_E_int_identity_ge2km"] = {"within1pct": verdict(block["primary_identity_ge2km"], MARGIN_PRIMARY), "within3pct": verdict(block["primary_identity_ge2km"], MARGIN_WIDE)}
        # P2 resolution
        dv = np.diff(vs)
        pos = dv[dv > 0]
        p2 = {"smallestPositiveCloudIncrementKm": round(float(pos.min()), 5) if len(pos) else None, "loggedResolutionKm": 0.1,
              "note": "a per-drive difference below the combined resolution is not read as disagreement"}
        # P3 anchor
        cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))["vehicle"]
        after = [(r["t0"], r["t1"], r["logged"]) for r in recs if r["logged"] is not None and r["t1"] > ts[-1]]
        p3 = anchor(float(cfg["odometerKm"]), float(vs[-1]), float(ts[-1]), after)
        p3["odometerAsOf"] = cfg.get("odometerAsOf")
        res = {"milestone": "M752", "spec": "analyses/M752_spec.md Rev 2", "role": "report-only; cloud-reported, interpolated odometer at drive ends; differences to the logged distance",
               "masterMd5": m0, "registeredMasterMd5": REGISTERED_MASTER, "storeManifestSha256": sha256(os.path.join(a.store, "manifest.json")), "seed": SEED, "nBoot": a.nb, "toolSha256": sha256(os.path.abspath(__file__)),
               "control_V0": {"cloudGainKm": gain, "registeredGainKm": GAIN_RAW_KM, "status": "reproduced"}, "P4_integrity": cnt,
               "P0_coverage": cov, "P0_selection_check": sel, "P1_agreement": p1, "P1_verdict_wording": verdicts, "P2_resolution": p2, "P3_anchor": p3,
               "reading": "consistent with the cloud-reported odometer; both counters rest on the same wheel-speed scale so a common scale error is undetectable; E_int is a lower and E_br an upper bracket; not distance accuracy",
               "scope": "report-only: no master column, payload or dashboard change; never substituted into distance_km or the logged-share KPI", "seconds": round(time.time() - t_start, 1)}
        if md5(a.master) != m0:
            raise Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        json.dump(res, open(os.path.join(a.out_dir, "M752_odometer_agreement.json"), "w", encoding="utf-8", newline="\n"), indent=1, default=float)
        cols = ["file", "date", "logged", "identity", "clean", "E_int_start", "E_int_end", "E_int_ageStart", "E_int_ageEnd", "E_int_reason", "E_br_start", "E_br_end"]
        df[cols].round(3).to_csv(os.path.join(a.out_dir, "M752_drive_odometer.csv"), index=False, lineterminator="\n")
        print("drive_odometer: %d drives; E_int available %d; V0 ok; %.0f s" % (len(df), cov["E_int"]["available"], res["seconds"]))
        return 0
    except Stop as e:
        print("drive_odometer: STOP (%s); nothing written" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
