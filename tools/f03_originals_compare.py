#!/usr/bin/env python3
"""F03 read-only comparison on the sha256-verified originals (owner-approved 2026-10-03; nothing is copied into raw/, no payload or master write).
Same code, same trips, two bases (raw/ copies vs originals) for the files that FAIL the raw_manifest hash (analyses/F03_originals/failing_keys.json):
 A. M339 charging sub-state: litres of logged fuel while net pack power < -deadband (0.1 / 0.5 / 1 kW), stationary and moving, via tools/fuel_analytics2 (load_trip, classify). Paired by trip; day-clustered percentile bootstrap (seed 42, 4000) of the difference in the charging share of litres (originals minus raw/).
 B. M356 phase energies (compute_summary_arrays._crawl_stop_go_phases): zero shares and medians of the regen-direction and discharge-direction window energies on the same drives, frames from the raw cache (raw/ basis) vs a temporary frame cache built from the originals.
Output: analyses/F03_originals/M365_compare.json. Provenance-sensitivity analysis, not a correction. Usage: python tools/f03_originals_compare.py [--limit N]"""
import json, os, sys, tempfile, time, hashlib
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import recon_engine as RE
import fuel_analytics as fa
import fuel_analytics2 as F2
import compute_summary_arrays as C
import drive_raw_cache as drc
import regen_seasonal_raw as R

ORIG = os.path.abspath(os.path.join(ROOT, "..", "..", "originals_recovered")) + os.sep
RAWD = os.path.join(ROOT, "raw") + os.sep
OUT = os.path.join(ROOT, "analyses", "F03_originals", "M365_compare.json")
DB = F2.DEADBANDS


def charging_row(name, off, base):
    RE.BASE = base
    T = F2.load_trip(name, off)
    if T is None:
        return None
    g, raw_dt = T["g"], T["rawDt"]
    if not (np.isfinite(off) and g["Pbatt"].notna().any()):
        return {"noBattery": True}
    spd, flow = g["spd"].values, g["flow"].values
    capped = np.minimum(raw_dt, fa.DT_CAP); capped[0] = 0.0
    lit = np.nan_to_num(flow) / 3600.0 * capped
    st = F2.classify(spd, raw_dt, fa.DT_CAP, F2.PRIMARY_THR, False)
    pb = np.nan_to_num(g["Pbatt"].values)
    return {"total": float(lit.sum()), **{f"db{d:g}": {"stationary": float(lit[(st == 0) & (pb < -d)].sum()), "moving": float(lit[(st == 1) & (pb < -d)].sum())} for d in DB}}


def boot_diff(days, a_chg, a_tot, b_chg, b_tot, B=4000, seed=42):
    rng = np.random.default_rng(seed)
    ud = np.unique(days); idx = {d: np.where(days == d)[0] for d in ud}
    est = b_chg.sum() / b_tot.sum() - a_chg.sum() / a_tot.sum()
    out = []
    for _ in range(B):
        sel = np.concatenate([idx[d] for d in rng.choice(ud, len(ud))])
        out.append(b_chg[sel].sum() / b_tot[sel].sum() - a_chg[sel].sum() / a_tot[sel].sum())
    return {"est": round(float(est), 5), "ci95": [round(float(np.percentile(out, 2.5)), 5), round(float(np.percentile(out, 97.5)), 5)], "nDays": int(len(ud))}


NAMES_RAW = {fa.key_digits(n): n for n in os.listdir(RAWD) if fa.key_digits(n)}
NAMES_ORIG = {fa.key_digits(n): n for n in os.listdir(ORIG) if fa.key_digits(n)}


