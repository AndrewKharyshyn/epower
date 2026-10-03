"""M361 known-answer tests: tools/intake_air_block (availability block from the master) and the -100 degC sentinel on the Records native-sample path (battery_temp_extremes.raw_pass)."""
import os, sys, tempfile, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools")); os.chdir(ROOT)
import numpy as np, pandas as pd
from intake_air_block import intake_air_block
import battery_temp_extremes as B
fails = 0
def ok(l, c, e=""):
    global fails
    print(("PASS " if c else "FAIL ") + l + ((" - " + str(e)) if (not c and e) else "")); fails += 0 if c else 1
nan = np.nan
dm = pd.DataFrame({"file": list("abcdefgh"), "date": ["2026-08-01", "2026-08-01", "2026-08-02", "2026-08-23", "2026-08-24", "2026-08-24", "2026-08-25", "2026-08-26"],
                   "time_start": ["08:00", "12:00", "09:00", "09:00", "08:18", "10:46", "09:00", "09:00"],
                   "T_intake": [20.0, nan, 18.0, 17.0, 17.3, nan, nan, nan]})
sdm = pd.DataFrame({"file": list("abcdefgh"), "date": dm["date"], "thermal_regime_raw": ["warm"] * 5 + ["shoulder", "shoulder", "cold"],
                    "ambient_time_mean_c": [25, 24, 22, 20, 19, 8, 7, 5.0], "batt_intake_time_mean_c": [20.0, nan, 18.0, 17.0, 17.3, nan, nan, nan]})
b = intake_air_block(dm, sdm)
ok("status unavailable and last valid drive/date (drive e, 2026-08-24)", b["status"] == "unavailable" and b["lastValidDrive"] == "e" and b["lastValidDate"] == "2026-08-24")
ok("counts: 8 drives, 4 valid, 4 without a value, 3 after the last valid drive on 3 days", (b["nDrives"], b["nDrivesValid"], b["nDrivesNoValue"], b["nDrivesAfterLastValid"], b["nDaysAfterLastValid"]) == (8, 4, 4, 3, 3), b)
ok("one earlier drive (b) also has no value: no-value minus after-last-valid == 1", b["nDrivesNoValue"] - b["nDrivesAfterLastValid"] == 1)
ok("first drive without a value after the last valid drive is f", b["firstDriveWithoutValue"] == "f")
ok("per-cohort counts (warm 5/4, shoulder 2/0, cold 1/0)", b["byCohort"] == {"cold": {"nDrives": 1, "nDrivesValid": 0}, "shoulder": {"nDrives": 2, "nDrivesValid": 0}, "warm": {"nDrives": 5, "nDrivesValid": 4}}, b["byCohort"])
ok("coldest ten by ambient: 8 drives, 3 after the last valid drive in drive order (f is on the same date as the last valid drive but after it)", b["coldestTenByAmbient"] == {"n": 8, "nAfterLastValidDrive": 3}, b["coldestTenByAmbient"])
ok("deterministic: two runs give identical blocks", json.dumps(intake_air_block(dm, sdm), sort_keys=True) == json.dumps(b, sort_keys=True))
dm2 = dm.copy(); dm2.loc[7, "T_intake"] = 15.0
ok("status available when the newest drive has a value", intake_air_block(dm2)["status"] == "available")
# -100 sentinel on the Records native-sample path: floor -40 excludes it, a valid sample is kept
col = "[BMS] HV Battery Intake Air Temperature (\u2103)"
with tempfile.TemporaryDirectory() as td:
    pd.DataFrame({col: [-100.0] * 5 + [12.5, 14.0]}).to_csv(os.path.join(td, "x.csv"), index=False)
    pd.DataFrame({col: [-100.0] * 7}).to_csv(os.path.join(td, "y.csv"), index=False)
    r = B.raw_pass(pd.DataFrame({"file": ["x.csv", "y.csv"]}), td).set_index("file")
ok("sentinel excluded from intake_min / intake_max (x keeps the valid samples only)", r.loc["x.csv", "intake_min"] == 12.5 and r.loc["x.csv", "intake_max"] == 14.0)
ok("all-sentinel drive gives NaN, never -100", np.isnan(r.loc["y.csv", "intake_min"]) and np.isnan(r.loc["y.csv", "intake_max"]))
print("FAILS:", fails); sys.exit(1 if fails else 0)
