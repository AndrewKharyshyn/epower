#!/usr/bin/env python3
"""M728 (analyses/M728_spec.md Rev 2, section 4): the fidelity check of the P4 extractor on the FROZEN BASIS only (day <= 2026-11-09, the 665 prototype keys; every later row masked), criteria written in the spec before the first run.
C-P4a: n_s (sum of pin_n) within 0.5 % of 89334 and 60 days with pin_n > 0; b0 within 0.05 kW of 33.92; bT within 0.01 kW per C of 1.553; the SoC slope within 0.01 of -1.01; the extractor's seed-42 b0 interval endpoints within 0.15 kW of [32.72, 35.47].
C-P4b (descriptive, no tolerance, never the check): the same fit over all drives of the frame (any date), the sensitivity to the key set.
Writes analyses/M728_consistency_check.json (every run keeps its own record under `runs`). Usage: python tools/winter_extractors_b_check.py [--run-label LABEL]"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_extractors as WE
import winter_extractors_b as WB

OUT = os.path.join(ROOT, "analyses", "M728_consistency_check.json")
BASIS_LAST_DAY = "2026-11-09"
REF = {"n_s": 89334, "nDays": 60, "b0": 33.92, "b0Ci": [32.72, 35.47], "bT": 1.553, "bS": -1.01}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    label = argv[argv.index("--run-label") + 1] if "--run-label" in argv else "run 1"
    allfr = WE.load_frame(ROOT)
    fr = allfr[allfr["day"] <= BASIS_LAST_DAY].copy()
    assert fr["day"].max() <= BASIS_LAST_DAY
    e = WB.extract_p4(fr, restrict_to_cold=False)
    rec = {"label": label, "basisDrives": int(len(fr)), "criteria": {"n_s": "within 0.5 % of 89334", "nDays": "== 60", "b0": "within 0.05 kW of 33.92", "bT": "within 0.01 of 1.553", "bS": "within 0.01 of -1.01", "b0Ci": "endpoints within 0.15 kW of [32.72, 35.47]"}}
    if e.get("status") != "fitted":
        rec["C-P4a"] = {"pass": False, "reason": e}
    else:
        c = {"n_s": e["regressionSeconds"], "nDays": e["nDays"], "b0": e["b0KwAt0CSoc60"], "b0Ci95": e["b0Ci95"], "bT": e["bTKwPerC"], "bS": e["bSKwPerSocPoint"], "coldestProbeMinC": e["coldestProbeMinC"],
             "pinWeightedMeanTminC": e["pinWeightedMeanTminC"], "conditionNumber": e["conditionNumber"], "nDrives": e["nDrives"]}
        c["diffs"] = {"n_sRel": abs(c["n_s"] / REF["n_s"] - 1.0), "nDays": c["nDays"] - REF["nDays"], "b0": abs(c["b0"] - REF["b0"]), "bT": abs(c["bT"] - REF["bT"]), "bS": abs(c["bS"] - REF["bS"]),
                      "b0CiEnds": [abs(c["b0Ci95"][0] - REF["b0Ci"][0]), abs(c["b0Ci95"][1] - REF["b0Ci"][1])]}
        d = c["diffs"]
        c["pass"] = bool(d["n_sRel"] <= 0.005 and d["nDays"] == 0 and d["b0"] <= 0.05 and d["bT"] <= 0.01 and d["bS"] <= 0.01 and max(d["b0CiEnds"]) <= 0.15)
        rec["C-P4a"] = c
    e2 = WB.extract_p4(allfr, restrict_to_cold=False)
    rec["C-P4b-descriptive"] = {"nDrives": e2.get("nDrives"), "nDays": e2.get("nDays"), "b0": e2.get("b0KwAt0CSoc60"), "reading": "sensitivity to the key set (all frame drives); never the check; the M713 production frame at 696 drives gave 34.04 kW"}
    rec["allCriteriaPassed"] = bool(rec["C-P4a"].get("pass"))
    log = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"spec": "analyses/M728_spec.md", "runs": []}
    log["runs"].append(rec)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(log, ensure_ascii=False, indent=1, default=float) + "\n")
    print(json.dumps(rec, indent=1, default=float)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
