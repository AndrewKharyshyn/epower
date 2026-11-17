#!/usr/bin/env python3
"""M717 (specs analyses/M708_spec.md Rev 2 section 9 and analyses/M712_spec.md Rev 1.1 section 9): the winter predictions P1-P7 and their frozen parameters, written ONCE from script-written source files before the first
winter drive (deadline 2026-12-01) so that winter data are a true out-of-sample test. Predictions are scored BEFORE any refit; a refit is a new version and the old predictions are kept.
Nothing is typed: every number is read from a source file (hashed below) or derived from such numbers by the formulas stated in the file. The predictions concern model-derived quantities; the cold outputs of the scenario model are
NOT SUPPORTED (M713 ruling), the winter drives are exactly the test that can change that.
Usage: python tools/winter_freeze.py [--out analyses/M717_winter_predictions.json] | --check    (--check: the file equals a fresh derivation and every source hash matches)"""
import argparse, hashlib, json, math, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
OUT = "analyses/M717_winter_predictions.json"
RGAS = 8.314462618
V_NOM, CAP_AH = 360.0, 5.0                                     # pack voltage (median logged) and the 5 Ah rated basis (verified:false), as in the scenario engine
SOURCES = {"stateParams": "analyses/M713/state_params.json", "parkModel": "analyses/M709/park_model.json", "scenarioResults": "analyses/M713/scenario_results_production.json", "scenarioGates": "analyses/M713/scenario_gates.json",
           "rangesFile": "analyses/M712_ranges.json", "specM712": "analyses/M712_spec.md", "specM708": "analyses/M708_spec.md", "prototypeThermalParams": "analyses/exposure_scenarios_2026-11-16/results/thermal_params.json"}


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def load(k):
    return json.load(open(SOURCES[k], encoding="utf-8"))


def ratio(ea_kj, t_c):
    return math.exp(ea_kj * 1000 / RGAS * (1 / (t_c + 273.15) - 1 / 298.15))


