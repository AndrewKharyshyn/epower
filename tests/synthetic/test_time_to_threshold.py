"""M435 known-answer tests (spec analyses/M435_spec.md Rev 2, section 8; criteria declared there before any result): tools/time_to_threshold.py estimators.
(i) no censoring: Kaplan-Meier = empirical distribution; (ii) hand-computed 8-drive product-limit example; (iii) theta = 1 equals KM and the EXACT theta limits;
(iv) Manski bounds bracket KM and every tilt row; (v) median unidentified / +inf draws; (vi) support rule; (viii) coverage simulation with day frailty (GATE 0.92-0.98) and the informative-censoring scenario."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import time_to_threshold as T

# ---- (i) no censoring
rng = np.random.default_rng(1)
t = rng.integers(1, 400, 60).astype(float)
c = T.Cell(t, np.ones(60, bool), np.arange(60))
S = c.surv_steps(c.ones())
for h in (10, 100, 250, 399, 500):
    assert abs(c.surv_at(S, h)[0, 0] - (t > h).mean()) < 1e-12, h
    lo, hi = c.manski(c.ones(), h)
    assert abs(lo[0] - (t <= h).mean()) < 1e-12 and abs(hi[0] - lo[0]) < 1e-12        # no censoring: both bounds equal the empirical F

# ---- (ii) hand example: (time, event) = (2,1)(3,0)(3,1)(5,1)(6,0)(8,1)(8,0)(9,0); events before censorings at ties
c = T.Cell([2, 3, 3, 5, 6, 8, 8, 9], [1, 0, 1, 1, 0, 1, 0, 0], [1, 1, 2, 2, 3, 3, 4, 4])
S = c.surv_steps(c.ones())
assert np.allclose(S[0], [0.875, 0.75, 0.6, 0.4])                                     # 7/8 ; x6/7 ; x4/5 ; x2/3
assert np.allclose(c.surv_at(S, [1, 2, 2.5, 3, 4, 5, 7, 8, 100])[0], [1, .875, .875, .75, .75, .6, .6, .4, .4])
assert abs(c.rmst(S, 9)[0] - (2 * 1 + 1 * .875 + 2 * .75 + 3 * .6 + 1 * .4)) < 1e-12   # integral of S over [0, 9]
assert c.at_risk(3) == (7, 4) and c.at_risk(9) == (1, 1)
lo, hi = c.manski(c.ones(), 6)                                                        # reached by 6: 3 ; censored strictly before 6: (3,c) -> 1 ; n = 8
assert abs(lo[0] - 3 / 8) < 1e-12 and abs(hi[0] - 4 / 8) < 1e-12
lo, hi = c.manski(c.ones(), 3)                                                        # censored strictly before 3: none (c = 3 is not < 3)
assert abs(lo[0] - 2 / 8) < 1e-12 and abs(hi[0] - 2 / 8) < 1e-12

# ---- (iii) theta = 1 equals KM; exact limits
for seed in range(8):
    r = np.random.default_rng(seed)
    n = int(r.integers(30, 120))
    tt = r.integers(5, 500, n).astype(float); ee = r.random(n) < 0.55
    cc = T.Cell(tt, ee, r.integers(0, 15, n))
    W = cc.ones(); S = cc.surv_steps(W)
    for h in (50, 120, 300, 480, 600):
        km = cc.surv_at(S, h)[0, 0]
        assert abs(cc.tilt_surv(W, S, h, 1.0)[0] - km) < 1e-12, (seed, h)             # redistribution to the right
        assert abs(cc.tilt_surv(W, S, h, 1e9)[0] - T.tilt_limit_inf(cc, h)) < 1e-6, (seed, h)
        assert abs(cc.tilt_surv(W, S, h, 1e-9)[0] - T.tilt_limit_zero(cc, h)) < 1e-6, (seed, h)
        lo, hi = cc.manski(W, h)
        Fk = 1 - km
        assert lo[0] - 1e-12 <= Fk <= hi[0] + 1e-12                                   # (iv) bracket KM
        for th in (0.25, 0.5, 2, 4, 1e-9, 1e9):
            Ft = 1 - cc.tilt_surv(W, S, h, th)[0]
            assert lo[0] - 1e-9 <= Ft <= hi[0] + 1e-9, (seed, h, th)                  # (iv) bracket every tilt row
        Fs = [1 - cc.tilt_surv(W, S, h, th)[0] for th in (0.25, 0.5, 1, 2, 4)]
        assert all(a <= b + 1e-12 for a, b in zip(Fs, Fs[1:])), "F_theta must increase with theta"
# S_KM reaching 0: the last observation is an event and everyone is still at risk; theta -> 0 limit counts censored-before-h as 0 when S(h) = 0
c0 = T.Cell([1, 2, 3, 4], [1, 0, 1, 1], [1, 2, 3, 4]); W = c0.ones(); S = c0.surv_steps(W)
assert c0.surv_at(S, 4)[0, 0] == 0.0
assert abs(c0.tilt_surv(W, S, 4, 1e-9)[0] - T.tilt_limit_zero(c0, 4)) < 1e-6 and T.tilt_limit_zero(c0, 4) == 0.0
# tipping point by bisection on log theta
cc = T.Cell(np.r_[np.full(30, 100.0), np.full(70, 900.0)], np.r_[np.ones(30, bool), np.zeros(70, bool)], np.arange(100))
th = T.bisect_tipping(cc, 600.0, level=0.5)
assert th is None or abs(1 - cc.tilt_surv(cc.ones(), cc.surv_steps(cc.ones()), 600.0, th)[0] - 0.5) < 1e-9
cc2 = T.Cell(np.r_[np.full(20, 100.0), np.full(30, 200.0), np.full(20, 400.0), np.full(30, 900.0)], np.r_[np.ones(20, bool), np.zeros(30, bool), np.ones(20, bool), np.zeros(30, bool)], np.arange(100))
th2 = T.bisect_tipping(cc2, 600.0, level=0.5)
assert th2 is not None and abs(th2 - np.log(2 / 3) / np.log(0.6)) < 1e-9 and abs(1 - cc2.tilt_surv(cc2.ones(), cc2.surv_steps(cc2.ones()), 600.0, th2)[0] - 0.5) < 1e-9
assert T.bisect_tipping(cc2, 600.0, level=0.99) is None                               # never crosses inside [0.01, 100]

# ---- (v) median
c = T.Cell([10, 20, 30, 40], [1, 0, 0, 0], [1, 2, 3, 4]); S = c.surv_steps(c.ones())
assert c.median_time(S)[0] == np.inf                                                  # S stays at 0.75
c = T.Cell([10, 20, 30, 40, 50], [1, 1, 1, 0, 0], [1, 2, 3, 4, 5]); S = c.surv_steps(c.ones())
assert c.median_time(S)[0] == 30.0                                                    # S = .8, .6, .4 -> first <= 0.5 at 30
W = c.draws(400, 42); Sb = c.surv_steps(W); m = c.median_time(Sb)
assert np.isinf(m).any() and (np.isinf(T.pct(m)[1]) == (np.mean(np.isinf(m)) > 0.025))   # +inf draws stay in the percentile

# ---- (vi) support rule inputs: 9 at risk on 4 days is below 10 / 5
c = T.Cell(np.r_[np.full(9, 700.0), np.full(20, 100.0)], np.r_[np.zeros(9, bool), np.ones(20, bool)], np.r_[[1, 1, 2, 2, 3, 3, 4, 4, 4], np.arange(10, 30)])
n_, d_ = c.at_risk(600)
assert (n_, d_) == (9, 4) and not (n_ >= 10 and d_ >= 5)

# ---- shared resamples: weights from one set of day counts over a universe equal the cell's own draws when the universe is the cell's days; bisect_limit crosses where the percentile does
c = T.Cell(np.r_[np.full(30, 100.0), np.full(30, 200.0), np.full(20, 400.0), np.full(20, 900.0)], np.r_[np.ones(30, bool), np.zeros(30, bool), np.ones(20, bool), np.zeros(20, bool)], np.repeat(np.arange(25), 4))
cnt = T.day_counts(c.days, 200, 42)
assert np.array_equal(c.draws(200, 42), c.weights(cnt, c.days)) and (cnt.sum(axis=1) == len(c.days)).all()
Wb = c.weights(cnt, c.days); Sb = c.surv_steps(Wb)
for side in ("upper", "lower"):
    th = T.bisect_limit(c, Wb, Sb, 600.0, side)
    if th is not None:
        q = 97.5 if side == "upper" else 2.5
        assert abs(np.percentile(1 - c.tilt_surv(Wb, Sb, 600.0, th), q) - 0.5) < 0.02          # tolerance 0.01 in log theta
Fb = [np.percentile(1 - c.tilt_surv(Wb, Sb, 600.0, th), 97.5) for th in (0.25, 0.5, 1, 2, 4)]
assert all(a <= b + 1e-12 for a, b in zip(Fb, Fb[1:]))                                          # the percentile of F_theta is monotone in theta (C4)

# ---- (viii) coverage simulation matching the live structure (113 days, Poisson 3.4/day, gamma day frailty var 0.5 on events AND on the censoring times, censoring times resampled from the
# live cold-start spans, 1 Hz, 30-60 % censoring); the gate applies per scenario (Weibull shape 1.5 and exponential events)
import pandas as pd
live = pd.read_csv("analyses/M435_result_per_drive.csv.gz")
SPANS = live[(live.fluid == "coolant") & (live.thresholdC == 80)]["tripEndS"].values.astype(float)
assert len(SPANS) > 300
V = 0.5


def scale_for(K):
    return 600 / ((1 / np.sqrt(0.55) - 1) / V) ** (1 / K)                                         # marginal F(600) = 0.45


def sim(r, K, SC):
    tt, ee, dd = [], [], []
    for d in range(113):
        z, zc = r.gamma(1 / V, V), r.gamma(1 / V, V)
        m = r.poisson(3.4)
        if m == 0:
            continue                                                                              # days without a drive are dropped
        ev = SC * (r.exponential(size=m) / z) ** (1 / K)
        ce = r.choice(SPANS, m) * zc
        tt += list(np.ceil(np.minimum(ev, ce))); ee += list(ev <= ce); dd += [d] * m
    return np.array(tt), np.array(ee, bool), np.array(dd)


for K in (1.5, 1.0):
    SC = scale_for(K)
    truth = lambda h: 1 - (1 + V * (h / SC) ** K) ** (-1 / V)
    r = np.random.default_rng(2026 + int(10 * K))
    cover = {600: 0, 1500: 0}; nsim = 400; cens_share = []; n15 = []
    for s_ in range(nsim):
        tt, ee, dd = sim(r, K, SC)
        cell = T.Cell(tt, ee, dd)
        cens_share.append(1 - ee.mean())
        Wd = cell.draws(400, 1000 + s_); Sb = cell.surv_steps(Wd)
        for h in cover:
            lo, hi = T.pct(1 - cell.surv_at(Sb, h)[:, 0])
            cover[h] += lo <= truth(h) <= hi
        n15.append(cell.at_risk(1500)[0])
    cov600, cov1500 = cover[600] / nsim, cover[1500] / nsim
    print("K=%.1f coverage F(600) %.3f ; F(1500) %.3f (mean at risk %.1f, not gated) ; censored share %.2f" % (K, cov600, cov1500, np.mean(n15), np.mean(cens_share)))
    assert 0.30 <= np.mean(cens_share) <= 0.60, (K, np.mean(cens_share))
    assert 0.92 <= cov600 <= 0.98, "GATE (K=%.1f): day-clustered 95 percent interval for F(600) covers the truth in [0.92, 0.98]" % K

# informative stopping: after the censoring time the remaining-time hazard is theta0 x the at-risk hazard, theta0 in {0.5, 2}; Kaplan-Meier is biased, the tilt row at theta0 recovers the truth
K, SC = 1.5, 763.0
H0 = lambda t: (t / SC) ** K
for TH0 in (0.5, 2.0):
    def sim_inf(r, n):
        c_ = r.choice(SPANS, n) * r.uniform(0.8, 1.2, n)
        t0 = SC * r.exponential(size=n) ** (1 / K)
        stop = t0 > c_
        t_lat = np.where(stop, SC * (H0(c_) + r.exponential(size=n) / TH0) ** (1 / K), t0)
        return np.ceil(np.minimum(t0, c_)), ~stop, t_lat
    _, _, tl = sim_inf(np.random.default_rng(7), 2_000_000)
    true_F = (tl <= 600).mean()
    bias_km, bias_t = [], []
    for s_ in range(200):
        tt, ee, _ = sim_inf(np.random.default_rng(5000 + s_), 1500)
        cell = T.Cell(tt, ee, np.arange(1500)); W = cell.ones(); S = cell.surv_steps(W)
        bias_km.append(1 - cell.surv_at(S, 600)[0, 0] - true_F)
        bias_t.append(1 - cell.tilt_surv(W, S, 600, TH0)[0] - true_F)
    se = lambda x: np.std(x, ddof=1) / np.sqrt(len(x))
    print("informative theta0=%.1f: Kaplan-Meier bias %+.4f (se %.4f), tilt(theta0) bias %+.4f (se %.4f), truth %.4f" % (TH0, np.mean(bias_km), se(bias_km), np.mean(bias_t), se(bias_t), true_F))
    assert abs(np.mean(bias_km)) > 2 * se(bias_km), "Kaplan-Meier must be biased by more than 2 Monte Carlo standard errors under informative stopping"
    assert abs(np.mean(bias_t)) < 2 * se(bias_t), "the tilt row at the true theta recovers the truth within two Monte Carlo standard errors"
print("OK test_time_to_threshold")
