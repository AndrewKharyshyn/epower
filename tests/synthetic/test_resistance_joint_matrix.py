"""M514 known-answer tests (analyses/M514_spec.md Rev 2): 54 cell ids, resampling engine equals the production day / ISO-week bootstraps, common random numbers, failed-draw rule, circular block weights,
indicator recovery, ladder edge cases, frozen modal pair, and (when the tracked sidecar exists) A1 differs from A0 and G2 excludes exactly the gridChange drives."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import resistance_joint_matrix as J
import day_bootstrap as DB
import m499_temp_spec as M9

assert len(J.CELL_IDS) == 54 and len(set(J.CELL_IDS)) == 54 and J.REFERENCE in J.CELL_IDS
rng = np.random.default_rng(7)
nd, per = 40, 4
dates = pd.date_range("2026-06-01", periods=nd)
rows = []
for k, dt in enumerate(dates):
    for j in range(per):
        rows.append({"date": dt.strftime("%Y-%m-%d"), J.T_: 25 - 0.1 * k + rng.normal(0, 1), "_chg": float(k >= 25), "_de": rng.normal(1, 0.1), "_dc": rng.uniform(0.5, 1), "_fast": float(rng.random() < 0.3)})
d = pd.DataFrame(rows)
d[J.I_] = rng.normal(80, 10, len(d)); d["a1_I"] = d[J.I_] + rng.normal(0, 1, len(d))
t = ((pd.to_datetime(d["date"]) - pd.Timestamp("2026-06-01")).dt.days / J.MONTH_DAYS).values
OFFSET = 3.0
d[J.R_] = 100 + 0.5 * t - 1.5 * d[J.T_] + 0.05 * d[J.I_] + OFFSET * d["_chg"] + rng.normal(0, 2, len(d))
d["a1_R"] = d[J.R_] + rng.normal(0, 0.5, len(d))
t0 = pd.Timestamp("2026-06-01")
knots = J.quantile_knots(d[J.T_].values)

# indicator recovery: G1 adds the grid-change column and recovers the injected offset
X1, y1 = J.design(d, "A0G1C1T0", t, knots)
b = np.linalg.lstsq(X1, y1, rcond=None)[0]
assert X1.shape[1] == 7 and abs(b[4] - OFFSET) < 1.0, (X1.shape, b)      # const, months, T, I, chg, de, dc
assert J.design(d, "A0G0C0T0", t, knots)[0].shape[1] == 4 and J.design(d, "A0G0C2T2", t, knots)[0].shape[1] == 9 and J.design(d, "A1G0C1T1", t, knots)[0].shape[1] == 7

# engine equals the production day bootstrap and the M499 ISO-week bootstrap on the reference design (no failed draws expected)
grp = J.make_group(d, ["A0G0C1T0", "A0G1C1T0"], t0, knots)
X, y = J.design(d, "A0G0C1T0", t, knots)
prod_day = DB.ols_boot_slopes(X, y, d["date"].values, coef=1, nb=500, seed=J.SEED, t=t)[0]
mine_day = J.run_procedure(grp["gday"], "day", 500)[:, 0]
assert np.sum(~np.isfinite(mine_day)) == 0 and np.allclose(mine_day, prod_day, atol=1e-8), (np.nanmax(np.abs(mine_day[: len(prod_day)] - prod_day)))
wk = J.iso_labels(d["date"].values)
prod_wk = M9.cluster_boot(X, y, wk, 1, 500, J.SEED)
mine_wk = J.run_procedure(grp["gweek"], "week", 500)[:, 0]
mw = mine_wk[np.isfinite(mine_wk)]          # draws with fewer than 3 distinct weeks fail here and are dropped by cluster_boot: the valid draws are identical
assert len(mw) == len(prod_wk) and np.allclose(mw, prod_wk, atol=1e-8)

# common random numbers: a cell against an identical copy has a zero paired difference
g2 = J.make_group(d, ["A0G0C1T0", "A0G0C1T0"], t0, knots)
res2 = {"day": J.run_procedure(g2["gday"], "day", 300)}
assert J.pair_interval(res2, 0, 1) == [0.0, 0.0]

# failed-draw rule: an indicator that is non-zero in a single day makes every draw that omits that day failed (about e^-1 of the draws)
d2 = d.copy(); d2["_chg"] = (d2["date"] == d2["date"].iloc[0]).astype(float)
g3 = J.make_group(d2, ["A0G1C1T0"], t0, knots)
dr = J.run_procedure(g3["gday"], "day", 1000)[:, 0]
share = float(np.mean(~np.isfinite(dr)))
assert 0.25 < share < 0.5, share

# circular blocks: coverage weights cover ceil(D/L) * L day-slots per draw and wrap
for L in (7, 14):
    for W in J.draws_blocks(30, L, 50, np.random.default_rng(1)):
        assert W.shape == (50, 30) and np.allclose(W.sum(axis=1), np.ceil(30 / L) * L)
dd_ = J.run_blocks(grp["gcal"], 7, 200, J.SEED + 7)
assert dd_.shape == (200, 2)

# ladder edge cases on fabricated cell records
def rec(i, slope, reading, dec=True, lo=-1.0, hi=1.0):
    ci = [lo, hi]
    base = {"ci95": ci, "reading": reading, "decisive": dec}
    return {"id": i, "slope": slope, **{p: dict(base) for p in ("day", "week", "M7", "M14")}}

cells = [rec("c%d" % k, 0.5 + 0.01 * k, "includesZero") for k in range(10)]
assert J.ladder(cells, cells[0])[0] == "L0"
cells2 = [dict(c) for c in cells]; cells2[3] = rec("c3", 0.7, "positive", lo=0.1, hi=1.5)
assert J.ladder(cells2, cells2[0])[0] == "L1"                                                  # the reference includes zero, one cell excludes it
cells3 = [rec("c%d" % k, 0.5 + 0.01 * k, "positive", lo=0.1, hi=1.0) for k in range(10)]
assert J.ladder(cells3, cells3[0])[0] == "L2"                                                  # reference and all intervals positive
cells4 = [rec("c%d" % k, 0.5, "includesZero", dec=(k > 3)) for k in range(10)]
assert J.ladder(cells4, cells4[5])[0] == "not assessable"                                       # 40 % non-decisive
cells5 = [dict(c) for c in cells]; cells5[2] = rec("c2", 5.0, "includesZero")
assert J.ladder(cells5, cells5[0])[0] == "L1" and J.ladder(cells5, cells5[0])[1]["spreadRatio"] > J.SPREAD_MAX      # same reading, spread too large
cells6 = [dict(c) for c in cells]; cells6[4] = dict(cells6[4], week=dict(cells6[4]["week"], reading="positive", ci95=[0.1, 1.0]))
assert J.ladder(cells6, cells6[0])[0] == "L1"                                                  # a week interval that differs counts

# frozen modal pair from the hash-recorded M503 record
mp, sha = J.frozen_modal_pair()
assert mp == ("fine", 0.16) and len(sha) == 64

# real data (tracked sidecar): A1 differs from A0 on at least one drive; G2 excludes exactly the gridChange drives of M503
if os.path.exists(J.SIDECAR):
    import json, powerfade_equivalence as PE
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    side = J._read(J.SIDECAR)
    ps = PE._read(PE.SIDECAR)
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in ps.to_dict("records")}
    cc, F = J.build_frame(dm, side, dens, mp)
    m = F.dropna(subset=["a1_R", J.R_])
    assert (np.abs(m["a1_R"] - m[J.R_]) > 1e-9).any()
    flagged = set(json.load(open("analyses/M503_result.json", encoding="utf-8"))["rev3DataInformed"]["flagsByFile"]["gridChange"])
    assert set(F.loc[F["_chg"].astype(bool), "file"]) == set(F["file"]) & flagged
    assert not (set(F[~F["_chg"].astype(bool)]["file"]) & flagged)
print("test_resistance_joint_matrix: OK")
