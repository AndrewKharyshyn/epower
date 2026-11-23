#!/usr/bin/env python3
"""M753 (spec analyses/M753_spec.md Rev 2, 2.1, 2.2): occupant-informed assumed-mass sensitivity of the mass-scaled regeneration display and the descent budget. REPORT-ONLY.

Mass enters the apparent KE recovery only in the denominator (charge is mass-free): the cache stores mass-free per-interval dv2 and the aggregation multiplies KE_FACTOR x mass[drive] x dv2, so the
per-drive mass array is swapped (compute_summary_arrays._mass_for_drive is patched for the duration of one rebuild; nothing is written back). Control V0: the display block rebuilt with the class masses
must equal the published regenDisplayV2 (and mountainPattern.descentBudget) byte for byte, else the tool STOPS (exit 3, nothing written). Seat weights, luggage and the mixed-highway share are
OWNER-ESTIMATED / ASSUMED inputs recorded below; nothing here is a measured mass and the class mass is never replaced.
Usage: python tools/mass_sensitivity.py [--out-dir analyses] [--scenarios S2c_central,...] [--skip-descent] [--skip-regen] [--nb 4000]
Environment: XT_REGEN_CACHE_DIR (regen cache), XT_RAW_DIR_STAGED (staged raw files for the cache identity), XT_CLOUD_STORE (cloud store with Trip_Information)."""
import argparse, hashlib, json, os, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_import as mi
import mynissan_coverage as mc

REGISTERED_MASTER = "d514d6009d6d9a0a168ad4fb09b9bb98"
SEED, NB_DEFAULT = 42, 4000
IDX = {"low": 0, "central": 1, "high": 2}
# owner-estimated usual weights, kg (low, central, high); passenger high = worst-case bracket, not an interval for the mean (spec 9.2)
WEIGHTS = {"P": (52.0, 55.075, 90.0), "L": (30.0, 35.0, 40.0), "C": (20.0, 27.5, 35.0), "R": (8.0, 17.25, 27.0)}
SEATS = {"P": "SeatBeltFirstRowPassenger", "L": "SeatBeltSecondRowLeft", "C": "SeatBeltSecondRowCenter", "R": "SeatBeltSecondRowRight"}
# luggage by drive class (owner, 2026-11-23): highway 40-65; mixed_highway share f = 0.5 / 0.75 / 1.0 (assumption); urban and mixed 5 / 10 / 15 (mixed as urban, owner-confirmed); unknown 0
LUGGAGE = {"highway": (40.0, 52.5, 65.0), "mixed_highway": (0.5 * 40.0, 0.75 * 52.5, 65.0), "urban": (5.0, 10.0, 15.0), "mixed": (5.0, 10.0, 15.0), "unknown": (0.0, 0.0, 0.0)}
SCENARIOS = ("S2c", "S1c", "S2", "S3")
COMMON_BASE_KG = 1890.0


class Stop(Exception):
    pass


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


# ---------------------------------------------------------------------------- loads
def payload_of(pattern, i):
    """Weight of the latched passenger and rear seats (kg) at bracket index i; pattern: {seat: 0/1}; the driver is part of the class mass."""
    return float(sum(WEIGHTS[s][i] for s, v in pattern.items() if v))


def luggage_of(drive_type, i):
    return LUGGAGE.get(drive_type, LUGGAGE["unknown"])[i]


def class_group(drive_type):
    return drive_type if drive_type in ("highway", "mixed_highway", "mixed", "urban") else "unknown"


def load_table(rows):
    """rows: dicts with file, date, drive_type, class_mass, pattern (dict or None). Adds payload / luggage / load for the three brackets (NaN without a pattern)."""
    out = []
    for r in rows:
        rec = {"file": r["file"], "date": r["date"], "drive_type": r["drive_type"], "group": class_group(r["drive_type"]), "class_mass": float(r["class_mass"]), "has_pattern": r["pattern"] is not None,
               "pattern": "".join(str(int(r["pattern"][s])) for s in "PLCR") if r["pattern"] else ""}
        for name, i in IDX.items():
            rec["payload_" + name] = payload_of(r["pattern"], i) if r["pattern"] else np.nan
            rec["luggage_" + name] = luggage_of(r["drive_type"], i) if r["pattern"] else np.nan
            rec["load_" + name] = rec["payload_" + name] + rec["luggage_" + name] if r["pattern"] else np.nan
        out.append(rec)
    return pd.DataFrame(out)


