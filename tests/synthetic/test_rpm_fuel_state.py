"""M531 known-answer tests for tools/rpm_fuel_state.py (analyses/M531_spec.md Rev 2): hand-counted motored / fuelled seconds with the pipeline thresholds (boost exactly at -0.70 and -0.55, load exactly at 8.0,
rpm exactly at the 1400 floor excluded), a drive without boost (not on the boost-verified path), leading NaN boost dropped, the day bootstrap with a known ratio, an all-zero cohort (no interval), seed reproducibility,
and cache invalidation by thresholds."""
import copy, io, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import compute_summary_arrays as cs
import rpm_fuel_state as F

inv = {v: k for k, v in cs.RAW_MAP.items()}
RPM, BOOST, LOAD = inv["eng_rpm"], inv["boost"], inv["eng_load_calc"]
assert cs.RPM_HIST_FUELSTATE_RPM_MIN == 1400.0 and cs.RPM_HIST_BOOST_MOTORED == -0.70 and cs.RPM_HIST_BOOST_FUELLED == -0.55 and cs.RPM_HIST_LOAD_MAX == 8.0

def drive(blocks, with_boost=True):
    """blocks: (seconds, rpm, boost, load) per block, 1 Hz."""
    rpm, boost, load = [], [], []
    for n, r, b, l in blocks:
        rpm += [r] * n; boost += [b] * n; load += [l] * n
    t = pd.date_range("2026-01-01 00:00:00", periods=len(rpm), freq="1s").strftime("%Y-%m-%d %H:%M:%S.%f")
    d = {"time": t, RPM: rpm, LOAD: load}
    if with_boost:
        d[BOOST] = boost
    return pd.DataFrame(d)

nan = float("nan")
df = drive([(5, 1500.0, nan, 5.0),          # leading NaN boost: dropped by dropna(['eng_rpm','boost']) (no value to forward-fill)
            (10, 1500.0, -0.80, 5.0),       # motored (boost < -0.70, load < 8)
            (5, 1500.0, -0.70, 5.0),        # boost exactly at the motored threshold: NOT motored (strict), not fuelled (< -0.55): unclassified
            (5, 1500.0, -0.55, 5.0),        # boost exactly at the fuelled threshold: fuelled (>=)
            (5, 1500.0, -0.80, 8.0),        # load exactly at the maximum: NOT motored (strict <): unclassified
            (5, 1400.0, -0.80, 5.0),        # rpm exactly at the floor: base is strict (> 1400): excluded entirely
            (5, 1401.0, 0.0, 30.0),         # fuelled, bin [1400, 1475)
            (5, 2000.0, 0.0, 30.0)])        # fuelled, bin [1975, 2025)
bv, n, hm, hf, u, gv = F.fuel_state_row(df, cs)
edges = list(cs.RPM_HIST_EDGES)
bin_of = lambda r: int(np.searchsorted(edges, r, side="right") - 1)
assert bv == 1 and n == len(df) - 5, (bv, n)                                   # the 5 leading NaN-boost seconds are dropped
assert int(hm.sum()) == 10 and hm[bin_of(1500.0)] == 10 and int(hm.sum()) == hm[bin_of(1500.0)]
assert int(hf.sum()) == 15 and hf[bin_of(1500.0)] == 5 and hf[bin_of(1401.0)] == 5 and hf[bin_of(2000.0)] == 5
assert u == 10                                                                   # 5 s at boost -0.70 + 5 s at load 8.0
# grid-only ffill variant (post hoc sensitivity): with no gaps in this synthetic drive it equals the pipeline convention above the floor (10 motored, 25 classified)
assert gv == (1, 10, 25), gv
# a drive without the boost column is not on the boost-verified path
bv0, n0, hm0, hf0, u0, gv0 = F.fuel_state_row(drive([(20, 1500.0, -0.8, 5.0)], with_boost=False), cs)
assert bv0 == 0 and n0 == 0 and hm0.sum() == 0 and hf0.sum() == 0
# no time column -> no row
assert F.fuel_state_row(pd.DataFrame({RPM: [1.0]}), cs) is None

# day bootstrap: known ratio, seed reproducibility, zero-numerator share, all-zero cohort has no interval
num = np.array([1.0, 0.0, 0.0, 0.0]); den = np.array([10.0, 10.0, 10.0, 10.0]); days = np.array(["d1", "d1", "d2", "d2"])
pt, ci, nd, zero, bad, ndpos = F.boot(num, den, days, nb=2000)
assert abs(pt - 0.025) < 1e-12 and nd == 2 and ndpos == 1 and ci[0] <= pt <= ci[1] and 0.15 < zero < 0.35 and bad == 0       # one positive day of two: a zero numerator in about a quarter of the draws
assert F.boot(num, den, days, nb=2000) == (pt, ci, nd, zero, bad, ndpos)
e = F.est(np.zeros(30), np.full(30, 10.0), np.repeat(np.arange(15).astype(str), 2), nb=500)
assert e["pct"] == 0.0 and e["intervalShown"] is False and e["ci95Pct"] is None and e["nDaysWithMotored"] == 0
# the support rule: enough positive days and few zero draws -> interval shown
rng = np.random.default_rng(1)
num2 = rng.integers(1, 5, 40).astype(float); den2 = np.full(40, 1000.0); days2 = np.repeat(np.arange(20).astype(str), 2)
e2 = F.est(num2, den2, days2, nb=500)
assert e2["intervalShown"] is True and e2["ci95Pct"][0] <= e2["pct"] <= e2["ci95Pct"][1] and e2["nDaysWithMotored"] == 20

# cache invalidation: the meta key changes with a threshold constant
m0 = F.meta_now()
old = cs.RPM_HIST_BOOST_MOTORED
try:
    cs.RPM_HIST_BOOST_MOTORED = -0.71
    assert F.meta_now() != m0
finally:
    cs.RPM_HIST_BOOST_MOTORED = old
assert F.meta_now() == m0
assert len(F.cols(len(edges) - 1)) == 9 + 2 * (len(edges) - 1)
print("OK test_rpm_fuel_state: thresholds, floor, unclassified, boost-verified path, bootstrap, support rule, cache key")
