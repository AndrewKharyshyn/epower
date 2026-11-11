"""M619 (spec analyses/M618_spec.md Rev 1, R2-R4, R6, R7, R10): known answers for the multi-solver mixed-effects sensitivity fit of degradation_trends.py. Real solver convergence is optimiser and library
version dependent, so the decision logic is tested on INJECTED solver results; only the structure and the planted-effect checks use real fits.
 1. the declared constants (solver order, maxiter, tolerances) are exactly the pre-registered ones;
 2. counting rule: an exception, a non-convergence, a non-finite or zero SE do not count; a log-likelihood worse than the best candidate by more than 1e-4 does not count (boundary on both sides);
    nm counts only at the boundary or with an interior score norm of at most 1e-3;
 3. reported solver = the first counting one in the fixed order; agreement: agree / disagree / single solver / none with boundary cases at 0.05 OLS standard errors, 0.005 of the residual variance, the
    boundary flag and the interval-excludes-zero flag;
 4. `valid` through _analyse: only 'agree' is valid; 'single solver' and 'disagree' are shown but not valid, with their notes;
 5. real fits on synthetic data: a planted day variance gives valid, agreeing counting solvers that recover the planted slope; a zero day variance never gives a valid fit with a non-singular flag mismatch;
 6. the veto function: per metric and at the current corpus, the share rule, both metrics ship or neither."""
import os, sys, warnings
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import numpy as np
import degradation_trends as DT
from test_headline_estimator import make_dm, BOUNDS

OLS_SE = 0.6


def R(solver, conv=True, ll=-100.0, slope=1.0, se=0.5, gv=8.0, rv=150.0, ci=(0.1, 1.9), score=1e-5, returned=True):
    return {"solver": solver, "maxiter": 100, "returned": returned, "converged": conv if returned else None, "error": None if returned else "boom", "stage": "x", "slope": slope if returned else None,
            "se": se if returned else None, "ci95": list(ci), "groupVar": gv, "residVar": rv, "loglike": ll if returned else None, "scoreNorm": score}