def allowance(tab, scenario, bracket):
    """Allowance A per drive (kg) for a scenario, computed inside the bracket over drives that have a pattern."""
    load = tab["load_" + bracket]
    ok = tab["has_pattern"]
    if scenario == "S2c":
        means = load[ok].groupby(tab.loc[ok, "group"]).mean()
        return tab["group"].map(means)
    if scenario == "S2":
        return pd.Series(float(load[ok].mean()), index=tab.index)
    if scenario == "S3":
        return pd.Series(float(np.percentile(load[ok], 95)), index=tab.index)
    return pd.Series(0.0, index=tab.index)


def scenario_mass(tab, scenario, bracket):
    """Occupant-informed assumed mass per drive (kg). S2c (central): class mass + within-class deviation of the total load; S1c: common base 1890 + load; S2: pooled mean allowance; S3: P95 allowance.
    Drives without a belt pattern keep the class mass."""
    load = tab["load_" + bracket]
    if scenario == "S1c":
        m = COMMON_BASE_KG + load
    else:
        m = tab["class_mass"] + load - allowance(tab, scenario, bracket)
    return m.where(tab["has_pattern"], tab["class_mass"])


def mass_bias(tab, mass, days, nb, seed=SEED):
    """Aggregate relative mass difference sum(m - m_class) / sum(m_class) with a day-clustered percentile bootstrap."""
    d = (mass - tab["class_mass"]).to_numpy(float)
    base = tab["class_mass"].to_numpy(float)
    codes, uniq = pd.factorize(np.asarray(days))
    groups = [np.where(codes == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(nb):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        draws.append(d[idx].sum() / base[idx].sum())
    return {"est": round(float(d.sum() / base.sum()), 5), "ci95": [round(float(np.percentile(draws, 2.5)), 5), round(float(np.percentile(draws, 97.5)), 5)]}


# ---------------------------------------------------------------------------- belt patterns from the cloud
def belt_patterns(trip_rows, windows):
    """trip_rows: [(t, dict)] sorted; windows: [(file, t0, t1)]. Modal latched state (code 2) over the moving rows (displayed speed above 20 km/h) that carry all four seat readings inside the padded window, per seat; None with fewer than 3 such rows."""
    ts = np.array([t for t, _ in trip_rows], float)
    sp = np.array([mc.speed_kmh(x.get("SpeedDisplayedValueinkmh", "")) if x.get("SpeedDisplayedValueinkmh", "") != "" else np.nan for _, x in trip_rows], dtype=float)
    seat = {s: np.array([mc.fnum(x.get(col, "")) if x.get(col, "") != "" else np.nan for _, x in trip_rows], dtype=float) for s, col in SEATS.items()}
    # Rev 2.3 (spec 12): the moving rows that carry all four seat readings; at least 3 such rows (rows with a missing reading are skipped, not a reason to drop the drive)
    mv = np.isfinite(sp) & (sp > 20) & np.all([np.isfinite(seat[s_]) for s_ in SEATS], axis=0)
    out = {}
    for f, t0, t1 in windows:
        i0, i1 = int(np.searchsorted(ts, t0 - 60)), int(np.searchsorted(ts, t1 + 60))
        sel = np.arange(i0, i1)
        sel = sel[mv[sel]] if len(sel) else sel
        if len(sel) < 3:
            out[f] = None
            continue
        out[f] = {s: int(np.round(np.median((seat[s][sel] == 2).astype(float)))) for s in SEATS}
    return out


# ---------------------------------------------------------------------------- comparison of the displayed cells
def compare_cells(pub, new):
    """Walk the published and the scenario regeneration display in parallel; for each cell with eff and a massRange: relative change, inside the published mass range, change in units of the day-interval half-width."""
    rows = []

    def walk(a, b, path):
        if isinstance(a, dict) and isinstance(b, dict):
            if "eff" in a and "massRange" in a:
                if a.get("eff") is not None and b.get("eff") is not None and a.get("status") == "supported" and a["eff"] != 0:
                    mr = a.get("massRange")
                    ci = a.get("ci95")
                    hw = (ci[1] - ci[0]) / 2.0 if ci else None
                    rows.append({"path": path, "pub": a["eff"], "new": b["eff"], "relChange": (b["eff"] - a["eff"]) / a["eff"], "inRange": bool(mr and min(mr) - 1e-9 <= b["eff"] <= max(mr) + 1e-9),
                                 "rangeHalfWidth": (abs(mr[1] - mr[0]) / 2.0 if mr else None), "ciHalfWidth": hw, "inCi": bool(ci and ci[0] <= b["eff"] <= ci[1]),
                                 "shiftOverCiHalf": ((b["eff"] - a["eff"]) / hw if hw else None)})
            for k, v in a.items():
                if k in b:
                    walk(v, b[k], path + "/" + str(k))
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, path + "[%d]" % i)
    walk(pub, new, "")
    return rows


def summarise_cells(rows):
    if not rows:
        return {"cells": 0}
    df = pd.DataFrame(rows)
    rel = df["relChange"].to_numpy(float)
    return {"cells": int(len(df)), "medianRelChangePct": round(100 * float(np.median(rel)), 3), "p05RelChangePct": round(100 * float(np.percentile(rel, 5)), 3), "p95RelChangePct": round(100 * float(np.percentile(rel, 95)), 3),
            "minRelChangePct": round(100 * float(rel.min()), 3), "maxRelChangePct": round(100 * float(rel.max()), 3), "cellsOutsidePublishedMassRange": int((~df["inRange"]).sum()),
            "shareOutsideRange": round(float((~df["inRange"]).mean()), 4), "cellsOutsideDayInterval": int((~df["inCi"]).sum()), "medianShiftOverCiHalfWidth": round(float(df["shiftOverCiHalf"].dropna().median()), 3) if df["shiftOverCiHalf"].notna().any() else None}


def gate_detail(g):
    """Split the display build gates: the two internal-consistency gates (strata and SOC sums reconcile) must hold under any mass; the two gates that compare the pooled values with the published M441 / M444 blocks
    (built under the class masses) can only hold when the mass is the class mass, so they are expected to be False in a scenario."""
    tol = g.get("tolerance", 1e-9)
    return {"strataReconcileOk": bool(all(max(d.values()) <= tol for d in g.get("strataReconcile", {}).values())),
            "socSumReconcileOk": bool(all(r["nSoc"] == 0 and r["nAll"] == 0 and r["keKwh"] <= tol and r["chargeKwh"] <= tol and r["keAll"] <= tol for d in g.get("socSumReconcile", {}).values() for r in d.values())),
            "pooledMatchesM441": bool(all(g.get("pooledMatchesM441", {}).values())), "observedMatchesM444": bool(all(g.get("observedMatchesM444", {}).values()))}


# ---------------------------------------------------------------------------- M3 association (exploratory)
def cluster_ols(y, X, cl):
    """OLS with cluster-robust (CR1) standard errors; returns coefficients, standard errors."""
    y, X = np.asarray(y, float), np.asarray(X, float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    codes, uniq = pd.factorize(np.asarray(cl))
    G, n, k = len(uniq), len(y), X.shape[1]
    XtXi = np.linalg.pinv(X.T @ X)
    meat = np.zeros((k, k))
    for g in range(G):
        s = X[codes == g].T @ res[codes == g]
        meat += np.outer(s, s)
    V = XtXi @ meat @ XtXi * (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1))
    return beta, np.sqrt(np.diag(V)), G


def association(y_pct, load, groups, days, mean_mass):
    """Per-drive apparent recovery (percent) on the within-class load deviation (per 100 kg) with class dummies; predicted slope +100/m of the mean (pre-registered, spec 9.5).
    Verdict only when the minimum detectable slope is below the predicted one."""
    y, ld = np.asarray(y_pct, float), np.asarray(load, float)
    g = pd.Series(groups).astype(str)
    dev = ld - pd.Series(ld).groupby(g).transform("mean").to_numpy()
    dummies = pd.get_dummies(g, drop_first=True).to_numpy(float)
    X = np.column_stack([np.ones(len(y)), dev / 100.0, dummies]) if dummies.size else np.column_stack([np.ones(len(y)), dev / 100.0])
    beta, se, G = cluster_ols(y, X, days)
    slope, se_s = float(beta[1]), float(se[1])
    pred = float(np.mean(y)) * 100.0 / mean_mass
    mde = 2.8016 * se_s
    out = {"nDrives": int(len(y)), "nDays": int(G), "slopePctPerPer100kg": round(slope, 4), "ci95": [round(slope - 1.96 * se_s, 4), round(slope + 1.96 * se_s, 4)], "mdeSlope": round(mde, 4),
           "predictedSlope": round(pred, 4), "predictionNote": "apparent ratio = charge / (m_class dv2) and charge scales with the true mass: slope about +100/m of the mean ratio per 100 kg",
           "confounding": "occupancy goes with trip type, weekend and season; the battery charge-power limit makes the expected slope smaller"}
    if mde < abs(pred):
        out["verdict"] = "slope %s the prediction (interval %s the predicted value)" % ("consistent with" if out["ci95"][0] <= pred <= out["ci95"][1] else "not consistent with", "contains" if out["ci95"][0] <= pred <= out["ci95"][1] else "excludes")
    else:
        out["verdict"] = "not informative at this support (minimum detectable slope %.3f above the predicted %.3f)" % (mde, abs(pred))
    return out


# ---------------------------------------------------------------------------- rebuilds with a mass override
class MassPatch:
    """Context manager: compute_summary_arrays._mass_for_drive returns mass_map[file] for the duration of one rebuild; the original function is restored afterwards."""
    def __init__(self, C, mass_map):
        self.C, self.map = C, mass_map

    def __enter__(self):
        self.orig = self.C._mass_for_drive
        orig, mp = self.orig, self.map
        self.C._mass_for_drive = lambda drive_type, file_label: mp.get(file_label, orig(drive_type, file_label))
        return self

    def __exit__(self, *a):
        self.C._mass_for_drive = self.orig
        return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store())
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    ap.add_argument("--scenarios", default="S2c_central,S2c_low,S2c_high,S1c_central,S2_central,S3_central")
    ap.add_argument("--skip-regen", action="store_true")
    ap.add_argument("--skip-descent", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")):
        print("mass_sensitivity: no cloud store, skipped (optional)")
        return 0
    t_start = time.time()
    try:
        m0 = md5(a.master)
        if m0 != REGISTERED_MASTER:
            raise Stop("master MD5 %s differs from the registered master (a rerun on a larger corpus needs its own addendum)" % m0)
        import compute_summary_arrays as C
        master = mc.load_master(a.master)
        dm = pd.read_csv(a.master, low_memory=False)
        dtype = dict(zip(dm["file"], dm["drive_type"]))
        trip = mi.load_stream(a.store, "Trip_Information")
        pats = belt_patterns(trip, [(m["file"], m["t0"], m["t1"]) for m in master])
        rows = [{"file": m["file"], "date": m["date"], "drive_type": dtype.get(m["file"], "unknown"), "class_mass": C._mass_for_drive(dtype.get(m["file"], "unknown"), m["file"]), "pattern": pats.get(m["file"])} for m in master]
        tab = load_table(rows)
        days = tab["date"].astype(str).str[:10].to_numpy()
        res = {"milestone": "M753", "spec": "analyses/M753_spec.md Rev 2.2", "role": "report-only; occupant-informed assumed mass (owner-estimated seat weights, belt-state proxy); the class mass is not replaced",
               "masterMd5": m0, "seed": SEED, "nBoot": a.nb, "toolSha256": sha256(os.path.abspath(__file__)), "weights": {k: list(v) for k, v in WEIGHTS.items()}, "luggage": {k: list(v) for k, v in LUGGAGE.items()},
               "inputsNote": "seat weights and luggage are owner-estimated usual values (mixed-highway share f = 0.5 / 0.75 / 1.0 is an assumption); a latched belt is a proxy; fuel mass unobserved"}
        # M0
        have = tab[tab["has_pattern"]]
        res["M0"] = {"drives": int(len(tab)), "withPattern": int(len(have)), "withoutPattern": int((~tab["has_pattern"]).sum()),
                     "patternsPLCR": have["pattern"].value_counts().head(10).to_dict(),
                     "loadByClass": {g: {"n": int(len(s)), **{b: round(float(s["load_" + b].mean()), 1) for b in IDX}, "sdCentral": round(float(s["load_central"].std()), 1) if len(s) > 1 else None} for g, s in have.groupby("group")},
                     "payloadCentralMeanAll": round(float(have["payload_central"].mean()), 1)}
        sc = [s for s in a.scenarios.split(",") if s]
        res["M1_massBias"] = {}
        masses = {}
        for s in sc:
            name, br = s.split("_")
            mm = scenario_mass(tab, name, br)
            masses[s] = dict(zip(tab["file"], mm))
            res["M1_massBias"][s] = mass_bias(tab, mm, days, a.nb)
            res["M1_massBias"][s]["meanMassKg"] = round(float(mm.mean()), 1)
        res["M1_massBias"]["classMeanMassKg"] = round(float(tab["class_mass"].mean()), 1)
        # implied class-assumption bias for the highway class under S1c (spec 10.2)
        hw = have[have["group"] == "highway"]
        res["S1c_highwayImpliedClassBias"] = {"n": int(len(hw)), "impliedMeanKg": round(float(COMMON_BASE_KG + hw["load_central"].mean()), 1) if len(hw) else None, "assumedKg": 2000.0,
                                              "relative": round(float((COMMON_BASE_KG + hw["load_central"].mean()) / 2000.0 - 1.0), 4) if len(hw) else None, "note": "below the 20-drive floor: counts only" if len(hw) < 20 else ""}
        if not a.skip_regen:
            import regen_display as RD
            A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
            if not RD.frozen_ok():
                raise Stop("regen_display frozen inputs are not ok")
            with MassPatch(C, {}):
                base = RD.build(arrays=A)
            if json.dumps(base, sort_keys=True, default=float) != json.dumps(A["regenDisplayV2"], sort_keys=True, default=float):
                raise Stop("control V0: the regeneration display rebuilt with the class masses is not byte-equal to the published regenDisplayV2")
            res["control_V0_regen"] = {"status": "reproduced (byte-equal)", "chars": len(json.dumps(base, sort_keys=True, default=float)), "gateDetail": gate_detail(base.get("gates", {}))}
            res["M2_regen"] = {}
            for s in sc:
                with MassPatch(C, masses[s]):
                    built = RD.build(arrays=A)
                rows_c = compare_cells(A["regenDisplayV2"], built)
                res["M2_regen"][s] = {**summarise_cells(rows_c), "gatesPass": bool(built.get("gates", {}).get("pass")), "gateDetail": gate_detail(built.get("gates", {}))}
                print("mass_sensitivity: %s %s" % (s, res["M2_regen"][s]))
        if not a.skip_descent:
            staged = os.environ.get("XT_RAW_DIR_STAGED") or os.path.join(ROOT, "raw_only")

            def loader(fn):
                with open(os.path.join(staged, fn), "rb") as f:
                    return f.read()
            A2 = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
            pubd = A2["mountainPattern"]["descentBudget"]
            with MassPatch(C, {}):
                bd = C._mountain_pattern(dm, loader, frame_loader=None)
            if json.dumps(bd.get("descentBudget"), sort_keys=True, default=float) != json.dumps(pubd, sort_keys=True, default=float):
                raise Stop("control V0: the descent budget rebuilt with the class masses is not byte-equal to the published mountainPattern.descentBudget")
            res["control_V0_descent"] = {"status": "reproduced (byte-equal)"}
            res["M2_descent"] = {"published": {k: pubd.get(k) for k in ("captureFraction", "n", "assumedMassKg", "captureFractionRangeMassUncertainty", "urbanMixedRowShare")}}
            for s_ in sc:
                with MassPatch(C, masses[s_]):
                    md = C._mountain_pattern(dm, loader, frame_loader=None)["descentBudget"]
                res["M2_descent"][s_] = {"captureFraction": md.get("captureFraction"), "n": md.get("n"), "assumedMassKg": md.get("assumedMassKg"),
                                         "captureFractionRangeMassUncertainty": md.get("captureFractionRangeMassUncertainty"),
                                         "relChangeCaptureFractionPct": round(100.0 * (md["captureFraction"] / pubd["captureFraction"] - 1.0), 2) if pubd.get("captureFraction") else None,
                                         "rowsChanged": bool(md.get("n") != pubd.get("n")),
                                         "netDropToSaturateM": [r.get("netDropToSaturateM") for r in md.get("toSaturation", [])], "publishedNetDropToSaturateM": [r.get("netDropToSaturateM") for r in pubd.get("toSaturation", [])]}
                print("mass_sensitivity: descent %s %s" % (s_, res["M2_descent"][s_]["captureFraction"]))
            res["M2_descent"]["maskNote"] = "the mass-dependent potential-energy mask moves with the patched mass; rowsChanged reports whether the row population differs from the published one (the mask-held variant coincides when it does not)"
        if not a.skip_regen:
            import regen_v2 as R
            import regen_v2_agg as G
            import regen_v2_cache as K
            dm_g, _reg = G.load_master()
            files = list(dm_g["file"])
            T, _h = K.load(files, variant="base")
            co = G.Cohort(T, dm_g, np.ones(len(dm_g), bool), "all")
            ke = R.KE_FACTOR * co.mass * co.d["iv_dv2"] * co.est * co.w
            ch = co.d["iv_charge"] * co.est * co.w
            n_dr = len(dm_g)
            ke_d, ch_d = np.bincount(co.drive, weights=ke, minlength=n_dr), np.bincount(co.drive, weights=ch, minlength=n_dr)
            pos = {f: i for i, f in enumerate(files)}
            sel = [(i, f) for i, f in enumerate(tab["file"]) if tab.loc[i, "has_pattern"] and f in pos and ke_d[pos[f]] >= 0.05]
            if len(sel) >= 30:
                yy = np.array([100.0 * ch_d[pos[f]] / ke_d[pos[f]] for i, f in sel])
                ld = np.array([tab.loc[i, "load_central"] for i, f in sel])
                gr = np.array([tab.loc[i, "group"] for i, f in sel])
                dd = np.array([days[i] for i, f in sel])
                mm = float(np.mean([tab.loc[i, "class_mass"] for i, f in sel]))
                res["M3_association"] = association(yy, ld, gr, dd, mm)
                res["M3_association"]["definition"] = "per-drive apparent KE recovery (percent, assumed class mass; drives with at least 0.05 kWh of kinetic energy and a belt pattern) on the within-class deviation of the central load per 100 kg, class dummies, day-clustered robust standard errors; exploratory"
            else:
                res["M3_association"] = {"status": "not estimable (fewer than 30 drives)"}
        res["deviations_from_spec"] = []
        res["scope"] = "report-only: no payload, dashboard, master or published figure changes; the class mass is not replaced"
        res["seconds"] = round(time.time() - t_start, 1)
        if md5(a.master) != m0:
            raise Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        json.dump(res, open(os.path.join(a.out_dir, "M753_mass_sensitivity.json"), "w", encoding="utf-8", newline="\n"), indent=1, default=float)
        cols = ["file", "date", "drive_type", "class_mass", "has_pattern", "pattern", "payload_low", "payload_central", "payload_high", "luggage_low", "luggage_central", "luggage_high"]
        tab[cols].round(2).to_csv(os.path.join(a.out_dir, "M753_drive_payload.csv"), index=False, lineterminator="\n")
        print("mass_sensitivity: done in %.0f s" % res["seconds"])
        return 0
    except Stop as e:
        print("mass_sensitivity: STOP (%s); nothing written" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
