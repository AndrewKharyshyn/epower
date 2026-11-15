"""M672 (N-05, spec analyses/M672_spec.md Rev 1.1): known-answer test of tools/n05_between_drive_logging on a constructed master with planted odometer steps.
Run: python tests/synthetic/test_m672_between_drive_logging.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import pandas as pd
import n05_between_drive_logging as N
import odometer_check as OC

# (file, date, time_start, odo_start, odo_end, distance_km)
rows = [
    ("a01", "2026-05-30", "08:00:00", 1000.0, 1010.0, 10.0),
    ("a02", "2026-05-30", "09:00:00", 1010.0, 1020.0, 10.0),      # zero step
    ("a03", "2026-05-31", "08:00:00", 1020.04, 1030.0, 9.96),     # +0.04: inside the zero tolerance
    ("a04", "2026-05-31", "09:00:00", 1030.3, 1040.0, 9.7),       # +0.3: gap under 1 km (planted 0.3)
    ("a05", "2026-06-01", "08:00:00", 1043.2, 1050.0, 6.8),       # +3.2 cross-month gap (belongs to June)
    ("a06", "2026-06-01", "09:00:00", 1049.7, 1060.0, 10.3),      # -0.3: small backward, not R2, not summed
    ("a07", "2026-06-02", "08:00:00", 1060.05, 1070.0, 9.95),     # +0.05 exactly: zero (inclusive)
    ("a08", "2026-06-02", "09:00:00", 1220.0, 1230.0, 10.0),      # +150 gap
    ("a09", "2026-06-03", "08:00:00", 1430.0, 1440.0, 10.0),      # +200 exactly: gap (inclusive)
    ("a10", "2026-06-03", "09:00:00", 1640.1, 1650.0, 9.9),       # +200.1: large gap, kept out
    ("a11", "2026-06-04", "08:00:00", 1650.0, 1649.0, -1.0),      # R1 drive (odo_end < odo_start)
    ("a12", "2026-06-04", "09:00:00", 1649.0, 1659.0, 10.0),      # step next to the R1 drive
    ("a13", "2026-06-04", "09:00:00", 1659.0, 1669.0, 10.0),      # (date, time_start) tie with a12: row order decides
    ("a14", "2026-06-05", "08:00:00", 1669.0, 1679.0, 10.0),
    ("a15", "2026-06-05", "09:00:00", 5.0, 15.0, 10.0),           # reset regime: R2 + R3
    ("a16", "2026-06-05", "10:00:00", 15.0, 25.0, 10.0),          # continues the restarted scale (R3)
    ("a17", "2026-06-06", "08:00:00", 1679.0, 1689.0, 10.0),      # back on the old scale: R4 is not triggered (jump < 500 from 25? 1654 > 500: yes R4)
]
dm = pd.DataFrame(rows, columns=["file", "date", "time_start", "odo_start", "odo_end", "distance_km"])
found = OC.continuity_anomalies(dm)
ledger = {"anomalies": [{"file": x["file"], "rules": x["rules"]} for x in found]}
B = N.build(dm, ledger, "testmd5")
M = {r["month"]: r for r in B["months"]}
may, jun = M["2026-05"], M["2026-06"]
# May: a02 zero, a03 zero (+0.04 inside the tolerance), a04 gap under 1 km (0.3)
assert may["nDrives"] == 4 and may["nZeroSteps"] == 2 and may["gapUnder1km"]["n"] == 1 and abs(may["gapUnder1km"]["km"] - 0.3) < 1e-9 and may["gap1to200km"]["n"] == 0, may
assert may["nDrivingDays"] == 2 and may["labels"] == ["thin month (fewer than 5 driving days)", "partial month"], may["labels"]
# June: the cross-month gap (+3.2) belongs to June (month of the next drive); 150 and exactly 200 are gaps (inclusive); 200.1 is a large gap kept out of the sum
assert jun["gap1to200km"]["n"] == 3 and abs(jun["gap1to200km"]["km"] - 353.2) < 1e-6 and jun["gapUnder1km"]["n"] == 0 and abs(jun["unloggedGapKm"] - 353.2) < 1e-6, jun
assert jun["nLargeGapSteps"] == 1 and B["largeGapSteps"][0]["file"] == "a10"
assert jun["nSmallBackwardSteps"] == 1 and jun["nZeroSteps"] == 3, jun          # -0.3 is not R2 and not summed; +0.05 is zero (inclusive); the a12/a13 tie keeps row order
assert jun["nR1AdjacentSteps"] == 2 and [x["file"] for x in B["r1AdjacentSteps"]] == ["a11", "a12"]
assert jun["nAnomalySteps"] == 3 and jun["anomalyRules"] == ["R2", "R3", "R4"] and [x["file"] for x in B["anomalySteps"]] == ["a15", "a16", "a17"]
jd = dm[dm["date"].str.startswith("2026-06")]
nonr1 = jd[jd["file"] != "a11"]
assert abs(jun["loggedKm"] - jd["distance_km"].sum()) < 1e-6 and abs(jun["odometerAdvanceKm"] - (nonr1["odo_end"] - nonr1["odo_start"]).sum()) < 1e-6
assert abs(jun["shareDistanceBasis"] - jun["loggedKm"] / (jun["loggedKm"] + 353.2)) < 1e-6 and abs(jun["shareOdometerBasis"] - jun["odometerAdvanceKm"] / (jun["odometerAdvanceKm"] + 353.2)) < 1e-6
assert jun["nDrivingDays"] == 6 and jun["labels"] == ["partial month"]
# step accounting and validity rules all pass; reset-regime bridge is reported once and unsummed
assert all(B["validity"].values()) and B["window"]["nGapSteps"] == 4
assert len(B["bridgedAcrossResetRegime"]) == 1 and B["bridgedAcrossResetRegime"][0]["file"] == "a17"
assert B["window"]["odometerResolutionKm"] == 0.01 or B["window"]["odometerResolutionKm"] > 0
# V4: a ledger that misses an anomaly stops the build; an R1-only entry is not part of the R2/R3/R4 comparison
bad = {"anomalies": [e for e in ledger["anomalies"] if e["file"] != "a17"]}
try:
    N.build(dm, bad, "x"); raise SystemExit("FAIL: V4 did not stop the build")
except AssertionError:
    pass
only_r1 = {"anomalies": ledger["anomalies"] + [{"file": "a11", "rules": ["R1"]}]}
N.build(dm, only_r1, "x")
# determinism
assert json.dumps(N.build(dm, ledger, "testmd5"), sort_keys=True) == json.dumps(B, sort_keys=True)
# stage wiring
ids = [s["id"] for s in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
assert ids.index("seasonal_fits") < ids.index("between_drive_logging") < ids.index("stamp_basis")
print("PASS test_m672_between_drive_logging")
