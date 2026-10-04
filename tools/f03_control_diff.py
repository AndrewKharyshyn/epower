#!/usr/bin/env python3
"""F03 control diff: effect of replacing the 333 lower-precision raw/ re-exports by the sha256-verified originals on the arrays that build_summary_arrays produces.
Same code, same drive_master, same arguments on both sides (tools/f03_control_build.py): BASELINE = current raw/, CONTROL = originals. The only difference is the raw bytes, so every delta is a raw-content effect (provenance sensitivity), not pipeline noise.
Per leaf: identical / numeric change (abs, relative) / string, boolean or structural change. Where a baseline dict carries a 95% CI (ci95) next to an estimate (est, median, bootMedian, value, slope), the control estimate is checked against that CI and the shift is expressed in CI half-widths.
Output: analyses/F03_originals/M366_control_diff.json. Usage: python tools/f03_control_diff.py BASELINE.json CONTROL.json [OUT.json]  (for the post-swap headline gate: BASELINE = the published arrays from git, CONTROL = the regenerated summary_arrays.json)"""
import json, math, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
EST_KEYS = ("est", "median", "bootMedian", "value", "slope")
OUT = os.path.join(ROOT, "analyses", "F03_originals", "M366_control_diff.json")
if len(sys.argv) > 3:
    OUT = os.path.join(ROOT, sys.argv[3])


def isnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


class Acc:
    def __init__(self):
        self.n = 0; self.same = 0; self.num = []; self.strc = []; self.struct = []; self.ci = []


def walk(b, c, path, acc):
    if isinstance(b, dict) and isinstance(c, dict):
        for k in sorted(set(b) | set(c)):
            if k not in b or k not in c:
                acc.struct.append({"path": f"{path}/{k}", "kind": "key only in " + ("control" if k not in b else "baseline")})
                continue
            walk(b[k], c[k], f"{path}/{k}", acc)
        ci = b.get("ci95")
        if isinstance(ci, list) and len(ci) == 2 and isnum(ci[0]) and isnum(ci[1]):
            for ek in EST_KEYS:
                if isnum(b.get(ek)) and isnum(c.get(ek)) and b[ek] != c[ek]:
                    hw = (ci[1] - ci[0]) / 2.0
                    acc.ci.append({"path": f"{path}/{ek}", "baseline": b[ek], "control": c[ek], "baselineCi95": ci, "insideBaselineCi": bool(ci[0] <= c[ek] <= ci[1]),
                                   "shiftOverHalfWidth": (round(abs(c[ek] - b[ek]) / hw, 4) if hw > 0 else None)})
    elif isinstance(b, list) and isinstance(c, list):
        if len(b) != len(c):
            acc.struct.append({"path": path, "kind": f"list length {len(b)} -> {len(c)}"})
            return
        for i, (x, y) in enumerate(zip(b, c)):
            walk(x, y, f"{path}[{i}]", acc)
    else:
        acc.n += 1
        if isnum(b) and isnum(c):
            if b == c:
                acc.same += 1
            else:
                rel = abs(c - b) / max(abs(b), 1e-9)
                acc.num.append((path, b, c, rel))
        elif b == c:
            acc.same += 1
        else:
            acc.strc.append({"path": path, "baseline": b if not isinstance(b, str) else b[:140], "control": c if not isinstance(c, str) else c[:140]})


def main():
    B = json.load(open(sys.argv[1], encoding="utf-8")); Cn = json.load(open(sys.argv[2], encoding="utf-8"))
    P = json.load(open("summary_arrays.json", encoding="utf-8"))
    keys = sorted(set(B) & set(Cn))
    res = {"milestone": "M366", "note": "control minus baseline: same code and master, raw bytes = sha256-verified originals vs current raw/ re-exports; provenance sensitivity, not a correction",
           "nKeysBaseline": len(B), "nKeysControl": len(Cn), "keysOnlyInOne": sorted(set(B) ^ set(Cn)), "byKey": {}, "ciChecks": [], "stringOrBoolChanges": [], "structuralChanges": []}
    tot = {"leaves": 0, "same": 0, "numChanged": 0}
    allnum = []
    for k in keys:
        a = Acc(); walk(B[k], Cn[k], f"/{k}", a)
        tot["leaves"] += a.n; tot["same"] += a.same; tot["numChanged"] += len(a.num)
        allnum += a.num
        if a.num or a.strc or a.struct:
            res["byKey"][k] = {"leaves": a.n, "numericChanged": len(a.num), "maxRelativeChange": round(max((x[3] for x in a.num), default=0.0), 6), "stringOrBoolChanged": len(a.strc), "structural": len(a.struct)}
        res["ciChecks"] += a.ci; res["stringOrBoolChanges"] += a.strc; res["structuralChanges"] += a.struct
    tot["identicalShare"] = round(tot["same"] / max(tot["leaves"], 1), 6)
    res["totals"] = tot
    allnum.sort(key=lambda x: -x[3])
    res["largestNumericChanges"] = [{"path": p, "baseline": b, "control": c, "relative": round(r, 6)} for p, b, c, r in allnum[:40]]
    res["ciSummary"] = {"nChecked": len(res["ciChecks"]), "nOutsideBaselineCi": sum(1 for x in res["ciChecks"] if not x["insideBaselineCi"]),
                        "maxShiftOverHalfWidth": max((x["shiftOverHalfWidth"] for x in res["ciChecks"] if x["shiftOverHalfWidth"] is not None), default=None)}
    res["ciOutside"] = [x for x in res["ciChecks"] if not x["insideBaselineCi"]]
    res["relativeChangeQuantiles"] = {q: round(float(sorted(x[3] for x in allnum)[int(len(allnum) * q)]), 6) for q in (0.5, 0.9, 0.99)} if allnum else {}
    pk = sorted(k for k in keys if json.dumps(P.get(k), sort_keys=True) != json.dumps(B.get(k), sort_keys=True))
    res["context"] = {"keysWhereBaselineBuildDiffersFromPublishedArrays": len(pk), "note": "expected: post-steps and splices patch the published arrays after the builder; not attributable to raw content"}
    json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"totals": tot, "ciSummary": res["ciSummary"], "keysChanged": len(res["byKey"]), "stringOrBool": len(res["stringOrBoolChanges"]), "structural": len(res["structuralChanges"]), "quantiles": res["relativeChangeQuantiles"], "keysOnlyInOne": res["keysOnlyInOne"]}, indent=1))


if __name__ == "__main__":
    main()
