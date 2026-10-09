# M388b spec (pre-registered before the code): mixed-effects fallback chain, interDriveCarryover

Status: Director ruling M388b (revise: fallback chain as a method change; a declared loss rule is rejected). Blind diagnosis audit done (cause: lbfgs
path to a singular random-effect covariance on a flat REML surface; not a data defect). A second blind audit of the patched code is required before the splice.

## Scope
`compute_summary_arrays.py::_carryover_regression`, mixed-effects try-block only. Not touched: `_dayboot_ols`, `m119v2_model.py`, `degradation_trends.py`,
`drive_master.csv`. Applied by arrays-only additive splice at `interDriveCarryover/regressionModel/mixedEffects`; the bootstrap block is bit-identical.

## Estimator (secondary, never a headline, never in the article)
Model unchanged: `y ~ arrivalPmC + parkingGapH + arrivalSocPct`, day random intercept, REML, statsmodels 0.15.0.
Chain (fixed): (1) `lbfgs` (unchanged first try), (2) `nm`, (3) `powell`. Move to the next method on an exception or `converged == False`.
`maxiter` fixed per method (lbfgs default as before; nm 2000; powell 2000). If every method fails: the `error` leaf stays and `leaf_guard` STOPs (no loss rule).

## Leaves
Existing 18 leaves keep names and types (coefficients.{Intercept,arrivalPmC,parkingGapH,arrivalSocPct}.{estimate,se,ci95}, converged, statsmodelsVersion).
New leaves under `mixedEffects`: `optimizer`, `attempts[{method,converged,error}]`, `fallbackUsed`, `reVariance`,
`startSensitivity{starts,maxAbsFeDiffInSe,reVarMin,reVarMax,flag}`, `reVarianceIdentified`, `note`.

## Start-value sensitivity (fixed, not tuned)
Refit with the chosen method from the default start and from `start_params` = RE variance 1e4. `maxAbsFeDiffInSe` = max over the four fixed effects of
|difference| / SE (SE from the chosen fit). `flag = maxAbsFeDiffInSe > 0.25 or reVarMax/reVarMin > 2`.
`reVarianceIdentified = False` when the profile REML log-likelihood changes by < 1 unit over the variance ratio grid 0 to 0.1.

## Gates
Control: the patched function on the pre-M388 corpus, leaf deltas against the stored block (method-change effect separate from new-data effect).
Known answers on the new data (nm): arrivalPmC -3.443 (se 0.602), arrivalSocPct 4.519, RE variance 458.6, `flag = true` (audit figures; known-answer targets only, never typed into the repo).
Splice deep-diff: only `mixedEffects` changes/additions. ML16 0/16, master MD5 unchanged, m119v2 hash unchanged, `leaf_guard` and `release_check` green.
A mixed estimate outside the bootstrap CI or with a flipped sign vs the bootstrap goes to the Director.

## Wording
Estimated, descriptive association on one vehicle; the fit is start-value sensitive and the day random-effect variance is not identified. The day-clustered bootstrap OLS stays primary.

## Rev 2 (Director ruling after second blind audit "fix"; disclosed spec amendment, thresholds unchanged, nothing tuned)
R1 Sensitivity refit from RE-variance start 1e4: chosen method first; on exception or converged == False try the remaining chain methods in chain order; record `refitMethod`, `refitAttempts[{method,converged,error}]`.
R2 `flagReason` in {none, unstable, refit_failed}; `flag` true only for `unstable` (maxAbsFeDiffInSe > 0.25 or reVarMax/reVarMin > 2, unchanged); all refits fail: `flag` null, reason `refit_failed`. Known answer (new data) revised: flag false, reason none (refit by lbfgs); old corpus flag false.
R3 `reVarianceIdentified` keeps the pre-registered 1-log-lik rule. Disclosed deviation: the grid starts at 1e-3 (ratio 0 is not evaluable). New leaves `reVarProfileRange`, `reVarProfileGrid`. The Rev 1 narrative "RE variance not identified" is withdrawn: the computed leaves do not support it (margin small: range about 1.2 vs 1.0).
R4 bse_fe / conf_int / coefficient extraction inside the per-method try (an exception there triggers the next method).
R5 `note` is generated from the leaves; no unconditional claim.
R6 (re-audit note) The unstable rule also treats a non-positive minimum RE variance as unstable (guard against division by zero; same threshold otherwise).
