"""M614 (spec analyses/M614_spec.md Rev 1, T1-T4, T6, T7, T10, T11): the headline estimator of the degradation trends is the day-clustered cluster-robust OLS for every metric; the mixed model is a
sensitivity with separate validity components. Known answers on injected fits and on synthetic data, then an independent recomputation on the real corpus against the shipped payload.
 1. injected mixed fits (ok, SE blown up, failed, not converged, singular-but-unblown): the headline is always the OLS; validity components, `valid`, `degenerate` (legacy readers) and the note are right;
 2. synthetic data with a real day variance: the mixed fit is valid, the legacy rule would pick it, the headline still is the OLS;
 3. a boundary series: the retired rule flips at least once, the shipped rule never does;
 4. TOST fields and the OLS block are identical whatever the mixed fit did, and equal an independent _tost on the OLS slope / SE / t(G-1);
 5. `headlineVsMixed` has the right sign and value, and is null when the mixed fit failed;
 6. real corpus: shipped payload agrees with an independent statsmodels recomputation (OLS slope, SE, t(G-1) interval; mixed group / residual variance, variance ratio, SE ratio, singularity flag,
    headlineVsMixed) for resistanceVreg; cellSpread keeps its cluster-robust OLS headline."""
import json, os, sys, warnings
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import degradation_trends as DT

BOUNDS = [("b1", 0.5, "test bound")]
RULE = "fixed: clusterRobustOLS (M614)"


def make_dm(n_days=80, per_day=4, sd_day=3.0, sd_noise=3.0, slope=1.0, seed=7):
    rng = np.random.default_rng(seed)
    rows, t0 = [], pd.Timestamp("2026-05-11")
    for d in range(n_days):
        u = rng.normal(0, sd_day)
        for _ in range(per_day):
            T, I = rng.normal(25, 4), rng.normal(80, 10)
            y = 100 + slope * (d * 2 / 30.4375) + 0.5 * T + 0.1 * I + u + rng.normal(0, sd_noise)
            rows.append({"date": t0 + pd.Timedelta(days=2 * d), "ens_outlier_v2": False, "vreg_R_pack_mohm": y, "T_pack_mean_avg": T, "vreg_I_p95_A": I})
    return pd.DataFrame(rows)


def analyse(dm, inject=None):
    orig = DT._mixedlm
    if inject is not None:
        DT._mixedlm = lambda d, covars=('T',): dict(inject)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return DT._analyse(dm, "vreg_R_pack_mohm", "mOhm/month", BOUNDS, "b1", covars=("T", "I"), icol="vreg_I_p95_A")
    finally:
        DT._mixedlm = orig


OK = {"slope": 1.0, "se": 0.6, "ci95": [-0.2, 2.2], "nObs": 320, "nDays": 80, "groupVar": 8.0, "residVar": 150.0, "formula": "y ~ months + T + I", "converged": True, "solver": "lbfgs", "solverAgreement": "agree"}   # M619: the multi-solver fields an injected fit now carries
BLOWN = dict(OK, se=5.23e8, groupVar=1e-12)
FAILED = {"error": "LinAlgError('Singular matrix')", "formula": "y ~ months + T + I"}
NOCONV = dict(OK, converged=False)
SINGULAR_UNBLOWN = dict(OK, groupVar=0.0)


