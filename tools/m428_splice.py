#!/usr/bin/env python3
"""M428 splice (analyses/M428_spec.md Rev 2): adds ONE additive key, socHysteresisV2.outOfTimeEvaluation, to summary_arrays.json from the script-written
analyses/M428_result.json (tools/m428_oot.py). Every number is read from the result file (nothing typed). The carried block (recomputeMode, frozenBasis, surfaces,
ladder, every other leaf) is untouched: the deep diff against the previous arrays must show exactly this key and nothing else. Idempotent.
Usage: python tools/m428_splice.py [--dry-run]"""
import copy, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY = "--dry-run" in sys.argv
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
R = json.load(open("analyses/M428_result.json", encoding="utf-8"))
import pandas as pd
DM = pd.read_csv("drive_master.csv", low_memory=False)
NB = None
raw = open("summary_arrays.json", "rb").read().decode("utf-8")
A = json.loads(raw)
if json.dumps(A, ensure_ascii=False, indent=1) != raw:
    raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
prov = R["_provenance"]
NB = prov["nBasisDrives"]
OFF = (DM["engine_on_pct"] == 0)          # drives with no engine-on second cannot enter the STOP at-risk table
if prov["masterMd5"] != hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest():
    raise SystemExit("M428_result.json was computed on a different master")


def r4(x, d=4):
    return None if x is None else round(float(x), d)


def _supp(b):
    if not b:
        return None
    return {"share": b.get("share"), "atRiskSeconds": b["atRiskSeconds"], "events": b["events"], "OE": r4(b["point"]["OE"]), "OEci95": b["ci95Percentile"]["OE"], "nDays": b["nDays"]}


def side(s):
    x = R[s]; p = x["primary"]; pt, ci, jk = p["point"], p["ci95Percentile"], p["jackknife"]
    f = x["fidelity"]; c = f.get("counts", {}); sf = f.get("surfaces") or {}
    sens = x.get("sensitivities", {})
    return {
        "basis": {"nDrives": x["basis"]["nDrives"], "nDays": x["basis"]["nDays"], "atRiskSecondsCompleteCase": x["basis"]["atRiskSecondsCompleteCase"], "events": x["basis"]["eventsCompleteCase"], "eventRate": x["basis"]["eventRate"]},
        "later": {"nDrives": p["nDrives"], "nDays": p["nDays"], "atRiskSeconds": p["atRiskSeconds"], "events": p["events"], "essDays": p["essDays"], "prevalence": r4(pt["prevalence"], 5),
                  "skippedFilesNotInTable": x["skippedFilesNotInTable"]["later"]},
        "OE": {"point": r4(pt["OE"]), "ci95": ci["OE"], "jackknifeT95": jk["OE"]["tInterval"]},
        "skillVsB0": {"point": r4(pt["skillVsB0"]), "ci95": ci["skillVsB0"], "jackknifeT95": jk["skillVsB0"]["tInterval"]},
        "skillVsB1": {"point": r4(pt["skillVsB1"]), "ci95": ci["skillVsB1"]},
        "prAuc": {"point": r4(pt["prAuc"]), "ci95": ci["prAuc"], "lift": r4(pt["lift"], 2), "liftCi95": ci["lift"]},
        "calibration": {"slope": r4(pt["calSlope"], 3), "intercept": r4(pt["calIntercept"], 3)},
        "logLoss": r4(pt["logLoss"], 5),
        "states": p["states"], "outcome": x["decision"]["outcome"], "notes": x["decision"]["notes"],
        "supportExcessPp": {k: round(v["excessPp"], 2) for k, v in x["support"]["perPredictor"].items()},
        "supportUnionOutsideP1P99": {"basis": r4(x["support"]["basisUnionOutsideP1P99"], 4), "later": r4(x["support"]["laterUnionOutsideP1P99"], 4)},
        "fidelity": {"withinTolerance": f.get("withinTolerance"), "evaluatedObject": f.get("evaluatedObject"), "diffAtRisk": c.get("diffAtRisk"), "diffEvents": c.get("diffEvents"),
                     "blockedCvRelDiff": (f.get("blockedCv") or {}).get("relDiff"), "surfaceMaxAbsDiff": sf.get("maxAbsDiff"), "surfaceMedianAbsDiff": sf.get("medianAbsDiff"),
                     "surfaceRelMedianDiff": sf.get("relMedianDiff"), "tolerances": f.get("tolerances")},
        "inTimeReference": {"blockedCvLogLoss": (x.get("inTimeReference") or {}).get("blockedCvFiveVarDur", {}).get("logLoss"),
                            "blockedCvLogLossCi95": (x.get("inTimeReference") or {}).get("blockedCvFiveVarDur", {}).get("logLossCI"),
                            "outOfTimeLogLossAboveInTimeCiUpper": (x.get("inTimeReference") or {}).get("flagOutOfTimeLogLossAboveInTimeCiUpper")},
        "OEbyPackTemperatureBand": sens.get("OEbyPackTemperatureBand"),
        "inSupport": _supp(sens.get("inSupport")), "outOfSupport": _supp(sens.get("outOfSupport")),
        "absentFromTable": {"basis": x["skippedFilesNotInTable"]["basis"], "later": x["skippedFilesNotInTable"]["later"],
                            "masterRowsEngineOnPctZero": {"basis": int(OFF.iloc[:NB].sum()), "later": int(OFF.iloc[NB:].sum())},
                            "reading": "files absent from this side's at-risk table; for STOP the number equals the number of master rows with engine_on_pct = 0 in the same split (no engine-on second, not a load failure); START has none"},
        "tpackBasis": {"p1": x["support"]["perPredictor"]["tpack"]["basisP1"], "min": x["support"]["perPredictor"]["tpack"]["basisMin"], "laterShareBelowP1": r4(x["support"]["perPredictor"]["tpack"]["laterShareBelowP1"], 4)},
        "descriptiveFlags": {"prAucBelowInTimeCiLower": ((pt["prAuc"] < f_ci[0]) if (f_ci := ((x.get("inTimeReference") or {}).get("blockedCvFiveVarDur", {}) or {}).get("prAucCI")) else None),
                             "note": "descriptive, not pre-registered; the in-time reference is a different protocol and prevalence"},
        "sensitivities": {"S1_perDrive": sens.get("S1_perDrive"), "S2_firstHalf": (sens.get("S2_firstHalf") or {}).get("point"), "S2_secondHalf": (sens.get("S2_secondHalf") or {}).get("point"),
                          "S3_dropSharedDaysStates": (sens.get("S3_dropSharedDays") or {}).get("states"), "S3_droppedDays": (sens.get("S3_dropSharedDays") or {}).get("droppedDays")},
    }


