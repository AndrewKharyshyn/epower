#!/usr/bin/env python3
"""M713c (spec analyses/M712_spec.md Rev 1.1, section 8): gate evaluation of the scenario engine.
G-S0  replay identity: the observed eligible day sequence replayed without transform, tilt or odometer factors conserves km, Ah, kWh, engine starts and drives (max relative difference <= 1e-9).
G-S1  anchoring: the tilted primary scenario's EXPECTED annual distance (logged + unlogged km once) is within 0.5 % of the odometer target.
G-S3  reproduction, binding on the IDENTICAL inputs of the prototype (prototype pool rule, prototype ambient reconstruction, superseded park constants, 21,132 km, seed 42, 4000 draws): every E-real mean of the
      S2 headline metrics lies inside the prototype day-block interval; the maximum relative difference of the means is reported; THEN the production run (data pool rule, M709 park, production ambient) is
      reported with the per-metric delta (attribution per input is the sensitivity work of M713d). A failed gate is recorded as failed and never relaxed.
G-S2 / G-S2b (consistency check and month-blocked hold-out) and G-S4 (assumption table) are M713d.
Usage: python tools/scenario_gates.py [--dir analyses/M713]   writes <dir>/scenario_gates.json"""
import argparse, json, os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import scenario_engine as SE

HEADLINE = ["annual_km", "drives", "ah_throughput", "gtc_5Ah_rated", "gtc_2p1kWh_legacy", "fce_5Ah_rated", "ahShare_T_lt10", "ahShare_T_ge35", "ahShare_T_ge40", "hotTail_ah_ge35",
            "coldChargeIndex_AhxC_lt10", "warmups_Tstart_lt15", "arrCycleAF_Ea50", "arrCalendarAF_year_Ea50", "parkedShareOfCalendarDose_Ea50", "parked_meanPackT", "engine_starts"]
PROTO_NAME = {"coldChargeIndex_AhxC_lt10": "coldChargeStress_AhxC_lt10", "coldChargeIndex_AhxC_lt0": "coldChargeStress_AhxC_lt0"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "analyses", "M713"))
    a = ap.parse_args(argv)
    g = {}
    # G-S0 / G-S1 on the production model
    M = SE.load_model(a.dir, "production")
    idt = SE.replay_identity(M)
    g["G-S0"] = {"pass": bool(idt["maxAbsRelDiff"] <= 1e-9), "maxAbsRelDiff": idt["maxAbsRelDiff"], "nEligibleDays": int(M.ok.sum()), "totals": {k: v for k, v in idt.items() if k != "maxAbsRelDiff"}}
    sc = SE.scenarios(M.ODO_KM)["S2_balanced_owner_expected"]
    tilt = SE.solve_tilt(M, sc["km"], sc["w_sum"], M.params["f_s"], M.params["f_a"])
    ek = SE.expected_km(M, sc["w_sum"], tilt, M.params["f_s"], M.params["f_a"])
    g["G-S1"] = {"pass": bool(abs(ek - M.ODO_KM) / M.ODO_KM < 0.005), "targetKm": round(M.ODO_KM, 2), "expectedKmAtTilt": round(float(ek), 2), "tilt_per100km": round(float(tilt), 5),
                 "relError": float(abs(ek - M.ODO_KM) / M.ODO_KM), "odometerTarget": "latest dash odometer / years since registration (summary_config.json), not typed"}
    # G-S3 binding on identical inputs
    pp = os.path.join(ROOT, "analyses", "exposure_scenarios_2026-11-16", "results", "scenario_results.json")
    fp = os.path.join(a.dir, "scenario_gs3_identical_S2.json")
    if os.path.exists(pp) and os.path.exists(fp):
        P = json.load(open(pp, encoding="utf-8"))["S2_balanced_owner_expected"]
        R = json.load(open(fp, encoding="utf-8"))
        E = R["S2_balanced_owner_expected"]["E_real"]
        rows, maxrel, inside = {}, 0.0, True
        for k in HEADLINE:
            q = P.get(PROTO_NAME.get(k, k))
            if q is None or E.get(k) is None:
                continue
            m, lo, hi = E[k]
            rel = abs(m - q[0]) / max(abs(q[0]), 1e-12)
            ins = bool(q[1] <= m <= q[2])
            inside &= ins
            maxrel = max(maxrel, rel)
            rows[k] = {"production": m, "prototype": q[0], "prototypeInterval": [q[1], q[2]], "inside": ins, "relDiff": round(rel, 6)}
        g["G-S3"] = {"pass": bool(inside), "maxRelDiffOfMeans": round(maxrel, 6), "identicalInputs": {"poolRule": "prototype assumption window 2026-05-19..06-08", "ambient": "prototype drive_ambient_recon.csv (comparison-only)", "park": "superseded prototype constants (tau 7.554 h, offsets 1.163 / 3.405 C)", "odoKm": 21132.0, "seed": 42, "draws": R["draws"]},
                     "identityOnPrototypeModel": R["identity"], "metrics": rows}
    else:
        g["G-S3"] = {"pass": None, "note": "prototype results or the identical-input run not available"}
    prod = os.path.join(a.dir, "scenario_results_production.json")
    if os.path.exists(prod) and os.path.exists(pp):
        R = json.load(open(prod, encoding="utf-8"))
        P = json.load(open(pp, encoding="utf-8"))["S2_balanced_owner_expected"]
        E = R["S2_balanced_owner_expected"]["E_real"]
        d = {}
        for k in HEADLINE:
            q = P.get(PROTO_NAME.get(k, k))
            if q is not None and E.get(k) is not None:
                d[k] = {"production": E[k], "prototype": q, "relDiffOfMean": round((E[k][0] - q[0]) / max(abs(q[0]), 1e-12), 4)}
        g["G-S3"]["productionVersionDelta"] = {"inputs": "data pool rule (Q5), M709 park (one offset), production ambient reconstruction, project integration rule NOT yet applied to the engine (prototype zero-order-hold Ah/kWh)", "excludedDays": R["excludedDays"], "pools": R["pools"], "metrics": d}
    json.dump(g, open(os.path.join(a.dir, "scenario_gates.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: v.get("pass") for k, v in g.items()}))
    return 0 if all(v.get("pass") in (True, None) for v in g.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
