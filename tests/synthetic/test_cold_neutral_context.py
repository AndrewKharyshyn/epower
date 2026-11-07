"""M605 known-answer tests (analyses/M605_spec.md Rev 1 section 5) for tools/cold_neutral_context.py. Written before the tool."""
import os, sys
import numpy as np
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import cold_neutral_context as N

BASE = N.BASE


def frame(n, **over):
    """n-second grid at 1 s steps; defaults meet every base condition (discharge-positive I = 0 A)."""
    d = dict(rpm=900.0, soc=70.0, fuel=2.0, I=0.0, speed=0.0, load=10.0)
    d.update(over)
    g = pd.DataFrame({k: np.full(n, v, dtype=float) for k, v in d.items()})
    g.index = pd.date_range("2026-01-01 10:00:00", periods=n, freq="1s")
    cool = np.full(n, 40.0); age = np.zeros(n)
    return g, cool, age


def runs_of(g, cool, age, p=None, minlen=10):
    q = N.qualify(g, cool, age, dict(BASE, **(p or {})))
    return N.find_runs(q, minlen)


# 1. a 12 s run -> one interval of 12 s; 9 s -> fragment only; two 6 s runs split by one failing second -> two fragments
g, c, a = frame(12)
iv, fr = runs_of(g, c, a)
assert iv == [(0, 12)] and fr == [], (iv, fr)
g, c, a = frame(9)
iv, fr = runs_of(g, c, a)
assert iv == [] and fr == [(0, 9)], (iv, fr)
g, c, a = frame(13)
g.iloc[6, g.columns.get_loc("soc")] = 10.0
iv, fr = runs_of(g, c, a)
assert iv == [] and fr == [(0, 6), (7, 6)], (iv, fr)
# a NaN second also breaks a run (no bridging)
g, c, a = frame(13)
g.iloc[6, g.columns.get_loc("rpm")] = np.nan
iv, fr = runs_of(g, c, a)
assert iv == [] and fr == [(0, 6), (7, 6)], (iv, fr)

# 2. threshold edges: each condition inclusive at its edge, excluded just beyond
def one(col, v, cool=None, I=None):
    g, c, a = frame(1, **{col: v})
    if cool is not None:
        c = np.array([cool])
    return bool(N.qualify(g, c, a, dict(BASE))[0])

assert one("soc", 68.0) and not one("soc", 67.9)
assert one("rpm", 40.0, cool=60.0) is False                       # rpm far below
assert one("soc", 70.0, cool=60.0) and not one("soc", 70.0, cool=60.1)
assert one("rpm", 500.0) and not one("rpm", 499.0)
assert one("fuel", 1.5) and not one("fuel", 1.49)
assert one("I", 3.0) and one("I", -3.0) and not one("I", 3.1) and not one("I", -3.1)
assert one("I", 0.0)

# 3. NaN or stale coolant, or missing fuel rate, never qualifies
g, c, a = frame(1)
assert not N.qualify(g, np.array([np.nan]), a, dict(BASE))[0]
assert not N.qualify(g, c, np.array([30.1]), dict(BASE))[0] and N.qualify(g, c, np.array([30.0]), dict(BASE))[0]
assert not one("fuel", np.nan) and not one("soc", np.nan) and not one("I", np.nan) and not one("rpm", np.nan)

# 3b. strict rpm rule: rpm > 400 strict excludes 400 and includes 400.1; base rule rpm >= 500 includes 500
gg, c, a = frame(1, rpm=400.0)
assert not N.qualify(gg, c, a, dict(BASE, rpm_min=400.0, rpm_strict=True))[0]
gg, c, a = frame(1, rpm=400.1)
assert N.qualify(gg, c, a, dict(BASE, rpm_min=400.0, rpm_strict=True))[0]
gg, c, a = frame(1, rpm=500.0)
assert not N.qualify(gg, c, a, dict(BASE, rpm_min=500.0, rpm_strict=True))[0] and N.qualify(gg, c, a, dict(BASE))[0]

