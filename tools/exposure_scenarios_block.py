#!/usr/bin/env python3
"""M714 (spec analyses/M712_spec.md Rev 1.1, section 11): the ADDITIVE payload block `exposureScenarios` of summary_arrays.json, assembled from the M713 result files (analyses/M713/*.json, produced by tools/scenario_*.py,
tools/exposure_state.py and tools/exposure_odometer.py), with a support status per metric (Director ruling of M713, option A) and the failed gates shown beside every cold figure.
Nothing is displayed: no dashboard binding, no relabelling of the legacy blocks (cycleLife, seasonalLife, kLadderScenarios, dod, parkedTimeBudget); that is M715 and needs Andrii's sign-off.
The block is model-derived (never "measured"), an exposure scenario and not an ageing or end-of-life estimate (M114), on two capacity bases (5 Ah rated and 2.1 kWh legacy, both verified:false).
Refresh: ON DEMAND (about 2.5 h: scenario_frame, exposure_state, exposure_odometer, scenario_engine, scenario_validation, scenario_sensitivity, scenario_gates), then --splice. Each ingestion carries the block forward at its basis.
Modes: (none) assemble and print the size | --splice [--dry-run] | --check (the spliced block equals a fresh assembly from the files and every recorded source hash matches)."""
import copy, datetime, hashlib, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

KEY = "exposureScenarios"
DIR = "analyses/M713"
SOURCES = ["scenario_results_production.json", "scenario_expected.json", "scenario_gates.json", "scenario_attribution.json", "scenario_sensitivity.json", "scenario_lodo.json", "state_params.json",
           "odometer_check.json", "scenario_results_production_projectrule_S2.json", "scenario_validation.json", "scenario_validation_diagnostics.json", "exposure_frame_check.json", "odometer_readings.json"]
HEADLINE = ["annual_km", "drives", "ah_throughput", "gtc_5Ah_rated", "gtc_2p1kWh_legacy", "fce_5Ah_rated", "ahShare_T_lt10", "ahShare_T_ge35", "ahShare_T_ge40", "hotTail_ah_ge35", "coldChargeIndex_AhxC_lt10",
            "warmups_Tstart_lt15", "arrCycleAF_Ea50", "arrCalendarAF_year_Ea50", "parkedShareOfCalendarDose_Ea50", "parked_meanPackT", "engine_starts"]

COLD = re.compile(r"^(coldCharge|ahShare_T_lt|ah_T_(<0|0-5|5-10)$|warmups_|starts_Tstart|ah_in_warmup|chargeAh_aboveExtrapolatedLimit|coldest_start_T|parked_hours_lt)")
HOT = re.compile(r"^(ahShare_T_ge|hotTail_|ah_T_(30-35|35-40|40-45|>=45)$|parked_hours_ge)")
DOSE = re.compile(r"^(arr|parked_meanPackT|parkedShare)")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def metric_status(name):
    """Support status of a metric (Director ruling M713, option A): cold outputs NOT SUPPORTED, hot outputs a BRACKET, dose indices exposure-weighted INDICES, everything else SUPPORTED."""
    if COLD.match(name):
        return "notSupported"
    if HOT.match(name):
        return "bracket"
    if DOSE.match(name):
        return "index"
    return "supported"


STATUS_TEXT = {
    "supported": "supported: passes the replay identity, the odometer anchoring and the reproduction of the prototype; independent of the parked-temperature model",
    "notSupported": "NOT SUPPORTED (model-derived): the consistency check (G-S2) and the month-blocked hold-out (G-S2b) failed on starts with pack temperature below 15 C (simulated +28 % / +32 % above the logged count); not displayed, not used in the article",
    "bracket": "bracket: the simulated hot share is biased low (-5.8 points in-sample, -3.3 points in the month-blocked hold-out; -13 % / -25 % relative); read it as a lower bound with the hold-out bias as its bound",
    "index": "exposure-weighted index (Arrhenius-weighted hours or Ah), not ageing and not damage; sensitive to the parked pack temperature (offset bracket 0 to 2.7 C reported)",
}


def load(name):
    return json.load(open(os.path.join(DIR, name), encoding="utf-8"))


