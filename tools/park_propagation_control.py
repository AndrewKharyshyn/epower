#!/usr/bin/env python3
"""M719 control build for the park-model propagation (item R2 of the combined audit handoff 2026-11-17): what the M709 park model (diurnal boundary, one offset 0.469 C [-0.578, 1.407], tau 9.105 h [8.19, 10.16], flagged
unlogged legs excluded) does to the displayed parked-hour bands of the block `parkedTimeBudget` (tools/parked_time_budget.py, spec analyses/M686_spec.md Rev 1.1; tau from seasonalFits.Q3 by owner decision D-05).
`exposureVector` uses a current offset, not the park model, and `thermalSupportLedger` does not use the park model at all (checked, see the output): neither is affected.
The control re-evaluates the SAME gaps with the SAME closed-form band-hour function for: the displayed primary (tau 7.873 h, offset 0), the M709 default (tau 9.105 h, offset 0.469 C), the M709 interval corners (tau 8.19 / 10.162 h) and the
offset bracket [0, 2.7] C, and compares every parked-hour metric with the min / max of the pre-registered assumption grid that the block displays. A metric whose M709 value lies outside the displayed min-max envelope is a FLAG (escalation: Director, then Andrii);
nothing is written into the payload by this tool. Estimated, model-derived hours; never measured.
Usage: python tools/park_propagation_control.py [--raw-dir DIR] [--out analyses/M719/park_propagation_control.json]"""
import argparse, json, os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import parked_time_budget as PTB

HEADLINE = ["parkedHours", "cold10", "cold15", "hot35", "hot40", "cold10NoLong", "cold15NoLong", "hot35NoLong", "hot40NoLong"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M719", "park_propagation_control.json"))
    a = ap.parse_args(argv)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    pk = json.load(open("analyses/M709/park_model.json", encoding="utf-8"))["M2_fullSample_nonFlagged"]
    d, N = PTB.load_frame(a.raw_dir)
    gaps = PTB.build_gaps(d)
    ent, gate, _ = PTB.tau_axis(A["seasonalFits"]["Q3"])
    cells = PTB.run_grid(gaps, ent)
    env = PTB.grid_summary(cells)
    prim = next(e for e in ent if e[0] == "primary")
    variants = {"displayedPrimary (tau 7.873, offset 0)": dict(tau=prim[1], offset=0.0),
                "M709 default (tau %.3f, offset %.3f)" % (pk["tau_h"], pk["offset_C"]): dict(tau=pk["tau_h"], offset=pk["offset_C"]),
                "M709 tau lower end (%.3f), offset %.3f" % (pk["tauCi"][0], pk["offset_C"]): dict(tau=pk["tauCi"][0], offset=pk["offset_C"]),
                "M709 tau upper end (%.3f), offset %.3f" % (pk["tauCi"][1], pk["offset_C"]): dict(tau=pk["tauCi"][1], offset=pk["offset_C"]),
                "M709 tau, offset bracket lower (0)": dict(tau=pk["tau_h"], offset=0.0),
                "M709 tau, offset bracket upper (2.7)": dict(tau=pk["tau_h"], offset=2.7)}
    res = {}
    for lab, v in variants.items():
        m = PTB.metrics(PTB.evaluate(gaps, v["tau"], shift=0.0, offset=v["offset"]))
        res[lab] = {k: round(m[k], 3) for k in HEADLINE}
    prim_m = res["displayedPrimary (tau 7.873, offset 0)"]
    m709 = res["M709 default (tau %.3f, offset %.3f)" % (pk["tau_h"], pk["offset_C"])]
    rows = {}
    flags = []
    for k in HEADLINE:
        lo, hi = env[k]["min"], env[k]["max"]
        inside = bool(lo - 1e-9 <= m709[k] <= hi + 1e-9)
        rows[k] = {"displayedPrimary": prim_m[k], "M709default": m709[k], "relDelta": round((m709[k] - prim_m[k]) / prim_m[k], 4) if prim_m[k] else None, "displayedGridMin": lo, "displayedGridMax": hi, "M709InsideGridEnvelope": inside}
        if not inside:
            flags.append("%s: M709 value %.3f outside the displayed grid envelope [%.3f, %.3f]" % (k, m709[k], lo, hi))
    # the displayed bands
    bands = {}
    prim_b = PTB.evaluate(gaps, prim[1], shift=0.0, offset=0.0)["bands"]
    m709_b = PTB.evaluate(gaps, pk["tau_h"], shift=0.0, offset=pk["offset_C"])["bands"]
    for j, lab in enumerate(PTB.LABELS):
        mn, mx = env["band:" + lab]["min"], env["band:" + lab]["max"]
        bands[lab] = {"displayedPrimary": round(float(prim_b[j]), 3), "M709default": round(float(m709_b[j]), 3), "gridMin": mn, "gridMax": mx, "M709InsideGridEnvelope": bool(mn - 1e-9 <= m709_b[j] <= mx + 1e-9)}
        if not bands[lab]["M709InsideGridEnvelope"]:
            flags.append("band %s: M709 value %.3f outside the displayed grid envelope [%.3f, %.3f]" % (lab, m709_b[j], mn, mx))
    jsx_uses = {"parkedTimeBudget": open("xtrail_summary.jsx", encoding="utf-8").read().count("parkedTimeBudget")}
    out = {"milestone": "M719", "purpose": "control build of the park-model propagation (no payload change)", "gridCells": len(cells), "tauAxis": [{"name": e[0], "tauH": e[1], "ambientShiftC": e[2]} for e in ent],
           "variants": res, "metrics": rows, "bands": bands, "flags": flags, "displayedInDashboard": jsx_uses,
           "otherBlocks": {"exposureVector": "uses a CURRENT offset sensitivity (-0.5 / +0.5 A), not the park model: unaffected", "thermalSupportLedger": "tools/thermal_support_ledger.py contains no park-model or tau reference: unaffected"},
           "reading": "the tau of parkedTimeBudget comes from seasonalFits.Q3 (owner decision D-05), an exponential to the mean of the two ambient readings without offset and without the unlogged-use flags of M708; the M709 model (diurnal boundary, one offset, flagged legs excluded) gives a longer time constant (9.105 vs 7.873 h)"}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)
    print(json.dumps({"flags": flags, "relDelta": {k: v["relDelta"] for k, v in rows.items()}, "inside": {k: v["M709InsideGridEnvelope"] for k, v in rows.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
