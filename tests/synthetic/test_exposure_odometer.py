"""M713b known-answer tests for tools/exposure_odometer.py (spec analyses/M712_spec.md Rev 1.1 section 4): the logged share of the dash odometer by interval, the UNLOGGED interval rule (share < 0.5: its empty
days are unlogged, never zero-drive days), true zero-drive days, days without odometer cover, the summer / later factors, and the reading sidecar (extend from the config, conflicting reading stops)."""
import json, os, sys, tempfile
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import exposure_odometer as EO

# frame: logged km per day. Readings: 100 km between 07-01 and 07-05 (logged 90), then 200 km between 07-05 and 07-10 with only 20 km logged (share 0.1 -> unlogged interval),
# then 50 km between 07-10 and 07-12 (logged 45).
days = {"2026-06-29": 5.0, "2026-07-02": 40.0, "2026-07-04": 50.0, "2026-07-06": 12.0, "2026-07-09": 8.0, "2026-07-11": 45.0, "2026-07-12": 0.0}
D = pd.DataFrame({"key": ["k%d" % i for i in range(len(days))], "day": list(days), "km": list(days.values())})
readings = [{"asOf": "2026-07-01", "km": 1000}, {"asOf": "2026-07-05", "km": 1100}, {"asOf": "2026-07-10", "km": 1300}, {"asOf": "2026-07-12", "km": 1350}]
o = EO.check(D, readings, summer_end="2026-07-05", first_day="2026-06-28", last_day="2026-07-13")
rows = {(r["from"], r["to"]): r for r in o["rows"]}
assert rows[("2026-07-01", "2026-07-05")]["loggedKm"] == 90.0 and rows[("2026-07-01", "2026-07-05")]["share"] == 0.9
assert rows[("2026-07-05", "2026-07-10")]["loggedKm"] == 20.0 and rows[("2026-07-05", "2026-07-10")]["share"] == 0.1 and rows[("2026-07-05", "2026-07-10")]["unloggedKm"] == 180.0
assert rows[("2026-07-10", "2026-07-12")]["loggedKm"] == 45.0
assert o["unloggedIntervals"] == [["2026-07-05", "2026-07-10"]]
assert o["unloggedDays"] == ["2026-07-07", "2026-07-08", "2026-07-10"], "empty days of the low-share interval (from, to]"
assert o["zeroDriveDays"] == ["2026-07-03", "2026-07-05"], o["zeroDriveDays"]          # empty day inside a normal interval: a true zero-drive day
assert o["noOdometerCoverDays"] == ["2026-06-28", "2026-06-30", "2026-07-01", "2026-07-13"], o["noOdometerCoverDays"]
assert o["factors"]["f_s_summerWindow"] == round(100 / 90, 4) and o["factors"]["f_a_laterIntervalsWithoutUnlogged"] == round(50 / 45, 4), o["factors"]
assert o["total"]["odoKm"] == 350 and abs(o["total"]["share"] - round(155 / 350, 3)) < 1e-9

# sidecar: extend from the config, idempotent, a conflicting reading for the same date stops
with tempfile.TemporaryDirectory() as td:
    rp = os.path.join(td, "odometer_readings.json")
    json.dump({"readings": [{"asOf": "2026-07-01", "km": 1000, "source": "t"}]}, open(rp, "w", encoding="utf-8"))
    cp = os.path.join(td, "summary_config.json")
    json.dump({"vehicle": {"odometerKm": 1100, "odometerAsOf": "2026-07-05"}}, open(cp, "w", encoding="utf-8"))
    assert EO.extend_from_config(rp, cp) == 1 and EO.extend_from_config(rp, cp) == 0
    assert [x["km"] for x in EO.load_readings(rp)] == [1000, 1100]
    json.dump({"vehicle": {"odometerKm": 1111, "odometerAsOf": "2026-07-05"}}, open(cp, "w", encoding="utf-8"))
    try:
        EO.extend_from_config(rp, cp)
        raise AssertionError("conflicting reading must stop")
    except RuntimeError as ex:
        assert "differs" in str(ex)
print("test_exposure_odometer: ok")
