"""M420: compare the blind audit (analyses/M420_audit/result.json, written by the auditor from definitions only) with the integrationScenarios block."""
import json, os
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
r = json.load(open("analyses/M420_audit/result.json", encoding="utf-8"))
B = json.load(open("summary_arrays.json", encoding="utf-8"))["integrationScenarios"]
rows = {x["id"]: x for x in B["scenarios"]}
amap = {"A3": "A3", "B1": "B1", "B2": "B2", "C1": "C1", "C3": "cap3", "C4": "cap10", "D1": "D1"}
out = {"pairs": [], "allEqual": True}


def cmp(name, a, b, tol):
    eq = abs(a - b) <= tol
    out["pairs"].append({"name": name, "block": a, "audit": b, "equal": eq})
    out["allEqual"] &= eq


S0 = r["scenarios"]["S0"]
cmp("baseline.discharge", B["baseline"]["grossDischargeKwh"], S0["discharge_kwh"], 1e-4)
cmp("baseline.charge", B["baseline"]["grossChargeKwh"], S0["charge_kwh"], 1e-4)
cmp("baseline.n>=0.1", rows["A3"]["perDriveRatio"]["nDrives"], S0["n_drives_ge_0.1"], 0)
cmp("baseline.maxdev<5e-4", float(B["checks"]["baselineReproducesMaster"]["maxAbsDevKwh"] <= 5e-4), float(r["baseline_vs_master"]["max_abs_dev_kwh"] <= 5e-4), 0)
for k, v in (("n5", "n5"), ("n10", "n10"), ("n30", "n30")):
    cmp("gaps." + k, B["baseline"]["gapInventory"][k], r["gaps_baseline"][v], 0)
cmp("gaps.s5", B["baseline"]["gapInventory"]["s5"], r["gaps_baseline"]["d5"], 0.2)
cmp("gaps.excess", B["baseline"]["gapInventory"]["excessBeyondCapS"], r["gaps_baseline"]["beyond5"], 0.2)
for mine, theirs in amap.items():
    a, b = rows[mine], r["scenarios"][theirs]
    cmp(mine + ".discharge", a["grossDischargeKwh"], b["discharge_kwh"], 1e-4)
    cmp(mine + ".charge", a["grossChargeKwh"], b["charge_kwh"], 1e-4)
    cmp(mine + ".ratio", a["ratioToBaseline"], b["ratio"], 1e-6)
    cmp(mine + ".median", a["perDriveRatio"]["median"], b["median_drive_ratio"], 1e-6)
    cmp(mine + ".ci_lo", a["dayVariabilityOfRatio95"][0], b["ratio_ci95"][0], 2e-6)
    cmp(mine + ".ci_hi", a["dayVariabilityOfRatio95"][1], b["ratio_ci95"][1], 2e-6)
json.dump(out, open("analyses/M420_audit/compare.json", "w", encoding="utf-8"), indent=1)
print(len(out["pairs"]), "pairs; all equal:", out["allEqual"], [p for p in out["pairs"] if not p["equal"]])
