#!/usr/bin/env python3
"""M420 (analyses/M420_spec.md Rev 1, audit F17): integration-scenario sensitivities beside the energy Monte Carlo. Additive: writes ONLY the payload block summary_arrays.json['integrationScenarios'] (+ its artifact stamp).
Reporting-only: every computed row changes ONE choice of the production integration (alignment, interpolation, gap policy, offset) and re-integrates the logged HV current and voltage samples of the same drive set; rows are never
summed, unioned or turned into one interval. Carried studies (cadence, quantisation, midpoint rule) and the capacity references are copied from their own blocks with their own n, in separate subtables. The baseline pass is the
production algorithm of compute_drive_summary_v6.py (energy_mc_precompute._integrate) and must reproduce the master per drive.
Usage: python tools/integration_scenarios.py [--dry-run] [--workers N]"""
import datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
ALLOWED = ["/integrationScenarios", "/_artifactStamps/integrationScenarios"]
METHOD_VERSION = 1
BASE_TOL_MS = 1500
BASE_CAP_S = 5.0
BOOT_DRAWS, BOOT_SEED = 4000, 42
BASE_MATCH_GATE_KWH = 5e-4
D1_REPRODUCES_KWH = 0.05      # D1 must reproduce energyUncertaintyMC.offsetGrossSensitivity.throughputShiftKwh within this
MIN_DRIVE_KWH = 0.1           # the per-drive spread is defined for drives with a baseline throughput of at least this
GAP_THRESHOLDS_S = [5, 10, 30]

# id, family, kind, definition, parameters, inMonteCarlo (pre-registered: True / "partial" / False)
SCENARIOS = [
    ("A0", "alignment", "data process", "I/V nearest-match tolerance 500 ms (baseline 1500 ms; the lower end of the Monte Carlo sweep)", {"tol": 500}, True),
    ("A1", "alignment", "data process", "I/V nearest-match tolerance 1000 ms (baseline 1500 ms)", {"tol": 1000}, True),
    ("A2", "alignment", "data process", "I/V nearest-match tolerance 2000 ms (baseline 1500 ms; the upper end of the Monte Carlo sweep)", {"tol": 2000}, True),
    ("A3", "alignment", "estimator choice", "backward-only voltage match: the last voltage at or before each current sample, tolerance 1500 ms (baseline: nearest)", {"direction": "backward"}, False),
    ("B1", "interpolation", "estimator choice", "left-hold: the interval takes the power at its start (baseline: piecewise-linear power with the zero-crossing-aware split); same alignment and 5 s cap as the baseline", {"mode": "left"}, False),
    ("B2", "interpolation", "estimator choice", "right-hold: the interval takes the power at its end; same alignment and 5 s cap as the baseline", {"mode": "right"}, False),
    ("C1", "gaps", "estimator choice", "no bridging: intervals longer than 5 s contribute zero (baseline: step capped at 5 s)", {"no_bridge": True}, False),
    ("C2", "gaps", "data process", "step cap 2 s (baseline 5 s)", {"cap": 2.0}, "partial"),
    ("C3", "gaps", "data process", "step cap 3 s (baseline 5 s)", {"cap": 3.0}, "partial"),
    ("C4", "gaps", "data process", "step cap 10 s (baseline 5 s)", {"cap": 10.0}, "partial"),
    ("C5", "gaps", "data process", "step cap 30 s (baseline 5 s)", {"cap": 30.0}, "partial"),
    ("D1", "offset", "data process", "sample-level current offset at the released point estimate subtracted before the discharge / charge split", {"offset": "point"}, True),
    ("D2", "offset", "data process", "offset at the lower end of its day-cluster 95 % interval (a deterministic row at an interval end)", {"offset": "lo"}, True),
    ("D3", "offset", "data process", "offset at the upper end of its day-cluster 95 % interval (a deterministic row at an interval end)", {"offset": "hi"}, True),
]
NO_CI = ("D2", "D3")
COL_MAP = {"[BMS] HV Battery Current (A)": "I", "[BMS] HV Battery voltage (V)": "V"}


