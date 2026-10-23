#!/usr/bin/env python3
"""M495 splice (analyses/M495_spec.md Rev 2): adds TWO additive leaves to socHysteresisV2 in summary_arrays.json from the script-written analyses/M495_result.json and analyses/M495_frozen_fit.json (tools/m495_rolling_origin.py):
  socHysteresisV2.rollingOriginEvaluation  per-origin results, verdicts, pooled summary, sensitivities, fidelity, provenance (compact: no row-level arrays);
  socHysteresisV2.prospectiveProtocol      the frozen-fit hash, the last training date, the held-out rule and thresholds, and (refreshed by the flag-only monitor at every ingestion) the held-out drive and day counts.
Every number is read from the result files (nothing typed). The carried block (surfaces, ladder, outOfTimeEvaluation, sensitivity.rollingOrigin, ...) is untouched: the deep diff against the previous arrays must show exactly these leaves. Idempotent.
Usage: python tools/m495_splice.py [--dry-run] | python tools/m495_splice.py --monitor [--dry-run]   (--monitor refreshes only prospectiveProtocol.heldOut)"""
import copy, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd

sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
LEAVES = ("rollingOriginEvaluation", "prospectiveProtocol")


def r4(x, d=4):
    return None if x is None else round(float(x), d)


def fold_row(f):
    base = {"origin": f["fold"]["k"], "cut": f["fold"]["cut"], "trainEnd": f["fold"]["trainEnd"], "testStart": f["fold"]["testStart"], "testEnd": f["fold"]["testEnd"], "train": f["train"], "test": f["test"], "evaluable": f["evaluable"]}
    if not f["evaluable"]:
        return base
    p = f["primary"]; pt, ci, jk = p["point"], p["ci95Percentile"], p["jackknife"]
    base.update({"essDays": p["essDays"], "prevalence": r4(pt["prevalence"], 5),
                 "skillVsB0": {"point": r4(pt["skillVsB0"]), "ci95": ci["skillVsB0"], "ci95Bonferroni": p["ci95PercentileBonferroni"]["skillVsB0"], "jackknifeT95": jk["skillVsB0"]["tInterval"]},
                 "skillVsB1": {"point": r4(pt["skillVsB1"]), "ci95": ci["skillVsB1"]},
                 "OE": {"point": r4(pt["OE"]), "ci95": ci["OE"], "ci95Bonferroni": p["ci95PercentileBonferroni"]["OE"], "jackknifeT95": jk["OE"]["tInterval"]},
                 "prAuc": r4(pt["prAuc"]), "lift": r4(pt["lift"], 2), "calibration": {"slope": r4(pt["calSlope"], 3), "intercept": r4(pt["calIntercept"], 3)},
                 "states": p["states"], "supportExcessPp": {k: round(v["excessPp"], 2) for k, v in f["support"]["perPredictor"].items()},
                 "inSupport": ({"share": f["supportSplit"]["inSupport"]["share"], "skillVsB0": r4(f["supportSplit"]["inSupport"]["point"]["skillVsB0"]), "OE": r4(f["supportSplit"]["inSupport"]["point"]["OE"]), "states": f["supportSplit"]["inSupport"]["states"]}
                               if "inSupport" in f.get("supportSplit", {}) else None),
                 "perDrive": f.get("perDrive")})
    return base


def side_block(x):
    s = x["sensitivities"]
    return {"verdict": x["verdict"]["verdict"], "notes": x["verdict"]["notes"], "flaggedOrigins": x["verdict"]["flaggedOrigins"], "extrapolationOrigins": x["verdict"]["extrapolationOrigins"],
            "origins": [fold_row(f) for f in x["folds"]],
            "pooled": ({"nDrives": x["pooled"]["nDrives"], "nDays": x["pooled"]["nDays"], "events": x["pooled"]["events"], "point": {k: r4(v) for k, v in x["pooled"]["point"].items()}, "ci95": x["pooled"]["ci95Percentile"], "note": x["pooled"]["note"]}
                       if x["pooled"] else None),
            "sensitivities": {"S1_embargoStates": s["S1_embargo"], "S2_windows": s["S2_windows"],
                              "S5_m2221GeometryPooled": {k: s["S5_m2221Geometry"].get(k) for k in ("nRounds", "minTrainDays", "stepDays", "pooled", "pooledLogLossCI")}}}