# 3c. drop-filled sensitivity: a second without a real rpm / fuel / current sample does not qualify
g, c, a = frame(3)
real = pd.DataFrame({k: np.ones(3, bool) for k in ("rpm", "fuel", "I", "soc")}, index=g.index)
real.iloc[1, real.columns.get_loc("fuel")] = False
q_all = N.qualify(g, c, a, dict(BASE), real=real)
q_real = N.qualify(g, c, a, dict(BASE, need_real=True), real=real)
assert list(q_all) == [True, True, True] and list(q_real) == [True, False, True], (q_all, q_real)

# 4. bands (edges) and sign sub-field
assert list(N.band_speed(np.array([0, 4.99, 5, 29.99, 30, np.nan]))) == ["standing", "standing", "low", "low", "moving", "unknown"]
assert list(N.band_load(np.array([0, 7.99, 8, 29.99, 30, np.nan]))) == ["<8", "<8", "8-30", "8-30", ">=30", "unknown"]
assert list(N.band_rpm(np.array([500, 999, 1000, 1999, 2000]))) == ["500-1000", "500-1000", "1000-2000", "1000-2000", ">=2000"]
assert list(N.band_cool(np.array([40.0, 40.1, 60.0]))) == ["<=40", "40-60", "40-60"]
assert list(N.band_fuel(np.array([1.5, 2.99, 3.0]))) == ["1.5-3", "1.5-3", ">=3"]
assert list(N.band_since(np.array([0, 299, 300, 900]))) == ["<300", "<300", ">=300", ">=300"]
sg = N.sign_counts(np.array([-3.0, -0.5, 0.0, 0.0, 2.0]))          # discharge-positive
assert sg == {"charging": 2, "zero": 2, "discharging": 1}, sg

# 5. support rule
assert N.support_label(199, 10, 5)[0] == "candidate, not supported"
assert N.support_label(200, 10, 5)[0] == "supported"
assert N.support_label(200, 9, 5)[0] == "candidate, not supported"
assert N.support_label(200, 10, 4)[0] == "candidate, not supported"

# 6. conditional rate on degenerate data: all neutral -> share 1.0 with a degenerate interval; unsupported stratum -> None
rec = [dict(day="2026-01-0%d" % (1 + i % 6), denCold=20, numCold=20, denWarm=0, numWarm=0) for i in range(12)]
r = N.conditional_rate(rec, "Cold", supported=True)
assert r["share"] == 1.0 and r["ci95"] == [1.0, 1.0] and r["nDrives"] == 12 and r["nDays"] == 6, r
assert N.conditional_rate(rec, "Cold", supported=False) is None
assert N.conditional_rate(rec, "Warm", supported=True) is None      # empty denominator

# 7. first-rotation clock: seconds since the first grid second with rpm > 400
g, c, a = frame(6)
g["rpm"] = [0.0, 0.0, 450.0, 450.0, 450.0, 450.0]
assert list(N.seconds_since_first_rotation(g["rpm"].to_numpy())) == [-1, -1, 0, 1, 2, 3]
assert list(N.seconds_since_first_rotation(np.array([np.nan, 300.0]))) == [-1, -1]

# 8. per-interval summary on a hand-built run: means, sign counts, real-sample counts
g, c, a = frame(12, I=-2.0, soc=70.0)
g.iloc[0:4, g.columns.get_loc("I")] = 1.0
real = pd.DataFrame({k: np.ones(12, bool) for k in ("rpm", "fuel", "I", "soc")}, index=g.index)
real.iloc[2:4, real.columns.get_loc("rpm")] = False
since = N.seconds_since_first_rotation(g["rpm"].to_numpy())
s = N.summarize_interval(g, c, real, since, 0, 12)
assert s["len"] == 12 and s["sign"] == {"charging": 8, "zero": 0, "discharging": 4}, s
assert abs(s["meanAbsI"] - (8 * 2.0 + 4 * 1.0) / 12) < 1e-12 and s["realRpm"] == 10 and s["realFuel"] == 12
print("ok test_cold_neutral_context")