def _aligned(I, V, tol_ms, direction="nearest"):
    return pd.merge_asof(I, V.rename(columns={"v": "V"}), on="t", direction=direction, tolerance=pd.Timedelta("%dms" % tol_ms)).dropna(subset=["V"]).reset_index(drop=True)


def integrate(I, V, tol_ms=BASE_TOL_MS, offset_a=0.0, mode="linear", cap_s=BASE_CAP_S, no_bridge=False, direction="nearest"):
    """One re-integration pass. I, V: DataFrames with columns t (datetime) and v. Returns (discharge_kwh, charge_kwh).
    mode 'linear' is the production construction (piecewise-linear power, zero-crossing-aware directional split)."""
    e = _aligned(I, V, tol_ms, direction)
    if len(e) < 2:
        return 0.0, 0.0
    Id = -e["v"].to_numpy() - offset_a
    P = Id * e["V"].to_numpy() / 1000.0
    gap = np.nan_to_num(e["t"].diff().dt.total_seconds().to_numpy(), nan=0.0)
    if no_bridge:
        dt = np.where(gap > BASE_CAP_S, 0.0, np.clip(gap, 0, None)) / 3600.0
    else:
        dt = np.clip(gap, 0, cap_s) / 3600.0
    p0 = np.nan_to_num(np.concatenate([[np.nan], P[:-1]]), nan=0.0)
    if mode == "linear":
        cross = (p0 * P) < 0
        absum = np.abs(p0) + np.abs(P)
        den = np.where(absum > 0, 2.0 * absum, 1.0)
        disc_c = dt * ((p0 > 0) * p0 ** 2 + (P > 0) * P ** 2) / den
        chg_c = dt * ((p0 < 0) * p0 ** 2 + (P < 0) * P ** 2) / den
        signed = dt * (p0 + P) / 2.0
        disc = np.where(cross, disc_c, np.where(signed > 0, signed, 0.0))
        chg = np.where(cross, chg_c, np.where(signed < 0, -signed, 0.0))
    else:
        signed = dt * (p0 if mode == "left" else P)
        disc = np.where(signed > 0, signed, 0.0)
        chg = np.where(signed < 0, -signed, 0.0)
    return float(disc.sum()), float(chg.sum())


def gap_inventory(I, V):
    """Intervals of the baseline aligned series longer than each threshold: count and total duration (s); excess = time beyond the 5 s cap."""
    e = _aligned(I, V, BASE_TOL_MS)
    gap = np.nan_to_num(e["t"].diff().dt.total_seconds().to_numpy(), nan=0.0) if len(e) else np.array([])
    out = {"n%d" % t: int((gap > t).sum()) for t in GAP_THRESHOLDS_S}
    out.update({"s%d" % t: float(gap[gap > t].sum()) for t in GAP_THRESHOLDS_S})
    out["excessBeyondCapS"] = float(np.clip(gap - BASE_CAP_S, 0, None).sum())
    return out


def load_iv(path):
    from drive_raw_cache import fast_time as _ft
    raw = pd.read_csv(path, usecols=["time"] + list(COL_MAP), low_memory=False).rename(columns=COL_MAP)
    t = _ft(raw["time"], mixed=True)

    def ser(col, lo=None, hi=None):
        m = raw[col].notna()
        if not m.any():
            return None
        s = pd.DataFrame({"t": t[m].values, "v": raw.loc[m, col].astype(float).values})
        if lo is not None:
            s = s[s["v"] >= lo]
        if hi is not None:
            s = s[s["v"] <= hi]
        return s.sort_values("t").reset_index(drop=True)
    I = ser("I")
    I = I[I["v"].abs() < 900] if I is not None else None
    V = ser("V", lo=200, hi=450)
    return I, V


def scenario_energies(I, V, scen, offsets):
    """Baseline and every scenario for one drive: {id: (discharge, charge)}."""
    out = {"S0": integrate(I, V)}
    for sid, _f, _k, _d, p, _mc in scen:
        kw = dict(p)
        if "offset" in kw:
            kw = {"offset_a": offsets[kw["offset"]]}
        if "tol" in kw:
            kw = {"tol_ms": kw["tol"]}
        if "cap" in kw:
            kw = {"cap_s": kw["cap"]}
        out[sid] = integrate(I, V, **kw)
    return out


