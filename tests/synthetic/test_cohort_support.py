"""M472 known-answer test of tools/cohort_support.py: (1) a synthetic cohort where one drive holds 90 % of the km (share, effective drives and days, both flags); (2) a three-day cohort with known leave-one-day-out
values and the metric without the largest drive; (3) the live block reproduced independently from the CSVs (cold support, physical vs assigned lists differ on exactly the one override drive); (4) the splice writes only
/cohortSupport and its stamp and is idempotent."""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import cohort_support as C

# (1) concentration
df = pd.DataFrame(dict(file=list("abcd"), date=["d1", "d1", "d2", "d3"], distance_km=[90.0, 4.0, 3.0, 3.0], duration_s=[3600.0] * 4))
s = C.support(df)
assert s["largestDrive"] == {"file": "a", "km": 90.0, "share": 0.9} and s["largestDay"]["date"] == "d1" and s["largestDay"]["share"] == 0.94
assert abs(s["effectiveDrives"] - 1 / (0.9 ** 2 + 0.04 ** 2 + 0.03 ** 2 * 2)) < 0.01 and s["nDays"] == 3 and abs(s["effectiveDays"] - 1 / (0.94 ** 2 + 0.03 ** 2 * 2)) < 0.01
assert s["flags"] == {"dominatedByOneDrive": True, "fewEffectiveDays": True}
eq = C.support(pd.DataFrame(dict(file=list("abcdef"), date=list("112233"), distance_km=[10.0] * 6, duration_s=[60.0] * 6)))
assert eq["effectiveDays"] == 3.0 and eq["effectiveDrives"] == 6.0 and eq["flags"]["dominatedByOneDrive"] is False
# (2) LODO
m = pd.DataFrame(dict(file=list("abc"), date=["d1", "d2", "d3"], distance_km=[10.0, 10.0, 80.0], gross_throughput_kwh=[2.0, 3.0, 8.0], duration_s=[1.0] * 3))
b = C.metric_block(m, METRICS_fn := C.METRICS["grossKwhPer100km"][1], "c")
assert b["value"] == round(13.0 / 100.0 * 100.0, 4) and b["nDays"] == 3
assert b["lodo"]["min"] == round(10 / 90 * 100, 4) and b["lodo"]["minLeftOutDate"] == "d2"          # leaving out d2: (2 + 8) / 90 x 100
assert b["lodo"]["max"] == 25.0 and b["lodo"]["maxLeftOutDate"] == "d3"                              # leaving out d3: (2 + 3) / 20 x 100
assert b["lodo"]["nDaysLeftOut"] == 3
assert b["withoutLargestDrive"]["value"] == 25.0 and abs(b["lodo"]["relativeRange"] - (b["lodo"]["max"] - b["lodo"]["min"]) / b["value"]) < 1e-4
one = C.metric_block(m[m["date"] == "d1"], METRICS_fn, "a")
assert one["lodo"] is None            # one day: nothing to leave out

# (3) live block vs the CSVs
dm = pd.read_csv("drive_master.csv", low_memory=False); sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False); fuel = pd.read_csv("fuel_recon_master.csv", low_memory=False)
A = json.load(open("summary_arrays.json", encoding="utf-8")); live = A["cohortSupport"]
assert live == C.build(dm, sdm, fuel), "the committed block must equal a fresh build"
cold = sdm.loc[sdm["thermal_regime_raw"] == "cold", ["file"]].merge(dm[["file", "distance_km"]], on="file")
assert live["assigned"]["cold"]["nDrives"] == len(cold) and abs(live["assigned"]["cold"]["km"] - cold["distance_km"].sum()) < 0.06
assert abs(live["assigned"]["cold"]["largestDrive"]["share"] - cold["distance_km"].max() / cold["distance_km"].sum()) < 1e-4
n_diff = int((sdm["thermal_regime_raw"] != sdm["thermal_regime_physical"]).sum())
assert len(live["reassigned"]) == n_diff == 1 and live["reassigned"][0]["override"] == "cold->shoulder"
assert sum(live["assigned"][c]["nDrives"] for c in ("warm", "shoulder", "cold")) == live["assigned"]["all"]["nDrives"] == len(dm)
assert sum(live["physicalSensitivity"][c]["nDrives"] for c in ("warm", "shoulder", "cold")) == len(dm)

# (4) splice
md5 = "x"
new, ch, bad = C.splice(A, live, md5)
assert not bad and set(ch) <= {"/_artifactStamps/cohortSupport"} | {c for c in ch if c.startswith("/_artifactStamps/cohortSupport")}
B = copy.deepcopy(A); B["cohortSupport"]["methodVersion"] = 99
new2, ch2, bad2 = C.splice(B, live, md5)
assert not bad2 and any(c.startswith("/cohortSupport") for c in ch2)
print("OK test_cohort_support (cold %d drives, %d days, largest share %.4f)" % (live["assigned"]["cold"]["nDrives"], live["assigned"]["cold"]["nDays"], live["assigned"]["cold"]["largestDrive"]["share"]))
