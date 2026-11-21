#!/usr/bin/env python3
"""M713c (spec analyses/M712_spec.md Rev 1.1, section 8): gate evaluation of the scenario engine.
G-S0  replay identity: the observed eligible day sequence replayed without transform, tilt or odometer factors conserves km, Ah, kWh, engine starts and drives (max relative difference <= 1e-9).
G-S1  anchoring: the tilted primary scenario's EXPECTED annual distance (logged + unlogged km once) is within 0.5 % of the odometer target.
G-S3  reproduction, binding on the IDENTICAL inputs of the prototype (prototype pool rule, prototype ambient reconstruction, superseded park constants, 21,132 km, seed 42, 4000 draws): every E-real mean of the
      S2 headline metrics lies inside the prototype day-block interval; the maximum relative difference of the means is reported; THEN the production run (data pool rule, M709 park, production ambient) is
      reported with the per-metric delta (attribution per input is the sensitivity work of M713d). A failed gate is recorded as failed and never relaxed.
G-S2 / G-S2b (consistency check and month-blocked hold-out; tools/scenario_validation.py) and G-S4 (assumption table, reported; tools/scenario_sensitivity.py) are aggregated here with the attribution, leave-one-day-out, integration-rule and E-exp results (M713d).
Usage: python tools/scenario_gates.py [--dir analyses/M713]   writes <dir>/scenario_gates.json"""
import argparse, hashlib, json, os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import scenario_engine as SE

HEADLINE = ["annual_km", "drives", "ah_throughput", "gtc_5Ah_rated", "gtc_2p1kWh_legacy", "fce_5Ah_rated", "ahShare_T_lt10", "ahShare_T_ge35", "ahShare_T_ge40", "hotTail_ah_ge35",
            "coldChargeIndex_AhxC_lt10", "warmups_Tstart_lt15", "arrCycleAF_Ea50", "arrCalendarAF_year_Ea50", "parkedShareOfCalendarDose_Ea50", "parked_meanPackT", "engine_starts"]
PROTO_NAME = {"coldChargeIndex_AhxC_lt10": "coldChargeStress_AhxC_lt10", "coldChargeIndex_AhxC_lt0": "coldChargeStress_AhxC_lt0"}


def accepted_pattern(g, d):
    """Wrapper: any missing key or None value is a stop with a printed reason, never an uncaught exception."""
    try:
        return _accepted_pattern(g, d)
    except (KeyError, TypeError, ValueError) as e:
        return False, ["malformed gate record: %s %s" % (type(e).__name__, e)]