def _work(args):
    path, scen, offsets = args
    try:
        I, V = load_iv(path)
        if I is None or V is None or len(I) < 3:
            return {"error": "insufficient I/V samples"}
        return {"e": scenario_energies(I, V, scen, offsets), "gaps": gap_inventory(I, V)}
    except Exception as ex:
        return {"error": repr(ex)}


def ratio_ci(a_by_day, b_by_day, seed=BOOT_SEED, draws=BOOT_DRAWS):
    """Day-clustered percentile bootstrap of sum(a)/sum(b): the calendar day is the resampling unit (variability of the ratio across days)."""
    a, b = np.asarray(a_by_day, float), np.asarray(b_by_day, float)
    n = len(a)
    idx = np.random.default_rng(seed).integers(0, n, size=(draws, n))
    r = a[idx].sum(axis=1) / b[idx].sum(axis=1)
    return [float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))]


def aggregate(drives, scen):
    """drives: list of {file, day, e:{id:(dis,chg)}}. Returns the computed rows plus the baseline totals."""
    days = sorted({d["day"] for d in drives})
    di = {d: i for i, d in enumerate(days)}
    dayix = np.array([di[d["day"]] for d in drives], dtype=int)

    def per_day(vals):
        out = np.zeros(len(days))
        np.add.at(out, dayix, vals)
        return out
    b_dis = np.array([d["e"]["S0"][0] for d in drives]); b_chg = np.array([d["e"]["S0"][1] for d in drives])
    b_thr = b_dis + b_chg
    m = b_thr >= MIN_DRIVE_KWH
    rows = []
    for sid, fam, kind, definition, _p, in_mc in scen:
        dis = np.array([d["e"][sid][0] for d in drives]); chg = np.array([d["e"][sid][1] for d in drives])
        thr = dis + chg
        ratio = thr[m] / b_thr[m]
        row = {"id": sid, "family": fam, "kind": kind, "definition": definition, "status": "computed in this run", "inMonteCarlo": in_mc,
               "grossDischargeKwh": round(float(dis.sum()), 4), "grossChargeKwh": round(float(chg.sum()), 4), "grossThroughputKwh": round(float(thr.sum()), 4),
               "shiftDischargeKwh": round(float(dis.sum() - b_dis.sum()), 4), "shiftChargeKwh": round(float(chg.sum() - b_chg.sum()), 4), "shiftKwh": round(float(thr.sum() - b_thr.sum()), 4),
               "netDrawShiftKwh": round(float((dis - chg).sum() - (b_dis - b_chg).sum()), 4),
               "ratioToBaseline": round(float(thr.sum() / b_thr.sum()), 6),
               "perDriveRatio": {"nDrives": int(m.sum()), "nUndefined": int((~m).sum()), "minBaselineKwh": MIN_DRIVE_KWH, "min": round(float(ratio.min()), 6), "p10": round(float(np.percentile(ratio, 10)), 6),
                                 "median": round(float(np.median(ratio)), 6), "p90": round(float(np.percentile(ratio, 90)), 6), "max": round(float(ratio.max()), 6)},
               "nDrives": len(drives), "nDays": len(days), "support": [days[0], days[-1]]}
        if sid in NO_CI:
            row["dayVariabilityOfRatio95"] = None
            row["dayVariabilityNote"] = "a deterministic row at an interval end: no variability interval is computed"
        else:
            row["dayVariabilityOfRatio95"] = [round(x, 6) for x in ratio_ci(per_day(thr), per_day(b_thr))]
        rows.append(row)
    base = {"grossThroughputKwh": round(float(b_thr.sum()), 4), "grossDischargeKwh": round(float(b_dis.sum()), 4), "grossChargeKwh": round(float(b_chg.sum()), 4), "netDrawKwh": round(float((b_dis - b_chg).sum()), 4),
            "nDrives": len(drives), "nDays": len(days), "support": [days[0], days[-1]]}
    return rows, base