def part_a(failing, dm, lim):
    prev = json.load(open("summary_arrays.json", encoding="utf-8")).get("fuelAnalytics", {})
    ok_ids = {t["id"] for t in prev.get("trips", []) if not t["reset"]}
    failing_k = {fa.key_digits(f) for f in failing}
    rows = []
    for _, m in dm.iterrows():
        k = fa.key_digits(m["file"])
        if k not in failing_k or k not in ok_ids or k not in NAMES_ORIG or k not in NAMES_RAW:
            continue
        off = float(m["I_offset_A_applied"]) if pd.notna(m.get("I_offset_A_applied")) else np.nan
        a = charging_row(NAMES_RAW[k], off, RAWD); b = charging_row(NAMES_ORIG[k], off, ORIG)
        if not a or not b or a.get("noBattery") or b.get("noBattery"):
            continue
        rows.append({"file": m["file"], "day": k[:8], "raw": a, "orig": b})
        if lim and len(rows) >= lim:
            break
    res = {"nTrips": len(rows), "nDays": len({r["day"] for r in rows}), "byDeadbandKw": {}}
    days = np.array([r["day"] for r in rows])
    tr = np.array([r["raw"]["total"] for r in rows]); to = np.array([r["orig"]["total"] for r in rows])
    res["totalLitres"] = {"raw": round(float(tr.sum()), 3), "originals": round(float(to.sum()), 3)}
    for d in DB:
        key = f"db{d:g}"
        cr = np.array([r["raw"][key]["stationary"] + r["raw"][key]["moving"] for r in rows]); co = np.array([r["orig"][key]["stationary"] + r["orig"][key]["moving"] for r in rows])
        res["byDeadbandKw"][key] = {
            "litresCharging": {"raw": round(float(cr.sum()), 3), "originals": round(float(co.sum()), 3)},
            "stationaryLitres": {"raw": round(float(sum(r["raw"][key]["stationary"] for r in rows)), 3), "originals": round(float(sum(r["orig"][key]["stationary"] for r in rows)), 3)},
            "movingLitres": {"raw": round(float(sum(r["raw"][key]["moving"] for r in rows)), 3), "originals": round(float(sum(r["orig"][key]["moving"] for r in rows)), 3)},
            "chargingShare": {"raw": round(float(cr.sum() / tr.sum()), 5), "originals": round(float(co.sum() / to.sum()), 5)},
            "shareDifferenceOriginalsMinusRaw": boot_diff(days, cr, tr, co, to)}
    return res


def phase_summary(P):
    o = {"nCycles": P.get("nCycles")}
    for w in ("launch", "approach", "cycle"):
        W = P[w]
        o[w] = {"regenZeroShare": (W.get("regenWh") or {}).get("zeroShare"), "regenMedian": (W.get("regenWh") or {}).get("median"), "regenN": (W.get("regenWh") or {}).get("n"),
                "dischargeZeroShare": (W.get("dischargeWh") or {}).get("zeroShare"), "dischargeMedian": (W.get("dischargeWh") or {}).get("median"), "netMedian": (W.get("netWh") or {}).get("median")}
    return o


def part_b(failing, dm):
    fk = {fa.key_digits(f) for f in failing}
    sub = dm[[fa.key_digits(f) in fk and fa.key_digits(f) in NAMES_ORIG for f in dm["file"]]].reset_index(drop=True)
    with tempfile.TemporaryDirectory() as td:
        t0 = time.time()
        for f in sub["file"]:
            drc.add_file(f, open(ORIG + NAMES_ORIG[fa.key_digits(f)], "rb").read(), cache_dir=td)
        fl_o = drc.make_frame_loader(cache_dir=td)
        fl_r = drc.make_frame_loader()
        Pr = C._crawl_stop_go_phases(sub, R.raw_loader, frame_loader=fl_r)["phaseEnergy"]
        Po = C._crawl_stop_go_phases(sub, R.raw_loader, frame_loader=fl_o)["phaseEnergy"]
    return {"nDrives": int(len(sub)), "raw": phase_summary(Pr), "originals": phase_summary(Po), "cacheBuildSeconds": round(time.time() - t0, 1)}


def main():
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    failing = set(json.load(open("analyses/F03_originals/failing_keys.json", encoding="utf-8")))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    res = {"milestone": "M365", "note": "read-only provenance-sensitivity comparison (originals minus raw/); not a correction; owner-approved 2026-10-03", "nFailingFiles": len(failing),
           "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "originalsDir": "originals_recovered (outside the repo, read-only)"}}
    res["A_chargingSubState"] = part_a(failing, dm, lim)
    print("A done", res["A_chargingSubState"]["nTrips"], flush=True)
    if not lim:
        res["B_phaseEnergies"] = part_b(failing, dm)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT if not lim else OUT.replace(".json", "_limit.json"), "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps(res, indent=1, default=float)[:3500])


if __name__ == "__main__":
    main()