def _accepted_pattern(g, d):
    """(True, []) only for the Director-accepted failure pattern (analyses/M713/accepted_failure_pattern.json); otherwise (False, reasons)."""
    pp = os.path.join(d, "accepted_failure_pattern.json")
    fails = sorted(k for k, v in g.items() if isinstance(v, dict) and v.get("pass") is False)
    if not fails or not os.path.exists(pp):
        return False, []
    P = json.load(open(pp, encoding="utf-8"))
    why = []
    if fails != sorted(P["gates"]):
        why.append("false gates %s differ from the accepted set %s" % (fails, P["gates"]))
    for k in ("G-S0", "G-S1", "G-S3"):
        if g.get(k, {}).get("pass") is not True:
            why.append("%s is not true" % k)
    if g.get("G-S4", {}).get("pass") is not None:
        why.append("G-S4 is not null")
    if why:
        return False, why
    sf = (g.get("supportStatus") or {}).get("failedGates")
    if sorted(sf or []) != fails:
        why.append("supportStatus.failedGates differs from the false gates")
    for k in P["gates"]:
        r, b = g[k], P["baseline"][k]
        st, hs = r["startsBelow15C"]["relError"], r["ahShare_ge35"]["relError"]
        if st is None or not st > 0:
            why.append("%s starts below 15 C no longer an overestimate" % k)
        if hs is None or not hs < 0:
            why.append("%s hot share no longer biased low" % k)
        if abs(r["arrCycleAF_Ea50"]["relError"]) > P["arrCycleAF_tolerance"]:
            why.append("%s arrCycleAF_Ea50 outside tolerance" % k)
        for nm, x in (("startsBelow15C", st), ("ahShare_ge35", hs)):
            if x is None:
                continue
            bb = b[nm + "_relError"]
            toward = (x * bb > 0) and abs(x) <= abs(bb)     # Director M721: same sign, not larger: accepted against the FIXED M713 baseline
            if not toward and abs(x - bb) > P["maxMovement"] + 1e-9:
                why.append("%s %s relError %.4f moved away from or across the M713 baseline %.4f by more than %.2f" % (k, nm, x, bb, P["maxMovement"]))
    if g["G-S2b"]["gate"].get("cleanHoldout") != P["baseline"]["G-S2b"]["cleanHoldout"]:
        why.append("G-S2b cleanHoldout changed")
    return (not why), why


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
    # M713d: G-S2 / G-S2b (tools/scenario_validation.py), G-S4 (reported), attribution, influence, E-exp, project integration rule
    vp = os.path.join(a.dir, "scenario_validation.json")
    if os.path.exists(vp):
        V = json.load(open(vp, encoding="utf-8"))
        for k in ("G-S2", "G-S2b"):
            if k in V:
                g[k] = {"pass": V[k]["gate"]["pass"], "gate": V[k]["gate"], "ahShare_ge35": V[k]["ahShare_ge35"], "arrCycleAF_Ea50": V[k]["arrCycleAF_Ea50"], "startsBelow15C": V[k]["startsBelow15C"], "nDays": V[k]["nDays"]}
                for extra in ("fit", "parameterCheck", "hotShareBracket"):
                    if extra in V[k]:
                        g[k][extra] = V[k][extra]
        failed = [k for k in ("G-S2", "G-S2b") if k in g and g[k]["pass"] is False]
        # Director ruling (M713, option A): the baseline stays the pre-registered M709 one-offset park model; the failed gates are never relaxed; support status per metric group
        # (all figures below are generated from the computed gate records, none typed)
        pc = lambda x: "%+.0f %%" % (100 * x)
        s2, s2b = g.get("G-S2", {}), g.get("G-S2b", {})
        g["supportStatus"] = {"ruling": "Director M713: option A (keep the M709 one offset, offset bracket [0, 2.7] C as an ASSUMPTION range, G-S2 / G-S2b shown beside every cold figure); option B only as a pre-registered M708 Rev 3 post-result deviation acknowledged by Andrii; option C rejected as baseline (sensitivity only)",
                              "failedGates": failed,
                              "nonThermal (annual km, drives, Ah, GTC, FCE, engine starts)": "supported: pass G-S0, G-S1, G-S3, unaffected by the park step",
                              "cold outputs (Ah and charge Ah below 10 / 0 C, cold-charge index, starts and Ah while pack < 15 C, coldest start)": "NOT SUPPORTED (model-derived; G-S2 / G-S2b failed on starts below 15 C: simulated %s / %s); not displayed, not used in the article" % (pc(s2.get("startsBelow15C", {}).get("relError") or 0), pc(s2b.get("startsBelow15C", {}).get("relError") or 0)),
                              "hot share (Ah at or above 35 / 40 C, pack mean)": "reported as a BRACKET: biased low by %+.1f points (%s) in-sample and %+.1f points (%s) in the hold-out; bias bound from the hold-out" % (s2.get("ahShare_ge35", {}).get("diffPoints", 0), pc(s2.get("ahShare_ge35", {}).get("relError") or 0), s2b.get("ahShare_ge35", {}).get("diffPoints", 0), pc(s2b.get("ahShare_ge35", {}).get("relError") or 0)),
                              "calendar and cycle dose indices": "exposure-weighted indices; sensitive to the parked temperature (offset bracket reported); not ageing"}
    sp = os.path.join(a.dir, "scenario_sensitivity.json")
    if os.path.exists(sp):
        S = json.load(open(sp, encoding="utf-8"))
        g["G-S4"] = {"pass": None, "reportedNotGated": True, "rangesSha256": S["rangesSha256"], "sobolN": S["sobol"]["N"],
                     "topTotalOrder": {y: [(b["param"], b["ST"]) for b in v["indices"][:4]] for y, v in S["sobol"]["outputs"].items()}}
    ap_ = os.path.join(a.dir, "scenario_attribution.json")
    if os.path.exists(ap_):
        A = json.load(open(ap_, encoding="utf-8"))
        g["attribution"] = {"stepNames": A["stepNames"], "stepRelativeDeltasOfMeans": {k: v for k, v in A["stepDeltas"].items() if k in ("annual_km", "gtc_5Ah_rated", "ahShare_T_lt10", "ahShare_T_ge35", "coldChargeIndex_AhxC_lt10", "warmups_Tstart_lt15", "arrCalendarAF_year_Ea50")}}
    lp, ep = os.path.join(a.dir, "scenario_lodo.json"), os.path.join(a.dir, "scenario_expected.json")
    if os.path.exists(lp) and os.path.exists(ep):
        L, Ex = json.load(open(lp, encoding="utf-8")), json.load(open(ep, encoding="utf-8"))["S2_balanced_owner_expected"]["E_exp"]
        hw = {k: (Ex[k][2] - Ex[k][1]) / 2 / max(abs(Ex[k][0]), 1e-12) for k in L["baseline"] if k in Ex}
        infl = [{"day": d, "metric": k, "relChange": round(x, 4), "relHalfWidth": round(hw[k], 4)} for d, v in L["days"].items() for k, x in v.items() if k in hw and hw[k] > 0 and abs(x) > hw[k]]
        mx = max((abs(x) / hw[k] for v in L["days"].values() for k, x in v.items() if k in hw and hw[k] > 0), default=0.0)
        g["leaveOneDayOut"] = {"draws": L["draws"], "nDays": len(L["days"]), "daysMovingAMetricBeyondItsEexpHalfWidth": infl, "maxInfluenceOverHalfWidth": round(float(mx), 3)}
    pr = os.path.join(a.dir, "scenario_results_production_projectrule_S2.json")
    if os.path.exists(prod) and os.path.exists(pr):
        Z = json.load(open(prod, encoding="utf-8"))["S2_balanced_owner_expected"]["E_real"]
        P = json.load(open(pr, encoding="utf-8"))["S2_balanced_owner_expected"]["E_real"]
        g["integrationRule"] = {"note": "S2 on the PROJECT integration rule (Ah sidecar, master kWh) against the zero-order-hold frame (prototype rule)", "relDiffOfMeans": {k: round(P[k][0] / Z[k][0] - 1, 4) for k in ("ah_throughput", "gtc_5Ah_rated", "gtc_2p1kWh_legacy")},
                                "projectRuleS2": {k: P[k] for k in ("ah_throughput", "gtc_5Ah_rated", "gtc_2p1kWh_legacy", "annual_km")}}
    if os.path.exists(ep):
        Ex = json.load(open(ep, encoding="utf-8"))
        g["E_exp_vs_E_real_S2"] = {k: {"E_exp": Ex["S2_balanced_owner_expected"]["E_exp"][k], "E_real": json.load(open(prod, encoding="utf-8"))["S2_balanced_owner_expected"]["E_real"][k]} for k in ("annual_km", "gtc_5Ah_rated", "coldChargeIndex_AhxC_lt10")}
    json.dump(g, open(os.path.join(a.dir, "scenario_gates.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: v.get("pass") for k, v in g.items() if isinstance(v, dict) and "pass" in v}))
    ok, why = accepted_pattern(g, a.dir)
    if ok:
        BASE = json.load(open(os.path.join(a.dir, "accepted_failure_pattern.json"), encoding="utf-8"))["baseline"]
        g["acceptedFailures"] = {"ruling": "Director M713 option A; gate exit code accepts the pre-ruled failure pattern, gate results unchanged", "gates": sorted(k for k in ("G-S2", "G-S2b") if g[k]["pass"] is False),
                                 "relErrors": {k: {nm: {"x": g[k][nm]["relError"], "baseline": BASE[k][nm + "_relError"], "diff": round(g[k][nm]["relError"] - BASE[k][nm + "_relError"], 4), "direction": "toward zero" if abs(g[k][nm]["relError"]) < abs(BASE[k][nm + "_relError"]) else "away from zero or equal"} for nm in ("startsBelow15C", "ahShare_ge35")} for k in ("G-S2", "G-S2b")}, "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()}
        json.dump(g, open(os.path.join(a.dir, "scenario_gates.json"), "w", encoding="utf-8"), indent=1)
        print("[scenario_gates] failure pattern equals the accepted M713 pattern: exit 0 (G-S2 / G-S2b stay FAILED)")
        return 0
    fails = [k for k, v in g.items() if isinstance(v, dict) and v.get("pass") is False]
    if not fails:
        return 0 if not (g.get("G-S2", {}).get("pass") is True or g.get("G-S2b", {}).get("pass") is True) else (print("[scenario_gates] STOP, escalate to the Director: G-S2 or G-S2b passed (pass flip; no automatic SUPPORTED)") or 1)
    print("[scenario_gates] STOP, escalate to the Director: " + ("; ".join(why) if why else "false gates outside the accepted set or no accepted-pattern file"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
