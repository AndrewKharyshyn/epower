#!/usr/bin/env python3
"""M731 (analyses/M731_spec.md Rev 2, section 3): the checks of the P6 extractor on the FROZEN BASIS only (day <= 2026-11-09), criteria written in the spec before the first run.
C-P6a: the all-seconds peak charge C-rate recomputed on the vendored 1 Hz grid equals the frame column `peak_c_chg` within 1e-6 for 100 % of the drives, or every exception is listed with its cause.
C-P6b: the sum of `p6_n_s` (charge seconds with the coldest probe below 0 C) over the frozen basis equals 0, consistent with `h_T_<0` summing to 0.
C-P6c (defines `tol`, never pass/fail): the margin (max over charge seconds) for Tlo in 0..10 C; tol = max(0, the 95th percentile over drives with such seconds) (Rev 2.2 floor); written with n drives and days.
Writes analyses/M731_consistency_check.json (every run keeps its own record under `runs`). Usage: python tools/winter_p6_check.py [--run-label LABEL] [--raw-dir DIR]"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_p6 as W6
import raw_resolver as RR

OUT = os.path.join(ROOT, "analyses", "M731_consistency_check.json")
BASIS_LAST_DAY = "2026-11-09"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    label = argv[argv.index("--run-label") + 1] if "--run-label" in argv else "run 1"
    raw_dir = argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    SF = W6.vendored_frame_module()
    fr = pd.read_csv(os.path.join(ROOT, "analyses", "M713", "exposure_drives.csv"), dtype={"key": str}, usecols=["key", "day", "peak_c_chg", "h_T_<0"], low_memory=False)
    fr["day"] = pd.to_datetime(fr["day"]).dt.strftime("%Y-%m-%d")
    fr = fr[fr["day"] <= BASIS_LAST_DAY].reset_index(drop=True)
    assert fr["day"].max() <= BASIS_LAST_DAY
    res = RR.resolve(raw_dir, os.path.join(ROOT, "raw_manifest.json"))
    exc, n_s0, ref = [], 0, []
    for _, r in fr.iterrows():
        path = res.index.get(r["key"])
        if path is None:
            exc.append({"key": r["key"], "cause": "raw file not found"})
            continue
        g = SF.extract_drive(path)
        a = W6.p6_row(g, 0.0)
        n_s0 += a["p6_n_s"]
        if not (abs(a["p6_all_peak_c"] - r["peak_c_chg"]) <= 1e-6 or (np.isnan(a["p6_all_peak_c"]) and np.isnan(r["peak_c_chg"]))):
            exc.append({"key": r["key"], "recomputed": a["p6_all_peak_c"], "frame": float(r["peak_c_chg"]), "cause": "peak differs"})
        b = W6.p6_row(g, 10.0)
        if b["p6_n_s"] > 0:
            ref.append({"day": r["day"], "margin": b["p6_margin_c"], "Tlo": b["p6_Tlo"]})
    rec = {"label": label, "basisDrives": int(len(fr)), "criteria": {"C-P6a": "peak equals frame peak_c_chg within 1e-6 for 100 % or exceptions listed", "C-P6b": "sum p6_n_s == 0", "C-P6c": "tol = 95th percentile of the 0..10 C margin"}}
    rec["C-P6a"] = {"nExceptions": len(exc), "exceptions": exc[:50], "pass": len(exc) == 0 or all("cause" in e for e in exc)}
    rec["C-P6a"]["passStrict100pct"] = len(exc) == 0
    rec["C-P6b"] = {"sumP6Ns": int(n_s0), "frameHoursBelow0C": float(fr["h_T_<0"].sum()), "pass": bool(n_s0 == 0)}
    if ref:
        m = np.array([x["margin"] for x in ref])
        rec["C-P6c"] = {"nDrives": len(ref), "nDays": len({x["day"] for x in ref}), "tolRefP95C": float(np.percentile(m, 95)), "tolC": max(0.0, float(np.percentile(m, 95))), "medianMarginC": float(np.median(m)), "maxMarginC": float(m.max()), "quantiles": {"p50": float(np.percentile(m, 50)), "p90": float(np.percentile(m, 90)), "p95": float(np.percentile(m, 95))}}
    else:
        rec["C-P6c"] = {"nDrives": 0, "tolC": None, "reason": "no charge second with Tlo in 0..10 C on the frozen basis"}
    rec["allCriteriaPassed"] = bool(rec["C-P6a"]["passStrict100pct"] and rec["C-P6b"]["pass"] and rec["C-P6c"].get("tolC") is not None)
    log = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"spec": "analyses/M731_spec.md", "runs": []}
    log["runs"].append(rec)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(log, ensure_ascii=False, indent=1, default=float) + "\n")
    print(json.dumps(rec, indent=1, default=float)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
