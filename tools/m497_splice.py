#!/usr/bin/env python3
"""M497 additive splice: writes ONLY socHysteresis.startRatioClustered into summary_arrays.json from analyses/M497_result.json (spec Rev 2, Director decision 'accept').
Idempotent; refuses to run if the result's masterMd5 or specSha256 differ from the live files. Usage: python tools/m497_splice.py [--dry-run]"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
R = json.load(open("analyses/M497_result.json", encoding="utf-8"))
P = "summary_arrays.json"
A = json.load(open(P, encoding="utf-8"))
md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
if R["provenance"]["masterMd5"] != md5:
    raise SystemExit("STOP: M497 result was computed on another master")
if R["provenance"]["specSha256"] != hashlib.sha256(open("analyses/M497_spec.md", "rb").read()).hexdigest():
    raise SystemExit("STOP: M497 spec changed after the result")
p, d, s = R["primary"], R["decision"], R["sensitivities"]
old = A["socHysteresis"]["stationaryVsHighwayContrast"][0]
ci = lambda o: {"lo": o.get("lo"), "hi": o.get("hi"), "upperUnbounded": o.get("upperUnbounded", False)}
leaf = {
    "label": "estimated per-second start-hazard ratio, high speed vs stationary, SoC-standardised (Mantel-Haenszel); detector-derived starts (rpm > 500); descriptive, not an effect of speed",
    "spec": R["spec"], "specSha256": R["provenance"]["specSha256"], "scriptSha256": R["provenance"]["scriptSha256"], "masterMd5": md5,
    "resultFile": "analyses/M497_result.json", "resultSha256": hashlib.sha256(open("analyses/M497_result.json", "rb").read()).hexdigest(),
    "seed": R["provenance"]["seed"], "B": R["provenance"]["B"], "resamplingUnit": "calendar day (co-primary: ISO week; Poisson regression clustered by day)",
    "nDrivesCovered": R["nDrivesCovered"], "nDays": R["nDays"], "nWeeks": R["nWeeks"], "frozenBins": R["frozenBins"],
    "R": p["R"], "kStationary": p["kStationary"], "kHigh": p["kHigh"], "nAtRiskStationary": p["nAtRiskStationary"], "nAtRiskHigh": p["nAtRiskHigh"],
    "daysWithStationaryStart": p["daysWithStationaryStart"], "weeksWithStationaryStart": p["weeksWithStationaryStart"], "top3DayShareOfStationaryStarts": p["top3DayShareOfStationaryStarts"],
    "dayBootstrap": ci(p["dayBootstrap"]), "weekBootstrap": {**ci(p["weekBootstrap"]), "coPrimary": p["weekBootstrap"]["coPrimary"]},
    "poissonClusterByDay": {k: p["poissonClusterByDay"][k] for k in ("ratio", "lo", "hi", "method")},
    "decision": {"L": d["L"], "widestInterval": d["widestInterval"], "widest": d["widest"], "wording": d["wording"], "thinSupport": d["thinSupport"]},
    "perBin": [{k: b.get(k) for k in ("socBin", "ratio", "kStationary", "kHigh", "lo", "hi", "upperUnbounded", "note") if k in b} for b in R["perBin"]],
    "perBinRange": R["perBinRange"],
    "sensitivities": {"crudeRatioIgnoringSoc": s["S1_crudeRatio"], "driveLevelBootstrap": ci(s["S2_driveBootstrap"]), "leaveOneDayOut": s["S3_leaveOneDayOut"],
                      "leaveOneBinOut": s["S4_leaveOneBinOut"], "stationaryBelow2kmh": {"R": s["S5_stationaryBelow2kmh"]["R"], **ci(s["S5_stationaryBelow2kmh"]["dayBootstrap"])},
                      "firstStartPerDriveRemoved": {"R": s["S7_firstStartPerDriveRemoved"]["R"], **ci(s["S7_firstStartPerDriveRemoved"]["dayBootstrap"])},
                      "iidKatzOldHeadlineCell": s["S6_iidKatzOldHeadlineCell"]},
    "previousHeadline": {"socBin": old["socBin"], "ratioPublished": old["ratio"], "ratioFromCounts": s["S6_iidKatzOldHeadlineCell"]["ratio"],
                         "note": "a single SoC-bin ratio (the largest of the bin ratios) with an iid per-second interval, a different estimand; the published value is computed from probabilities rounded to 5 decimals, the counts give the second figure"},
}
changed = A["socHysteresis"].get("startRatioClustered") != leaf
print(json.dumps({"changed": changed, "R": leaf["R"]}))
if changed and "--dry-run" not in sys.argv:
    A["socHysteresis"]["startRatioClustered"] = leaf
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
