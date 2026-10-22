"""M480 known-answer tests (analyses/M480_spec.md Rev 2): recovery of a known time slope, a regime step correlated with time (the leaked case must not be 'supported'), an imprecise
design, each outcome of the decision rule, transforms, p95 sample-size dependence, CR1 = released, CR2 = HC2 on singleton clusters, the S0 reproduction stop, VIF and leverage.
Run: python tests/synthetic/test_m480.py"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import degradation_trends as DT                 # noqa: E402
import dependence_sensitivity as DS             # noqa: E402
import m480_spread_sensitivity as M             # noqa: E402

B = 200


def ok(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + ((" -- " + str(detail)) if not cond else ""))
    if not cond:
        ok.bad += 1


ok.bad = 0


def make_frame(seed=1, n_days=100, per_day=5, slope=0.5, noise=0.4, leak_step=0.0, collinear=False, flip_p=0.02):
    rng = np.random.default_rng(seed)
    day_idx = np.repeat(np.arange(n_days), per_day)
    months = day_idx / n_days * 12.0 + rng.uniform(0, 0.05, len(day_idx))
    n = len(day_idx)
    f = pd.DataFrame({"months": months, "T": rng.normal(25, 6, n), "I": rng.normal(150, 20, n), "day": ["d%03d" % i for i in day_idx]})
    f["date"] = pd.Timestamp("2026-05-01") + pd.to_timedelta(day_idx, unit="D")
    step = (months > 6).astype(float)
    flip = rng.random(n) < flip_p
    for c in M.DRIFT_COLS:
        f[c] = rng.normal(0, 1, n)
    f["gt3_ind"] = np.where(flip, 1 - step, step) if leak_step else (rng.random(n) < 0.3).astype(float)
    if collinear:
        f["i_dt_q50"] = months + rng.normal(0, 1e-4, n)
    f["n_loaded"] = rng.integers(40, 300, n)
    f["n_episodes"] = rng.integers(3, 20, n)
    day_eff = rng.normal(0, 0.2, n_days)[day_idx]
    f["y"] = slope * months + 0.05 * f["T"] + 0.01 * f["I"] + leak_step * step + day_eff + rng.normal(0, noise, n)
    f["regime"] = np.where(months < 6, "fast", "slow")
    return f


# (1) recovery of a known slope with uncorrelated added covariates --------------------------------------------------------------------------------------------
res = M.analyse(make_frame(), B)
sl = {k: v["slope"] for k, v in res["specs"].items()}
ok("(1) S0 and S1-S4 recover the true slope 0.5 within 0.12 when the added covariates are unrelated to time", abs(res["S0"]["slope"] - 0.5) < 0.12 and all(abs(v - 0.5) < 0.12 for v in sl.values()), (res["S0"]["slope"], sl))
ok("(1) no specification is imprecise and the verdict is 'supported_provisional' with the pair-level caveat", all(v["label"] == "ok" for v in res["specs"].values()) and res["verdict"] == "supported_provisional"
   and "M480b" in res["verdictLabel"], (res["verdict"], {k: v["label"] for k, v in res["specs"].items()}))
ok("(1) every specification carries n, days, interval reference, VIF, partial R2, leverage days, CR2 and wild cluster rows", all(k in v for v in res["specs"].values() for k in ("n_drives", "n_days", "ciReference", "vif_months", "partial_r2_months_on_block", "days_for_half_leverage", "cr2", "wildClusterBootstrapT")))

# (2) regime step correlated with time: the leaked case must not be 'supported' ---------------------------------------------------------------------------------
res2 = M.analyse(make_frame(slope=0.0, leak_step=6.0), B)
ok("(2) leaked design: S0 slope equals the OLS slope of a 6 mV step at month 6 on a 12-month axis (6 * 1.5 / 12 = 0.75 by hand) although the true time slope is 0", abs(res2["S0"]["slope"] - 0.75) < 0.15 and res2["S0"]["ci95"][0] > 0, res2["S0"]["slope"])
ok("(2) the step covariate attenuates S2 and S4 to below half of S0|rows; the verdict is not 'supported'", res2["specs"]["S2"]["slope"] < 0.5 * res2["specs"]["S2"]["S0_on_rows"]["slope"]
   and res2["specs"]["S4"]["slope"] < 0.5 * res2["specs"]["S4"]["S0_on_rows"]["slope"] and res2["verdict"] != "supported_provisional", (res2["verdict"], res2["specs"]["S2"]["slope"]))

# (2b) limitation, recorded as a test: a NOISY proxy of the step (30 % of labels wrong) absorbs only part of the leaked slope, so the adjusted slope can stay above half of S0 -------------
res2b = M.analyse(make_frame(slope=0.0, leak_step=6.0, flip_p=0.3), B)
ok("(2b) limitation: with a poor proxy of the confound the adjusted S2 slope stays above half of S0|rows (a 'supported' verdict is conditional on the quality of the tested proxies)",
   res2b["specs"]["S2"]["slope"] > 0.5 * res2b["specs"]["S2"]["S0_on_rows"]["slope"], (res2b["specs"]["S2"]["slope"], res2b["specs"]["S2"]["S0_on_rows"]["slope"]))

# (3) imprecise design: a covariate nearly collinear with time -----------------------------------------------------------------------------------------------------
res3 = M.analyse(make_frame(collinear=True), B)
ok("(3) a covariate collinear with calendar time is labelled imprecise (VIF above 10) and excluded from the verdict count", res3["specs"]["S1"]["label"] == "imprecise" and res3["specs"]["S1"]["vif_months"] > 10, res3["specs"]["S1"]["vif_months"])

# (4) decision rule: each outcome --------------------------------------------------------------------------------------------------------------------------------
mk = lambda slope, lo, hi, s0=1.0, lab="ok": {"slope": slope, "ci95": [lo, hi], "s0": s0, "label": lab}
ok("(4) supported_provisional: all above half, three lower bounds above zero", M.verdict([mk(0.9, 0.2, 1.6)] * 4) == "supported_provisional")
ok("(4) not_supported: two specifications below half with the upper bound below S0", M.verdict([mk(0.2, -0.3, 0.7), mk(0.3, -0.2, 0.8), mk(0.9, 0.2, 1.6), mk(0.9, 0.2, 1.6)]) == "not_supported")
ok("(4) not_supported: a negative point estimate whose upper bound is below S0", M.verdict([mk(-0.4, -0.9, 0.5), mk(0.9, 0.2, 1.6), mk(0.9, 0.2, 1.6), mk(0.9, 0.2, 1.6)]) == "not_supported")
ok("(4) attenuated_inconclusive: a wide interval keeps a below-half estimate from counting as explained", M.verdict([mk(0.2, -1.5, 1.9), mk(0.9, 0.2, 1.6), mk(0.9, 0.2, 1.6), mk(0.9, 0.2, 1.6)]) == "attenuated_inconclusive")
ok("(4) attenuated_inconclusive: fewer than three non-imprecise specifications", M.verdict([mk(0.9, 0.2, 1.6), mk(0.9, 0.2, 1.6), mk(0.1, -2, 2, lab="imprecise"), mk(0.1, -2, 2, lab="imprecise")]) == "attenuated_inconclusive")
ok("(4) not_evaluable when S0 on the rows is not positive", M.verdict([mk(0.5, 0.1, 0.9, s0=-0.2)] * 4) == "not_evaluable")

# (5) transforms -----------------------------------------------------------------------------------------------------------------------------------------------------
t = M.add_transforms(pd.DataFrame({"n_loaded": [0, 9, np.nan], "i_gap20_s": [0.0, 59.0, 0.0], "i_frac_dt_gt3s": [0.0, 0.2, np.nan], "n_loaded_chg": [0, 3, 1]}))
ok("(5) log1p(0) = 0 (no break), log1p(gap), indicator of a positive share above 3 s, charge share undefined at zero loaded pairs",
   t["log1p_n_loaded"].iloc[0] == 0 and abs(t["log1p_n_loaded"].iloc[1] - np.log(10)) < 1e-12 and list(t["gt3_ind"].iloc[:2]) == [0.0, 1.0] and np.isnan(t["gt3_ind"].iloc[2])
   and np.isnan(t["chg_share"].iloc[0]) and abs(t["chg_share"].iloc[1] - 1 / 3) < 1e-12, t.to_dict("list"))

# (6) the p95 of a small sample is biased low relative to a large sample from the same distribution --------------------------------------------------------------
rng = np.random.default_rng(7)
small = np.mean([np.quantile(rng.gamma(4, 2, 5), 0.95) for _ in range(4000)])
large = np.mean([np.quantile(rng.gamma(4, 2, 400), 0.95) for _ in range(300)])
ok("(6) p95 of n=5 is lower on average than p95 of n=400 from the same distribution (sample-size dependence of the outcome)", small < large - 1.0, (small, large))

# (7) CR1 of the design equals the released _cluster_ols ---------------------------------------------------------------------------------------------------------
f = make_frame()
rel = DT._cluster_ols(f, covars=("T", "I"))
mine, _, _ = M.fit(f, [], 0)
ok("(7) S0 slope and interval equal the released cluster-robust OLS (t(G-1)) to 4 decimals", abs(mine["slope"] - rel["slope"]) < 1e-3 and abs(mine["ci95"][0] - rel["ci95"][0]) < 1e-3 and abs(mine["ci95"][1] - rel["ci95"][1]) < 1e-3, (mine["slope"], rel["slope"], mine["ci95"], rel["ci95"]))

# (8) CR2 equals HC2 when every cluster is a single observation ------------------------------------------------------------------------------------------------
g = make_frame(n_days=60, per_day=1)
g["day"] = ["u%d" % i for i in range(len(g))]
sg, Xg, yg = M.fit(g, ["i_dt_q50"], B, full=True)
hc2 = DS.hc2_equivalent_check(Xg, yg)[1]
ok("(8) CR2 standard error equals HC2 with singleton clusters", abs(sg["cr2"]["se"] - hc2) < 1e-8, (sg["cr2"]["se"], hc2))
ok("(8) the wild cluster row is deterministic for a fixed seed", M.fit(g, ["i_dt_q50"], B, full=True)[0]["wildClusterBootstrapT"] == sg["wildClusterBootstrapT"])

# (9) S0 reproduction guard ----------------------------------------------------------------------------------------------------------------------------------------------
try:
    M.analyse(make_frame(), B, released={"slope": 9.99, "nObs": 500, "nDays": 100})
    stopped = False
except SystemExit:
    stopped = True
ok("(9) a mismatch between S0 and the released model stops the run", stopped)

# (10) VIF and leverage ------------------------------------------------------------------------------------------------------------------------------------------------
Xc = np.column_stack([np.ones(100), np.linspace(0, 1, 100), np.zeros(100), np.zeros(100), np.linspace(0, 1, 100) + np.random.default_rng(3).normal(0, 1e-3, 100)])
vif, _ = M.months_diagnostics(Xc)
ok("(10) VIF of months is very large for a nearly collinear covariate", vif > 1e3, vif)
Xl = np.column_stack([np.ones(100), np.r_[np.zeros(95), np.full(5, 10.0)], np.zeros(100), np.zeros(100)])
nl, nd = M.leverage_days(Xl, np.arange(100) // 1)
ok("(10) five days carry all the leverage when months moves on five days only: half of it needs 3 days", nl == 3 and nd == 100, (nl, nd))

if ok.bad:
    sys.exit(1)
print("OK test_m480")
