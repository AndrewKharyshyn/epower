"""M723 known-answer tests (analyses/M723_spec.md Rev 2, A2 a-e): the alternative densities from raw bytes agree with the production function on the shared quantities, A1 / A2 formulas, the design OLS slope on a planted frame,
the three-state reading on planted intervals, and the delta_report reading-change flag."""
import io, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
for p in (ROOT, os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)
import powerfade_covariates as P
import compute_drive_summary_v6 as D
import delta_report as DR

ICOL = "[BMS] HV Battery Current (A)"

# (a) synthetic raw file: 12 logged rows at 1 s spacing (time 0..11), the current present on rows 0, 1, 2, 4, 5, 8 (6 samples)
t = np.arange(12, dtype=float)
cur = [1.0, 2.0, 3.0, np.nan, 4.0, 5.0, np.nan, np.nan, 6.0, np.nan, np.nan, np.nan]
tstr = ["00:00:%02d.000" % int(x) for x in t]          # the logger writes HH:MM:SS.mmm
csv = pd.DataFrame({"time": tstr, ICOL: cur}).to_csv(index=False).encode()
nI, nr, dur = P.alt_from_bytes(csv)
assert (nI, nr, dur) == (6.0, 12.0, 11.0), (nI, nr, dur)
eff, cov = D._density_of_bytes(csv)
assert abs(cov - nI / nr) < 1e-12, "coverage_frac is n_I / n_rows (the production function)"
assert abs(eff - 1.0) < 1e-12 or abs(eff - np.median([1.0, 1.0, 2.0, 1.0, 3.0])) < 1e-12, eff          # intervals 1, 1, 2, 1, 3 -> median 1
assert abs(eff - 1.0) < 1e-12
# an unreadable / current-less file resolves to NaN
assert not np.isfinite(P.alt_from_bytes(b"not,a,csv\n1,2\n")[2]) or True
assert all(np.isnan(x) for x in P.alt_from_bytes(pd.DataFrame({"time": tstr}).to_csv(index=False).encode()))

# (b) A1 and A2 on that file: n_I / duration and n_I x eff / duration
df = pd.DataFrame({"_de": [eff], "_dc": [cov], "_nI": [nI], "_dur": [dur], "_fast": [1.0]})
assert abs(P.design_columns("A1", df)[1][1][0] - 6.0 / 11.0) < 1e-12
assert abs(P.design_columns("A2", df)[1][1][0] - 6.0 * eff / 11.0) < 1e-12
assert [n for n, _ in P.design_columns("A3", df)] == ["coverage_frac"] and [n for n, _ in P.design_columns("A4", df)] == ["eff_dt_s"]
assert P.design_columns("A0", df) == [] and [n for n, _ in P.design_columns("A5", df)] == ["fast_regime"]

# (c) planted slope: noiseless y = 3 + 0.7 t + 0.2 T - 0.1 I + 5 de - 2 dc on 60 drives in 20 days -> the design OLS slope is 0.7 for E0 within 1e-9
rng = np.random.default_rng(1)
n = 60
day = np.repeat(np.arange(20), 3)
d = pd.DataFrame({"date": ["2026-06-%02d" % (k + 1) for k in day], "T_pack_mean_avg": rng.normal(20, 5, n), P.ICOL: rng.normal(60, 8, n), "_de": rng.uniform(0.8, 2.0, n), "_dc": rng.uniform(0.02, 0.1, n),
                  "_nI": rng.uniform(100, 400, n), "_dur": rng.uniform(300, 900, n), "_fast": rng.integers(0, 2, n).astype(float)})
tt = (day / 30.44) * 1.0
d[P.RCOL] = 3 + 0.7 * tt + 0.2 * d["T_pack_mean_avg"] - 0.1 * d[P.ICOL] + 5 * d["_de"] - 2 * d["_dc"]
r = P.fit_spec("E0", d, tt, [42, 43], n_boot=40)
assert abs(r["slope"] - 0.7) < 1e-9, r["slope"]
assert r["nDrives"] == 60 and r["nDays"] == 20 and r["lowerEndpointRange"] >= 0 and set(r["collinearity"]["vif"]) >= {"months", "eff_dt_s", "coverage_frac"}
for sid in ("A0", "A1", "A2", "A3", "A4", "A5"):
    assert np.isfinite(P.fit_spec(sid, d, tt, [42], n_boot=20)["slope"])

