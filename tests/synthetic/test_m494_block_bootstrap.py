"""M494 known-answer tests (spec analyses/M494_spec.md Rev 2, KAT1-KAT7): block bootstraps of the Shoulder-minus-Warm difference of ratios of sums (tools/block_bootstrap.py) on a realistic layout: cohorts segregated in time
(Warm active early, Shoulder late), about a quarter of the Shoulder dates shared with Warm, empty days. Thresholds are the pre-registered ones; nothing is tuned after a result.
KAT1 iid day shocks: mean W / joint-day width ratio over 20 seeds in 0.85-1.20. KAT2 AR(1) shocks (phi = 0.7) shared by the two cohorts: W / joint-day > 1.25 and M7 / joint-day > 1.25 (mean over 20 seeds).
KAT3 L = 1 circular blocks on data without empty days equal the day bootstrap within Monte Carlo error (mean ratio 0.9-1.1). KAT4 hand-computed two-week case. KAT5 the hard stop of the tool. KAT6 iid segregated data: W / WS <= 1.5.
KAT7 the circular moving-block distribution is centred on the point estimate; the released non-circular start rule is not (negative control)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import block_bootstrap as BB
import joint_day_bootstrap as J

N = 4000
D0 = pd.Timestamp("2026-05-11")
width = lambda x: float(np.quantile(x, 0.975) - np.quantile(x, 0.025))
date = lambda i: (D0 + pd.Timedelta(days=int(i))).strftime("%Y-%m-%d")


def layout(rg, ar=0.0, n_days=120, warm=(0, 80), shoulder=(60, 120), p=0.6, empty=True, rw=27.0, rs=26.0):
    """Per-date sums for two cohorts. Warm active on days [0, 80), Shoulder on [60, 120) (20 shared days), each present with probability p (empty days when `empty`). Day shocks AR(1) with parameter ar, shared by both cohorts."""
    shock = np.zeros(n_days)
    e = rg.normal(0, 0.12, n_days)
    for i in range(n_days):
        shock[i] = (ar * shock[i - 1] if i else 0.0) + e[i]
    def coh(lo, hi, r):
        rows = {}
        for i in range(lo, hi):
            if (not empty) or rg.random() < p:
                den = rg.uniform(15, 40)
                rows[date(i)] = (r * np.exp(shock[i]) * den / 100.0, den)
        return pd.DataFrame.from_dict(rows, orient="index", columns=["num", "den"])
    return coh(*warm, rw), coh(*shoulder, rs)


def widths(a, b, seed):
    j = width(J.joint_difference(a, b, np.random.default_rng(seed), N)[0])
    w = width(BB.week_difference(a, b, np.random.default_rng(seed + 1000), N)[0])
    ws = width(BB.stratified_weeks(a, b, np.random.default_rng(seed + 2000), N)[0])
    m7 = width(BB.circular_moving_block(a, b, 7, np.random.default_rng(seed + 3000), N)[0])
    return j, w, ws, m7


# KAT1 and KAT6: iid shocks on the segregated layout with empty days
r1, r6 = [], []
for s in range(20):
    a, b = layout(np.random.default_rng(100 + s))
    j, w, ws, m7 = widths(a, b, s)
    r1.append(w / j); r6.append(w / ws)
assert 0.85 <= np.mean(r1) <= 1.20, ("KAT1 W / joint-day", np.mean(r1))
assert np.mean(r6) <= 1.5, ("KAT6 W / WS", np.mean(r6))

# KAT2: AR(1) day shocks shared by the cohorts
r2w, r2m = [], []
for s in range(20):
    a, b = layout(np.random.default_rng(200 + s), ar=0.7)
    j, w, ws, m7 = widths(a, b, s)
    r2w.append(w / j); r2m.append(m7 / j)
assert np.mean(r2w) > 1.25 and np.mean(r2m) > 1.25, ("KAT2", np.mean(r2w), np.mean(r2m))

# KAT3: no empty days, both cohorts on every day: circular L = 1 equals the day bootstrap (draws on the same axis)
r3 = []
for s in range(20):
    a, b = layout(np.random.default_rng(300 + s), n_days=60, warm=(0, 60), shoulder=(0, 60), empty=False)
    jd = width(J.joint_difference(a, b, np.random.default_rng(s), N)[0])
    l1 = width(BB.circular_moving_block(a, b, 1, np.random.default_rng(s + 500), N)[0])
    r3.append(l1 / jd)
assert 0.9 <= np.mean(r3) <= 1.1, ("KAT3", np.mean(r3))

# KAT4: two ISO weeks (2026-05-11 is a Monday): week 1 = 05-11, 05-12, week 2 = 05-18; hand values
a = pd.DataFrame({"num": [1.0, 1.0, 4.0], "den": [10.0, 10.0, 10.0]}, index=["2026-05-11", "2026-05-12", "2026-05-18"])       # week 1: 2/20, week 2: 4/10
b = pd.DataFrame({"num": [3.0, 2.0], "den": [10.0, 10.0]}, index=["2026-05-12", "2026-05-18"])                                   # week 1: 3/10, week 2: 2/10
d, ra, rb, drop, nbk, nwa, nwb, nmix = BB.week_difference(a, b, np.random.default_rng(1), 2000)
assert (nbk, nwa, nwb, nmix, drop) == (2, 2, 2, 2, 0)
hand = sorted({round(100 * 3 / 10 - 100 * 2 / 20, 6), round(100 * 5 / 20 - 100 * 6 / 30, 6), round(100 * 2 / 10 - 100 * 4 / 10, 6)})      # multisets {1,1}, {1,2}, {2,2}
got = sorted({round(float(x), 6) for x in d})
assert len(got) == 3 and np.allclose(got, hand, atol=1e-5), (got, hand)
# a draw without any Warm unit is discarded and counted
a2 = pd.DataFrame({"num": [1.0], "den": [10.0]}, index=["2026-05-11"]); b2 = pd.DataFrame({"num": [1.0, 1.0, 1.0], "den": [10.0] * 3}, index=["2026-05-18", "2026-05-25", "2026-06-01"])
dd = BB.week_difference(a2, b2, np.random.default_rng(2), 1000)
assert dd[3] > 0 and len(dd[0]) == 1000 - dd[3]

# KAT5: the tool refuses a population that differs from the cube
import urban_week_block as U
dm = pd.read_csv("drive_master.csv", low_memory=False)
reg = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "thermal_regime"]]
import json
cube = json.load(open("summary_arrays.json", encoding="utf-8"))["comparisonCube"]
bad = json.loads(json.dumps(cube)); bad["urbanContrast"]["bands"][0]["difference"]["estimate"] += 0.01
try:
    U.build(dm, reg, bad); raise SystemExit("KAT5: a differing cube estimate was accepted")
except SystemExit as e:
    assert "M494 STOP" in str(e), e

# KAT7: circular moving blocks are centred on the point; the released non-circular start rule is not (negative control), segregated layout, L = 14
rg = np.random.default_rng(7)
a, b = layout(rg, empty=True)
point = 100 * b["num"].sum() / b["den"].sum() - 100 * a["num"].sum() / a["den"].sum()
dc = BB.circular_moving_block(a, b, 14, np.random.default_rng(11), 20000)[0]
dn = BB.circular_moving_block(a, b, 14, np.random.default_rng(11), 20000, circular=False)[0]
mcse = dc.std() / np.sqrt(len(dc))
assert abs(dc.mean() - point) < 4 * mcse + 0.05 * dc.std(), ("KAT7 circular bias", dc.mean() - point, mcse)
assert abs(dn.mean() - point) > abs(dc.mean() - point), ("KAT7 negative control", dn.mean() - point, dc.mean() - point)
print("test_m494_block_bootstrap OK (KAT1 %.3f, KAT6 %.3f, KAT2 %.3f / %.3f, KAT3 %.3f, KAT7 bias circular %.4f vs released %.4f)" % (np.mean(r1), np.mean(r6), np.mean(r2w), np.mean(r2m), np.mean(r3), dc.mean() - point, dn.mean() - point))
