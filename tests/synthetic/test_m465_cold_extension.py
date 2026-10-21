"""M465 known-answer tests: Cold column of the urban contrast (point estimate only, independent recomputation from drive_master/seasonal master), no interval where the
support floor (>= 10 drives on >= 5 days) is not met, fuelWarmup cold groups carry no CI below 10 trips on 7 days, deep-diff allow-list."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
A = json.load(open("summary_arrays.json", encoding="utf-8"))
U = A["comparisonCube"]["urbanContrast"]
dm = pd.read_csv("drive_master.csv", low_memory=False)
reg = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "thermal_regime"]]
d = dm.merge(reg, on="file", how="left")
flag = lambda c: d[c].astype(str).str.strip().str.lower().eq("true")
d = d[~(flag("ens_invalid") | flag("ens_outlier_v2"))]
u = d[d.drive_type.astype(str).str.strip().str.lower().replace({"city": "urban"}).eq("urban") & d.thermal_regime.eq("cold") & d.gross_throughput_kwh.notna() & d.distance_km.gt(0)]
c0 = U["bands"][0]["cold"]
assert c0["nDrives"] == len(u) and c0["nDays"] == u["date"].nunique()
assert abs(c0["estimate"] - round(100 * u.gross_throughput_kwh.sum() / u.distance_km.sum(), 2)) < 1e-9
assert c0["ci95"] is None and "difference" not in c0                       # exploratory: no interval, no difference
assert (c0["nDays"] >= 5 and c0["nDrives"] >= 10) == (c0["status"] == "observed")
for b in U["bands"]:
    c = b.get("cold")
    if c is not None:
        assert c["nDrives"] >= 1 and (c["ci95"] is None or c["status"] == "observed")
assert U["descriptive"]["cold"]["nDrives"] == len(u)
for k, g in A["fuelWarmup"]["groups"].items():
    if k.startswith("cold|"):
        for s in g["sets"].values():
            for pts in s.values():
                for p in pts:
                    if p.get("ci95") is not None:
                        assert p["n"] >= 10 and p["days"] >= 7, (k, p)       # pointwise rule unchanged for the new cohort
import m465_diff_check as D
out = []
D.walk({"a": {"x": 1}}, {"a": {"x": 1, "cold": 2}}, "", out)
assert out == [("add", "/a/cold")]
print("test_m465_cold_extension OK")
