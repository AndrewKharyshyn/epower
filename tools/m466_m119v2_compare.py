#!/usr/bin/env python3
"""M466 stage C: three-way split of the M119-v2 difference (published 489-basis block -> shipped 606 refit), from the control refits written by tools/m466_m119v2_control.py.
  code        = published (carried block at --prev-ref) -> control(489 rows, FORMER re-export raw, today's code)
  provenance  = control(former) -> control(originals): the M366 raw swap
  newData     = control(originals, 489) -> shipped 606 block in summary_arrays.json
Compares numeric leaves of the fitted blocks (ladder, sensitivity, partialDependence, surfaces, bootstrap, detector counts); text leaves are ignored. Writes analyses/M466_m119v2_split.json.
Usage: python tools/m466_m119v2_compare.py --prev-ref 3eb3f3c~1"""
import argparse, json, os, subprocess, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
KEYS = ("nDrivesCovered", "nDays", "nStartAtRisk", "nStartEvents", "startRatePct", "nStopAtRisk", "nStopEvents", "stopRatePct", "detector", "predictorAges", "ladder", "sensitivity", "partialDependence", "medianProfileCaptionStats", "surfaces", "bootstrap")


def flat(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, p + "/" + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from flat(v, p + "[%d]" % i)
    elif isinstance(o, (int, float)) and not isinstance(o, bool) and o == o:
        if "tempLevels" not in p and "tempLadder" not in p:       # the pack-temperature levels come from the M320/M321 ladder splice, not from build_m119v2: compared separately (ladder control)
            yield p, float(o)


def compare(a, b):
    out = {}
    for k in KEYS:
        fa, fb = dict(flat(a.get(k))), dict(flat(b.get(k)))
        common = sorted(set(fa) & set(fb))
        d = np.array([fb[p] - fa[p] for p in common]) if common else np.array([])
        rel = np.array([abs(fb[p] - fa[p]) / max(abs(fa[p]), 1e-9) for p in common]) if common else np.array([])
        out[k] = {"nLeavesA": len(fa), "nLeavesB": len(fb), "nCommon": len(common), "nIdentical": int((d == 0).sum()) if len(d) else 0, "maxAbs": None if not len(d) else round(float(np.abs(d).max()), 6),
                  "medianRel": None if not len(d) else round(float(np.median(rel)), 6), "p95Rel": None if not len(d) else round(float(np.percentile(rel, 95)), 6),
                  "argmaxAbs": None if not len(d) else common[int(np.abs(d).argmax())]}
    return out


def headline(b):
    L = (b.get("ladder") or {})
    g = lambda *ks: next(iter([]), None)
    out = {"nDrivesCovered": b.get("nDrivesCovered"), "nStartEvents": b.get("nStartEvents"), "nStopEvents": b.get("nStopEvents"), "startRatePct": b.get("startRatePct"), "stopRatePct": b.get("stopRatePct")}
    for side in ("start", "stop"):
        bs = (b.get("bootstrap") or {}).get(side) or {}
        out["bootstrap_" + side] = {k: bs.get(k) for k in ("logLossCI", "prAucCI", "socOnlyPrAucCI")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev-ref", required=True)
    ap.add_argument("--out", default="analyses/M466_m119v2_split.json")
    a = ap.parse_args()
    pub = json.loads(subprocess.run(["git", "show", a.prev_ref + ":summary_arrays.json"], capture_output=True, check=True).stdout.decode("utf-8"))["socHysteresisV2"]
    former = json.load(open("analyses/M466_c_control/ctrl489_former.json", encoding="utf-8"))
    orig = json.load(open("analyses/M466_c_control/ctrl489_originals.json", encoding="utf-8"))
    ship = json.load(open("summary_arrays.json", encoding="utf-8"))["socHysteresisV2"]
    res = {"prevRef": a.prev_ref, "code": compare(pub, former), "provenance": compare(former, orig), "newData": compare(orig, ship), "totalPublishedToShipped": compare(pub, ship),
           "headline": {"published489": headline(pub), "controlFormer": headline(former), "controlOriginals": headline(orig), "shipped606": headline(ship)},
           "note": "numeric leaves only; 'code' includes any change of m119v2_model / loaders since the published fit; 'provenance' is the M366 raw swap; 'newData' adds the 117 drives after the 489 basis. Associational model-derived quantities; not article-eligible."}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    for k in ("code", "provenance", "newData"):
        print(k, {kk: (v["nCommon"], v["nIdentical"], v["maxAbs"], v["p95Rel"]) for kk, v in res[k].items() if v["nCommon"]})
    print(json.dumps(res["headline"], ensure_ascii=False)[:2500])


if __name__ == "__main__":
    main()