def assemble(md5=None):
    md5 = md5 or hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    R, E, G, A, S, L = (load(n) for n in ("scenario_results_production.json", "scenario_expected.json", "scenario_gates.json", "scenario_attribution.json", "scenario_sensitivity.json", "scenario_lodo.json"))
    ST, O, PR, V, VD, FC = (load(n) for n in ("state_params.json", "odometer_check.json", "scenario_results_production_projectrule_S2.json", "scenario_validation.json", "scenario_validation_diagnostics.json", "exposure_frame_check.json"))
    names = [k for k in R if k[:1] == "S" and isinstance(R[k], dict) and "E_real" in R[k]]
    scen = {}
    for nm in names:
        er = R[nm]["E_real"]
        scen[nm] = {"note": R[nm]["note"], "tiltPer100km": R[nm]["tilt_per100km"], "E_real": er,
                    "E_exp": {k: E[nm]["E_exp"][k] for k in HEADLINE if k in E.get(nm, {}).get("E_exp", {})}}
    metrics = sorted({k for nm in names for k in R[nm]["E_real"]})
    S2 = "S2_balanced_owner_expected"
    pr = PR[S2]["E_real"]
    sens = {y: {"mean": v["mean"], "p2.5": v["p2.5"], "p97.5": v["p97.5"], "top4TotalOrder": [[b["param"], b["ST"]] for b in v["indices"][:4]]} for y, v in S["sobol"]["outputs"].items()}
    tor = {y: {"base": v["base"], "top3Spans": [[b["param"], b["atLo"], b["atHi"]] for b in v["bars"][:3]]} for y, v in S["tornado"].items()}
    blk = {
        "milestone": "M714", "spec": "analyses/M712_spec.md", "specSha256": sha("analyses/M712_spec.md"), "rangesFile": "analyses/M712_ranges.json", "rangesSha256": sha("analyses/M712_ranges.json"),
        "masterMd5": md5, "nDrives": FC["nDrives"], "basisNDrives": FC["nDrives"], "scriptSha256": sha(os.path.abspath(__file__)),
        "label": "exposure scenarios of one vehicle-year from a day-block replay with a pack-temperature state model: ESTIMATED, model-derived exposure indices (Ah, GTC, FCE, temperature, dose); not measured, not an ageing or end-of-life estimate; capacity bases 5 Ah rated and 2.1 kWh legacy, both unverified",
        "supportStatus": {"ruling": "Director ruling of M713 (option A): the pre-registered one-offset park model stays the baseline, the offset bracket 0 to 2.7 C is an assumption range, the failed gates are never relaxed",
                          "byGroup": {k: STATUS_TEXT[k] for k in ("supported", "notSupported", "bracket", "index")},
                          "byMetric": {k: metric_status(k) for k in metrics}},
        "gates": {"G-S0 replay identity": G["G-S0"]["pass"], "G-S1 distance anchoring": G["G-S1"]["pass"], "G-S3 reproduction of the prototype on identical inputs": G["G-S3"]["pass"],
                  "G-S2 consistency check (in-sample)": G["G-S2"]["pass"], "G-S2b month-blocked hold-out": G["G-S2b"]["pass"], "G-S4 assumption table": "reported, not gated",
                  "detail": {"G-S0": {"maxAbsRelDiff": G["G-S0"]["maxAbsRelDiff"], "nEligibleDays": G["G-S0"]["nEligibleDays"]}, "G-S1": {"targetKm": G["G-S1"]["targetKm"], "relError": G["G-S1"]["relError"]},
                             "G-S3": {"maxRelDiffOfMeans": G["G-S3"]["maxRelDiffOfMeans"], "inputs": G["G-S3"]["identicalInputs"]},
                             "G-S2": {"startsBelow15C": G["G-S2"]["startsBelow15C"], "arrCycleAF_Ea50": G["G-S2"]["arrCycleAF_Ea50"], "ahShare_ge35": G["G-S2"]["ahShare_ge35"], "nDays": G["G-S2"]["nDays"]},
                             "G-S2b": {"startsBelow15C": G["G-S2b"]["startsBelow15C"], "ahShare_ge35": G["G-S2b"]["ahShare_ge35"], "arrCycleAF_Ea50": G["G-S2b"]["arrCycleAF_Ea50"], "fit": G["G-S2b"]["fit"],
                                       "parameterCheck": G["G-S2b"]["parameterCheck"], "cleanHoldout": False, "note": "not a clean hold-out: ambient amplitude and peak hour were fitted on the whole corpus; the split is confounded with slow polling and the battery software update"}}},
        "intervals": {"E_real": "predictive distribution of single replayed-year totals (one day-pool bootstrap and one synthetic year per draw, seed 42, 4000 draws)", "E_exp": "day-pool bootstrap of the mean of 8 replayed years per pool (500 pools, fixed seed), headline metrics",
                      "scope": "neither interval contains assumption uncertainty; for the cold outputs the assumption spread is several times wider than the sampling interval"},
        "pools": {"summerPattern": R["pools"]["summer"], "autumnPattern": R["pools"]["autumn"], "eligibleDays": R["pools"]["all"], "excludedDays": R["excludedDays"], "poolRule": "data rule (dash-odometer evidence); the prototype assumption window is a sensitivity of the attribution"},
        "odometer": {"loggedShareSince": O["rows"][0]["from"], "totalOdoKm": O["total"]["odoKm"], "loggedKm": O["total"]["loggedKm"], "share": O["total"]["share"], "factors": O["factors"], "unloggedIntervals": O["unloggedIntervals"],
                     "unloggedDays": len(O["unloggedDays"]), "zeroDriveDays": len(O["zeroDriveDays"]), "noOdometerCoverDays": len(O["noOdometerCoverDays"]), "rule": O["rule"], "target": "odometer lifetime mean km per year (latest dash reading over years since registration), not typed: %s km" % round(R["odoKmTarget"], 2)},
        "stateModel": {"R_T": ST["R_T"], "drive": {k: ST["drive"][k] for k in ("alpha_C_per_A2h", "tau_d_h", "c0_C", "c1", "n", "nDays", "mae_Tend_C", "bias_Tend_C")}, "limitMap": ST["limitMap"], "diurnalAmbient": ST["diurnalAmbient"], "park": ST["park"],
                       "scenarioDefaults": R["defaults"]},
        "scenarios": scen,
        "attribution": {"scenario": S2, "stepNames": A["stepNames"], "stepRelativeDeltasOfMeans": {k: v for k, v in A["stepDeltas"].items() if k in ("annual_km", "gtc_5Ah_rated", "ahShare_T_lt10", "ahShare_T_ge35", "coldChargeIndex_AhxC_lt10", "warmups_Tstart_lt15", "arrCalendarAF_year_Ea50")},
                        "reading": "the rise of the cold-charge index and of the Ah share below 10 C against the prototype comes from the one-offset park model; the same park model overpredicts starts below 15 C"},
        "diagnostics": {"startsBelow15C_byParkConstants": VD["variants"], "note": VD["note"]},
        "integrationRule": {"S2_projectRule": {k: pr[k] for k in ("ah_throughput", "gtc_5Ah_rated", "gtc_2p1kWh_legacy", "annual_km")}, "relDiffVsZeroOrderHold": G["integrationRule"]["relDiffOfMeans"],
                            "note": "the frame uses the zero-order-hold 1 Hz rule (prototype); the project rule (Ah sidecar, master kWh) is 3.5 % lower on throughput"},
        "sensitivity": {"rangesSha256": S["rangesSha256"], "sobolN": S["sobol"]["N"], "outputs": sens, "tornado": tor, "reading": "the ranking follows the chosen ranges: it describes this table, it is not a finding about the vehicle"},
        "influence": G["leaveOneDayOut"],
        "limits": ["one vehicle, a half-year window of logged days; annual distance is anchored on the dash odometer, not identified by the window", "no sub-zero pack data: cold behaviour is an extrapolation",
                   "parked pack temperature is never logged: the park model is estimated on restart pairs; the climate normal is an external assumption", "the hold-out is not clean", "calendar and cycle terms cannot be separated on one vehicle"],
        "refresh": "on demand (about 2.5 h: tools/scenario_frame.py, exposure_state.py, exposure_odometer.py, scenario_engine.py, scenario_validation.py, scenario_sensitivity.py, scenario_gates.py, then this tool with --splice); each ingestion carries the block forward at its basis",
        "sources": {n: sha(os.path.join(DIR, n)) for n in SOURCES},
    }
    return blk


