"""M460 post-run diagnostics required by the Director ruling (no new hypothesis test; same drives, same evaluator, read-only):
(1) the cross-tab of the RPM polling stratum (master ev_rpm_dt_med_s < 1.0 s) against the fuel polling stratum (per-drive median sampling interval of the fuel-rate channel < 1.0 s) on P_F;
(2) the motored distance B (km) under each declared convention (primary, raw, eps 0.05 / 0.10 / 0.35, 1.5 s alignment), i.e. the convention range of B.
Output: analyses/M460_diag.json.  Usage: python analyses/M460_diag/diag.py   (re-evaluates the 483 released-population drives; about 20 s)"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import zero_fuel as Z

if __name__ == "__main__":
    out, rows = Z.build()
    ct = {}
    for r in rows:
        k = "rpm=%s|fuel=%s" % (r["rpmPoll"], r["fuelPoll"])
        ct[k] = ct.get(k, 0) + 1
    cfgs = {"primary": "primary", "raw": "raw", "eps0.05": "eps0.05", "eps0.1": "eps0.1", "eps0.35": "eps0.35"}
    B = {name: round(sum(r[cfg]["B"] for r in rows), 2) for name, cfg in cfgs.items()}
    B["tol1.5"] = round(sum(r["tol1.5"]["B"] for r in rows if r["tol1.5"]["covFuel"] >= Z.COV_MIN), 2)
    lo, hi = min(B.values()), max(B.values())
    fuel_dt = [r["fuelDtMedS"] for r in rows]
    res = {"nPF": len(rows), "pollCrossTab": ct, "identicalPartition": bool(all(r["rpmPoll"] == r["fuelPoll"] for r in rows)),
           "fuelDtMedS_minMax_fast": [round(min(x for x in fuel_dt if x < 1.0), 3), round(max(x for x in fuel_dt if x < 1.0), 3)], "fuelDtMedS_minMax_slow": [round(min(x for x in fuel_dt if x >= 1.0), 3), round(max(x for x in fuel_dt if x >= 1.0), 3)],
           "motoredKmByConvention": B, "motoredKmRange": [lo, hi], "gate": {"nPFMatchesResult": len(rows) == json.load(open("analyses/M460_result.json", encoding="utf-8"))["nPF"]}}
    with open("analyses/M460_diag.json", "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps(res))
