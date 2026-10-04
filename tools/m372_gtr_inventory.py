#!/usr/bin/env python3
"""M372 (analyses/M372_spec.md): read-only inventory for the GTR block refresh. Reads drive_master.csv, fuel_recon_master.csv and the committed M336 per-drive CSV only
(no raw file, no recomputation); writes analyses/M372_gtr_inventory.json. Establishes (script-written, never typed): the eligible sets (fuel_recon_master rows, canonical-clean,
the published gtrClosure set), n drives / n days per set, and which basis-date cutoffs reproduce the published old drive counts (M255 181, M279 181 fuel / 180 clean).
Usage: python tools/m372_gtr_inventory.py"""
import hashlib, json, os, subprocess
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
dm = pd.read_csv("drive_master.csv", low_memory=False)
fr = pd.read_csv("fuel_recon_master.csv")
cl = pd.read_csv("analyses/M336_closure_perdrive.csv")
A = json.load(open("summary_arrays.json", encoding="utf-8"))["generatorTractionRecon"]
norm = lambda s: str(s)
clean_files = set(dm.loc[~dm["ens_outlier_v2"].fillna(False).astype(bool), "file"])
fr["clean"] = fr["file"].isin(clean_files)
dist = dm.set_index("file")["distance_km"]
fr["dist_gt0"] = fr["file"].map(dist) > 0


def desc(df):
    return {"nDrives": int(len(df)), "nDays": int(df["date"].nunique()), "km": round(float(df["distance_km"].sum()), 1)}


inv = {
    "headline": {"nProduction": A["nProduction"], "nDrives": A["nDrives"], "km": A["kmProduction"]},
    "fuelReconMaster": desc(fr),
    "fuelReconMasterCanonicalClean": desc(fr[fr["clean"]]),
    "fuelReconMasterCleanDistGt0": desc(fr[fr["clean"] & fr["dist_gt0"]]),
    "publishedClosureSet": {"nDrives": int(len(cl)), "nDays": int(cl["date"].nunique()), "km": round(float(cl["km"].sum()), 1), "source": "analyses/M336_closure_perdrive.csv"},
    "closureSetMinusFuelReconMaster": sorted(set(cl["file"]) - set(fr["file"])),
    "fuelReconMasterMinusClosureSet": sorted(set(fr["file"]) - set(cl["file"])),
    "notInClosureReason": {},
}
for f in inv["fuelReconMasterMinusClosureSet"]:
    r = fr[fr["file"] == f].iloc[0]
    inv["notInClosureReason"][f] = {"canonicalClean": bool(r["clean"]), "distanceGt0": bool(r["dist_gt0"])}
cut = []
for d in pd.date_range("2026-09-10", "2026-09-20").strftime("%Y-%m-%d"):
    s = fr[fr["date"].astype(str) <= d]
    cut.append({"cutoff": d, "fuelReconRows": int(len(s)), "clean": int(s["clean"].sum()), "days": int(s["date"].nunique()), "masterRows": int((dm["date"].astype(str) <= d).sum())})
inv["dateCutoffTable"] = cut
inv["publishedOldCounts"] = {"M255_speedSplit_largestBin": max(r["nDrives"] for r in A["speedSplit"]), "M279_sensitivity_fuel_clean": [r for r in A["staleBlocks"]["perBlock"] if r["block"] == "sensitivity"][0].get("nDrives"),
                             "M282_simultaneity_total": sum(r["nDrives"] for r in A["simultaneity"]), "crossval": A["crossval"]["nDrives"]}
inv["scriptGit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
inv["inputs"] = {p: hashlib.sha256(open(p, "rb").read()).hexdigest() for p in ("drive_master.csv", "fuel_recon_master.csv", "analyses/M336_closure_perdrive.csv")}
with open("analyses/M372_gtr_inventory.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(inv, f, indent=1, ensure_ascii=False)
    f.write("\n")
print(json.dumps({k: inv[k] for k in ("headline", "fuelReconMaster", "fuelReconMasterCanonicalClean", "fuelReconMasterCleanDistGt0", "publishedClosureSet", "closureSetMinusFuelReconMaster", "fuelReconMasterMinusClosureSet", "notInClosureReason", "publishedOldCounts")}, indent=1))
for c in cut:
    print(c)
