"""M780 known-answer test (spec analyses/M780_spec.md Rev 2): the ambient axis of `batteryTempRanges` uses 5 C bins [a, a+5) over the whole observed range, floor-safe extrema, nDays,
regime tags from the seasonal_core thresholds; the refresh tool's consistency gates catch a changed non-ambient row and a changed ambient total."""
import os, sys
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
import compute_summary_arrays as C
import battery_temp_ranges_refresh as R

# synthetic corpus: drive k has ambient pair [a, a], Sensor-1 min / peak, a calendar day
spec = [  # file, ambient, t1_min, t1_peak, date
    ("f1", -5.0, -4, 10, "2026-12-01"),     # exactly -5.0 -> bin -5 (lower edge closed)
    ("f2", -0.5, -3, 8, "2026-12-01"),      # -0.5 -> bin -5
    ("f3", 0.0, -1, 12, "2026-12-02"),      # 0.0 -> bin 0
    ("f4", 4.5, 0, 14, "2026-12-03"),       # 4.5 -> bin 0
    ("f5", 5.0, 2, 20, "2026-12-03"),       # exactly 5.0 -> bin 5 (Cold cohort but this row)
    ("f6", 14.5, 12, 30, "2026-12-04"),     # -> bin 10
    ("f7", 15.0, 14, 32, "2026-12-05"),     # exactly 15.0 -> bin 15 (Warm)
    ("f8", 15.0, 15, 36, "2026-12-05"),     # same day as f7
    ("f9", 31.0, 20, 45, "2026-12-06"),     # -> bin 30, no catch-all at 26
]
dm = pd.DataFrame({"file": [x[0] for x in spec], "date": [x[4] for x in spec], "drive_type": ["urban"] * len(spec), "duration_s": [600] * len(spec)})
traj = {x[0]: {"t1_min": x[2], "t1_peak": x[3]} for x in spec}
ambient = {x[0]: [x[1], x[1]] for x in spec}
rows = C._battery_temp_ranges(dm, traj, ambient)
amb = [r for r in rows if r["group"] == "ambient"]
by = {r["ambLoC"]: r for r in amb}
assert [r["ambLoC"] for r in amb] == sorted(by), "coldest row first"
assert set(by) == {-5, 0, 5, 10, 15, 30}, set(by)        # bins with no drive (20, 25) are omitted, no catch-all row
assert [r["label"] for r in amb] == ["-5 to <0 C", "0 to <5 C", "5 to <10 C", "10 to <15 C", "15 to <20 C", "30 to <35 C"], [r["label"] for r in amb]
assert by[-5]["n"] == 2 and by[-5]["nDays"] == 1 and by[-5]["lo"] == -4 and by[-5]["hi"] == 10     # negative extremum kept, exact edge -5.0 in the -5 row
assert by[0]["n"] == 2 and by[0]["nDays"] == 2                                                  # 0.0 and 4.5; 5.0 is NOT in this row
assert by[5]["n"] == 1 and by[5]["regime"] == "shoulder" and by[5]["lo"] == 2                   # exact 5.0 sits in the 5 to <10 row
assert by[15]["n"] == 2 and by[15]["nDays"] == 1 and by[15]["regime"] == "warm"                 # exact 15.0 in the warm row; two drives on one day
assert by[-5]["regime"] == "cold" and by[0]["regime"] == "cold" and by[10]["regime"] == "shoulder" and by[30]["regime"] == "warm"
assert by[30]["n"] == 1 and by[30]["lo"] == 20 and by[30]["hi"] == 45
assert sum(r["n"] for r in amb) == len(spec)
assert all(r["ambHiC"] == r["ambLoC"] + 5 for r in amb)
# floor semantics below zero (defensive): a fractional negative minimum is floored, not truncated toward zero
traj2 = {"f1": {"t1_min": -2.7, "t1_peak": 10.9}}
r2 = C._battery_temp_ranges(dm.iloc[:1], traj2, {"f1": [-5.0, -5.0]})
a2 = [r for r in r2 if r["group"] == "ambient"][0]
assert a2["lo"] == -3 and a2["hi"] == 10, a2
# class and duration rows exist and carry no ambient fields (published rows unchanged)
assert all("ambLoC" not in r and "nDays" not in r for r in rows if r["group"] != "ambient")

# the refresh tool's consistency gates
old = [{"group": "ambient", "label": "Cool ambient (<20 C)", "n": 5, "lo": -4, "hi": 36, "ambHiC": None},
       {"group": "ambient", "label": "Hot ambient (>=26 C)", "n": 1, "lo": 20, "hi": 45},
       {"group": "class", "label": "Urban", "n": 9, "lo": -4, "hi": 45}]
new = [{"group": "ambient", "label": "-5 to <0 C", "n": 2, "lo": -4, "hi": 10, "ambHiC": 0},
       {"group": "ambient", "label": "0 to <5 C", "n": 2, "lo": -1, "hi": 14, "ambHiC": 5},
       {"group": "ambient", "label": "15 to <20 C", "n": 1, "lo": 14, "hi": 36, "ambHiC": 20},
       {"group": "ambient", "label": "30 to <35 C", "n": 1, "lo": 20, "hi": 45, "ambHiC": 35},
       {"group": "class", "label": "Urban", "n": 9, "lo": -4, "hi": 45}]
assert R.consistency(old, new) == [], R.consistency(old, new)
bad = [dict(x) for x in new]
bad[-1]["hi"] = 44
assert any("non-ambient" in f for f in R.consistency(old, bad))
bad2 = [dict(x) for x in new]
bad2[0]["n"] = 3
assert any("ambient total" in f for f in R.consistency(old, bad2))
print("PASS test_battery_temp_ranges")
