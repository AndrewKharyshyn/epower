#!/usr/bin/env python3
"""M373 control (analyses/M373_spec.md Rev 2, tolerances and reading flips FROZEN before any run). Reads analyses/M373_O_blocks.json and M373_R_blocks.json and the PUBLISHED blocks
in the committed summary_arrays.json (git HEAD, read-only); writes analyses/M373_delta.json. Attribution labels: O minus R = provenance (F03 swap); R minus P = combined drive-set + code + basis drift,
unattributed (R is the current master with FORMER per-sample raw); O minus P is reported as the total. Per block: tolerance breaches (O minus R) go to the Director; a reading flip
on O blocks THAT block's splice and wording. Reading checks are flip detectors only, never presented as tested orderings.
Usage: python tools/m373_diff.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
O = json.load(open("analyses/M373_O_blocks.json", encoding="utf-8"))
R = json.load(open("analyses/M373_R_blocks.json", encoding="utf-8"))
import subprocess
# the PUBLISHED blocks are read from the committed payload (git HEAD), never from the working tree: after a splice the working tree already holds the refreshed blocks (M373 lesson)
G = json.loads(subprocess.run(["git", "show", "HEAD:summary_arrays.json"], capture_output=True, cwd=ROOT).stdout.decode("utf-8"))["generatorTractionRecon"]
assert "refreshedBlocks" not in G or not any(p["block"] in ("sensitivity", "simultaneity", "speedSplit") for p in G["refreshedBlocks"]), "HEAD already holds refreshed blocks: the comparison base must be the previously published blocks"
TOL = {"sens_kwh": 0.02, "sens_frac": 0.002, "split_fgen": 0.005, "split_km_rel": 0.005, "simul_pp": 0.5}
STATES = ("genPlusBattDischarge", "chargesAndDrives", "genAloneNeutral", "fullyBanked")
out = {"tolerancesFrozenIn": "analyses/M373_spec.md Rev 2", "specSha256": O["meta"]["specSha256"], "specShaEqualBothPoints": O["meta"]["specSha256"] == R["meta"]["specSha256"],
       "gates": {"O": {k: O["meta"].get(k) for k in ("sensitivityBaseGate", "speedSplitValidation")}, "R": {k: R["meta"].get(k) for k in ("sensitivityBaseGate", "speedSplitValidation")}},
       "driveIds": {"O": O["meta"]["driveIds"], "R": R["meta"]["driveIds"], "nanOnOneBasisOnly": R["meta"].get("nanOnOneBasisOnly")}, "blocks": {}, "breaches": [], "flips": []}


def cmp_rows(a, b, key, fields):
    return [{"key": x[key], **{f: (x.get(f), y.get(f), None if x.get(f) is None or y.get(f) is None else round(x[f] - y[f], 6)) for f in fields}} for x, y in zip(a, b)]


# ---- sensitivity ----
sa = lambda blk: blk["sensitivity"]["axes"]
labels_ok = [r["axis"] for r in sa(O)] == [r["axis"] for r in G["sensitivity"]]
b = {"axisLabelsEqualPublished": labels_ok, "O_minus_R_provenance": [], "R_minus_P_combined_unattributed": [], "O_minus_P_total": []}
for o, r, p in zip(sa(O), sa(R), G["sensitivity"]):
    for lab, x, y in (("O_minus_R_provenance", o, r), ("R_minus_P_combined_unattributed", r, p), ("O_minus_P_total", o, p)):
        b[lab].append({"axis": o["axis"], **{k: round(x[k] - y[k], 4) for k in ("gen100", "trac100", "fgen", "etaBus")}})
    for k, tol in (("gen100", TOL["sens_kwh"]), ("trac100", TOL["sens_kwh"]), ("fgen", TOL["sens_frac"]), ("etaBus", TOL["sens_frac"])):
        if abs(o[k] - r[k]) > tol + 1e-9:
            out["breaches"].append({"block": "sensitivity", "axis": o["axis"], "field": k, "O_minus_R": round(o[k] - r[k], 4), "tol": tol})
    if o["fgen"] >= 0.5:
        out["flips"].append({"block": "sensitivity", "axis": o["axis"], "rule": "f_gen >= 0.5 on an axis", "value": o["fgen"]})
b["fgenRangeO"] = [min(r["fgen"] for r in sa(O)), max(r["fgen"] for r in sa(O))]
# Director condition: unrounded O-minus-R sensitivity deltas (analysis aggregates without the final rounding); a gen/trac delta above 0.02 is a breach -> Director note, not an automatic failure
unr = {k: round(max(abs(o[k] - r[k]) for o, r in zip(O["sensitivity"]["axesUnrounded"], R["sensitivity"]["axesUnrounded"])), 6) for k in ("gen100", "trac100", "fgen", "etaBus")}
b["unroundedMaxAbsDelta_O_minus_R"] = unr
for k, tol in (("gen100", TOL["sens_kwh"]), ("trac100", TOL["sens_kwh"]), ("fgen", TOL["sens_frac"]), ("etaBus", TOL["sens_frac"])):
    if unr[k] > tol + 1e-9:
        out["breaches"].append({"block": "sensitivity", "field": k + " (unrounded)", "O_minus_R_max_abs": unr[k], "tol": tol})
if "sensitivityRcut" in R:
    b["R_cut_partialStepA"] = {"nFuel": R["sensitivityRcut"]["nFuel"], "nClean": R["sensitivityRcut"]["nClean"], "matchesPublishedClean180": R["sensitivityRcut"]["nClean"] == 180,
                               "baseR_cut": {k: R["sensitivityRcut"]["axes"][0][k] for k in ("gen100", "trac100", "fgen", "etaBus")}, "basePublished": {k: G["sensitivity"][0][k] for k in ("gen100", "trac100", "fgen", "etaBus")},
                               "axesVsPublished": [{"axis": x["axis"], **{k: round(x[k] - y[k], 4) for k in ("gen100", "trac100", "fgen", "etaBus")}} for x, y in zip(R["sensitivityRcut"]["axes"], G["sensitivity"])]}
out["blocks"]["sensitivity"] = b

# ---- speedSplit ----
so, sr, sp = O["speedSplit"]["bins"], R["speedSplit"]["bins"], G["speedSplit"]
b = {"binsEqualPublished": [r["bin"] for r in so] == [r["bin"] for r in sp], "nDrives": {"O": O["speedSplit"]["nDrives"], "R": R["speedSplit"]["nDrives"], "P_largestBin": max(r["nDrives"] for r in sp)}, "nDaysO": O["speedSplit"]["nDays"],
     "O_minus_R_provenance": [], "R_minus_P_combined_unattributed": [], "O_minus_P_total": []}
f = lambda x, y: {"bin": x["bin"], **{k: (None if x[k] is None or y[k] is None else round(x[k] - y[k], 4)) for k in ("distKm", "generator", "battery", "fGen")}}
for x, y, z in zip(so, sr, sp):
    b["O_minus_R_provenance"].append(f(x, y)); b["R_minus_P_combined_unattributed"].append(f(y, z)); b["O_minus_P_total"].append(f(x, z))
    if x["fGen"] is not None and y["fGen"] is not None and abs(x["fGen"] - y["fGen"]) > TOL["split_fgen"] + 1e-9:
        out["breaches"].append({"block": "speedSplit", "bin": x["bin"], "field": "fGen", "O_minus_R": round(x["fGen"] - y["fGen"], 4), "tol": TOL["split_fgen"]})
    if y["distKm"] and abs(x["distKm"] - y["distKm"]) / y["distKm"] > TOL["split_km_rel"] + 1e-12:
        out["breaches"].append({"block": "speedSplit", "bin": x["bin"], "field": "distKm", "O_minus_R_rel": round((x["distKm"] - y["distKm"]) / y["distKm"], 5), "tol": TOL["split_km_rel"]})
d = {r["bin"]: r for r in so}
if d["20-60"]["fGen"] is not None and d["90-120"]["fGen"] is not None and d["90-120"]["fGen"] < d["20-60"]["fGen"]:
    out["flips"].append({"block": "speedSplit", "rule": "f_gen decreasing from 20-60 to 90-120", "values": [d["20-60"]["fGen"], d["90-120"]["fGen"]]})
b["fGenByBinO"] = {r["bin"]: r["fGen"] for r in so}
b["totalsReconcileToHeadline"] = None
out["blocks"]["speedSplit"] = b

# ---- simultaneity ----
mo, mr, mp = O["simultaneity"]["rows"], R["simultaneity"]["rows"], G["simultaneity"]
b = {"typesEqualPublished": [r["type"] for r in mo] == [r["type"] for r in mp], "nDrives": {"O": [(r["type"], r["nDrives"]) for r in mo], "R": [(r["type"], r["nDrives"]) for r in mr], "P": [(r["type"], r["nDrives"]) for r in mp]}, "nDaysO": O["simultaneity"]["nDays"],
     "O_minus_R_provenance": [], "R_minus_P_combined_unattributed": [], "O_minus_P_total": []}
g = lambda x, y: {"type": x["type"], "engineOnHours": round(x["engineOnHours"] - y["engineOnHours"], 2), **{s: round(x[s] - y[s], 2) for s in STATES}}
for x, y, z in zip(mo, mr, mp):
    b["O_minus_R_provenance"].append(g(x, y)); b["R_minus_P_combined_unattributed"].append(g(y, z)); b["O_minus_P_total"].append(g(x, z))
    for s in STATES:
        if abs(x[s] - y[s]) > TOL["simul_pp"] + 1e-9:
            out["breaches"].append({"block": "simultaneity", "type": x["type"], "state": s, "O_minus_R_pp": round(x[s] - y[s], 2), "tol": TOL["simul_pp"]})
dd = {r["type"]: r for r in mo}
if "urban" in dd and "highway" in dd:
    if dd["urban"]["genPlusBattDischarge"] >= dd["highway"]["genPlusBattDischarge"]:
        out["flips"].append({"block": "simultaneity", "rule": "urban gen+battery-discharge >= highway", "values": [dd["urban"]["genPlusBattDischarge"], dd["highway"]["genPlusBattDischarge"]]})
    if dd["urban"]["chargesAndDrives"] <= dd["highway"]["chargesAndDrives"]:
        out["flips"].append({"block": "simultaneity", "rule": "urban charge-and-drive <= highway", "values": [dd["urban"]["chargesAndDrives"], dd["highway"]["chargesAndDrives"]]})
# deadband (analysis only): O minus R at every grid point, with the band shares
grid = {}
for k in O["deadband"]:
    mx = 0.0
    per = []
    for x, y in zip(O["deadband"][k]["rows"], R["deadband"][k]["rows"]):
        dl = {s: round(x[s] - y[s], 2) for s in STATES}
        mx = max(mx, max(abs(v) for v in dl.values()))
        per.append({"type": x["type"], **dl})
    grid[k] = {"maxAbsDeltaPP_O_minus_R": round(mx, 2), "perType": per, "bandShareO": O["deadband"][k]["bandShareEngineOn"], "bandShareR": R["deadband"][k]["bandShareEngineOn"]}
b["deadbandGrid"] = grid
b["deadbandNote"] = "analysis only; epsilon stays 0.5 kW; eps 0.25 kW is below the re-export current resolution (~1 A); read together with the deltas at 0.5_0.5"
out["blocks"]["simultaneity"] = b
out["summary"] = {"nBreaches": len(out["breaches"]), "nFlips": len(out["flips"]), "gatesPassed": all(out["gates"][p][k]["passed"] for p in ("O", "R") for k in ("sensitivityBaseGate", "speedSplitValidation")),
                  "blocksWithBreach": sorted({x["block"] for x in out["breaches"]}), "blocksWithFlip": sorted({x["block"] for x in out["flips"]})}
with open("analyses/M373_delta.json", "w", encoding="utf-8", newline="\n") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False)
    fh.write("\n")
print(json.dumps(out["summary"], indent=1))
print("breaches:", json.dumps(out["breaches"][:12])); print("flips:", json.dumps(out["flips"]))