def main():
    dm = make_dm()
    # 1. injected fits
    for name, inj, valid, degenerate, legacy, note in (("ok", OK, True, False, "mixedEffects", None), ("blown", BLOWN, False, True, "clusterRobustOLS", "singular day random-effects covariance"),
                                                       ("failed", FAILED, False, True, "clusterRobustOLS", "failed to fit"), ("noconv", NOCONV, False, True, "clusterRobustOLS", "did not converge"),
                                                       ("singularUnblown", SINGULAR_UNBLOWN, False, False, "mixedEffects", "singular boundary")):
        r = analyse(dm, inj)
        me = r["mixedEffects"]
        assert r["primaryEstimator"] == "clusterRobustOLS" and r["headlineEstimatorRule"] == RULE, (name, r["primaryEstimator"])
        assert me["valid"] is valid and set(me["validity"]) == {"fitted", "converged", "seFinitePositive", "seNotBlownUp"}, (name, me)
        assert bool(me.get("degenerate", False)) is degenerate, (name, me.get("degenerate"))
        assert DT.legacy_primary(inj, r["clusterRobustOLS"])[0] == legacy, (name, "legacy rule")
        assert ("reCovarianceSingular" in me) and (me["reCovarianceSingular"] is (None if "groupVar" not in inj else bool(inj["groupVar"] <= 1e-8))), (name, me.get("reCovarianceSingular"))
        assert (note is None and "degenerateNote" not in me) or (note in me.get("degenerateNote", "")), (name, me.get("degenerateNote"))
        assert "mixed-effects headline" not in json.dumps(r) and "mixed primary" not in json.dumps(r)
    assert analyse(dm, SINGULAR_UNBLOWN)["mixedEffects"]["reCovarianceSingular"] is True and DT.legacy_primary(SINGULAR_UNBLOWN, analyse(dm, OK)["clusterRobustOLS"])[1] is True   # the M155 flaw (R2): singular yet "ok"
    # 2. real day variance, no injection
    r2 = analyse(dm)
    me2 = r2["mixedEffects"]
    assert me2["valid"] is True and me2["reCovarianceSingular"] is False and me2["varianceRatio"] > 0.2 and r2["primaryEstimator"] == "clusterRobustOLS"
    assert DT.legacy_primary(me2, r2["clusterRobustOLS"])[0] == "mixedEffects", "the retired rule would have picked the mixed model here"
    assert abs(me2["slope"] - 1.0) < 4 * me2["se"] and abs(r2["clusterRobustOLS"]["slope"] - 1.0) < 4 * r2["clusterRobustOLS"]["se"]
    # 3. boundary series: legacy flips, shipped never
    seq = (OK, SINGULAR_UNBLOWN, OK, BLOWN, OK, OK)
    co = analyse(dm, OK)["clusterRobustOLS"]
    legacy = [DT.legacy_primary(m, co)[0] for m in seq]
    shipped = [analyse(dm, m)["primaryEstimator"] for m in seq]
    flips = lambda xs: sum(1 for a, b in zip(xs, xs[1:]) if a != b)
    assert flips(legacy) >= 1 and flips(shipped) == 0, (legacy, shipped)
    # 4. TOST and OLS identical whatever the mixed fit did; equal to an independent _tost
    keys = ("tostEstimatorBasis", "tostSlopeUsed", "tostSeUsed", "tostCandidates", "releasedEquivalence", "equivalenceBoundStatus", "clusterRobustOLS", "nObs", "nDays", "windowMonths")
    base = analyse(dm, OK)
    for inj in (BLOWN, FAILED, NOCONV, SINGULAR_UNBLOWN, None):
        other = analyse(dm, inj)
        assert all(base[k] == other[k] for k in keys), inj
    c = base["clusterRobustOLS"]
    ind = DT._tost(c["slope"], c["se"], BOUNDS[0][1], df=c["nDays"] - 1)
    assert base["releasedEquivalence"]["pTOST"] == ind["pTOST"] and base["tostSlopeUsed"] == round(c["slope"], 4)
    # 5. headlineVsMixed
    assert analyse(dm, FAILED)["headlineVsMixed"] is None
    hv = analyse(dm, OK)["headlineVsMixed"]
    assert abs(hv - round((OK["slope"] - c["slope"]) / c["se"], 3)) < 1e-9 and np.sign(hv) == np.sign(OK["slope"] - c["slope"]), hv
    assert analyse(dm, dict(OK, slope=c["slope"] - 2 * c["se"]))["headlineVsMixed"] < 0 < analyse(dm, dict(OK, slope=c["slope"] + 2 * c["se"]))["headlineVsMixed"]
    # 6. real corpus, independent recomputation against the shipped payload
    import statsmodels.api as sm, statsmodels.formula.api as smf
    from scipy import stats
    A = json.load(open("summary_arrays.json", encoding="utf-8"))["degradationTrends"]
    m = pd.read_csv("drive_master.csv")
    m = m[~m["ens_outlier_v2"].astype(str).str.lower().isin(["true", "1"])].copy()
    m["date"] = pd.to_datetime(m["date"])
    m = m.dropna(subset=["vreg_R_pack_mohm", "date", "T_pack_mean_avg", "vreg_I_p95_A"])
    m["months"] = (m["date"] - m["date"].min()).dt.total_seconds() / (30.4375 * 86400)
    m["day"] = m["date"].dt.date.astype(str)
    m["y"], m["T"], m["I"] = m["vreg_R_pack_mohm"].astype(float), m["T_pack_mean_avg"].astype(float), m["vreg_I_p95_A"].astype(float)
    P = A["resistanceVreg"]
    assert P["primaryEstimator"] == "clusterRobustOLS" and P["headlineEstimatorRule"] == RULE and P["nObs"] == len(m) and P["nDays"] == m["day"].nunique(), (P["primaryEstimator"], P["nObs"], len(m))
    X = sm.add_constant(m[["months", "T", "I"]])
    ols = sm.OLS(m["y"].values, X).fit(cov_type="cluster", cov_kwds={"groups": m["day"].values})
    G = m["day"].nunique()
    b, se = float(ols.params["months"]), float(ols.bse["months"])
    t = stats.t.ppf(0.975, G - 1)
    o = P["clusterRobustOLS"]
    assert abs(o["slope"] - b) < 6e-4 and abs(o["se"] - se) < 6e-4 and abs(o["ci95"][0] - (b - t * se)) < 6e-4 and abs(o["ci95"][1] - (b + t * se)) < 6e-4, (o["slope"], b)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = smf.mixedlm("y ~ months + T + I", m, groups=m["day"]).fit(method="lbfgs", reml=True, disp=False)
    gv, rv = float(np.asarray(fit.cov_re)[0, 0]), float(fit.scale)
    me = P["mixedEffects"]
    assert abs(me["groupVar"] - gv) < 2e-3 * gv and abs(me["residVar"] - rv) < 2e-3 * rv, (me["groupVar"], gv, me["residVar"], rv)
    assert abs(me["varianceRatio"] - gv / rv) < 1e-3 and me["reCovarianceSingular"] is bool(gv <= 1e-8)
    assert abs(me["seRatioToOLS"] - float(fit.bse_fe["months"]) / se) < 5e-3, (me["seRatioToOLS"], float(fit.bse_fe["months"]) / se)
    assert abs(P["headlineVsMixed"] - (float(fit.fe_params["months"]) - b) / se) < 5e-3
    cs = A["cellSpread"]
    assert cs["primaryEstimator"] == "clusterRobustOLS" and cs["headlineEstimatorRule"] == RULE and cs["clusterRobustOLS"]["slope"] is not None
    print("test_headline_estimator OK")


if __name__ == "__main__":
    main()
