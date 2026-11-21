#!/usr/bin/env python3
"""M727 (analyses/M727_spec.md Rev 2, section 4): the consistency check of the extractors on the FROZEN BASIS only (drives through 2026-11-09; every later row is masked), with the acceptance criteria written in the spec before the first run.
C-P7: the P7 extractor reproduces the prototype slope -0.00812 per C and its interval [-0.01061, -0.00566] on the prototype set (no clean filter, as the prototype) within 1e-5 absolute.
C-P3: on pulses with T_pulse in [23, 27] C the mean of R_pulse / R25_frozen lies in [0.95, 1.05].
C-P2: the P2 extractor's Ah share below 10 C on the frozen basis equals the sum of the three lowest bins of the prototype's observed free-run share (0 + 0.0005 + 0.0042) within 0.005 absolute.
C-P5: placebo (September against October-November of the frozen basis, same filters and classes), reported with NO tolerance.
Writes analyses/M727_consistency_check.json (every run keeps its own record under `runs`). Reads the frozen freeze file parameters only for R25. Usage: python tools/winter_extractors_check.py [--run-label LABEL]"""
import json, os, sys, hashlib
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_extractors as WE

OUT = os.path.join(ROOT, "analyses", "M727_consistency_check.json")
BASIS_LAST_DAY = "2026-11-09"
PROTO_SLOPE, PROTO_CI = -0.00812, [-0.01061, -0.00566]
PROTO_P2 = 0.0 + 0.0005 + 0.0042


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    label = argv[argv.index("--run-label") + 1] if "--run-label" in argv else "run 1"
    run2 = "--run2" in argv
    fr = WE.load_frame(ROOT)
    fr = fr[fr["day"] <= BASIS_LAST_DAY].copy()                      # post-freeze rows masked
    assert fr["day"].max() <= BASIS_LAST_DAY
    freeze = json.load(open(os.path.join(ROOT, "analyses", "M717_winter_predictions.json"), encoding="utf-8"))
    r25 = freeze["params"]["R_T"]["R25_mohm"]
    rec = {"label": label, "masterBasisDrives": int(len(fr)), "criteria": {"C-P7": "slope -0.00812 and CI [-0.01061, -0.00566] within 1e-5 on the prototype set", "C-P3": "mean R_pulse / R25 in [0.95, 1.05] for T_pulse in [23, 27] C",
                                                                           "C-P2": "Ah share below 10 C within 0.005 of 0.0047", "C-P5": "placebo, no tolerance"}}
    # C-P7 on the prototype set (no clean filter, as the prototype)
    p7 = WE.extract_p7(fr)
    slope = -p7["estimate"]                                          # the prototype coefficient of A on engine-on share (fraction, x100 for points)
    ci_proto = [-p7["ci95"][1] / 100.0, -p7["ci95"][0] / 100.0] if p7["ci95"] else None
    # the extractor works in points per C of cooling; the prototype coefficient is a fraction per C of ambient: coefficient = -estimate / 100
    coef = -p7["estimate"] / 100.0
    ci_coef = [-p7["ci95"][1] / 100.0, -p7["ci95"][0] / 100.0]
    rec["C-P7"] = {"nDrives": p7["nDrives"], "nDays": p7["nDays"], "coefficientOfA": round(coef, 6), "ci95": [round(ci_coef[0], 6), round(ci_coef[1], 6)], "prototype": {"slope": PROTO_SLOPE, "ci95": PROTO_CI, "n": 375, "nDays": 89},
                   "absDiffSlope": abs(coef - PROTO_SLOPE), "absDiffCi": [abs(ci_coef[0] - PROTO_CI[0]), abs(ci_coef[1] - PROTO_CI[1])]}
    rec["C-P7"]["pass"] = bool(rec["C-P7"]["absDiffSlope"] <= 1e-5 and max(rec["C-P7"]["absDiffCi"]) <= 1e-5)
    # C-P3
    pl = fr[(fr["R_pulse_mohm"] > 20) & (fr["R_pulse_mohm"] < 600) & fr["T_pulse"].notna() & (fr["T_pulse"] >= 23.0) & (fr["T_pulse"] <= 27.0)]
    m = float((pl["R_pulse_mohm"] / r25).mean()) if len(pl) else None
    rec["C-P3"] = {"nPulses": int(len(pl)), "meanRatio25": m, "r25Frozen": r25, "pass": bool(m is not None and 0.95 <= m <= 1.05)}
    # C-P2
    p2 = WE.extract_p2(fr)
    rec["C-P2"] = {"estimate": p2["estimate"], "prototypeSum": PROTO_P2, "absDiff": abs(p2["estimate"] - PROTO_P2), "pass": bool(abs(p2["estimate"] - PROTO_P2) <= 0.005)}
    # C-P5 placebo: September against October-November (frozen basis, same filters and classes)
    sep = fr[fr["month"] == 9].copy()
    on = fr[fr["month"].isin([10, 11])].copy()
    rec["C-P5-placebo"] = {"label": "placebo, no tolerance: 'winter' = October-November, 'autumn' = September of the frozen basis", "result": WE.extract_p5(on, sep)}
    rec["allCriteriaPassed"] = bool(rec["C-P7"]["pass"] and rec["C-P3"]["pass"] and rec["C-P2"]["pass"])
    if run2:
        # run 2 (spec 8.4): C-P5 re-run with the Rev 3 scheme; P2, P3, P7 only as a byte-identical regression against run 1; descriptive extras (no tolerance)
        prev = json.load(open(OUT, encoding="utf-8"))["runs"][0]
        rec["regressionVsRun1"] = {"C-P7": bool(rec["C-P7"]["coefficientOfA"] == prev["C-P7"]["coefficientOfA"] and rec["C-P7"]["ci95"] == prev["C-P7"]["ci95"] and rec["C-P7"]["nDrives"] == prev["C-P7"]["nDrives"]),
                                   "C-P3": bool(rec["C-P3"]["meanRatio25"] == prev["C-P3"]["meanRatio25"] and rec["C-P3"]["nPulses"] == prev["C-P3"]["nPulses"]),
                                   "C-P2": bool(rec["C-P2"]["estimate"] == prev["C-P2"]["estimate"])}
        cl = fr[fr["clean"]].copy()
        p7c = WE.extract_p7(cl)
        rec["descriptive"] = {"P7_cleanFilteredFrozenBasis": {"nDrives": p7c["nDrives"], "nDays": p7c["nDays"], "coolingSlopePointsPerC": p7c["estimate"], "ci95": p7c["ci95"],
                                                            "reading": "descriptive only, no tolerance; the frozen interval came from the unfiltered basis"}}
        own = float(pl["R_pulse_mohm"].mean()) if len(pl) else None
        ea = freeze["params"]["R_T"]["EaR_kJmol"]
        p3m = WE.extract_p3(fr, ea, r25, own25_mohm=own)                                   # main window [-2, +2] C
        p3s = WE.extract_p3(fr, ea, r25, window=WE.P3_WINDOW_SENS, own25_mohm=own)          # sensitivity window [-5, +3] C
        rec["descriptive"]["P3_ownLevelSensitivity"] = {"ownLevelMohm": own, "nPulsesAt25C": int(len(pl)),
                                                       "mainWindow": {k: p3m.get(k) for k in ("nDrives", "nDays", "estimate", "ci95", "ownLevelSensitivity", "uncorrected")},
                                                       "sensitivityWindow": {k: p3s.get(k) for k in ("nDrives", "nDays", "estimate", "ci95", "ownLevelSensitivity", "uncorrected")},
                                                       "reading": "descriptive; the frozen basis holds few or no pulses in the cold windows (coldest pack probe 1.0 C)"}
    log = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"spec": "analyses/M727_spec.md", "runs": []}
    log["runs"].append(rec)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(log, ensure_ascii=False, indent=1, default=float) + "\n")
    print(json.dumps({k: rec[k] for k in rec if k in ("label", "allCriteriaPassed", "regressionVsRun1", "descriptive", "C-P5-placebo")}, indent=1, default=float)[:3500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
