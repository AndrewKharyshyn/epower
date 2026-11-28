"""M796 known-answer tests (analyses/M796_spec.md Rev 2) for tools/stopgo_per_drive.py: binning, the med/IQR arithmetic of the released census, the small-n flags, and the identity of the published block with S.crawlStopGo."""
import json, os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import stopgo_per_drive as X

# 1. binning: 0..20 are exact integer bins, 21 and above are the overflow; non-finite values are ignored
c, o = X.bin_counts([0, 0, 1, 20, 21, 35, np.nan])
assert c[0] == 2 and c[1] == 1 and c[20] == 1 and sum(c) == 4 and o == 2, (c, o)
assert X.bin_counts([])[1] == 0 and sum(X.bin_counts([])[0]) == 0

# 2. the med/IQR arithmetic equals the released census function exactly (same rounding, linear percentiles)
import compute_summary_arrays as C
rng = np.random.default_rng(3)
for n in (1, 2, 7, 40, 615):
    v = rng.integers(0, 30, n).astype(float).tolist()
    assert X.med_iqr(v) == C._csg_med_iqr(v), (n, X.med_iqr(v), C._csg_med_iqr(v))
assert X.med_iqr([]) is None

# 3. type block: shares of drives, small-n and count-list flags, one drive = x %
b = X.type_block([0, 1, 2, 3, 10, 12, 25, 4, 4, 4])
assert b["nDrives"] == 10 and b["overflow"] == 1 and b["share0to2"] == 0.3 and b["share10plus"] == 0.3 and b["fewDrives"] is True and b["countListOnly"] is False and b["oneDrivePct"] == 10.0, b
b1 = X.type_block([5]); assert b1["countListOnly"] is True and b1["oneDrivePct"] == 100.0
assert X.type_block(list(range(30)))["fewDrives"] is False

# 4. the published block reproduces the published census (G1) and the sidecar
A = json.load(open("summary_arrays.json", encoding="utf-8")); B = A["stopGoPerDrive"]; csg = A["crawlStopGo"]
assert B["reconciliation"]["identityOk"] is True and B["reconciliation"]["rows"] == csg["nDrivesCovered"] and B["reconciliation"]["sumCycles"] == csg["nStopGoCycles"] and B["reconciliation"]["sumStops"] == csg["nStops"]
assert sum(v["nDrives"] for v in B["types"].values()) == csg["nDrivesCovered"] == B["all"]["nDrives"]
for t, v in B["types"].items():
    pub = csg["byDriveType"][t]["cyclesPerDrive"]
    assert (v["nDrives"], v["median"], v["p25"], v["p75"], v["p95"]) == (pub["n"], pub["median"], pub["p25"], pub["p75"], pub["p95"]), t
    assert sum(v["counts"]) + v["overflow"] == v["nDrives"] and len(v["counts"]) == X.MAX_BIN + 1
import pandas as pd
side = pd.read_csv("stopgo_per_drive.csv", keep_default_na=False, na_values=[""])
assert len(side) == csg["nDrivesCovered"] and int(side["n_cycles"].sum()) == csg["nStopGoCycles"] and side["file"].is_unique
txt = json.dumps(B)
assert not any(f in txt for f in side["file"].astype(str).tolist()[:200]), "no drive file name in the payload"
assert len(txt) < 20000
print("ok test_stopgo_per_drive")
