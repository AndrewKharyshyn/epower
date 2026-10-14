"""F14 known-answer tests (external audit 2026-10-13): tools/fit_contract.fit_glm_strict and the census spy tools/fit_glm_census.spy_fit_glm against m119v2_model.fit_glm.
1. When the contract holds the strict fit is NUMERICALLY IDENTICAL to fit_glm (parameters, standard errors, clustered and plain) and the census spy returns the same numbers.
2. Today's behaviour of fit_glm is pinned (this IS the finding): a singular design is accepted silently via the fallback, and a non-converged fit is returned without any record.
3. The strict fit refuses each of: a singular design, non-convergence, non-finite parameters, and a primary-fit exception; the census spy records the same cases (fallback path, rank deficiency, not converged)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import m119v2_model as m
import fit_contract as FC
import fit_glm_census as CEN

rng = np.random.default_rng(3)
n = 4000
X = np.column_stack([np.ones(n), rng.normal(size=(n, 3))])
y = (rng.uniform(size=n) < 1 - np.exp(-np.exp(-3 + 0.5 * X[:, 1] - 0.3 * X[:, 2]))).astype(float)
g = rng.integers(0, 40, n)

# 1. identical numbers when the contract holds
for groups in (None, g):
    a = m.fit_glm(X, y, groups)
    b, rec = FC.fit_glm_strict(X, y, groups)
    c = CEN.spy_fit_glm(X, y, groups)
    assert np.array_equal(a.params, b.params) and np.array_equal(a.bse, b.bse), "strict fit differs from fit_glm"
    assert np.array_equal(a.params, c.params) and np.array_equal(a.bse, c.bse), "census spy differs from fit_glm"
    assert rec["path"] == "primary" and rec["converged"] and rec["rank"] == rec["p"] == 4 and rec["covType"] == ("cluster" if groups is not None else "nonrobust")
    assert CEN.REC[-1]["path"] == "primary" and not CEN.REC[-1]["rankDeficient"] and CEN.REC[-1]["converged"]

# 2. today's silent behaviour of fit_glm (pinned)
Xs = np.column_stack([X, np.zeros(n)])                               # an all-zero column: singular design
a = m.fit_glm(Xs, y, g)                                              # no exception, no record
assert a is not None and np.all(np.isfinite(a.params)), "fit_glm no longer accepts a singular design silently: update this pinned test and the refit checklist"
c = CEN.spy_fit_glm(Xs, y, g)
assert CEN.REC[-1]["path"] == "fallback" and CEN.REC[-1]["rankDeficient"] and "Singular" in (CEN.REC[-1]["exception"] or ""), CEN.REC[-1]
assert np.array_equal(a.params, c.params), "the spy must return the fallback numbers fit_glm returns"
nc = m.fit_glm(X, y, None, maxiter=1)                                # one IRLS iteration: not converged, returned without a record
assert getattr(nc, "converged", True) is False

# 3. the strict fit refuses
def refuses(fn, text):
    try:
        fn()
    except FC.FitContractError as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError("no FitContractError for " + text)

refuses(lambda: FC.fit_glm_strict(Xs, y, g), "primary fit raised")                                  # the clustered fit raises on the singular design
refuses(lambda: FC.fit_glm_strict(Xs, y, None), "")                                                 # plain fit: rank deficiency or an exception, either way refused
refuses(lambda: FC.fit_glm_strict(X, y, None, maxiter=1), "did not converge")
Xc = np.column_stack([X, X[:, 1]])                                                                  # a duplicated column: rank-deficient
refuses(lambda: FC.fit_glm_strict(Xc, y, None), "")
print("OK test_fit_contract")