def carried_studies(A):
    cad = A["loggerCadence"]["sensitivity"]
    st = cad["study"]
    mc = A["energyUncertaintyMC"]
    sb = mc["grossThroughputMC"]["sourceBudget"]
    mid = mc["independentIntegrationCheck"]["midpointRule"]
    rows = []
    for key, label in (("fastToSlow", "fast-regime logs thinned to the slow-regime interval distribution"), ("fastToSlower", "thinned to twice the slow intervals (beyond the observed slow regime: a stress emulation)")):
        g = cad["grossThroughputRatio"][key]
        rows.append({"id": "E-" + key, "family": "cadence", "kind": "data process (emulated)", "definition": label + "; an emulated sampling sensitivity, not a causal cadence effect", "status": "carried from the M379b study",
                     "inMonteCarlo": False, "ratioToStudyBaseline": round(g["estimate"], 6), "ci95DayCluster": [round(x, 6) for x in g["ci95"]], "nDrives": st["nDrives"], "nDays": st["nDays"],
                     "scope": "the fast-regime drives of that study; never applied to the drive set of the computed rows"})
    rows.append({"id": "F-quantisation", "family": "quantisation", "kind": "data process", "definition": "ADC quantisation of the logged current and voltage (delta-method SD of the percent shift)", "status": "carried from the energy Monte Carlo (sourceBudget)",
                 "inMonteCarlo": True, "sdPercent": sb["quantizationOnlySdPct"], "nDrives": mid["n"], "nDays": None, "scope": "Monte Carlo drive set"})
    rows.append({"id": "H-midpoint", "family": "interpolation", "kind": "estimator choice", "definition": "midpoint rule on the native series (independentIntegrationCheck, a code-correctness cross-check)", "status": "carried from independentIntegrationCheck (M220.1)",
                 "inMonteCarlo": False, "meanAbsDevPctThroughput": mid["meanAbsDevPctThroughput"], "p95AbsDevPctThroughput": mid["p95AbsDevPctThroughput"], "nDrives": mid["n"], "nDays": None, "scope": "per-drive deviations; not a corpus ratio"})
    return rows


def capacity_references(A):
    import compute_summary_arrays as C
    win = A["capacityBasis"]["lag"]["0"]["E_kWh"]
    return [{"id": "G1", "family": "capacity", "kind": "reference scaling", "applies": "GTC and FCE only; the integrated throughput is unchanged", "definition": "rated 5.0 Ah documentary reference versus the legacy 2.1 kWh reference (CAP_KWH=2.1, verified:false): the accumulated GTC / FCE scale by this factor",
             "status": "read from exposureBasis", "factor": A["exposureBasis"]["factor"]["aggregateRatedOverLegacy"]},
            {"id": "G2", "family": "capacity", "kind": "reference scaling", "applies": "GTC and FCE only; the integrated throughput is unchanged", "definition": "matched-window capacity point estimate of capacityBasis (lag 0) versus the legacy 2.1 kWh reference; GTC / FCE scale inversely with the reference. A descriptive result of capacityBasis, not an accepted capacity",
             "status": "read from capacityBasis", "factor": round(C.CAP_KWH / win["est"], 6), "referenceKwh": win["est"], "referenceCi95Kwh": win["ci95"], "ratioCi": None}]


def gap_summary(per_drive):
    keys = ["n%d" % t for t in GAP_THRESHOLDS_S] + ["s%d" % t for t in GAP_THRESHOLDS_S] + ["excessBeyondCapS"]
    tot = {k: round(sum(g[k] for g in per_drive), 1) for k in keys}
    tot["nDrivesWithGapOver5s"] = int(sum(1 for g in per_drive if g["n5"] > 0))
    return tot