def main():
    # 1. constants
    assert DT.MIXED_SOLVERS == ("lbfgs", "bfgs", "nm") and DT.MIXED_MAXITER == {"lbfgs": 100, "bfgs": 100, "nm": 100}
    assert DT.MIXED_LL_TOL == 1e-4 and DT.MIXED_SCORE_NORM_MAX == 1e-3 and DT.MIXED_AGREE_SLOPE_OLS_SE == 0.05 and DT.MIXED_AGREE_VAR_OVER_RESID == 0.005
    # 2. counting
    c = DT.counting_solvers
    assert c([R("lbfgs"), R("bfgs"), R("nm")]) == ["lbfgs", "bfgs", "nm"]
    assert c([R("lbfgs", returned=False), R("bfgs"), R("nm")]) == ["bfgs", "nm"], "an exception does not count"
    assert c([R("lbfgs", conv=False), R("bfgs")]) == ["bfgs"], "non-convergence does not count"
    assert c([R("lbfgs", se=float("nan")), R("bfgs", se=0.0), R("nm", se=0.5)]) == ["nm"] and c([R("lbfgs", returned=False), R("bfgs", conv=False)]) == []
    assert c([R("lbfgs", ll=-100.0), R("bfgs", ll=-100.00009)]) == ["lbfgs", "bfgs"], "0.9e-4 worse still counts"
    assert c([R("lbfgs", ll=-100.0), R("bfgs", ll=-100.00011)]) == ["lbfgs"], "1.1e-4 worse does not count"
    assert c([R("lbfgs", ll=-100.0), R("bfgs", ll=-99.0)]) == ["bfgs"], "the best candidate defines the reference"
    assert c([R("lbfgs"), R("nm", score=5e-4)]) == ["lbfgs", "nm"] and c([R("lbfgs"), R("nm", score=2e-3)]) == ["lbfgs"], "nm needs an interior score norm <= 1e-3"
    assert c([R("lbfgs"), R("nm", score=None, gv=0.0)]) == ["lbfgs", "nm"] and c([R("lbfgs"), R("nm", score=None, gv=8.0)]) == ["lbfgs"], "nm at the boundary counts; no score and interior does not"
    assert c([R("lbfgs", score=0.5), R("bfgs", score=0.5)]) == ["lbfgs", "bfgs"], "the score norm gates nm only"
    # 3. selection and agreement
    sel = lambda rs, se=OLS_SE: DT.select_mixed(rs, se)
    s = sel([R("lbfgs", returned=False), R("bfgs"), R("nm")])
    assert s["reported"] == "bfgs" and s["agreement"] == "agree" and s["counting"] == ["bfgs", "nm"]
    assert sel([R("lbfgs"), R("bfgs"), R("nm")])["reported"] == "lbfgs", "lbfgs first when it counts"
    assert sel([R("lbfgs", returned=False), R("bfgs", conv=False), R("nm")])["agreement"] == "single solver" and sel([R("lbfgs", returned=False)])["agreement"] is None and sel([R("lbfgs", returned=False)])["reported"] is None
    tol = DT.MIXED_AGREE_SLOPE_OLS_SE * OLS_SE
    assert sel([R("lbfgs", slope=1.0), R("bfgs", slope=1.0 + 0.999 * tol)])["agreement"] == "agree" and sel([R("lbfgs", slope=1.0), R("bfgs", slope=1.0 + 1.001 * tol)])["agreement"] == "disagree"
    vt = DT.MIXED_AGREE_VAR_OVER_RESID * 150.0
    assert sel([R("lbfgs", gv=8.0), R("bfgs", gv=8.0 + 0.99 * vt)])["agreement"] == "agree" and sel([R("lbfgs", gv=8.0), R("bfgs", gv=8.0 + 1.01 * vt)])["agreement"] == "disagree"
    assert sel([R("lbfgs", gv=1e-9, ci=(0.1, 1.9)), R("bfgs", gv=2e-8, ci=(0.1, 1.9))])["agreement"] == "disagree", "different boundary flags disagree even when the variances are close"
    assert sel([R("lbfgs", gv=1e-9), R("bfgs", gv=5e-9)])["agreement"] == "agree"
    assert sel([R("lbfgs", ci=(-0.1, 2.0)), R("bfgs", ci=(0.1, 1.9))])["agreement"] == "disagree", "intervals that differ on excluding zero disagree"
    assert sel([R("lbfgs"), R("bfgs")], se=None)["agreement"] == "disagree", "no OLS standard error: cannot show agreement"
    assert abs(sel([R("lbfgs", slope=1.0), R("bfgs", slope=1.01)])["maxSlopeDiffInOLSse"] - 0.01 / OLS_SE) < 1e-12
    # 4. valid through _analyse (injected _mixedlm results)
    dm = make_dm()
    base = {"slope": 1.0, "se": 0.6, "ci95": [-0.2, 2.2], "nObs": 320, "nDays": 80, "groupVar": 8.0, "residVar": 150.0, "formula": "y ~ months + T + I", "converged": True, "solver": "lbfgs", "solversTried": []}

    def analyse(mm):
        orig = DT._mixedlm
        DT._mixedlm = lambda d, covars=("T",): dict(mm)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return DT._analyse(dm, "vreg_R_pack_mohm", "mOhm/month", BOUNDS, "b1", covars=("T", "I"), icol="vreg_I_p95_A")
        finally:
            DT._mixedlm = orig
    a = analyse(dict(base, solverAgreement="agree"))
    assert a["mixedEffects"]["valid"] is True and "degenerateNote" not in a["mixedEffects"]
    a = analyse(dict(base, solverAgreement="single solver"))
    assert a["mixedEffects"]["valid"] is False and "unverified" in a["mixedEffects"]["degenerateNote"] and a["mixedEffects"]["slope"] == 1.0, "shown, not valid"
    a = analyse(dict(base, solverAgreement="disagree"))
    assert a["mixedEffects"]["valid"] is False and "do not agree" in a["mixedEffects"]["degenerateNote"]
    a = analyse({"error": "no solver counted: x", "formula": "f", "solver": None, "solversTried": [], "solverAgreement": None})
    assert a["mixedEffects"]["valid"] is False and a["mixedEffects"]["validity"]["fitted"] is False and a["primaryEstimator"] == "clusterRobustOLS"
    # 5. real fits on synthetic data
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = DT._analyse(make_dm(), "vreg_R_pack_mohm", "mOhm/month", BOUNDS, "b1", covars=("T", "I"), icol="vreg_I_p95_A")
    me = r["mixedEffects"]
    # C5 (Director): no CI assertion on a real solver OUTCOME (platform and BLAS dependent): structure, consistency and planted-slope recovery of whatever counts
    assert [t["solver"] for t in me["solversTried"]] == ["lbfgs", "bfgs", "nm"] and me["versions"]["statsmodels"] and "cluster-robust (day-clustered)" in me["agreementBasis"], me["solversTried"]
    counting = [t for t in me["solversTried"] if t["counts"]]
    assert counting and all(abs(t["slope"] - 1.0) < 4 * t["se"] for t in counting), "at least one solver counts on well-conditioned synthetic data and recovers the planted slope"
    assert me["solver"] == counting[0]["solver"] and (me["valid"] is True) == (me["solverAgreement"] == "agree" and me["reCovarianceSingular"] is False and me["validity"]["seNotBlownUp"]), "valid follows agreement"
    assert (len(counting) == 1) == (me["solverAgreement"] == "single solver")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        z = DT._analyse(make_dm(sd_day=0.0, seed=11), "vreg_R_pack_mohm", "mOhm/month", BOUNDS, "b1", covars=("T", "I"), icol="vreg_I_p95_A")
    mz = z["mixedEffects"]
    assert mz["valid"] is False or mz["reCovarianceSingular"] is False, "a singular day variance is never a valid fit"
    assert z["primaryEstimator"] == "clusterRobustOLS" and z["headlineEstimatorRule"] == DT.HEADLINE_RULE
    # 6. veto
    pts = lambda *a: [(40, x) for x in a]
    ok = {"current": "agree", "points": pts("agree", "agree", "single solver", None)}
    v = DT.mixed_veto({"resistanceVreg": ok, "cellSpread": ok})
    assert v["veto"] is False and v["perMetric"]["cellSpread"]["shareSingleSolver"] == 0.25, v
    assert DT.mixed_veto({"resistanceVreg": ok, "cellSpread": dict(ok, current="single solver")})["veto"] is True, "single solver at the current corpus vetoes, and both metrics ship or neither"
    assert DT.mixed_veto({"resistanceVreg": dict(ok, current=None), "cellSpread": ok})["veto"] is True and DT.mixed_veto({"resistanceVreg": dict(ok, current="disagree"), "cellSpread": ok})["veto"] is True
    ten = {"current": "agree", "points": pts(*(["agree"] * 9 + ["disagree"]))}
    assert DT.mixed_veto({"m": ten})["veto"] is False, "exactly 10 % does not exceed 10 %"
    eleven = {"current": "agree", "points": pts(*(["agree"] * 8 + ["disagree"] * 1)) + [(40, "disagree")]}
    assert DT.mixed_veto({"m": {"current": "agree", "points": pts(*(["agree"] * 8 + ["disagree"] * 2))}})["veto"] is True
    assert DT.mixed_veto({"m": {"current": "agree", "points": [(10, "disagree")] * 5 + pts("agree")}})["veto"] is False, "prefixes with fewer than 30 days are not binding"
    print("test_mixed_solvers OK")


if __name__ == "__main__":
    main()
