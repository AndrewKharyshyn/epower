"""M438 known-answer tests (spec analyses/M438_spec.md Rev 2 + 2.1, section 4; criteria declared there before any result): tools/m438_strata.py.
(i) tercile cut points, the 0.5 C rounding and ties; (ii) partition; (iii) the identity E1_std = E1, F_high_std = F_high; (iv) identical stratum curves -> pooled = strata, D = 0;
(v) different stratum curves + stratum-dependent censoring: pooled biased (>= 3 MCSE and >= 0.03), E2_std unbiased (<= 3 MCSE); (vi) an unsupported stratum -> 'not available', weights never renormalized;
(vii) D and the contrasts use the shared resample set; (viii) coverage simulation of E2_std(600) and of the stratum-3-minus-stratum-1 contrast (GATE 0.92-0.98 per scenario, >= 300 simulations with an interval); (ix) seeds reproduce."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import m435_tte as M
import m438_strata as S
import time_to_threshold as T

# ---- (i) cut points, rounding, ties
starts = np.array([20, 20, 25, 30, 30, 35, 40, 45, 50, 55, 55, 58], float)
cuts = S.cut_points(starts)
assert cuts == [30.0, 46.5], cuts                                            # percentiles 30.0 and 46.667 -> floor(2x + 0.5) / 2
assert S.assign([29.9, 30.0, 46.4, 46.5, 59.0], cuts).tolist() == [0, 1, 1, 2, 2]     # a start equal to a cut belongs to the higher stratum
assert S.cut_points([10, 10, 10, 10, 10, 10]) == [10.0, 10.0] and S.assign([10.0], [10.0, 10.0]).tolist() == [2]


# ---- synthetic per-drive records
def rec(start, t, e, last=None, end=None):
    last = t if last is None else last
    end = t + 2.0 if end is None else end
    f = {"thr": {str(k): {"t": t, "e": e, "reason": "event" if e else "tripEnd", "afterGap": False} for k in (60, 70, 80)}, "lastValidS": last, "tripEndS": end}
    return {"status": "cold", "startC": float(start), "lagFirstValidS": 0.0, "coolant": f, "oil": dict(f, startC=float(start), lagFirstValidS=0.0)}


def block_of(recs, days):
    return M.build_block(recs, [{} for _ in recs], days, ["warm"] * len(recs), C)


# base dataset used in all three strata (identical within-stratum curves)
rng = np.random.default_rng(1)
base = []
for k in range(120):
    ev = rng.random() < 0.6
    tt = float(rng.integers(100, 900)) if ev else float(rng.integers(80, 1200))
    base.append((tt, ev))
recs, days = [], []
st_values = {0: 20, 1: 40, 2: 55}
for s_, stv in st_values.items():
    for k, (tt, ev) in enumerate(base):
        recs.append(rec(stv, tt, ev)); days.append("2026-06-%03d" % (s_ * 40 + k // 3))
mb = block_of(recs, days)
blk = S.build_block(recs, days, mb, C)                                       # G1 (partition, pooled = M435) and the E1 / F_high identities are checked inside; a failure raises
assert blk["checks"]["allOk"]
cell = blk["cells"]["coolant/80"]
assert sum(s_["n"] for s_ in cell["strata"]) == cell["n"] == len(recs) and abs(sum(cell["weights"]) - 1.0) < 1e-5     # (ii) partition

# ---- post-hoc profile leaf and notes (Director ruling): hand-computed on the synthetic strata (distance 2 / 4 / 6 km, start hour 8 / 9 / 12)
sidx = S.assign(np.array([r["startC"] for r in recs]), blk["cutPointsC"])
meta = [{"distanceKm": 2.0 * (int(i) + 1), "startHour": [8, 9, 12][int(i)]} for i in sidx]
bm = S.build_block(recs, days, mb, C, meta)
prof = [s_["profilePostHoc"] for s_ in bm["cells"]["coolant/80"]["strata"]]
assert [p_["medianDistanceKm"] for p_ in prof] == [2.0, 4.0, 6.0] and [p_["shareUnder5km"] for p_ in prof] == [1.0, 1.0, 0.0] and [p_["shareStartBefore10h"] for p_ in prof] == [1.0, 1.0, 0.0]
assert all("post-hoc" in p_["label"] for p_ in prof) and "no gradient across the terciles is claimed" in bm["cells"]["coolant/80"]["notes"]["pattern"] and "not evidence that censoring can be ignored" in bm["cells"]["coolant/80"]["notes"]["dNote"]

# ---- (iv) identical within-stratum curves: pooled = strata, D = 0
allcold = np.array([r["startC"] for r in recs])
strat = S.assign(allcold, S.cut_points(allcold))
t_ = np.array([r["coolant"]["thr"]["80"]["t"] for r in recs]); e_ = np.array([r["coolant"]["thr"]["80"]["e"] for r in recs]); d_ = np.array(days)
uni = np.array(sorted(set(days))); counts = T.day_counts(uni, 400, 42)
subs = [S.StratCell(t_[strat == s], e_[strat == s], d_[strat == s], counts, uni) for s in range(3)]
pooled = S.StratCell(t_, e_, d_, counts, uni)
w = [float((strat == s).mean()) for s in range(3)]
pds = [sc.point_and_draws(600, tilt=False) for sc in subs]
ent, ok_id = S.standardize(pooled, w, 600, pds, tilt=False)
e2s = [pd_["E2"][0] for pd_ in pds]
assert max(e2s) - min(e2s) < 1e-12 and abs(pooled.point_and_draws(600, tilt=False)["E2"][0] - e2s[0]) < 1e-12, e2s
assert abs(ent["D"]["point"]) < 1e-12 and ok_id

# ---- (iii) the identities E1_std = E1 and F_high_std = F_high, point estimate and every draw, on data with different curves
rng = np.random.default_rng(9)
t2 = rng.integers(50, 1000, 300).astype(float); e2_ = rng.random(300) < 0.5; d2 = rng.integers(0, 60, 300); s2 = rng.integers(0, 3, 300)
u2 = np.array(sorted(set(d2.tolist()))); c2 = T.day_counts(u2, 300, 42)
sc2 = [S.StratCell(t2[s2 == s], e2_[s2 == s], d2[s2 == s], c2, u2) for s in range(3)]
pl2 = S.StratCell(t2, e2_, d2, c2, u2)
w2 = [float((s2 == s).mean()) for s in range(3)]
pds2 = [sc.point_and_draws(600, tilt=False) for sc in sc2]
ent2, ok2 = S.standardize(pl2, w2, 600, pds2, tilt=False)
assert ok2

# ---- (vi) an unsupported stratum: 'not available', never renormalized
recs6, days6 = [], []
for s_, stv in st_values.items():
    for k in range(60):
        recs6.append(rec(stv, float(100 + k), True) if s_ == 2 else rec(stv, float(1000 + k), False))      # stratum 3: all events early, nobody at risk at 900 s
        days6.append("2026-07-%03d" % (s_ * 30 + k // 3))
b6 = S.build_block(recs6, days6, block_of(recs6, days6), C)
std6 = b6["cells"]["coolant/80"]["standardized"]
assert std6["900"]["available"] is False and "not supported" in std6["900"]["reason"]

# ---- (vii) the contrast interval is the interval of the paired draws from the shared resample set
c31 = pds2[2]["E2"][1] - pds2[0]["E2"][1]
vv = pds2[2]["valid"] & pds2[0]["valid"]
assert ent2["contrasts"]["stratum3_minus_1"]["E2"]["ci95"] == [round(x, 4) for x in T.pct(c31[vv])]

# ---- (ix) fixed seeds reproduce
ent3, _ = S.standardize(pl2, w2, 600, [sc.point_and_draws(600, tilt=False) for sc in sc2], tilt=False)
assert ent3 == ent2

# ---- (v) different stratum curves + stratum-dependent censoring (colder strata stop earlier): the pooled estimate is biased, the standardized one is not
K = 1.5
SCALE = (1300.0, 750.0, 420.0); CMEAN = (250.0, 700.0, 2500.0)
truth = float(np.mean([1 - np.exp(-(600.0 / sc_) ** K) for sc_ in SCALE]))
bias_p, bias_s = [], []
for sim in range(200):
    r_ = np.random.default_rng(100 + sim)
    ts, es, ss, ds = [], [], [], []
    for s_ in range(3):
        n_ = 500
        ev = SCALE[s_] * r_.exponential(size=n_) ** (1 / K); ce = r_.exponential(CMEAN[s_], n_)
        ts += list(np.ceil(np.minimum(ev, ce))); es += list(ev <= ce); ss += [s_] * n_; ds += list(range(s_ * n_, (s_ + 1) * n_))
    ts, es, ss, ds = np.array(ts), np.array(es), np.array(ss), np.array(ds)
    cells_ = [T.Cell(ts[ss == s_], es[ss == s_], ds[ss == s_]) for s_ in range(3)]
    f_s = [1 - c_.surv_at(c_.surv_steps(c_.ones()), 600.0)[0, 0] for c_ in cells_]
    pc = T.Cell(ts, es, ds); fp = 1 - pc.surv_at(pc.surv_steps(pc.ones()), 600.0)[0, 0]
    bias_s.append(float(np.mean(f_s)) - truth); bias_p.append(fp - truth)
se = lambda x: np.std(x, ddof=1) / np.sqrt(len(x))
print("pooled bias %+.4f (se %.4f), standardized bias %+.4f (se %.4f), truth %.4f" % (np.mean(bias_p), se(bias_p), np.mean(bias_s), se(bias_s), truth))
assert abs(np.mean(bias_s)) <= 3 * se(bias_s)
assert abs(np.mean(bias_p)) >= 3 * se(bias_p) and abs(np.mean(bias_p)) >= 0.03

# ---- (viii) coverage simulation of E2_std(600) and of the stratum-3-minus-stratum-1 contrast
live = pd.read_csv("analyses/M435_result_per_drive.csv.gz")
SPANS = live[(live.fluid == "coolant") & (live.thresholdC == 80)]["tripEndS"].values.astype(float)
V = 0.5
BETA = 0.03


def gen(r, ndays, KK, SCL, ref_cuts):
    t_, e_, d_, st_, ev_all = [], [], [], [], []
    for d in range(ndays):
        z, zc = r.gamma(1 / V, V), r.gamma(1 / V, V)
        m = r.poisson(3.4)
        if m == 0:
            continue
        start = np.rint(np.clip(40 + 6 * np.log(z) + r.normal(0, 12, m), 5, 59))
        ev = SCL * (r.exponential(size=m) / (z * np.exp(BETA * (start - 40)))) ** (1 / KK)
        mult = np.where(start < ref_cuts[0], 0.6, np.where(start < ref_cuts[1], 1.0, 1.4))
        ce = r.choice(SPANS, m) * zc * mult
        t_ += list(np.ceil(np.minimum(ev, ce))); e_ += list(ev <= ce); d_ += [d] * m; st_ += list(start); ev_all += list(ev)
    return np.array(t_), np.array(e_, bool), np.array(d_), np.array(st_), np.array(ev_all)


for KK in (1.5, 1.0):
    SCL = 800.0
    _, _, _, st_ref, ev_ref = gen(np.random.default_rng(777), 60000, KK, SCL, [30.0, 48.0])        # large reference sample: latent event times, reference cuts and the truth
    rcut = S.cut_points(st_ref); sref = S.assign(st_ref, rcut)
    truth_std = float((ev_ref <= 600).mean())
    truth_c = float((ev_ref[sref == 2] <= 600).mean() - (ev_ref[sref == 0] <= 600).mean())
    cov_s = cov_c = n_int = n_na = 0
    for sim in range(400):
        r_ = np.random.default_rng(31000 + sim + int(10 * KK))
        t_, e_, d_, st_, _ = gen(r_, 113, KK, SCL, rcut)
        strat_ = S.assign(st_, S.cut_points(st_))                       # cut points recomputed in every simulation
        uni_ = np.unique(d_); cnt = T.day_counts(uni_, 400, 1000 + sim)
        if not all((strat_ == s_).any() for s_ in range(3)):
            n_na += 1
            continue
        scs = [S.StratCell(t_[strat_ == s_], e_[strat_ == s_], d_[strat_ == s_], cnt, uni_) for s_ in range(3)]
        pl = S.StratCell(t_, e_, d_, cnt, uni_)
        if any(not sc.supported(600) for sc in scs):
            n_na += 1
            continue
        w_ = [float((strat_ == s_).mean()) for s_ in range(3)]
        en, _ = S.standardize(pl, w_, 600, [sc.point_and_draws(600, tilt=False) for sc in scs], tilt=False)
        ci_s = en["E2std"]["ci95"]; ci_c = en["contrasts"]["stratum3_minus_1"]["E2"]["ci95"]
        if ci_s is None or ci_c is None:
            n_na += 1
            continue
        n_int += 1
        cov_s += ci_s[0] <= truth_std <= ci_s[1]; cov_c += ci_c[0] <= truth_c <= ci_c[1]
    a, b = cov_s / max(n_int, 1), cov_c / max(n_int, 1)
    print("K=%.1f: coverage E2_std %.3f, contrast %.3f over %d simulations with an interval (%d not available); truth %.3f, contrast truth %.3f" % (KK, a, b, n_int, n_na, truth_std, truth_c))
    assert n_int >= 300, "not evaluable: fewer than 300 simulations produced an interval (goes to the Director)"
    assert 0.92 <= a <= 0.98, "GATE: E2_std coverage (K=%.1f)" % KK
    assert 0.92 <= b <= 0.98, "GATE: contrast coverage (K=%.1f)" % KK
print("OK test_m438_strata")
