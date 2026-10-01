"""Known-answer tests for tools/m320_ladder.py (M320 spec rev 2, validity item b2). Run: python tests/synthetic/test_m320_ladder.py"""
import math, os, sys
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import numpy as np, pandas as pd
import m320_ladder as L
import m119v2_model as m

# --- weighted quantile = inverted CDF; uniform weights equal np.quantile(inverted_cdf)
x = np.array([5., 1., 3., 2., 4.])
assert L.weighted_quantile(x, np.ones(5), 0.5) == 3.0 and L.weighted_quantile(x, np.ones(5), 0.05) == 1.0 and L.weighted_quantile(x, np.ones(5), 0.95) == 5.0
assert L.weighted_quantile(x, np.array([10., 1, 1, 1, 1]), 0.5) == 5.0      # most of the weight sits on the value 5
assert L.weighted_quantile(np.array([1., 2.]), np.array([1., 3.]), 0.5) == 2.0
assert L.snap(18.6) == 17.5 and L.snap(18.8) == 20.0 and L.snap(36.2) == 35.0 and L.snap(36.3) == 37.5

# --- D: identical levels give 0; a constant contrast c gives |c| on supported cells; unsupported cells are ignored
eta = np.linspace(-6, -3, 140)
n = np.full(140, 50)
assert L.rms_contrast(eta, eta, n, n) == 0.0
assert abs(L.rms_contrast(eta + 0.7, eta, n, n) - 0.7) < 1e-12
n_a = n.copy(); n_a[:70] = 0                                   # first half unsupported at level a: only the second half counts
d = np.zeros(140); d[:70] = 100.0; d[70:] = 0.4                # a huge contrast on the unsupported cells must not leak in
assert abs(L.rms_contrast(eta + d, eta, n_a, n) - 0.4) < 1e-12
assert math.isnan(L.rms_contrast(eta, eta, np.zeros(140), n))
w_a = np.where(np.arange(140) < 70, 20, 40); w_b = np.where(np.arange(140) < 70, 20, 40)   # weights = pooled seconds
dd = np.where(np.arange(140) < 70, 1.0, 2.0)
exp = math.sqrt((np.sum(40 * 1.0 ** 2 * 70) + np.sum(80 * 2.0 ** 2 * 70)) / (40 * 70 + 80 * 70))
assert abs(L.rms_contrast(eta + dd, eta, w_a, w_b) - exp) < 1e-12

# --- pair status and the merge rule (fixed sequence; intersection-union for P50)
dl = L.DELTA
assert L.pair_status(0.5, dl + .1, dl + .1, 0, 4000) == "distinct"
assert L.pair_status(0.5, dl + .1, dl - .1, 0, 4000) == "borderline"
assert L.pair_status(0.5, dl - .1, dl - .1, 0, 4000) == "indistinct"
assert L.pair_status(0.5, dl + .1, dl + .1, 41, 4000) == "inconclusive"          # > 1% failed draws
assert L.pair_status(float("nan"), 1, 1, 0, 4000) == "inconclusive"
C = [dict(name="P5", value=18.0, admissible=True), dict(name="P50", value=33.0, admissible=True), dict(name="P95", value=42.5, admissible=True)]
K = lambda a, b: frozenset((a, b))
lev, ref, dr, st = L.decide_levels(C, {K(18.0, 42.5): "distinct", K(18.0, 33.0): "distinct", K(33.0, 42.5): "distinct"})
assert [c["name"] for c in lev] == ["P5", "P50", "P95"] and ref["name"] == "P50" and not dr and st is None
lev, ref, dr, st = L.decide_levels(C, {K(18.0, 42.5): "distinct", K(18.0, 33.0): "distinct", K(33.0, 42.5): "indistinct"})
assert [c["name"] for c in lev] == ["P5", "P95"] and ref["name"] == "P5"              # reference = the lower level when P50 is dropped
lev, ref, dr, st = L.decide_levels(C, {K(18.0, 42.5): "indistinct"})
assert [c["name"] for c in lev] == ["P50"] and st and "not established" in st and not dr and "no effect" not in st
lev, ref, dr, st = L.decide_levels(C, {K(18.0, 42.5): "borderline"})
assert [c["name"] for c in lev] == ["P50"] and dr                                     # borderline -> Director, conservative display
C2 = [dict(C[0], admissible=False), C[1], C[2]]
lev, ref, dr, st = L.decide_levels(C2, {K(33.0, 42.5): "distinct"})
assert lev == [] or [c["name"] for c in lev] == ["P50"]                               # an inadmissible P5 can never be shown

# --- support gate: 100 events on >= 10 days inside the +/-2.5 C band
rng = np.random.default_rng(1)
cc = pd.DataFrame({"tpack": rng.uniform(10, 40, 20000), "day": rng.integers(0, 30, 20000), "y": (rng.random(20000) < 0.05).astype(float)})
s = L.support_stats(cc, 25.0)
inb = (cc.tpack >= 22.5) & (cc.tpack <= 27.5)
assert s["nAtRiskS"] == int(inb.sum()) and s["nEvents"] == int((inb & (cc.y > 0)).sum()) and s["nDays"] == cc.day[inb & (cc.y > 0)].nunique() and s["admissible"]
assert not L.support_stats(cc, 60.0)["admissible"] and L.support_stats(cc, 60.0)["nEvents"] == 0

# --- end-to-end known answer: a pure pack-temperature main effect (cloglog slope b per C) through the SAME pipeline gives D ~ b * dT
b, N = 0.06, 120000
tp = rng.uniform(15, 45, N)
df = pd.DataFrame({"soc": rng.uniform(40, 85, N), "speed": rng.uniform(0, 130, N), "tpack": tp, "demand": rng.normal(0, 1, N), "durationS": rng.uniform(1, 60, N)})
p = 1 - np.exp(-np.exp(-3.5 + b * (tp - 30)))
df["y"] = (rng.random(N) < p).astype(float)
spec = m.DesignSpec(['soc', 'speed', 'tpack', 'demand', 'logdur'], m.INTERACTIONS).fit(df)
X, _ = spec.transform(df)
res = m.fit_glm(X, df["y"].values)
cs, cv = L.cell_frame(m)
dem = [-1.0, 0.0, 1.0]
eta_, nc = L.eta_block(m, spec, res.params, [20.0, 40.0], dem, cs, cv, sec=False)
e = eta_.reshape(nc, 2, L.NC)[0]
D = L.rms_contrast(e[0], e[1], np.full(L.NC, 100), np.full(L.NC, 100))
assert abs(D - b * 20.0) < 0.15, (D, b * 20.0)                                         # analytic 1.2
assert L.rms_contrast(e[0], e[0], np.full(L.NC, 100), np.full(L.NC, 100)) == 0.0
print("M320 ladder tests OK; synthetic D =", round(D, 3), "vs analytic", b * 20.0)
