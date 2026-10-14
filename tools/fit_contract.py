#!/usr/bin/env python3
"""F14 (external audit 2026-10-13): a strict, recorded GLM fit for NEW callers of the M119-v2 estimator.

m119v2_model.fit_glm runs the primary fit (cluster-robust covariance when groups are given, tol 1e-8) and, on ANY exception, silently refits with tol 1e-6 and scale=1.0, which can drop the clustered
covariance and accept a singular design without a record. The census (tools/fit_glm_census.py, analyses/F14_*.json) found 0 fallbacks in 549 replayed fits, so no published number came from that path; the
module itself is pinned by the M321 selection-code hash and is changed only together with the next M119 refit (docs/workflow-and-tools.md, refit checklist).

`fit_glm_strict` is the SAME primary estimator (identical parameters and covariance whenever the contract holds) with the contract made explicit: it never falls back and it raises FitContractError on an
exception of the primary fit, non-convergence, a rank-deficient design, non-finite parameters or a statsmodels ConvergenceWarning-class warning. It returns (result, record); the record is JSON-ready."""
import warnings
import numpy as np
import statsmodels.api as sm
from statsmodels.genmod.families.links import CLogLog, Logit


class FitContractError(RuntimeError):
    """The fit did not meet the estimator contract; the caller must treat the quantity as unavailable."""


def fit_glm_strict(X, y, groups=None, link="cloglog", maxiter=60):
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    rec = {"estimator": "GLM Binomial " + link, "n": int(X.shape[0]), "p": int(X.shape[1]), "covType": "cluster" if groups is not None else "nonrobust",
           "nGroups": int(len(np.unique(groups))) if groups is not None else None, "tol": 1e-8, "path": "primary"}
    fam = sm.families.Binomial(link=CLogLog() if link == "cloglog" else Logit())
    model = sm.GLM(y, X, family=fam)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        try:
            if groups is not None:
                res = model.fit(cov_type="cluster", cov_kwds={"groups": groups}, maxiter=maxiter, tol=1e-8)
            else:
                res = model.fit(maxiter=maxiter, tol=1e-8)
        except Exception as e:
            raise FitContractError("primary fit raised %s: %s" % (type(e).__name__, str(e)[:160])) from e
    rec["warnings"] = sorted({type(x.message).__name__ for x in w})
    rec["converged"] = bool(getattr(res, "converged", True))
    fh = getattr(res, "fit_history", None) or {}
    rec["iterations"] = int(fh.get("iteration", -1)) if isinstance(fh, dict) else None
    rec["rank"] = int(np.linalg.matrix_rank(X.T @ X))
    if not rec["converged"]:
        raise FitContractError("IRLS did not converge in %d iterations" % maxiter)
    if rec["rank"] < rec["p"]:
        raise FitContractError("rank-deficient design (rank %d of %d columns)" % (rec["rank"], rec["p"]))
    if not np.all(np.isfinite(np.asarray(res.params))):
        raise FitContractError("non-finite parameters")
    if any("Convergence" in k or "Separation" in k or "Singular" in k for k in rec["warnings"]):
        raise FitContractError("statsmodels warning: " + ", ".join(rec["warnings"]))
    return res, rec