def splice(A, blk, md5, now=None):
    import stamp_common as _sc
    new = copy.deepcopy(A)
    new[KEY] = blk
    ts = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    old = (A.get("_artifactStamps") or {}).get(KEY)
    st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=md5, generatedAt=ts, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M714: assembled by tools/exposure_scenarios_block.py from the M713 result files (tools/scenario_*.py, exposure_state.py, exposure_odometer.py; spec analyses/M712_spec.md Rev 1.1); model-derived exposure scenarios, cold outputs not supported")
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    bad = [k for k in set(A) | set(new) if k not in (KEY, "_artifactStamps") and A.get(k) != new.get(k)]
    bad += [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if k != KEY and A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k)]
    return new, bad


def do_splice(dry=False):
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    blk = assemble(md5)
    raw = open("summary_arrays.json", encoding="utf-8", newline="").read()
    new, bad = splice(json.loads(raw), blk, md5)
    print(json.dumps({"outsideKeys": bad, "sizeBytes": len(json.dumps(blk))}))
    if bad:
        return 1
    if not dry:
        open("summary_arrays.json", "w", encoding="utf-8", newline="").write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


def do_check():
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    problems = []
    if KEY not in A:
        return ["%s missing from summary_arrays.json" % KEY]
    fresh = assemble(A[KEY]["masterMd5"])
    if fresh != A[KEY]:
        problems.append("the spliced %s differs from a fresh assembly of analyses/M713 (re-run --splice, or a source file changed)" % KEY)
    for n, h in A[KEY]["sources"].items():
        if sha(os.path.join(DIR, n)) != h:
            problems.append("source %s changed since the splice" % n)
    return problems


if __name__ == "__main__":
    if "--splice" in sys.argv:
        sys.exit(do_splice("--dry-run" in sys.argv))
    if "--check" in sys.argv:
        p = do_check()
        print(json.dumps({"problems": p}))
        sys.exit(1 if p else 0)
    b = assemble()
    print(json.dumps({"sizeBytes": len(json.dumps(b)), "metrics": len(b["supportStatus"]["byMetric"]), "status": {s: sum(1 for v in b["supportStatus"]["byMetric"].values() if v == s) for s in ("supported", "notSupported", "bracket", "index")}}))
