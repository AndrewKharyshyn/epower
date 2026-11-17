#!/usr/bin/env python3
"""M709 (spec analyses/M708_spec.md Rev 2, section 5): gate evaluation of the production restart census against the frozen known-answer targets (analyses/M708_targets.json).
P-R0 pair and day counts within +-3 pairs and the eligible pair IDs (listed: only in production, only in the exploratory run); P-R1 class means on the INTERSECTION of pair IDs within 0.02 C
and no <1 h pair with a 4-probe-mean rise >= 2 C; P-R5 start-column difference (fast mean within 0.02 C of target and |mean| <= 0.05; slow mean within 0.02 C of target and interval excluding 0).
P-R2/P-R3/P-R4 are evaluated by tools/park_model.py. A failed gate is recorded as failed, never relaxed. Usage: python tools/restart_gates.py [--dir analyses/M709]  (exit 0 all pass, 1 any fail)"""
import json, os, sys
import numpy as np
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import restart_census as RC


def evaluate(out_dir, targets_path=None):
    T = json.load(open(targets_path or os.path.join(ROOT, "analyses", "M708_targets.json"), encoding="utf-8"))
    C = json.load(open(os.path.join(out_dir, "restart_census.json"), encoding="utf-8"))
    P = pd.read_csv(os.path.join(out_dir, "restart_pairs.csv"), dtype={"p_key": str, "n_key": str}, low_memory=False)
    g = {}
    ex, tx = C["exclusions"], T["exclusions"]
    prod_ids = set(P.loc[P["elig"], "pair_id"])
    tgt_ids = set(T["eligiblePairIds"])
    g["P-R0"] = {"pass": abs(ex["eligible"] - tx["eligible"]) <= 3 and abs(ex["eligibleDays"] - tx["eligibleDays"]) <= 3,
                 "eligible": [ex["eligible"], tx["eligible"]], "days": [ex["eligibleDays"], tx["eligibleDays"]], "onlyInProduction": sorted(prod_ids - tgt_ids), "onlyInExploratory": sorted(tgt_ids - prod_ids),
                 "exclusionsProduction": {k: ex[k] for k in ("odoStepAbsGt1km_appCounter", "noFreshProbeAtAnEndpoint", "gapOver168h")}, "exclusionsTarget": {k: tx[k] for k in ("odoStepAbsGt1km_appCounter", "noFreshProbeAtAnEndpoint", "gapOver168h")}}
    inter = P[P["elig"] & P["pair_id"].isin(tgt_ids)]
    cls = {}
    ok = True
    for lab, tv in T["E1"].items():
        sel = inter if lab == "all gaps" else (inter[inter["gc"].isin(RC.GAP_LAB[:2])] if lab == "<1 h" else inter[inter["gc"] == lab])
        m = float(sel["d_same"].mean())
        cls[lab] = {"production": round(m, 4), "target": tv["meanChange"], "absDiff": round(abs(m - tv["meanChange"]), 4), "n": int(len(sel))}
        ok &= abs(m - tv["meanChange"]) <= 0.02
    short_rise = int(((inter["gc"].isin(RC.GAP_LAB[:2])) & (inter["d_same"] >= 2)).sum())
    g["P-R1"] = {"pass": bool(ok and short_rise == 0), "classes": cls, "pairsBelow1hWithRiseGe2C": short_rise, "nIntersection": int(len(inter))}
    e5, te = C["E5"], T["E5"]
    f, s = e5["fastPerDrive"], e5["slowPerDrive"]
    g["P-R5"] = {"pass": bool(abs(f["est"] - te["fastPerDriveMean"]) <= 0.02 and abs(f["est"]) <= 0.05 and abs(s["est"] - te["slowPerDriveMean"]) <= 0.02 and s["lo"] > 0),
                 "fast": {"mean": round(f["est"], 4), "n": f["n"], "target": te["fastPerDriveMean"]}, "slow": {"mean": round(s["est"], 4), "ci": [round(s["lo"], 3), round(s["hi"], 3)], "n": s["n"], "target": te["slowPerDriveMean"]},
                 "note": "drive counts follow the production per-drive period rule on the 665-drive master (the exploratory run counted 444 fast-polled drives)"}
    return g


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    d = argv[argv.index("--dir") + 1] if "--dir" in argv else os.path.join(ROOT, "analyses", "M709")
    g = evaluate(d)
    json.dump(g, open(os.path.join(d, "restart_gates.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: v["pass"] for k, v in g.items()}), "onlyInProduction", g["P-R0"]["onlyInProduction"], "onlyInExploratory", g["P-R0"]["onlyInExploratory"])
    return 0 if all(v["pass"] for v in g.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
