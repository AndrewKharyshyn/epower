"""M339 known-answer tests for tools/fuel_analytics2.py (spec analyses/M339_spec.md rev 3): state partition on a scripted stop, unknown speed, dwell and threshold
reclassification, dt cap, left-censoring, no zero-filled continuation, gap/unknown-speed censoring, initial-temperature staleness, charging sign convention."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import numpy as np, pandas as pd
import fuel_analytics2 as f2
import fuel_analytics as fa
import recon_engine as RE

fails = 0
def ok(label, c, extra=""):
    global fails
    print(("PASS " if c else "FAIL ") + label + ((" - " + str(extra)) if (not c and extra) else ""))
    fails += 0 if c else 1

def trip(n=300, flow=3.6, speed=50.0, stop=None, unk=None, rpm_start=0, coolant=20.0, gap_at=None):
    t = np.arange(n, dtype=float)
    raw_dt = np.ones(n); raw_dt[0] = 0.0
    if gap_at is not None:
        raw_dt[gap_at] = 8.0
        t = np.cumsum(raw_dt)
    spd = np.full(n, speed)
    if stop:
        spd[stop[0]:stop[1]] = 0.0
    if unk:
        spd[unk[0]:unk[1]] = np.nan
    g = pd.DataFrame({"flow": np.full(n, flow), "rpm": np.where(np.arange(n) >= rpm_start, 1500.0, 0.0), "spd": spd, "tsec": t,
                      "coolant": np.full(n, coolant), "oil": np.full(n, np.nan)})
    return g, raw_dt

# 1 mL/s (3.6 L/h): a scripted 30 s stop -> stationary litres = 30 mL; partition = total
g, dt = trip(stop=(100, 130))
r = f2.litres_by_state(g.flow.values, dt, g.spd.values, 5.0, 1.0)
ok("known answer: 30 s stop at 1 mL/s -> stationary 0.030 L", abs(r["stationary"] - 0.030) < 1e-9, r)
ok("partition: stationary + moving + unknown = total", abs(r["stationary"] + r["moving"] + r["unknown"] - r["total"]) < 1e-12)
ok("total = 299 s x 1 mL/s (first interval has dt 0)", abs(r["total"] - 0.299) < 1e-9, r["total"])
# unknown speed
g, dt = trip(unk=(50, 60))
r = f2.litres_by_state(g.flow.values, dt, g.spd.values, 5.0, 1.0)
ok("unknown speed: 10 samples -> unknown 0.010 L, visible", abs(r["unknown"] - 0.010) < 1e-9, r)
# threshold boundary (<= threshold is stationary): speed 1.0 stationary at thr 1.0, moving at thr 0.5
g, dt = trip(speed=1.0)
ok("speed == 1.0 km/h is stationary at thr 1.0", f2.litres_by_state(g.flow.values, dt, g.spd.values, 5.0, 1.0)["stationary"] > 0.29)
ok("speed == 1.0 km/h is moving at thr 0.5", f2.litres_by_state(g.flow.values, dt, g.spd.values, 5.0, 0.5)["stationary"] == 0.0)
# dwell: a 3 s pause is reclassified as moving; a 30 s stop stays stationary
g, dt = trip(stop=(100, 103))
ok("dwell: a 3 s pause is moving when the 5 s dwell rule is on", f2.litres_by_state(g.flow.values, dt, g.spd.values, 5.0, 1.0, True)["stationary"] == 0.0 and
   abs(f2.litres_by_state(g.flow.values, dt, g.spd.values, 5.0, 1.0, False)["stationary"] - 0.003) < 1e-9)
g, dt = trip(stop=(100, 130))
ok("dwell: a 30 s stop stays stationary with the dwell rule", abs(f2.litres_by_state(g.flow.values, dt, g.spd.values, 5.0, 1.0, True)["stationary"] - 0.030) < 1e-9)
# dt cap: an 8 s gap is capped at 5 s (3 s lost)
g, dt = trip(gap_at=150)
r5 = f2.litres_by_state(g.flow.values, dt, g.spd.values, 5.0, 1.0); r10 = f2.litres_by_state(g.flow.values, dt, g.spd.values, 10.0, 1.0)
ok("dt cap: litres differ by the capped 3 s (3 mL) between cap 5 and cap 10", abs((r10["total"] - r5["total"]) - 0.003) < 1e-9, (r5, r10))

# FUEL-02 curves
g, dt = trip(n=300, speed=36.0, rpm_start=5)          # 0.01 km/s
c = f2.curves_for_trip(g, dt)
ok("alignment: t0 is the first rpm > 400 sample (index 5), not left-censored", c["i0"] == 5 and c["leftCensored"] is False)
ok("time curve: cumulative litres at 30 s = 30 mL", abs(c["timeCum"][0] - 0.030) < 1e-9, c["timeCum"][0])
ok("distance curve: 0.25 km at 25 s -> 25 mL cumulative", abs(c["distCumTotal"][0] - 0.025) < 1e-9, c["distCumTotal"][0])
g, dt = trip(n=300, speed=36.0, rpm_start=0)
ok("left-censoring: engine already on at the first sample is flagged", f2.curves_for_trip(g, dt)["leftCensored"] is True)
g, dt = trip(n=100, speed=36.0, rpm_start=5)           # 94 s after t0
c = f2.curves_for_trip(g, dt)
ok("no zero-filled continuation: grid positions beyond the trip end are NaN", np.isfinite(c["timeCum"][2]) and np.isnan(c["timeCum"][3]) and c["endReasonTime"] == "tripEnd", c["timeCum"][:5])
g, dt = trip(n=300, speed=36.0, rpm_start=5, gap_at=80)
c = f2.curves_for_trip(g, dt)
ok("gap above 5 s ends the contribution (reason 'gap'), later grid positions are NaN", c["endReasonTime"] == "gap" and np.isnan(c["timeCum"][4]) and np.isfinite(c["timeCum"][1]), (c["endReasonTime"], c["timeCum"][:5]))
g, dt = trip(n=300, speed=36.0, rpm_start=5, unk=(120, 130))
c = f2.curves_for_trip(g, dt)
ok("unknown speed ends the distance-axis contribution only", c["endReasonDist"] == "unknownSpeed" and np.isfinite(c["timeCum"][8]) and np.isnan(c["distCumTotal"][19]))
# initial temperature staleness: only coolant sample is > 120 s before t0 -> no initial temperature
g, dt = trip(n=400, speed=36.0, rpm_start=250)
g["coolant"] = np.nan; g.loc[0, "coolant"] = 25.0
c = f2.curves_for_trip(g, dt)
ok("stale initial coolant (> 120 s before t0) is not used", c["tempSource"] is None, c["tempSource"])
g, dt = trip(n=400, speed=36.0, rpm_start=100)
g["coolant"] = np.nan; g.loc[10, "coolant"] = 25.0
c = f2.curves_for_trip(g, dt)
ok("fresh initial coolant (< 120 s before t0) is used and flagged 'coolant'", c["tempSource"] == "coolant" and abs(c["tempC"] - 25.0) < 1e-9)
g, dt = trip(n=400, speed=36.0, rpm_start=100)
g["coolant"] = np.nan; g["oil"] = np.nan; g.loc[20, "oil"] = 30.0
ok("oil fallback is a separate source label", f2.curves_for_trip(g, dt)["tempSource"] == "oil-fallback")

# charging sign convention (open item M258+): raw BMS current is charge-positive, discharge-positive Pbatt = V*(-I - offset)/1000
with tempfile.TemporaryDirectory() as d:
    n = 60
    df = pd.DataFrame({"time": [(pd.Timestamp("2026-08-10 10:00:00") + pd.Timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S") for i in range(n)],
                       RE.CH["flow"]: np.full(n, 3.6), RE.CH["V"]: np.full(n, 350.0), RE.CH["I"]: np.full(n, 10.0)})
    p = os.path.join(d, "x.csv"); df.to_csv(p, index=False)
    RE.BASE = d + os.sep
    gl = RE.load_drive("x.csv", 0.0)
    ok("sign convention: raw charge-positive +10 A at 350 V -> Pbatt = -3.5 kW (charging)", abs(gl["Pbatt"].iloc[10] + 3.5) < 1e-9, gl["Pbatt"].iloc[10])
    gl2 = RE.load_drive("x.csv", 2.0)
    ok("applied offset is in the discharge-positive frame: -I - offset", abs(gl2["Pbatt"].iloc[10] - 350.0 * (-10.0 - 2.0) / 1000.0) < 1e-9)

print("FUEL ANALYTICS 2 TESTS: " + ("all passed" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
