"""M401 (audit D4): odometer continuity rules and the recorded-anomaly ledger (known answers on synthetic masters, then the real master)."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import odometer_check as OC


def mk(rows):
    return pd.DataFrame([dict(file=f"d{i}.csv", date="2026-08-%02d" % (1 + i // 3), time_start="%02d:00:00.0" % (8 + i % 3), odo_start=a, odo_end=b)
                         for i, (a, b) in enumerate(rows)])


# clean chain with an unlogged gap of 39 km (legitimate): no anomaly
assert OC.continuity_anomalies(mk([(100.0, 110.0), (110.0, 120.0), (159.0, 170.0)])) == []
# R1: odometer decreases inside a drive
a = OC.continuity_anomalies(mk([(100.0, 110.0), (110.0, 108.0)]))
assert [(x["file"], x["rules"]) for x in a] == [("d1.csv", ["R1"])], a
# R2: backward step between drives (a stale repeated start reading)
a = OC.continuity_anomalies(mk([(100.0, 110.0), (110.0, 120.0), (110.0, 111.0)]))
assert [(x["file"], x["rules"]) for x in a] == [("d2.csv", ["R2"])], a
# R3/R2 reset to 0 and R4 forward jump after the reset, with the second reset drive continuing from the first (63.8 -> 172.2)
a = OC.continuity_anomalies(mk([(6600.0, 6700.0), (6700.0, 6736.0), (0.0, 63.8), (63.8, 172.2), (6736.0, 6739.3)]))
got = {x["file"]: x["rules"] for x in a}
assert got == {"d2.csv": ["R2", "R3"], "d3.csv": ["R3"], "d4.csv": ["R4"]}, got
# ledger check: unrecorded anomaly fails, recorded passes, stale entry is reported
ok, msg = OC.check(mk([(100.0, 110.0), (110.0, 108.0)]), {"anomalies": []})
assert not ok and "unrecorded" in msg and "d1.csv" in msg
ok, msg = OC.check(mk([(100.0, 110.0), (110.0, 108.0)]), {"anomalies": [{"file": "d1.csv", "rules": ["R1"], "reason": "x"}]})
assert ok, msg
ok, msg = OC.check(mk([(100.0, 110.0), (110.0, 108.0)]), {"anomalies": [{"file": "d1.csv", "rules": ["R2"], "reason": "x"}]})
assert not ok and "rules differ" in msg
ok, msg = OC.check(mk([(100.0, 110.0)]), {"anomalies": [{"file": "gone.csv", "rules": ["R1"], "reason": "x"}]})
assert ok and "stale" in msg
# real master vs the recorded ledger
dm = pd.read_csv("drive_master.csv", low_memory=False)
ledger = json.load(open("odometer_anomalies.json", encoding="utf-8"))
ok, msg = OC.check(dm, ledger)
assert ok, msg
assert all(e.get("reason") for e in ledger["anomalies"])
print("OK test_odometer_check")
