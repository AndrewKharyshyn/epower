#!/usr/bin/env python3
"""M730: cloud-to-OBD clock offset and speed agreement (auxiliary diagnostic, report-only). Spec: analyses/M730_spec.md Rev 1.
Reads raw/ drive CSVs read-only and the M729 cloud store; writes analyses/M730_clock_offset.json and M730_clock_offset_drives.csv.
Usage: python tools/mynissan_clock_offset.py [--store DIR] [--raw DIR] [--out-dir analyses] [--limit N]"""
import argparse, csv, json, os, re, sys
from datetime import datetime
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mynissan_import as mi
import mynissan_coverage as mc

ROOT = mi.ROOT
SPEED, PEDAL = "Швидкість автомобіля (km/h)", "Положення педалі акселератора D (%)"
OFFS = np.arange(-60, 61)
MIN_MATCH, MIN_SD, MIN_CLOUD_KMH, MAX_OBD_GAP = 8, 3.0, 10.0, 3.0
KEY = lambda name: re.sub(r"\D", "", os.path.splitext(name)[0])


def obd_series(path, date):
    d = pd.read_csv(path, usecols=lambda c: c in ("time", SPEED, PEDAL), dtype=str)
    hms = d["time"].str.extract(r"(\d+):(\d+):(\d+(?:\.\d+)?)").astype(float)
    sod = (hms[0] * 3600 + hms[1] * 60 + hms[2]).to_numpy()
    sod = sod + 86400.0 * np.cumsum(np.r_[0, (np.diff(sod) < -43200).astype(int)])  # midnight rollover
    day0 = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=mc.KYIV).timestamp()
    t = day0 + sod
    out = {}
    for name, col in (("speed", SPEED), ("pedal", PEDAL)):
        if col in d.columns:
            v = pd.to_numeric(d[col], errors="coerce").to_numpy()
            ok = ~np.isnan(v)
            out[name] = (t[ok], v[ok])
    return out