def build():
    ST, PK, SR, RG = load("stateParams"), load("parkModel"), load("scenarioResults"), load("rangesFile")
    if os.path.exists(SOURCES["prototypeThermalParams"]):                     # untracked prototype output: its two used regressions are stored in the freeze so that --check works in a clean checkout
        TP = load("prototypeThermalParams")
        proto = {"eng": TP["ambientEffects"]["ambient_lt20"]["eng"], "lnahkm": TP["ambientEffects"]["ambient_lt20"]["lnahkm"], "sha256": sha(SOURCES["prototypeThermalParams"])}
    else:
        proto = json.load(open(OUT, encoding="utf-8"))["prototypeInputs"]
    ea, ea_lo, ea_hi = ST["R_T"]["EaR_kJmol"], ST["R_T"]["EaR_ci"][0], ST["R_T"]["EaR_ci"][1]
    lm = ST["limitMap"]
    b0, b0lo, b0hi = lm["b0_kW_at_0C_soc60"]
    bT, bTlo, bThi = lm["bT_kW_perC"]
    m2 = PK["M2_fullSample_nonFlagged"]
    S2, S3b, S3a, S3c = (SR[k]["E_real"] for k in ("S2_balanced_owner_expected", "S3b_cold_winter", "S3a_mild_winter", "S3c_severe_winter"))
    band = [min(S2["ahShare_T_lt10"][1], S3b["ahShare_T_lt10"][1], S3a["ahShare_T_lt10"][1]), max(S2["ahShare_T_lt10"][2], S3b["ahShare_T_lt10"][2], S3a["ahShare_T_lt10"][2])]
    eng, lnahkm = proto["eng"], proto["lnahkm"]
    crate = lambda kw: kw * 1000.0 / V_NOM / CAP_AH
    params = {
        "R_T": {"EaR_kJmol": ea, "EaR_ci": [ea_lo, ea_hi], "R25_mohm": ST["R_T"]["R25_mohm"]},
        "driveHeating": {k: ST["drive"][k][0] for k in ("alpha_C_per_A2h", "tau_d_h", "c0_C", "c1")},
        "limitMap": {"b0_kW_at_0C_soc60": b0, "bT_kW_perC": bT, "bS_kW_perSocPt": lm["bS_kW_perSocPt"][0], "extrapolatedBelowObservedRange": True},
        "diurnalAmbient": ST["diurnalAmbient"],
        "park": {"tau_h": m2["tau_h"], "tauCi": m2["tauCi"], "offset_C": m2["offset_C"], "offsetCi": m2["offsetCi"], "offsetBracketForSensitivity": ST["park"]["offsetBracketForSensitivity"], "oneOffsetAllSeasons": True},
        "scenarioDefaults": SR["defaults"], "climateNormalSource": "summary_arrays.json seasonalLife.assumptions.monthlyTempC (external, user-supplied, not measured by this study)",
        "assumptionRanges": {"file": SOURCES["rangesFile"], "sha256": sha(SOURCES["rangesFile"])},
    }
    pred = {
        "P1": {"name": "start-temperature accuracy of the state-model chain on winter drives", "rule": "free-run MAE of the simulated start temperature <= 3 C and |bias| <= 2 C; park model: held-out bias within +-1 C at gaps >= 12 h and within +-0.5 C around the 10 and 15 C thresholds on winter restart pairs",
               "frozenParameters": ["params.park", "params.driveHeating", "params.diurnalAmbient"], "scoredBefore": "any refit"},
        "P2": {"name": "Ah share below 10 C inside the scenario band for the realised ambient", "bandAhShareBelow10C": [round(band[0], 4), round(band[1], 4)], "source": "analyses/M713/scenario_results_production.json E_real 95 % intervals of S3a, S2, S3b (union)",
               "rule": "the day-clustered 95 % interval of the realised winter Ah share below 10 C lies inside the band (computed for the REALISED ambient when it is known); cold outputs are NOT SUPPORTED until this and P1 hold"},
        "P3": {"name": "resistance proxy ratio at 0 C", "ratio_R_0C_vs_25C": round(ratio(ea, 0), 3), "interval": [round(ratio(ea_lo, 0), 3), round(ratio(ea_hi, 0), 3)], "ratio_R_minus10C_vs_25C": round(ratio(ea, -10), 3),
               "formula": "exp(EaR/Rgas (1/T - 1/298.15 K)) with EaR and its bootstrap interval from the state parameters", "expected": "expected to fail HIGH if the slope steepens below the observed range (one activation energy is an extrapolation)",
               "rule": "the winter pulse-resistance proxy at 0 C over its 25 C value lies inside the interval; below the observed range the single-Ea form is an assumption"},
        "P4": {"name": "BMS charge-limit register at the coldest probe, SoC 60 %", "kW_at_0C": [round(b0, 2), round(b0lo, 2), round(b0hi, 2)], "kW_at_minus10C": round(b0 - 10 * bT, 2),
               "envelope_at_minus10C": [round(b0lo - 10 * bThi, 2), round(b0hi - 10 * bTlo, 2)], "formula": "b0 + bT * T (SoC 60) with the fitted map; envelope from the interval ends (conservative)", "label": "BMS-reported register, not delivered power; linear extrapolation below the observed range",
               "rule": "the logged register at 0 C and SoC 60 % lies inside the 0 C interval; at -10 C inside the envelope"},
        "P5": {"name": "Ah per km in the cold, no increase against autumn", "dataSlope_lnAhPerKm_perC_ambientBelow20C": lnahkm, "M28_alternative": "+6 to +16 % per 10 C of cooling",
               "rule": "one-sided: at matched trip-length and speed class, winter Ah per km is NOT higher than autumn; the hypothesis is rejected when the day-clustered lower 95 % bound of the winter-minus-autumn increase exceeds +6 % scaled to the realised temperature difference"},
        "P6": {"name": "peak charge C-rate below 0 C within the limit map", "C_at_0C_soc60": round(crate(b0), 2), "formula": "limit kW * 1000 / 360 V / 5 Ah (rated basis, verified:false)", "rule": "the peak charge C-rate below 0 C does not exceed the limit-map C-rate at the logged temperature and SoC"},
        "P7": {"name": "engine-on share rises with cooling", "points_per_C_cooling_ambientBelow20C": [round(-100 * eng["slopePerC"], 3), round(-100 * eng["ci"][1], 3), round(-100 * eng["ci"][0], 3)],
               "source": "prototype thermal_params.json ambientEffects.ambient_lt20.eng (per-drive regression with trip-length and mean-speed controls; association, not a temperature effect)", "rule": "the winter slope of the engine-on share on ambient (below 20 C) lies inside the interval (points per C)"},
    }
    return {
        "milestone": "M717", "status": "FROZEN before 2026-12-01 and before the first winter drive; scored before any refit; a refit is a NEW VERSION and the old predictions are kept",
        "language": "model-derived; logged readings are 'logged', never 'measured'; no end-of-life; cold outputs NOT SUPPORTED until P1 and P2 hold on winter data",
        "evaluation": {"cells": "each evaluation cell needs >= 10 drives (pairs) on >= 5 days, else 'not evaluable'", "cluster": "calendar day, percentile bootstrap, seed 42, 4000 draws", "looks": ["2027-02-11 descriptive", "2027-05-11 formal (N-01, equivalence needs SE <= 0.328)"],
                       "updateTriggers": ["a prediction outside its band on >= 10 drives / 5 days", "any pack reading below 0 C (first sub-zero data: refit R(T) and the limit map with a curvature term, as a new version)", "a change of the logged-share factor by more than 5 points"],
                       "decisionRule": "predictions are scored before any refit; refits are reported as new versions with the old predictions kept"},
        "prototypeInputs": proto, "params": params, "predictions": pred,
        "sources": {k: {"path": p, "sha256": (sha(p) if os.path.exists(p) else proto["sha256"])} for k, p in SOURCES.items()},
        "derivedBy": "tools/winter_freeze.py", "scriptSha256": sha(os.path.abspath(__file__)),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    fresh = build()
    if a.check:
        cur = json.load(open(a.out, encoding="utf-8"))
        problems = []
        if cur != fresh:
            problems.append("the file differs from a fresh derivation (a source file or this script changed)")
        for k, v in cur["sources"].items():
            if k == "prototypeThermalParams" and not os.path.exists(v["path"]):
                continue                                                     # untracked, absent in a clean checkout: the used values are stored in prototypeInputs
            if sha(v["path"]) != v["sha256"]:
                problems.append("source %s changed since the freeze" % k)
        print(json.dumps({"problems": problems, "fileSha256": sha(a.out)}))
        return 1 if problems else 0
    json.dump(fresh, open(a.out, "w", encoding="utf-8"), indent=1)
    print(json.dumps({"written": a.out, "sha256": sha(a.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
