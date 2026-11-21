#!/usr/bin/env python3
"""M731: cloud tyre pressure as an auxiliary covariate (descriptive, report-only). Spec: analyses/M731_spec.md Rev 1.
Writes analyses/M731_tyre_pressure.json and analyses/M731_tyre_snapshots.csv. Corner fields are read as tenths of kPa (UNVALIDATED scale).
Usage: python tools/mynissan_tyre.py [--store DIR] [--out-dir analyses] [--master drive_master.csv] [--coverage analyses/M729_cloud_coverage.csv]"""
import argparse, bisect, csv, json, os, sys
from datetime import datetime
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mynissan_import as mi
import mynissan_coverage as mc

ROOT = mi.ROOT
CORNERS = ["FrontLeft", "FrontRight", "RearLeft", "RearRight"]
TARGET = {"front": 250.0, "rear": 230.0}
REF_T, SETTLE_S = 15.0, 180.0


def ideal_gas_slope(target):
    return (target + 101.3) / (273.15 + 20.0)


def ols(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store()); ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--coverage", default=os.path.join(ROOT, "analyses", "M729_cloud_coverage.csv"))
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")):
        print("mynissan_tyre: no cloud store, skipped (optional)"); return 0
    veh = mi.load_stream(a.store, "Vehicle_Information")
    alerts = mi.load_stream(a.store, "System_Safety_Alerts")
    amb = [(t, mc.fnum(x["ExternalTempDisplayValue"])) for t, x in veh if x["ExternalTempDisplayValue"] != ""]
    amb_t = [t for t, _ in amb]
    keys = ["StatusWheelPressure" + c for c in CORNERS]
    snaps = []
    for t, x in veh:
        if all(x[k] != "" for k in keys):
            snaps.append({"t": t, "p": [mc.fnum(x[k]) / 10.0 for k in keys]})
    snaps.sort(key=lambda s: s["t"])
    # puncture window from front-right wheel-state code 2
    code2 = [t for t, x in alerts if x["StatusWheelStateFrontRight"] != "" and mc.fnum(x["StatusWheelStateFrontRight"]) == 2.0]
    punct = None
    if code2:
        t_a, t_b = min(code2), max(code2)
        before = [s["p"][1] for s in snaps if s["t"] < t_a][-10:]
        pre = float(np.median(before)) if before else None
        end = None
        for s in snaps:
            if s["t"] > t_b and pre is not None and abs(s["p"][1] - pre) <= 20:
                end = s["t"]; break
        punct = (t_a, end if end is not None else t_b)
    kyiv = lambda t: datetime.fromtimestamp(t, mc.KYIV).isoformat()
    excluded = [s for s in snaps if punct and punct[0] <= s["t"] <= punct[1]]
    keep = [s for s in snaps if s not in excluded]

    def amb_near(t, w=120):
        i = bisect.bisect_left(amb_t, t)
        c = [k for k in (i - 1, i) if 0 <= k < len(amb) and abs(amb_t[k] - t) <= w]
        return amb[min(c, key=lambda k: abs(amb_t[k] - t))][1] if c else None

    master = mc.load_master(a.master)
    # drive join: last snapshot in the padded window
    st = [s["t"] for s in keep]
    rows = []
    for d in master:
        lo, hi = d["t0"] - 60, d["t1"] + 60
        i, j = bisect.bisect_left(st, lo), bisect.bisect_right(st, hi)
        if j <= i:
            continue
        s = keep[j - 1]
        am = [v for t, v in amb if d["t0"] + SETTLE_S <= t <= d["t1"]]
        rows.append({"file": d["file"], "date": d["date"], "km": d["km"], "t": s["t"], "min_into_drive": (s["t"] - d["t0"]) / 60.0, "p": s["p"],
                     "n_snap": j - i, "amb": float(np.mean(am)) if len(am) >= 5 else None})
    res = {"milestone": "M731", "spec": "analyses/M731_spec.md Rev 1", "role": "auxiliary", "scale_assumption": "raw/10 = kPa, UNVALIDATED",
           "snapshots_total": len(snaps), "snapshots_excluded_puncture": len(excluded),
           "puncture_window_kyiv": [kyiv(punct[0]), kyiv(punct[1])] if punct else None, "drives_with_snapshot": len(rows)}
    # E1 level
    e1 = {}
    for ci, c in enumerate(CORNERS):
        tg = TARGET["front" if ci < 2 else "rear"]
        r = np.array([s["p"][ci] / tg for s in keep])
        e1[c] = {"median_ratio": float(np.median(r)), "p25": float(np.percentile(r, 25)), "p75": float(np.percentile(r, 75)), "median_kpa": float(np.median([s["p"][ci] for s in keep]))}
    for ax, idx in (("front_axle", (0, 1)), ("rear_axle", (2, 3))):
        tg = TARGET[ax.split("_")[0]]
        r = np.array([np.mean([s["p"][i] for i in idx]) / tg for s in keep])
        e1[ax] = {"median_ratio": float(np.median(r)), "p25": float(np.percentile(r, 25)), "p75": float(np.percentile(r, 75))}
    ok = all(0.90 <= e1[k]["median_ratio"] <= 1.20 for k in ("front_axle", "rear_axle"))
    e1["reading"] = "plausible, not validated" if ok else "scale unresolved"
    res["E1_level"] = e1
    # E2 temperature response
    rng = np.random.default_rng(42)
    e2, slopes = {}, {}
    sub = [r for r in rows if r["amb"] is not None]
    days = sorted({r["date"] for r in sub})
    for ax, idx in (("front", (0, 1)), ("rear", (2, 3))):
        y = np.array([np.mean([r["p"][i] for i in idx]) for r in sub]); X = np.column_stack([np.ones(len(sub)), [r["amb"] for r in sub], [r["min_into_drive"] for r in sub]])
        b = ols(X, y)
        dm = {dd: np.array([k for k, r in enumerate(sub) if r["date"] == dd]) for dd in days}
        bs = []
        for _ in range(4000):
            pick = np.concatenate([dm[days[i]] for i in rng.integers(0, len(days), len(days))])
            try:
                bs.append(ols(X[pick], y[pick])[1])
            except Exception:
                pass
        ref = ideal_gas_slope(TARGET[ax])
        lo, hi = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
        e2[ax] = {"n_drives": len(sub), "n_days": len(days), "slope_kpa_per_c": float(b[1]), "ci95_day_bootstrap": [lo, hi], "minutes_into_drive_coef_kpa_per_min": float(b[2]),
                  "ideal_gas_reference_kpa_per_c": ref, "ratio_to_reference": float(b[1] / ref), "supported_interval_excludes_zero": bool(lo > 0 or hi < 0)}
        slopes[ax] = float(b[1])
    res["E2_temperature_response"] = e2
    # E3 steps (ambient-adjusted per corner, snapshot level ambient)
    adj = []
    for s in keep:
        am = amb_near(s["t"])
        if am is None:
            continue
        adj.append({"t": s["t"], "v": [s["p"][i] - slopes["front" if i < 2 else "rear"] * (am - REF_T) for i in range(4)]})
    steps = []
    for ci, c in enumerate(CORNERS):
        byday = {}
        for z in adj:
            byday.setdefault(datetime.fromtimestamp(z["t"], mc.KYIV).date().isoformat(), []).append(z)
        dl = sorted(byday); med = [float(np.median([z["v"][ci] for z in byday[dd]])) for dd in dl]
        for i in range(1, len(dl)):
            if abs(med[i] - med[i - 1]) >= 20:
                nxt = [z["v"][ci] for dd in dl[i:] for z in byday[dd]][:5]
                if len(nxt) >= 5 and abs(float(np.median(nxt)) - med[i]) <= 10:
                    steps.append({"corner": c, "date": dl[i], "from_kpa": round(med[i - 1], 1), "to_kpa": round(med[i], 1)})
    res["E3_steps"] = {"n": len(steps), "list": steps, "note": "inflation, tyre swap or leak candidates; never confirmed events"}
    # E4 asymmetry
    e4 = {}
    for ax, (l, r_) in (("front", (0, 1)), ("rear", (2, 3))):
        dd = np.array([r["p"][l] - r["p"][r_] for r in rows])
        dmap = {day: np.array([r["p"][l] - r["p"][r_] for r in rows if r["date"] == day]) for day in sorted({r["date"] for r in rows})}
        dl = sorted(dmap)
        bs = [float(np.median(np.concatenate([dmap[dl[i]] for i in rng.integers(0, len(dl), len(dl))]))) for _ in range(4000)]
        e4[ax] = {"median_left_minus_right_kpa": float(np.median(dd)), "ci95_day_bootstrap": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], "n_drives": len(rows), "n_days": len(dl)}
    res["E4_asymmetry"] = e4
    # E5 feasibility counts
    cov = {r["file"]: r for r in csv.DictReader(open(a.coverage, encoding="utf-8"))} if os.path.exists(a.coverage) else {}
    cand = []
    for r in sub:
        c = cov.get(r["file"])
        if not c or not c.get("pos_first_lat") or not c.get("pos_last_lat") or r["km"] < 3:
            continue
        cand.append({**r, "s": (float(c["pos_first_lat"]), float(c["pos_first_lon"])), "e": (float(c["pos_last_lat"]), float(c["pos_last_lon"])), "pm": float(np.mean(r["p"]))})
    pairs = []
    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            p, q = cand[i], cand[j]
            if abs(p["pm"] - q["pm"]) >= 15 and abs(p["amb"] - q["amb"]) <= 5 and mc.hav_m(p["s"], q["s"]) <= 300 and mc.hav_m(p["e"], q["e"]) <= 300:
                pairs.append((p["file"], q["file"], p["date"], q["date"]))
    pd_days = {d for pr in pairs for d in (pr[2], pr[3])}
    res["E5_feasibility"] = {"candidate_drives": len(cand), "qualifying_pairs": len(pairs), "days_in_pairs": len(pd_days),
                             "meets_30_pairs_15_days": bool(len(pairs) >= 30 and len(pd_days) >= 15), "drives_with_snapshot_by_month": {}}
    for r in rows:
        m = r["date"][:7]
        res["E5_feasibility"]["drives_with_snapshot_by_month"][m] = res["E5_feasibility"]["drives_with_snapshot_by_month"].get(m, 0) + 1
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(res, open(os.path.join(a.out_dir, "M731_tyre_pressure.json"), "w", encoding="utf-8"), indent=1)
    with open(os.path.join(a.out_dir, "M731_tyre_snapshots.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["file", "date", "min_into_drive", "settled_ambient_c", "fl_kpa", "fr_kpa", "rl_kpa", "rr_kpa", "n_snapshots_in_window"])
        for r in rows:
            w.writerow([r["file"], r["date"], round(r["min_into_drive"], 2), "" if r["amb"] is None else round(r["amb"], 2)] + [round(v, 1) for v in r["p"]] + [r["n_snap"]])
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