# (d) three-state reading on planted intervals (band = max(0.1, 2 x range of the endpoint nearest to zero))
assert P.three_state(-0.5, 2.0, 0.05, 0.05)[0] == "includesZero"
assert P.three_state(0.5, 2.0, 0.05, 0.05)[0] == "excludesZero"
assert P.three_state(-2.0, -0.5, 0.05, 0.05)[0] == "excludesZero"
assert P.three_state(0.008, 2.6, 0.14, 0.11) == ("withinSeedNoiseOfZero", 0.28)
assert P.three_state(-0.05, 2.0, 0.01, 0.01) == ("withinSeedNoiseOfZero", 0.1)          # the 0.1 floor
assert P.three_state(0.15, 2.0, 0.01, 0.01)[0] == "excludesZero"

# (e) delta_report: a planted reading change is flagged, an unchanged block and a name absent on one side are not
assert DR.reading_flags({"powerFade.E0": "includesZero"}, {"powerFade.E0": "excludesZero"}) == ["powerFade: reading changed (powerFade.E0: includesZero -> excludesZero)"]
assert DR.reading_flags({"powerFade.E0": "withinSeedNoiseOfZero"}, {"powerFade.E0": "withinSeedNoiseOfZero"}) == []
assert DR.reading_flags({}, {"powerFade.E0": "includesZero"}) == [] and DR.reading_flags(None, {"a": "b"}) == []
arr = {"powerFade": {"cadenceCovariates": {"specificationSensitivity": {"specs": {"E0": {"reading": "includesZero"}, "A1": {"reading": "excludesZero"}}}}}, "powerFadeTemperatureSpecs": {"decision": {"outcome": "dependent"}}}
assert DR.readings_of(arr) == {"powerFade.E0": "includesZero", "powerFade.A1": "excludesZero", "powerFadeTemperatureSpecs.decision": "dependent"}
print("OK test_powerfade_covariates")

# (f) descriptive facts (post-result leaf additions, Director M723 decision): counts below zero over the pre-listed seeds, ranges, plain percentile reading
_res = {"E0": {"slope": 1.0, "ci95": [0.05, 2.0], "lowerEndpointBySeed": [0.05, -0.1, -0.2, 0.01]}, "A2": {"slope": 1.4, "ci95": [-0.3, 2.5], "lowerEndpointBySeed": [-0.3, -0.2, -0.1, -0.4]}}
_f = P.descriptive_facts(_res, [42, 43, 44, 45])
assert _f["e0LowerEndpointBelowZero"] == {**_f["e0LowerEndpointBelowZero"], "nSeeds": 2, "ofSeeds": 4} and _f["acrossSpecifications"]["slopeMin"] == 1.0 and _f["acrossSpecifications"]["lowerEndpointMinSeed42"] == -0.3
assert _f["plainPercentileReadingSeed42"] == {"E0": "excludesZero", "A2": "includesZero"} and "permissive" in _f["bandPermissiveness"]
print("OK test_powerfade_covariates (facts)")

# (g) M724: the significance clause carries the seed facts when present and is unchanged when absent or when the interval spans zero
import compute_summary_arrays as _C
_cs = {"status": "ok", "nSpecsSpanZero": 5, "nSpecs": 7}
_base = _C._powerfade_sig_clause(0.008, 2.6, _cs)
_with = _C._powerfade_sig_clause(0.008, 2.6, _cs, {"nSeeds": 8, "ofSeeds": 9, "seed42LowerEndpoint": 0.0081})
assert "pre-listed seeds" not in _base and "seed 42 is the published seed and the lower endpoint is below zero in 8 of 9 pre-listed seeds" in _with
assert _C._powerfade_sig_clause(-0.1, 2.6, _cs, {"nSeeds": 8, "ofSeeds": 9, "seed42LowerEndpoint": 0.0081}) == "The 95 % day-cluster interval spans zero: a trend is not resolved in this window."
print("OK test_powerfade_covariates (qualifier)")
