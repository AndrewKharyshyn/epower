#!/usr/bin/env python3
"""M432 splice (analyses/M432_spec.md Rev 2.1, gate G2): adds ONE additive key, evTraction.detectorSensitivity, to summary_arrays.json from the script-written
analyses/M432_result.json (tools/m432_ev_sens.py, which also passed gate G1). Every number is read from the result file (nothing typed). The deep diff against the
current payload must show exactly this key and nothing else. Idempotent.
Usage: python tools/m432_splice.py [--dry-run]
       python tools/m432_splice.py --verify RESULT2.json    (gate G3: a second run of the tool gives a byte-identical block)"""
import copy, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY = "--dry-run" in sys.argv
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
KEEP = ("axis", "value", "role", "alignment", "thresholdRpm", "debounceSamples", "coverageGate", "comparable", "nValidOwn", "nCommon", "nCommonPct", "kmCommonPct", "daysKept", "daysReleased",
        "unknownRpmShare", "ownSharePct", "supportLostPp", "detectorPp", "supportGainedPp", "totalPp", "detectorPpCi95")
CELL = ("direction", "A", "alignment", "thresholdRpm", "debounceSamples", "comparable", "detectorPp", "nCommonPct", "kmCommonPct")


def _dup(R, r):
    """A stress row whose alignment equals a factorial cell at the released threshold and debounce is the same convention evaluated twice (spec erratum, Director ruling): flag it, derived from the cells."""
    if r["role"] != "stress" or r["axis"] != "D":
        return {}
    for c in R["factorialCells"]:
        if c["alignment"] == r["alignment"] and c["thresholdRpm"] == 400 and c["debounceSamples"] == 3:
            return {"duplicateOf": "factorial cell %s, tolerance %s s (%s)" % (c["direction"], c["A"], c["alignment"])}
    return {}


def build(R, spec_sha, script_sha, result_sha):
    prov = R["_provenance"]
    f = R["factorial"]
    rel = R["released"]
    core = [r for r in R["oneAtATime"] if r["role"] == "core"]
    return {
        "milestone": "M432", "spec": prov["spec"], "specSha256": spec_sha, "result": "analyses/M432_result.json", "resultSha256": result_sha,
        "perDriveTable": "analyses/M432_result_per_drive.csv.gz", "scriptSha256": script_sha, "masterMd5": prov["masterMd5"], "label": prov["label"],
        "reading": ("Range of the engine-off distance share over declared detector conventions (RPM threshold, RPM alignment tolerance and direction, debounce), each recomputed on the same drives "
                    "with speed, odometer scale and distance denominator held fixed. The detector effect is the paired difference on the drives valid under both settings; support lost / gained is "
                    "reported separately. The range is deterministic given the data: it is not a confidence interval and not a bound on the true share. The sampling interval of the released share "
                    "is the day-clustered percentile interval below. Stress rows are shown beside the range and never enter it."),
        "released": rel,
        "nConventionsCore": len(core), "nComparableCore": sum(1 for r in core if r["comparable"]),
        "comparability": {"rule": "at least 90 % of the released drives and at least 90 % of the released distance remain valid under the variant", "minShare": 0.90},
        "oneAtATime": [dict({k: r[k] for k in KEEP if k in r}, **_dup(R, r)) for r in R["oneAtATime"]],
        "axisRanges": R["axisRanges"],
        "factorial": {"design": "RPM threshold x alignment (nearest / backward / forward at matched width) x tolerance x debounce, core values only", "nCells": f["nCells"], "nComparable": f["nComparable"],
                      "nNotComparable": f["nNotComparable"], "deltaPpRange": f["deltaPpRange"], "sharePctRange": f["sharePctRange"],
                      "minCell": {k: f["minCell"][k] for k in CELL}, "maxCell": {k: f["maxCell"][k] for k in CELL}},
        "evaluatedOn": {"nDrives": prov["nDrives"], "nWithResult": prov["nWithResult"], "nValid": rel["nValid"], "noResult": "the drive without a result has zero logged distance in the master"},
        "refresh": "on demand: re-run when the detector, the gates or the polling regime changes, or after about 14 calendar days of new drives; each ingestion carries this block forward unchanged",
    }


def main():
    R = json.load(open("analyses/M432_result.json", encoding="utf-8"))
    if "--verify" in sys.argv:
        R2 = json.load(open(sys.argv[sys.argv.index("--verify") + 1], encoding="utf-8"))
        a = build(R, "x", "x", "x"); b = build(R2, "x", "x", "x")
        same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        print(json.dumps({"G3_identical_block": same}))
        raise SystemExit(0 if same else 1)
    raw = open("summary_arrays.json", "rb").read().decode("utf-8")
    A = json.loads(raw)
    if json.dumps(A, ensure_ascii=False, indent=1) != raw:
        raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
    if R["_provenance"]["masterMd5"] != hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest():
        raise SystemExit("M432_result.json was computed on a different master")
    if not R["G1"]["ok"]:
        raise SystemExit("gate G1 did not pass in the result file")
    blk = build(R, sha("analyses/M432_spec.md"), sha("tools/m432_ev_sens.py"), sha("analyses/M432_result.json"))
    N = copy.deepcopy(A)
    changed = N["evTraction"].get("detectorSensitivity") != blk
    N["evTraction"]["detectorSensitivity"] = blk

    def diff(a, b, p=""):
        if type(a) is not type(b):
            return [p]
        if isinstance(a, dict):
            return [x for k in sorted(set(a) | set(b)) for x in diff(a.get(k), b.get(k), p + "/" + k)]
        if isinstance(a, list):
            return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff(u, v, p + "/%d" % i)] if len(a) == len(b) else [p + " len"]
        return [p] if a != b else []

    d = diff(A, N)
    stray = [x for x in d if not x.startswith("/evTraction/detectorSensitivity")]
    if stray:
        raise SystemExit("unexpected changed leaves: %r" % stray[:10])
    print(json.dumps({"changed": changed, "nChangedLeaves": len(d), "keys": sorted(blk)}, indent=1))
    if not DRY and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(N, ensure_ascii=False, indent=1))
        print("wrote summary_arrays.json")


main()
