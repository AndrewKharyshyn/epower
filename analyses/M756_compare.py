#!/usr/bin/env python3
"""M756: script-written side-by-side of the M751 result (former ambient basis) and the rerun on the M755 basis (analyses/M756_spec.md section 2). Writes analyses/M756_comparison.json."""
import json, os
R = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
L = lambda p: json.load(open(os.path.join(R, p), encoding="utf-8"))
o, n = L("analyses/M751_heatsoak_gap_sensitivity.json"), L("analyses/M756_rerun/M751_heatsoak_gap_sensitivity.json")
out = {"e2": [], "tau": {}, "decisionChanges": [], "overall": {"former": o["overall"], "rerun": n["overall"], "same": o["overall"] == n["overall"]}, "v0Rerun": n["control_V0"]}
for bo, bn in zip(o["E2_retained_fraction_shift"]["primaryArrivalDay"], n["E2_retained_fraction_shift"]["primaryArrivalDay"]):
    assert (bo["gapLoH"], bo["gapHiH"]) == (bn["gapLoH"], bn["gapHiH"])
    row = {"bin": [bo["gapLoH"], bo["gapHiH"]], "nAmbA": [bo["nAmbA"], bn["nAmbA"]], "medA": [bo["medA"], bn["medA"]]}
    for s in ("B", "C", "C1"):
        a, b = bo.get(s) or {}, bn.get(s) or {}
        row[s] = {"nAmb": [a.get("nAmb"), b.get("nAmb")], "supported": [a.get("supported"), b.get("supported")], "shiftPp": [a.get("shiftPp"), b.get("shiftPp")], "ci95Pp": [a.get("ci95Pp"), b.get("ci95Pp")], "verdict": [a.get("verdict"), b.get("verdict")]}
        if a.get("verdict") != b.get("verdict") or a.get("supported") != b.get("supported"):
            out["decisionChanges"].append({"bin": row["bin"], "set": s, "former": [a.get("supported"), a.get("verdict")], "rerun": [b.get("supported"), b.get("verdict")]})
    out["e2"].append(row)
for s in ("A", "B", "C", "C1"):
    a, b = o["E3_tau"].get(s), n["E3_tau"].get(s)
    if not a or not b:
        continue
    out["tau"][s] = {k: [a.get(k), b.get(k)] for k in ("nAmbBeforeFilter", "nFit", "decayRateK", "decayRateKCI", "tauH", "tauCI", "kShiftVsA", "kShiftCI95", "kRatioAOverSet", "verdictK")}
    if a.get("verdictK") != b.get("verdictK"):
        out["decisionChanges"].append({"tau": s, "former": a.get("verdictK"), "rerun": b.get("verdictK")})
json.dump(out, open(os.path.join(R, "analyses", "M756_comparison.json"), "w", encoding="utf-8", newline="\n"), indent=1)
print(json.dumps({"decisionChanges": out["decisionChanges"], "overall": out["overall"]}, indent=1))
for r in out["e2"]:
    print(r["bin"], r["nAmbA"], "B", r["B"]["supported"], r["B"]["shiftPp"], r["B"]["verdict"], "| C", r["C"]["shiftPp"], r["C"]["verdict"])
for s, v in out["tau"].items():
    print(s, v["nFit"], v["tauH"], v["kRatioAOverSet"], v["verdictK"])