def build(dm, raw_dir, A, workers=4):
    scen = SCENARIOS
    ou = A["offsetUncertainty"]
    lo, hi = sorted(float(x) for x in ou["ci95A"])
    offsets = {"point": float(ou["pointEstimateA"]), "lo": lo, "hi": hi}
    d = dm[dm["gross_discharge_kwh"].notna() & dm["file"].notna()].copy()      # the filter of energy_mc_precompute.build, i.e. the Monte Carlo drive set
    d["day"] = d["date"].astype(str).str[:10]
    jobs = [(os.path.join(raw_dir, f), scen, offsets) for f in d["file"]]
    if workers > 1:
        from multiprocessing import Pool
        with Pool(workers) as pool:
            res = pool.map(_work, jobs, chunksize=8)
    else:
        res = [_work(j) for j in jobs]
    ok, bad, gaps = [], [], []
    for (_, r), x in zip(d.iterrows(), res):
        if "e" in x:
            ok.append({"file": r["file"], "day": r["day"], "e": x["e"], "mdis": float(r["gross_discharge_kwh"]), "mchg": float(r["gross_charge_kwh"])}); gaps.append(x["gaps"])
        else:
            bad.append({"file": r["file"], "reason": x["error"]})
    dev = np.array([max(abs(o["e"]["S0"][0] - o["mdis"]), abs(o["e"]["S0"][1] - o["mchg"])) for o in ok])
    rows, base = aggregate(ok, scen)
    mcb = A["energyUncertaintyMC"]["grossThroughputMC"]
    off_ref = A["energyUncertaintyMC"]["offsetGrossSensitivity"]["throughputShiftKwh"]
    d1 = next(r for r in rows if r["id"] == "D1")
    checks = {"baselineReproducesMaster": {"maxAbsDevKwh": round(float(dev.max()), 6), "nDrivesAbove": int((dev > BASE_MATCH_GATE_KWH).sum()), "gateKwh": BASE_MATCH_GATE_KWH,
                                           "worst": [{"file": ok[i]["file"], "devKwh": round(float(dev[i]), 6)} for i in np.argsort(-dev)[:3]], "pass": bool((dev <= BASE_MATCH_GATE_KWH).all()),
                                           "note": "the baseline pass is the production algorithm; it must reproduce the master gross_discharge_kwh / gross_charge_kwh per drive (drives above the gate are listed, not tuned)"},
              "d1ReproducesOffsetGrossSensitivity": {"d1ShiftKwh": d1["shiftKwh"], "offsetGrossSensitivityShiftKwh": off_ref, "gateKwh": D1_REPRODUCES_KWH, "pass": abs(d1["shiftKwh"] - off_ref) <= D1_REPRODUCES_KWH},
              "driveSetMatchesMonteCarlo": {"baselineThroughputKwh": base["grossThroughputKwh"], "monteCarloNominalKwh": mcb["nominalReleasedThroughputKwh"], "differenceKwh": round(base["grossThroughputKwh"] - mcb["nominalReleasedThroughputKwh"], 4),
                                            "pass": abs(base["grossThroughputKwh"] - mcb["nominalReleasedThroughputKwh"]) < 0.01, "filter": "gross_discharge_kwh finite in drive_master.csv (the filter of energy_mc_precompute.build)"}}
    centre = mcb["throughputKwh"]["p50"] - mcb["nominalReleasedThroughputKwh"]
    blk = {"_provenance": "GENERATED by tools/integration_scenarios.py (M420, spec analyses/M420_spec.md Rev 1); do not hand-edit. Additive block: single-choice scenario sensitivities of the throughput integrated from logged HV current and voltage, beside the Monte Carlo; no row is summed, unioned or turned into one interval.",
           "methodVersion": METHOD_VERSION,
           "estimand": "gross throughput (kWh) integrated from logged HV current and voltage over the drives with a finite released gross_discharge_kwh (the Monte Carlo drive set), re-integrated from raw/ = sha256-verified originals (M366); GTC and FCE are this throughput divided by a capacity reference. Net draw is a secondary estimand, reported as a shift in kWh only.",
           "baseline": {**base, "algorithm": "I/V nearest match within 1500 ms, step cap 5 s, piecewise-linear power with the zero-crossing-aware directional split, offset 0 (compute_drive_summary_v6.py)", "gapInventory": gap_summary(gaps)},
           "checks": checks,
           "excludedDrives": bad,
           "scenarios": rows,
           "carriedStudies": carried_studies(A),
           "capacityReferences": capacity_references(A),
           "monteCarlo": {"interval95Kwh": [mcb["throughputKwh"]["p2_5"], mcb["throughputKwh"]["p97_5"]], "nominalKwh": mcb["nominalReleasedThroughputKwh"], "centreMinusNominalKwh": round(centre, 4),
                          "centreNote": "the Monte Carlo centre is not the nominal released value: the offset component shifts it (offsetGrossSensitivity)",
                          "included": ["I/V alignment tolerance (500-2000 ms)", "ADC quantisation of current and voltage", "gap truncation (time beyond the 5 s step cap)", "current offset (day-cluster interval)"],
                          "omitted": ["I/V lag beyond the tolerance sweep (not identifiable from round-robin logs; the Ready-mode experiment is pending)", "I-V co-timing and PID polling order", "voltage-sag and internal-resistance effects on power", "current-sensor gain", "logger sampling cadence (see the carried emulation)", "fuel-side quantities (not part of this integral)",
                                      "unlogged drives and unlogged intervals", "the interpolation rule, backward-only alignment and the no-bridging choice (scenario rows A3, B1, B2, C1)"],
                          "reading": "the Monte Carlo interval is conditional on the included components; it is not a statement of physical accuracy and is not combined with, drawn beside or drawn as whiskers on any scenario row"},
           "reading": ["each computed row changes one choice of the integration and nothing else; no interaction between choices is evaluated or implied",
                       "the shift of a computed row is a deterministic recomputation on this corpus; its day-cluster interval describes the day-to-day variability of the ratio, not an uncertainty of the total",
                       "a scenario range is the spread of single-choice changes; it is not an interval or a total",
                       "the production trapezoid is a released convention; A3, B1, B2 and C1 are estimator sensitivities, not an identified ground truth; A0-A2, C2-C5 and D1-D3 are data-process sensitivities",
                       "cadence, quantisation and midpoint rows are carried from their own studies and are not on the drive set of the computed rows; the capacity rows rescale GTC and FCE only (reference scaling)"],
           "limits": ["single vehicle, one driver, May-October", "ratios of sums are dominated by long drives; the per-drive spread is reported beside each row",
                      "the shift may vary over time or with the logger cadence; a split by month and cadence regime is a follow-up, not part of this block"]}
    return blk


