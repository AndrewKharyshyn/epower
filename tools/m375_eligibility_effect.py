#!/usr/bin/env python3
"""M375 step 1 (analyses/M375_spec.md): READ-ONLY effect of aligning the GTR headline eligibility to the canonical-clean rule (ens_outlier_v2 == False).
Reuses the published aggregation `wire_gtr_seasonal.aggregate` UNCHANGED (import-safe since M374) on (a) the current set (clean = f_gen not NaN) and (b) the canonical-clean set,
for All / Warm / Shoulder, and diffs every corpus / flows / driveTypeSplit field. Writes analyses/M375_eligibility_effect.json only; touches no other file.
Usage: python tools/m375_eligibility_effect.py"""
import hashlib, json, os, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
from wire_gtr_seasonal import aggregate

sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
fr = pd.read_csv("fuel_recon_master.csv")
sdm = pd.read_csv("seasonal_drive_master.csv")[["file", "thermal_regime"]]
dm = pd.read_csv("drive_master.csv", usecols=["file", "ens_outlier_v2"], low_memory=False)
m = fr.merge(sdm, on="file", how="left").merge(dm, on="file", how="left")
assert m["thermal_regime"].isna().sum() == 0
A = json.load(open("summary_arrays.json", encoding="utf-8"))
cc = A["seasonalCharts"]["_meta"]["cohortCounts"]
canon = m[m["ens_outlier_v2"].astype(str) != "True"]
out = {"inputs": {p: sha(p) for p in ("fuel_recon_master.csv", "seasonal_drive_master.csv", "drive_master.csv", "summary_arrays.json")},
       "sets": {"fuelReconRows": int(len(m)), "fNotNaN": int(m["f_gen"].notna().sum()), "canonicalCleanRows": int(len(canon)), "canonicalCleanFNotNaN": int(canon["f_gen"].notna().sum()),
                "excludedByCanonical": [{"file": r.file, "drive_type": r.drive_type, "date": str(r.date), "km": float(r.distance_km), "fGenNaN": bool(pd.isna(r.f_gen)), "regime": r.thermal_regime} for r in m[m["ens_outlier_v2"].astype(str) == "True"].itertuples()],
                "nDaysCurrent": int(m[m["f_gen"].notna()]["date"].astype(str).nunique()), "nDaysCanonical": int(canon[canon["f_gen"].notna()]["date"].astype(str).nunique())},
       "cohorts": {}}


def flat(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from flat(v, f"{p}[{i}]")
    else:
        yield p, o


for name, sel in (("all", None), ("warm", "warm"), ("shoulder", "shoulder")):
    cur = m if sel is None else m[m["thermal_regime"] == sel]
    can = canon if sel is None else canon[canon["thermal_regime"] == sel]
    a = aggregate(cur, name.title(), cc[name])
    b = aggregate(can, name.title(), cc[name])
    fa, fb = dict(flat({k: a[k] for k in ("nProduction", "nDrives", "kmProduction", "corpus", "flows", "driveTypeSplit")})), dict(flat({k: b[k] for k in ("nProduction", "nDrives", "kmProduction", "corpus", "flows", "driveTypeSplit")}))
    diffs = []
    for k in sorted(set(fa) | set(fb)):
        x, y = fa.get(k), fb.get(k)
        if x != y:
            diffs.append({"path": k, "current": x, "canonical": y, "delta": (round(y - x, 4) if isinstance(x, (int, float)) and isinstance(y, (int, float)) else None)})
    out["cohorts"][name] = {"current": {k: a[k] for k in ("nProduction", "nDrives", "kmProduction")}, "canonical": {k: b[k] for k in ("nProduction", "nDrives", "kmProduction")}, "nFieldsDiffer": len(diffs), "nFieldsCompared": len(fa), "diffs": diffs,
                            "corpusCurrent": a["corpus"], "corpusCanonical": b["corpus"]}
# does the current-definition aggregate reproduce the published headline (known answer)?
pub = A["generatorTractionRecon"]
out["currentReproducesPublishedHeadline"] = bool(aggregate(m, "All", cc["all"])["corpus"] == pub["corpus"] and aggregate(m, "All", cc["all"])["nDrives"] == pub["nDrives"])
with open("analyses/M375_eligibility_effect.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(out, f, indent=1, ensure_ascii=False, default=float)
    f.write("\n")
print(json.dumps({"sets": out["sets"], "reproducesPublished": out["currentReproducesPublishedHeadline"],
                  "all": {k: out["cohorts"]["all"][k] for k in ("current", "canonical", "nFieldsDiffer", "nFieldsCompared")}}, indent=1, ensure_ascii=False))
for n in ("all", "warm", "shoulder"):
    print(n, "differing fields:", [(d["path"], d["current"], d["canonical"]) for d in out["cohorts"][n]["diffs"]][:14])