def interp_valid(ot, ov, q):
    """linear interpolation at q, valid only inside a bracket of observations at most MAX_OBD_GAP apart"""
    if len(ot) < 2:
        return np.full(len(q), np.nan)
    i = np.searchsorted(ot, q)
    ok = (i > 0) & (i < len(ot))
    ii = np.clip(i, 1, len(ot) - 1)
    t0, t1 = ot[ii - 1], ot[ii]
    ok &= (t1 - t0) <= MAX_OBD_GAP
    w = np.where(t1 > t0, (q - t0) / np.where(t1 > t0, t1 - t0, 1), 0)
    res = ov[ii - 1] + w * (ov[ii] - ov[ii - 1])
    return np.where(ok, res, np.nan)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store()); ap.add_argument("--raw", default=os.path.join(ROOT, "raw"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses")); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")):
        print("mynissan_clock_offset: no cloud store, skipped (optional)"); return 0
    trip = mi.load_stream(a.store, "Trip_Information")
    cspd = [(t, mc.speed_kmh(x["SpeedDisplayedValueinkmh"])) for t, x in trip if mc.speed_kmh(x["SpeedDisplayedValueinkmh"]) is not None]
    cped = [(t, mc.fnum(x["AcceleratorPedalOpeningRatio"])) for t, x in trip if x["AcceleratorPedalOpeningRatio"] != ""]
    ct, cv = np.array([p[0] for p in cspd]), np.array([p[1] for p in cspd])
    pt, pv = np.array([p[0] for p in cped]), np.array([p[1] for p in cped])
    raw = {KEY(f): f for f in os.listdir(a.raw) if f.endswith(".csv") and not f.startswith("e4ORCE")}
    master = mc.load_master(a.master)
    drives = []
    for d in master[: a.limit or None]:
        rf = raw.get(KEY(d["file"]))
        if not rf:
            continue
        m = (ct >= d["t0"]) & (ct <= d["t1"]) & (cv >= MIN_CLOUD_KMH)
        if m.sum() < MIN_MATCH:
            continue
        try:
            s = obd_series(os.path.join(a.raw, rf), d["date"])
        except Exception:
            continue
        if "speed" not in s:
            continue
        T, V = ct[m], cv[m]
        errs = {}
        for o in OFFS:
            q = interp_valid(s["speed"][0], s["speed"][1], T + o)
            ok = ~np.isnan(q)
            errs[int(o)] = np.abs(V[ok] - q[ok]) if ok.sum() >= MIN_MATCH else np.array([])
        q0 = interp_valid(s["speed"][0], s["speed"][1], T)
        if len(errs[0]) < MIN_MATCH or np.std(V[~np.isnan(q0)]) < MIN_SD:
            continue
        med = {o: float(np.median(e)) for o, e in errs.items() if len(e)}
        best = min(med, key=lambda o: (med[o], abs(o)))
        mp = (pt >= d["t0"]) & (pt <= d["t1"])
        drives.append({"file": d["file"], "date": d["date"], "month": d["date"][:7], "day": int(d["date"][8:]), "dur_s": d["t1"] - d["t0"], "n": len(errs[0]),
                       "best": best, "mae0": med[0], "mae_best": med[best], "errs": errs, "pedal": (pt[mp], pv[mp], s.get("pedal"))})
    if not drives:
        print("no eligible drives"); return 1

    def pooled(sub, o):
        e = [x["errs"][o] for x in sub if len(x["errs"][o])]
        return float(np.median(np.concatenate(e))) if e else float("nan")

    def best_global(sub):
        sc = {int(o): pooled(sub, int(o)) for o in OFFS}
        sc = {o: v for o, v in sc.items() if not np.isnan(v)}
        return min(sc, key=lambda o: (sc[o], abs(o))), sc

    gl, sc = best_global(drives)
    bests = np.array([x["best"] for x in drives])
    res = {"milestone": "M730", "spec": "analyses/M730_spec.md Rev 1", "role": "auxiliary", "n_drives": len(drives), "n_days": len({x["date"] for x in drives}),
           "pooled_best_offset_s": gl, "pooled_median_abs_err_at_0": sc[0], "pooled_median_abs_err_at_best": sc[gl],
           "per_drive_best": {"median": float(np.median(bests)), "p10": float(np.percentile(bests, 10)), "p90": float(np.percentile(bests, 90)),
                              "share_within_30s": float(np.mean(np.abs(bests) <= 30)), "share_within_60s": float(np.mean(np.abs(bests) <= 60))}}
    split = {}
    for tr_par in (1, 0):
        tr = [x for x in drives if x["day"] % 2 == tr_par]
        te = [x for x in drives if x["day"] % 2 != tr_par]
        if not tr or not te:
            continue
        g, _ = best_global(tr)
        own = float(np.median(np.concatenate([x["errs"][x["best"]] for x in te])))
        split["train_odd_days" if tr_par else "train_even_days"] = {
            "global_offset_s": g, "n_train": len(tr), "n_test": len(te), "test_median_abs_err_at_0": pooled(te, 0),
            "test_median_abs_err_at_global": pooled(te, g), "test_median_abs_err_at_own_best_optimistic": own}
    res["split_validation"] = split

    def grp(keyf):
        return {str(k): {"median_best_s": float(np.median([x["best"] for x in drives if keyf(x) == k])), "n": sum(1 for x in drives if keyf(x) == k)}
                for k in sorted({keyf(x) for x in drives})}
    res["by_month"] = grp(lambda x: x["month"])
    res["by_dst_period"] = grp(lambda x: "before_2026-10-25" if x["date"] < "2026-10-25" else "after_2026-10-25")
    q = np.percentile([x["dur_s"] for x in drives], [33.3, 66.7])
    res["by_duration_tercile"] = grp(lambda x: int(np.searchsorted(q, x["dur_s"])))
    rng = np.random.default_rng(42)
    days = sorted({x["date"] for x in drives})
    byday = {dd: np.array([x["best"] for x in drives if x["date"] == dd]) for dd in days}
    boots = [float(np.median(np.concatenate([byday[days[i]] for i in rng.integers(0, len(days), len(days))]))) for _ in range(4000)]
    res["median_best_offset_ci95_day_bootstrap"] = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
    diffs = {0: [], gl: []}
    for x in drives:
        T, V, ob = x["pedal"]
        if ob is None or len(T) == 0:
            continue
        for o in diffs:
            qv = interp_valid(ob[0], ob[1], T + o)
            ok = ~np.isnan(qv)
            diffs[o].append(np.abs(V[ok] - qv[ok]))
    if diffs[0] and sum(len(v) for v in diffs[0]):
        res["pedal_secondary"] = {"median_abs_diff_pp_at_0": float(np.median(np.concatenate(diffs[0]))),
                                  "median_abs_diff_pp_at_global": float(np.median(np.concatenate(diffs[gl]))), "n_matches": int(sum(len(v) for v in diffs[0]))}
    sv = list(split.values())
    month_ok = all(abs(v["median_best_s"] - gl) <= 5 for v in res["by_month"].values() if v["n"] >= 5)
    gain = bool(sv) and all(v["test_median_abs_err_at_global"] < v["test_median_abs_err_at_0"] and
                            v["test_median_abs_err_at_global"] - v["test_median_abs_err_at_own_best_optimistic"] <= 0.25 for v in sv)
    res["decision_rule"] = {"held_out_gain_and_within_0.25_of_own_best": bool(gain), "months_within_5s": bool(month_ok),
                            "adopt_global_offset": bool(gain and month_ok), "recommended_offset_s": gl}
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(res, open(os.path.join(a.out_dir, "M730_clock_offset.json"), "w", encoding="utf-8"), indent=1)
    with open(os.path.join(a.out_dir, "M730_clock_offset_drives.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["file", "date", "n_matches", "best_offset_s", "mae_at_0", "mae_at_best"])
        for x in drives:
            w.writerow([x["file"], x["date"], x["n"], x["best"], round(x["mae0"], 3), round(x["mae_best"], 3)])
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