blk = {"milestone": "M428", "spec": "analyses/M428_spec.md", "specSha256": prov["specSha256"], "result": "analyses/M428_result.json", "resultSha256": sha("analyses/M428_result.json"),
       "scriptSha256": prov["scriptSha256"], "masterMd5": prov["masterMd5"], "bootstrap": {"B": prov["bootB"], "seed": prov["bootSeed"], "unit": "calendar day"},
       "split": {"corpusDrivesAtEvaluation": prov["nBasisDrives"] + prov["nLaterDrives"], "nBasisDrives": prov["nBasisDrives"], "lastLaterFile": prov.get("lastLaterFile") or DM["file"].iloc[-1], "nLaterDrives": prov["nLaterDrives"], "lastBasisFile": prov["lastBasisFile"], "firstLaterFile": prov["firstLaterFile"]},
       "thresholds": R["start"]["decision"]["thresholds"],
       "label": prov["label"],
       "reading": ("Out-of-time evaluation of the frozen design (audit F08): the model is fit once on the basis drives and applied unchanged to the later drives; no later row enters knots, scale or coefficients. "
                   "Events are detector-derived (M231), hazards are model-derived; intervals are conditional on the fitted basis model and rest on few day clusters, so a non-detection is not equivalence. "
                   "The thresholds are declared planning choices, not validated."),
       "start": side("start"), "stop": side("stop")}
N = copy.deepcopy(A)
V = N["socHysteresisV2"]
changed = V.get("outOfTimeEvaluation") != blk
V["outOfTimeEvaluation"] = blk


def diff(a, b, p=""):
    if type(a) is not type(b):
        return [p]
    if isinstance(a, dict):
        return [x for k in sorted(set(a) | set(b)) for x in diff(a.get(k), b.get(k), p + "/" + k)]
    if isinstance(a, list):
        return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff(u, v, p + "/%d" % i)] if len(a) == len(b) else [p + " len"]
    return [p] if a != b else []


d = diff(A, N)
stray = [x for x in d if not x.startswith("/socHysteresisV2/outOfTimeEvaluation")]
if stray:
    raise SystemExit("unexpected changed leaves: %r" % stray[:10])
print(json.dumps({"changed": changed, "nChangedLeaves": len(d), "keys": sorted(blk)}, indent=1))
if not DRY and changed:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(N, ensure_ascii=False, indent=1))
    print("wrote summary_arrays.json")