def build(R, art, dm):
    prov = R["_provenance"]
    if prov["masterMd5"] != hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest():
        raise SystemExit("M495_result.json was computed on a different master")
    roe = {"milestone": "M495", "spec": "analyses/M495_spec.md", "specSha256": prov["specSha256"], "result": "analyses/M495_result.json", "resultSha256": sha(os.path.join(ROOT, "analyses", "M495_result.json")),
           "scriptSha256": prov["scriptSha256"], "masterMd5": prov["masterMd5"], "bootstrap": {"B": prov["bootB"], "seed": prov["bootSeed"], "unit": "calendar day"},
           "geometry": R["geometry"], "fidelityM428": {"reproducesM428": R["fidelityM428"]["reproducesM428"], "m119v2ModelSha256": R["fidelityM428"]["m119v2ModelSha256"], "m428ModelSha256": R["fidelityM428"]["m428ModelSha256"]},
           "fits": R["fits"], "label": prov["label"],
           "thresholds": R["start"]["folds"][0]["primary"].get("thresholds") or {"skillLowerBound": 0.0, "OEband": [0.8, 1.25], "excessPpMax": 10.0, "note": "declared planning thresholds, not validated"},
           "reading": ("Rolling-origin evaluation of the declared M119-v2 pipeline design (the design was selected on the full data; out-of-time for estimation only, not prospective): at each origin the design is fit on the past only "
                       "(spline knots, scale and baselines learned on the training rows) and applied unchanged to the next 28 calendar days, with a one-day embargo. Events are detector-derived (M231), hazards are model-derived; "
                       "intervals are conditional on each fold's fitted model and rest on few day clusters. The verdict rules are declared planning thresholds, not validated; a flag is not a refit decision and a non-detection is not equivalence."),
           "start": side_block(R["start"]), "stop": side_block(R["stop"])}
    pp = {"milestone": "M495", "frozenFit": "analyses/M495_frozen_fit.json", "frozenFitSha256": sha(os.path.join(ROOT, "analyses", "M495_frozen_fit.json")), "frozenMasterMd5": art["_provenance"]["masterMd5"],
          "lastTrainingDate": art["lastTrainingDate"], "heldOutRule": art["heldOutRule"], "thresholds": {"drives": 100, "days": 40, "eventsPerSide": 300, "effectiveDayClusters": 15},
          "plan": ("The frozen 606-drive fit is evaluated unchanged on drives logged after the last training date once the held-out period holds at least 100 drives on at least 40 days, at least 300 events per side and an effective number of day clusters of at least 15 (one primary look; later looks descriptive). "
                   "Cold pack temperatures are expected to give extrapolation; the in-support reading is reported beside the primary one. A refit is a separate owner decision."),
          "countFidelity": {s: art[s]["countFidelity"] for s in ("start", "stop")}, "bitIdenticalRefit": {s: art[s]["bitIdenticalRefit"] for s in ("start", "stop")},
          "heldOut": held_out(dm, art["lastTrainingDate"])}
    return roe, pp


def held_out(dm, last):
    d = dm[pd.to_datetime(dm["date"]) > pd.Timestamp(last)]
    nd, ndays = int(len(d)), int(d["date"].nunique())
    return {"drives": nd, "days": ndays, "driveAndDayThresholdMet": bool(nd >= 100 and ndays >= 40),
            "note": "flag-only monitor: counts of drives and days after the last training date; no event count and no hazard value is read"}


def diff(a, b, p=""):
    if type(a) is not type(b):
        return [p]
    if isinstance(a, dict):
        return [x for k in sorted(set(a) | set(b)) for x in diff(a.get(k), b.get(k), p + "/" + k)]
    if isinstance(a, list):
        return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff(u, v, p + "/%d" % i)] if len(a) == len(b) else [p + " len"]
    return [p] if a != b else []


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dry = "--dry-run" in argv
    raw = open("summary_arrays.json", "rb").read().decode("utf-8")
    A = json.loads(raw)
    if json.dumps(A, ensure_ascii=False, indent=1) != raw and json.dumps(A, ensure_ascii=False, indent=1) + "\n" != raw:
        raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    N = copy.deepcopy(A)
    V = N["socHysteresisV2"]
    if "--monitor" in argv:
        pp = V.get("prospectiveProtocol")
        if not pp:
            print(json.dumps({"monitor": "skipped: prospectiveProtocol not present"})); return 0
        pp["heldOut"] = held_out(dm, pp["lastTrainingDate"])
        allowed = ("/socHysteresisV2/prospectiveProtocol/heldOut",)
    else:
        R = json.load(open("analyses/M495_result.json", encoding="utf-8"))
        art = json.load(open("analyses/M495_frozen_fit.json", encoding="utf-8"))
        stops = {s: art[s]["STOP"] for s in ("start", "stop") if art[s].get("STOP")}
        if stops:
            raise SystemExit("M495 STOP: the frozen fit is not valid: %r" % stops)
        roe, pp = build(R, art, dm)
        V["rollingOriginEvaluation"], V["prospectiveProtocol"] = roe, pp
        allowed = tuple("/socHysteresisV2/" + k for k in LEAVES)
    d = diff(A, N)
    stray = [x for x in d if not any(x == a_ or x.startswith(a_ + "/") for a_ in allowed)]
    if stray:
        raise SystemExit("unexpected changed leaves: %r" % stray[:10])
    print(json.dumps({"nChanged": len(d), "stray": [], "heldOut": V.get("prospectiveProtocol", {}).get("heldOut")}))
    if not dry and d:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(N, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
