#!/usr/bin/env python3
"""M336 step 3: additive leaf splice of S.generatorTractionRecon.gtrClosure into summary_arrays.json.
Every number is read from the script-written M336 result files (analyses/M336_closure_diag.json, analyses/M336_step2_result.json); nothing is typed here.
Adds one new key only (no existing leaf touched; asserted). Idempotent. The block is carried forward by ingestion (the producing tools take ~15 min and are
re-run by hand: tools/gtr_closure_diag.py, tools/gtr_interval_sens.py, then this script).
Usage: python tools/gtr_closure_block.py [--dry-run]"""
import hashlib, json, os, sys
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
DIAG = os.path.join(ROOT, "analyses", "M336_closure_diag.json")
STEP2 = os.path.join(ROOT, "analyses", "M336_step2_result.json")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def build():
    d = json.load(open(DIAG, encoding="utf-8"))
    s = json.load(open(STEP2, encoding="utf-8"))
    A = json.load(open(ARR, encoding="utf-8"))
    n_canon = A["meta"]["totalDrives"]
    V = s["variants"]
    base = V["baseline"]
    t = d["per100km_totals"]
    rel = d["relative_to_generator"]
    fg = [v["f_gen"]["est"] for v in V.values()]
    al = [v["alpha_star"]["est"] for v in V.values()]
    fr = pd.read_csv(os.path.join(ROOT, "fuel_recon_master.csv"))
    pub = fr[fr.file.isin(s["excluded_no_battery_inputs"])]
    f1 = sorted(pub[(pub.f_gen - 1.0).abs() < 1e-6].file.tolist())
    return {
        "basis": "fuel-PID subset, model-derived; computed on the former raw/ re-exports (pre-M366); not refreshed on the originals; not M299-reproducible",
        "scope": {"nDrives": s["n_drives"], "nDays": s["n_days"], "km": s["km"], "nCanonical": n_canon,
                  "excludedNoBatteryInputs": s["excluded_no_battery_inputs"],
                  "excludedNote": "NaN battery offset or NaN charge-class columns in the master: where the published reconstruction has a row for such a drive it gives zero battery power, so f_gen = 1 by construction",
                  "publishedRowsWithFgenOne": f1, "excludedWithoutPublishedRow": sorted(set(s["excluded_no_battery_inputs"]) - set(pub.file.tolist()))},
        "per100km": {"generator": t["E_gen"], "genToTraction": t["g2t"], "genToBattEngineOn": t["eng_only"], "genToBattDual": t["dual"],
                     "genToBattUpper": t["g2b_master"], "regenToBatt": t["regen"], "battToTractionResidual": t["b2t"]},
        "nodeExcess": {"relToGenerator": rel["excess"]["est"], "ci95": rel["excess"]["ci95"], "tolerance": 0.05,
                       "closedUnderRule": bool(rel["excess"]["ci95"][0] >= -0.05 and rel["excess"]["ci95"][1] <= 0.05)},
        "excessWithoutDual": {"relToGenerator": rel["excess_engonly"]["est"], "ci95": rel["excess_engonly"]["ci95"]},
        "interval": {"lo": base["X_lo_rel"]["est"], "hi": base["X_hi_rel"]["est"],
                     "zeroInsideAllVariants": all(v["zero_in_X_pointwise"] for v in V.values()), "nVariants": len(V)},
        "fGen": {"est": base["f_gen"]["est"], "ci95": base["f_gen"]["ci95"], "ciContains0p5": base["f_gen_ci_contains_0p5"],
                 "variantMin": min(fg), "variantMax": max(fg), "pointBelow0p5AllVariants": all(x < 0.5 for x in fg), "nVariants": len(V),
                 "stopTriggered": s["stop_triggered"]},
        "alphaStar": {"est": base["alpha_star"]["est"], "ci95": base["alpha_star"]["ci95"], "variantMin": min(al), "variantMax": max(al),
                      "nInfeasibleDrivesBaseline": base["n_infeasible_alpha_drives"],
                      "label": "implied closure parameter solved from the same data; not an estimate of the generator share of the dual charge"},
        "method": "day-clustered percentile bootstrap (seed 42, 4000 draws), corpus ratio-of-sums",
        "sources": {"closureDiag": {"path": "analyses/M336_closure_diag.json", "sha256": sha(DIAG)},
                    "step2": {"path": "analyses/M336_step2_result.json", "sha256": sha(STEP2)}},
        "_staleness": "computed at M336 on the 489-drive master; carried forward by ingestion; re-run tools/gtr_closure_diag.py, tools/gtr_interval_sens.py and tools/gtr_closure_block.py to refresh",
    }


def main():
    A = json.load(open(ARR, encoding="utf-8"))
    R = A["generatorTractionRecon"]
    blk = build()
    before = {k: json.dumps(v, sort_keys=True) for k, v in R.items() if k != "gtrClosure"}
    status = "added" if "gtrClosure" not in R else ("unchanged" if R["gtrClosure"] == blk else "replaced")
    R["gtrClosure"] = blk
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in R.items() if k != "gtrClosure"}   # additive: no other leaf touched
    if "--dry-run" not in sys.argv and status != "unchanged":
        with open(ARR, "w", encoding="utf-8", newline="\n") as f:
            json.dump(A, f, ensure_ascii=False, indent=1)
    print(json.dumps({"gtrClosure": status}))


if __name__ == "__main__":
    main()