def splice(A, blk, master_md5="", now=None):
    new = json.loads(json.dumps(A))
    old = A.get("integrationScenarios")
    new["integrationScenarios"] = blk
    st = dict(A["_artifactStamps"]["fuelContract"])
    st.update(generatedAt=now or datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M420: derived by tools/integration_scenarios.py from the raw I/V samples of the master drives; additive single-choice integration scenarios (audit F17)",
              upstreamHashes={"driveMasterMd5": master_md5})
    for k in ("carriedForward", "basisNDrives", "carriedFromMaster", "carryForwardNote", "reissuedFrom", "reissueNote", "supersededCarryNote", "carriedBlocks", "includedInReleaseAt", "computedAt", "computedAtNote", "inputBasis"):
        st.pop(k, None)
    new["_artifactStamps"]["integrationScenarios"] = st
    changed = ([] if old == blk else ["/integrationScenarios"]) + ["/_artifactStamps/integrationScenarios"]
    bad = [c for c in changed if c not in ALLOWED]
    return new, changed, bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 4
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    raw_dir = os.environ.get("XT_RAW_DIR_STAGED") or os.path.join(ROOT, "raw_only")   # master-key view of raw/ (tools/stage_raw.py), as the other raw-pass tools
    blk = build(dm, raw_dir, A0, workers)
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, changed, bad = splice(A0, blk, md5)
    ck = blk["checks"]
    print(json.dumps({"changed": changed, "outsideAllowList": bad, "checks": {k: v.get("pass") for k, v in ck.items()}, "maxDevKwh": ck["baselineReproducesMaster"]["maxAbsDevKwh"],
                      "ratios": {r["id"]: r["ratioToBaseline"] for r in blk["scenarios"]}}, indent=1))
    if bad or not all(v["pass"] for v in ck.values()):
        return 1
    if "--dry-run" not in argv:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
