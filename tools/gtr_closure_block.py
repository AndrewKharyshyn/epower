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
M372 = "--m372" in sys.argv     # M372: regenerated block from analyses/M372_* (spec analyses/M372_spec.md Rev 2); default = the M336 files
PFX = "M372" if M372 else "M336"
DIAG = os.path.join(ROOT, "analyses", PFX + "_closure_diag.json")
STEP2 = os.path.join(ROOT, "analyses", PFX + ("_step2_result.json"))


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
    headline_note = ""
    base_note = ""
    if M372:   # after M349 the published rows of the NaN-offset drives are repaired (f_gen no longer 1 by construction): state the CURRENT published values, bound to fuel_recon_master.csv
        cur = {r.file: r.f_gen for r in pub.itertuples()}
        base_note = ("NaN battery offset or NaN charge-class columns in the master: the closure skips these drives by design (pre-registered M336 rule). Before M349 the published reconstruction gave zero battery power for such a drive "
                     "(f_gen = 1 by construction); M349 repaired the published rows" + (" (current published f_gen: " + ", ".join(f"{k.replace('.csv', '')} {v:.4f}" for k, v in sorted(cur.items())) + ")" if cur else "")
                     + (f"; {len(f1)} published row(s) still have f_gen = 1" if f1 else "; no published row has f_gen = 1 now"))
    if M372:   # Director rulings (M372 trigger ruling; M375 Rev 2): the closure set differs from the headline set; the note is written from a per-ID reconciliation of the FILES (no payload dependence)
        import eligibility as EL
        head_all = set(fr.file)                                                      # fuel-instrumented rows of fuel_recon_master.csv
        head = head_all - EL.excluded_files(EL.load_flags(os.path.join(ROOT, "drive_master.csv")), fr.file)     # headline set since M375: canonical-clean (ens_outlier_v2)
        closure = set(pd.read_csv(os.path.join(ROOT, "analyses", "M372_closure_perdrive.csv")).file)
        nan_in = set(s["excluded_no_battery_inputs"])
        reasons = {f: ("NaN battery inputs" if f in nan_in else "other") for f in sorted(head - closure)}
        assert not (closure - head), "closure drives outside the headline set"
        assert "other" not in reasons.values(), reasons
        assert len(head) - len(reasons) == len(closure) == s["n_drives"], (len(head), len(reasons), len(closure))
        not_in_head = sorted(nan_in - head)
        headline_note = (f". Set note (as of the M375 eligibility alignment): the closure set is {len(closure)} drives; the headline set is the {len(head)} canonical-clean (ens_outlier_v2) of {len(head_all)} fuel-instrumented drives, "
                         f"{len(head)} - {len(reasons)} = {len(closure)}; headline drives not in the closure: " + "; ".join(f"{f.replace('.csv', '')} ({r})" for f, r in reasons.items())
                         + ("; NaN-battery-input drive(s) in neither set (no published row or canonical outlier): " + ", ".join(f.replace('.csv', '') for f in not_in_head) if not_in_head else ""))
    return {
        "basis": ("fuel-PID subset, model-derived; raw/ = sha256-verified originals (M366); not M299-reproducible" if M372 else "fuel-PID subset, model-derived; computed on the former raw/ re-exports (pre-M366); not refreshed on the originals; not M299-reproducible"),
        "scope": {"nDrives": s["n_drives"], "nDays": s["n_days"], "km": s["km"], "nCanonical": n_canon,
                  "excludedNoBatteryInputs": s["excluded_no_battery_inputs"],
                  "excludedNote": (base_note if M372 else "NaN battery offset or NaN charge-class columns in the master: where the published reconstruction has a row for such a drive it gives zero battery power, so f_gen = 1 by construction") + headline_note,
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
        "sources": {"closureDiag": {"path": "analyses/" + PFX + "_closure_diag.json", "sha256": sha(DIAG)},
                    "step2": {"path": "analyses/" + PFX + "_step2_result.json", "sha256": sha(STEP2)},
                    **({"fuelReconMaster": {"path": "fuel_recon_master.csv", "sha256": sha(os.path.join(ROOT, "fuel_recon_master.csv"))}} if M372 else {})},
        "_staleness": ("refreshed at M372 on the sha256-verified originals (M366 basis), same 257-drive set as M336 (ID set asserted before any estimate); producers tools/gtr_closure_diag.py sha256 " + sha(os.path.join(ROOT, "tools", "gtr_closure_diag.py"))[:12] + " and tools/gtr_interval_sens.py sha256 " + sha(os.path.join(ROOT, "tools", "gtr_interval_sens.py"))[:12] + " (run at repo HEAD " + d["m372"]["scriptGit"] + " plus the M372 changes of those two scripts, committed with this milestone); carried forward by ingestion until a refresh stage exists (spec analyses/M372_spec.md); re-run tools/gtr_closure_diag.py --m372, tools/gtr_interval_sens.py --m372 and tools/m372_closure_splice.py to refresh"
                        if M372 else "computed at M336 on the 489-drive master; carried forward by ingestion; re-run tools/gtr_closure_diag.py, tools/gtr_interval_sens.py and tools/gtr_closure_block.py to refresh"),
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
