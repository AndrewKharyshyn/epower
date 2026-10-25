"""M499 known-answer tests: specification recovery on a synthetic corpus and the tipping identity slope(bT + d) = slope0 - d * tau."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import m499_temp_spec as M
import powerfade_equivalence as PE

rng = np.random.default_rng(3)
n_days, per = 90, 4
days = pd.date_range("2026-05-15", periods=n_days)
rows = []
for k, dt in enumerate(days):
    T = 30 - 0.12 * k + rng.normal(0, 1.5)                       # seasonal cooling drift plus noise
    for j in range(per):
        Tj = T + rng.normal(0, 1.0)
        rows.append({"date": dt.strftime("%Y-%m-%d"), M.TREF: Tj, PE.ICOL: rng.normal(80, 10), "_de": rng.normal(1.0, 0.2), "_dc": rng.uniform(0.5, 1.0),
                     "pack_temp_start_c": Tj - 2 + rng.normal(0, 1), "ambient_time_mean_c": Tj - 8 + rng.normal(0, 2)})
d = pd.DataFrame(rows)
t_m = (pd.to_datetime(d["date"]) - pd.Timestamp("2026-05-15")).dt.days.values / M.MONTH_DAYS
TRUE_SLOPE, BT = 0.5, -2.0
d[PE.RCOL] = 120 + TRUE_SLOPE * t_m + BT * d[M.TREF] + 0.05 * d[PE.ICOL] + rng.normal(0, 3, len(d))
t0 = pd.Timestamp("2026-05-15")
knots = tuple(np.quantile(d[M.TREF], [1 / 3, 2 / 3]))
f0, X0, y0, tt0, names = M.fit(d, "T0", t0, knots, 400)
b = np.linalg.lstsq(X0, y0, rcond=None)[0]
assert abs(f0["slope"] - b[1]) < 1e-12 and names[:3] == ["const", "months", "T"]
assert abs(f0["slope"] - TRUE_SLOPE) < 0.35 and f0["day"]["ci95"][0] < TRUE_SLOPE < f0["day"]["ci95"][1], f0
for s in ("T1", "T2", "T3", "T4", "T5"):
    r = M.fit(d, s, t0, knots, 400)[0]
    assert r["n"] == len(d) and np.isfinite(r["slope"]) and r["isoWeek"]["drawsUsed"] > 0, (s, r)
# tipping identity: refit with the temperature coefficient shifted by d equals slope0 - d * tau (exact algebra)
Z = np.column_stack([np.ones(len(d)), tt0, d[PE.ICOL].values, d["_de"].values, d["_dc"].values])
tau = np.linalg.lstsq(Z, d[M.TREF].values, rcond=None)[0][1]
for dd in (-1.0, 0.5, 1.0):
    refit = np.linalg.lstsq(np.delete(X0, 2, axis=1), y0 - (b[2] + dd) * X0[:, 2], rcond=None)[0][1]   # restricted refit: T dropped, its coefficient fixed at bT + d
    assert abs(refit - (f0["slope"] - dd * tau)) < 1e-9, (dd, refit, f0["slope"] - dd * tau)
# a quadratic truth: T1 reduces the bias of the months slope relative to T0
d2 = d.copy(); Tc = d2[M.TREF] - d2[M.TREF].mean()
d2[PE.RCOL] = 120 + TRUE_SLOPE * t_m + BT * d2[M.TREF] + 0.15 * Tc ** 2 + 0.05 * d2[PE.ICOL] + rng.normal(0, 1, len(d2))
s0 = M.fit(d2, "T0", t0, knots, 100)[0]["slope"]; s1 = M.fit(d2, "T1", t0, knots, 100)[0]["slope"]
assert abs(s1 - TRUE_SLOPE) < abs(s0 - TRUE_SLOPE), (s0, s1)
print("test_m499_temp_spec: OK")

# language rule added with M499: forbidden trend phrasings fire, the shipped wording does not
import language_gate as _G
_r = [x for x in _G.RULES if x.rid == "M499-resistance-trend-wording"][0]
assert _r.hits("The resistance trend is significant in this window") and _r.hits("pack resistance is rising")
assert not _r.hits("the resistance trend remains unresolved and no slope is promoted")
print("test_m499_temp_spec (language rule): OK")

# A01 (audit 2026-10-25): the main-entry fidelity guard compares nDays with the live reference, not a constant 98
_c = {"slope": 0.6564, "publishedSlope": 0.65641, "n": 274, "publishedN": 274, "nDays": 98, "publishedNDays": 98, "bT": -1.234, "publishedBT": -1.2341,
      "dayCi95": [-0.4262, 1.8374], "publishedDayCi95": [-0.42623, 1.83743]}
assert M.fidelity_ok(_c)
assert M.fidelity_ok({**_c, "nDays": 99, "publishedNDays": 99})        # grown, consistent reference passes
assert M.fidelity_ok({**_c, "nDays": 100, "publishedNDays": 100})
assert not M.fidelity_ok({**_c, "nDays": 99})                          # inconsistent reference still fails
assert not M.fidelity_ok({**_c, "nDays": 99, "publishedNDays": 99, "slope": 0.7})   # other checks stay strict
assert not M.fidelity_ok({**_c, "n": 275})
print("test_m499_temp_spec (A01 fidelity guard): OK")
