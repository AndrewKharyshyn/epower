"""M495 known-answer tests (spec analyses/M495_spec.md Rev 2, KAT1-KAT7 and the Rev 2 additions): the rolling-origin engine of tools/m495_rolling_origin.py on synthetic cloglog hazard tables.
KAT1 stationary hazard: no fold is flagged, every fold has D1 PASS and O/E near 1. KAT2 a planted coefficient flip after the second origin: the later folds show D1 FAIL and the verdict flags exactly those origins.
KAT3 leakage: training and test day sets are disjoint on every fold, the embargo day is in neither, and the training fit is unchanged when the test rows are altered (knots and scale use training rows only).
KAT4 (acceptance run, needs the 606 tables via M495_TABLES) the M428 split is reproduced. KAT5 test temperatures outside the training range: D3 MATERIAL, listed as extrapolation, not counted as degradation.
KAT6 the frozen artifact round-trips: apply_frozen on the saved knots, scale and coefficients reproduces the fit's predictions to 1e-9, the B1 and B0 baselines likewise. KAT7 the monitor returns counts only.
Rev 2: a fold with fewer than 10 observed days is not evaluable; all-indeterminate D2 gives 'partial'; the verdict logic on constructed states."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import m119v2_model as m
import m428_oot as O
import m495_rolling_origin as R

D0 = pd.Timestamp("2026-05-11")
B = 300


def synth(seed, n_days=130, shift_from=None, rows_per_file=100, files_per_day=3, gap_days=(), tpack_shift_from=None, rate_shift=0.0):
    rg = np.random.default_rng(seed)
    rows = []
    for i in range(n_days):
        if i in gap_days:
            continue
        day = (D0 + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        for f in range(files_per_day):
            n = rows_per_file
            soc = rg.uniform(30, 90, n); speed = rg.uniform(0, 110, n); tp = rg.normal(28, 5, n); dem = rg.normal(0, 1, n); dur = rg.exponential(60, n) + 1
            if tpack_shift_from is not None and i >= tpack_shift_from:
                tp = tp - 40.0                                       # a cold regime far outside the training range
            sz, dz = (soc - 60) / 17, dem
            sign = -1.0 if (shift_from is not None and i >= shift_from) else 1.0
            eta = -4.0 - sign * 0.9 * sz + sign * 0.7 * dz + 0.15 * (speed - 55) / 30 + 0.2 * np.log1p(dur) / 4 + rate_shift
            y = (rg.random(n) < 1 - np.exp(-np.exp(eta))).astype(float)
            rows.append(pd.DataFrame({"file": "d%03d_f%d.csv" % (i, f), "day": day, "soc": soc, "speed": speed, "tpack": tp, "demand": dem, "durationS": dur, "y": y}))
    return pd.concat(rows, ignore_index=True)


# fold geometry on a known date range
f = R.make_folds([D0.strftime("%Y-%m-%d"), (D0 + pd.Timedelta(days=129)).strftime("%Y-%m-%d")])
assert [x["cut"] for x in f] == [(D0 + pd.Timedelta(days=56 + 28 * k)).strftime("%Y-%m-%d") for k in range(3)], f
assert f[0]["trainEnd"] == (D0 + pd.Timedelta(days=54)).strftime("%Y-%m-%d") and f[-1]["testEnd"] == (D0 + pd.Timedelta(days=130)).strftime("%Y-%m-%d")
short = R.make_folds([D0.strftime("%Y-%m-%d"), (D0 + pd.Timedelta(days=56 + 28 + 6)).strftime("%Y-%m-%d")])           # a 7-day last window is merged into the previous one
assert len(short) == 2 or short[-1]["testEnd"].endswith(str((D0 + pd.Timedelta(days=56 + 28 + 7)).date())), short

# KAT1 stationary
cc = synth(1)
res1 = []
for fo in R.make_folds(cc["day"].values):
    o, _ = R.eval_fold(cc, fo, B, 42 + fo["k"], full=False)
    res1.append(o)
ev = [o for o in res1 if o["evaluable"]]
assert len(ev) >= 2, [o["test"] for o in res1]
for o in ev:
    s = o["primary"]["states"]
    assert s["D1"] == "PASS" and s["D2"] != "MATERIAL", (o["fold"], s)
    assert 0.8 < o["primary"]["point"]["OE"] < 1.25, o["primary"]["point"]["OE"]
v1 = R.verdict_side(res1, {})
assert not v1["flaggedOrigins"], v1

# KAT2 planted flip from day 84 (the second origin): origins whose test window lies after the flip fail
cc2 = synth(2, shift_from=84)
res2 = []
for fo in R.make_folds(cc2["day"].values):
    o, _ = R.eval_fold(cc2, fo, B, 42 + fo["k"], full=False)
    res2.append(o)
v2 = R.verdict_side(res2, {})
assert v2["flaggedOrigins"] and 0 not in v2["flaggedOrigins"] and 1 in v2["flaggedOrigins"], (v2, [(o["fold"]["k"], o.get("primary", {}).get("states")) for o in res2])
assert v2["verdict"].startswith("degradation flagged"), v2["verdict"]

# KAT3 leakage and train-only knots
for fo in R.make_folds(cc["day"].values):
    tr, te = R.split(cc, fo)
    assert not (set(tr["day"]) & set(te["day"])) and not (set(tr["day"]) & {(pd.Timestamp(fo["cut"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")})
    assert tr["day"].max() <= fo["trainEnd"] and te["day"].min() >= fo["testStart"] and te["day"].max() < fo["testEnd"]
fo = R.make_folds(cc["day"].values)[0]
tr, te = R.split(cc, fo)
spec_a, res_a, *_ = O.fit_frozen(tr)
cc_alt = cc.copy(); dd = pd.to_datetime(cc_alt["day"]); mk = (dd >= pd.Timestamp(fo["testStart"])).values
cc_alt.loc[mk, "soc"] = cc_alt.loc[mk, "soc"] * 0.3 + 5; cc_alt.loc[mk, "tpack"] += 50.0
tr2, _ = R.split(cc_alt, fo)
spec_b, res_b, *_ = O.fit_frozen(tr2)
assert np.array_equal(np.asarray(res_a.params), np.asarray(res_b.params)) and all(np.array_equal(spec_a.knots[k], spec_b.knots[k]) for k in spec_a.knots) and spec_a.scale == spec_b.scale

# KAT5 extrapolation: cold test temperatures
cc5 = synth(5, tpack_shift_from=100)
res5 = []
for fo in R.make_folds(cc5["day"].values):
    o, _ = R.eval_fold(cc5, fo, B, 42 + fo["k"], full=False)
    res5.append(o)
v5 = R.verdict_side(res5, {})
assert v5["extrapolationOrigins"] and not any(k in v5["flaggedOrigins"] for k in v5["extrapolationOrigins"] if res5[k]["primary"]["states"]["D1"] == "PASS" and res5[k]["primary"]["states"]["D2"] != "MATERIAL"), v5
assert not v5["verdict"].startswith("stable")

# KAT6 frozen artifact round trip
tr, te = R.split(cc, R.make_folds(cc["day"].values)[0])
spec, res, spec1, res1, p0 = O.fit_frozen(tr)
art = {"spec": R._spec_dict(spec), "fit": R._fit_dict(res), "baselineB0Rate": p0, "baselineB1SocOnly": {"spec": R._spec_dict(spec1), "fit": R._fit_dict(res1)}}
art = json.loads(json.dumps(art))                                       # through JSON, as saved
p, p1, p0v = R.apply_frozen(art, te)
assert np.max(np.abs(p - m._predict(res, spec.transform(te)[0]))) < 1e-9 and np.max(np.abs(p1 - m._predict(res1, spec1.transform(te)[0]))) < 1e-9 and np.all(p0v == p0)
assert art["fit"]["usedClusterCovariance"] and art["fit"]["converged"] and np.asarray(art["fit"]["covarianceClusterByDay"]).shape[0] == len(art["fit"]["coefficients"])

# KAT7 monitor: counts only
dm = pd.DataFrame({"file": ["a", "b", "c"], "date": ["2026-10-17", "2026-10-18", "2026-10-19"]})
c = R.monitor_counts(dm)
assert set(c) == {"heldOutDrives", "heldOutDays"} and c == {"heldOutDrives": 2, "heldOutDays": 2}

# Rev 2: evaluability (observed days), all-indeterminate D2 -> partial, stable only when every condition holds
cc8 = synth(8, gap_days=set(range(56, 130)) - {60, 62, 64, 66, 68, 70, 72, 74})          # a test window with only 8 observed days
o8 = [R.eval_fold(cc8, fo, B, 42, full=False)[0] for fo in R.make_folds(cc8["day"].values)[:1]]
assert o8[0]["test"]["nDays"] < R.MIN_TEST_DAYS and not o8[0]["evaluable"]
def fake(k, d1="PASS", d2="within", d3="not material", j=("PASS", "within")):
    return {"fold": {"k": k}, "evaluable": True, "primary": {"states": {"D1": d1, "D2": d2, "D3": d3, "jackknifeD1": j[0], "jackknifeD2": j[1]}}}
assert R.verdict_side([fake(0), fake(1)], {0: {0: ("PASS", "within", "not material")}, 1: {}})["verdict"].startswith("stable")
assert R.verdict_side([fake(0, d2="indeterminate"), fake(1, d2="indeterminate")], {})["verdict"].startswith("partial")
assert R.verdict_side([fake(0), fake(1, d1="FAIL")], {})["flaggedOrigins"] == [1]
assert R.verdict_side([fake(0, j=("PASS", "indeterminate"))], {})["verdict"].startswith("partial")
assert R.verdict_side([fake(0)], {0: {3: ("PASS", "indeterminate", "not material")}})["verdict"].startswith("partial")
assert R.verdict_side([{"fold": {"k": 0}, "evaluable": False}], {})["verdict"] == "not assessable"

# KAT4 (acceptance run only): the M428 split on the real tables
tp = os.environ.get("M495_TABLES")
if tp:
    P, S, T = R.load_tables(tp)
    dmr = pd.read_csv("drive_master.csv", low_memory=False)
    fid = R.m428_fidelity(S, T, P, list(dmr["file"]), 4000, 42)
    assert fid["reproducesM428"], fid
print("test_m495_rolling_origin OK (KAT1 folds %d, KAT2 flagged %s, KAT5 extrapolation %s%s)" % (len(ev), v2["flaggedOrigins"], v5["extrapolationOrigins"], ", KAT4 run" if tp else ", KAT4 skipped"))
