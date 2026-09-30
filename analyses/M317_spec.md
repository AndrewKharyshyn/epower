# M317 pre-registered spec (rev 2): fit provenance for the M19 Huber block + a bootstrap CI for the Huber-adjusted slope

Status: written BEFORE any M317 result exists (2026-09-30; master 489 drives, MD5 bd9d10726bb064d857cf9ff98d2b7338; main at cb20165, tag M314). Revision 2 folds in the Director's review of revision 1
(decision "revise", 8 required edits), still before any result.
Origin: follow-ups from the Director's M312 decision ("store the pipeline slope, coefficients and keep-set hash with every published fit"; "a CI for the Huber-adjusted slope, separate spec"; "watch the bT instability").
Wording: model-adjusted / estimated, never measured. The block is non-authoritative (`authoritative:false`); `degradationTrends.cellSpread` governs headline claims. Not article-eligible (F03), so no Andrii sign-off is required; a blind audit and a Director decision are.
No master value, no adj_hub value and no other estimator changes in this milestone.

## Part A. Fit provenance (metadata only, no estimator change)
Problem: the M312 comparison against the published values (baseline B2) could not evaluate the pipeline slope and coefficient criteria because those were never stored.
Change: every ingestion records the M19b fit in an append-only `spread_fit_history.json` (one record per distinct master MD5 + estimator-config hash; written by `tools/record_spread_fit.py`, new ingestion stage, idempotent;
existing records are never rewritten) and publishes the latest record in a new arrays block `spreadFitProvenance` (registered in the release check and `REQUIRED_BLOCKS`).
Record fields (all computed, none typed): master MD5; milestone id; n_rows, n_days; exclusion column; keep-set hash (sha256 of the sorted kept file ids); n_clean; Huber coefficients (intercept at T_ref, bT, bI, I_ref, `n_iter_`, `scale_`);
`SPREAD_T_REF`, epsilon, `max_iter`; slope (i) and its CI, labelled exactly: "OLS slope of the Huber-adjusted series, CI from a day-clustered bootstrap with an OLS first stage" (NOT a Huber slope CI; months = days / 30.44 as in m19b);
slope (ii) with the Part B intervals (months = total_seconds / (30.4375 x 86400)); bootstrap settings (draws, seed); the estimator-config/code key: sha256 of the source text of `m19b_huber_adjust` and of the Part B function, git commit, python / numpy / pandas / scikit-learn versions; a UTC timestamp
(kept OUT of every determinism comparison).
Stability diagnostic (standing "watch bT" item, report-only): the first-stage fit refit leaving the last 8 calendar days out, with the bT day-clustered bootstrap CI of the full fit shown beside it. Pre-registered FLAG (not a gate): bT sign flip, or |delta bT| > half the width of that bT CI. A raised flag is shown in the record and on the dashboard note; it blocks nothing.
Acceptance: the record of the current master reproduces the M312 values (coefficients, slope (i) 0.151, n 465, I_ref 101.9) and is deterministic (two runs identical apart from the timestamp).

## Part B. Bootstrap CI for `huberSlopeMvPerMo` (new estimator output)
Estimand: the linear trend (mV per month) of the Huber-adjusted loaded cell spread (`cell_spread_loaded_p95_adj_hub_mv`), second-stage `HuberRegressor` (defaults, epsilon 1.35) of the adjusted series on months since the first kept drive, exactly as `cellHealthTrend.huberSlopeMvPerMo` is computed today.
Population and eligibility: canonical-clean rows (`~ens_outlier_v2`) with non-null adjusted value and date (n = 465 on the current master, 100 days).
Data path, pinned: PRIMARY uses the STORED adjusted column (rounded to 0.1 mV), months = total_seconds / (30.4375 x 86400). S1 uses UNROUNDED adjusted values recomputed inside each draw (same months definition); the m19b slope (i) uses days / 30.44 and is a different object.
Primary method: day-clustered percentile bootstrap CONDITIONAL on the first-stage fit (the adjusted series is held fixed): resample calendar days with replacement (4000 draws, seed 42), refit the second-stage Huber slope, report the 2.5 / 97.5 percentiles, n_days and the number of failed or non-converged draws.
Sensitivity S1 (two-stage): resample days, refit the FIRST-stage Huber (T and peak current; epsilon 1.35, max_iter 500) on the resampled kept rows, recompute I_ref from the resample (SPREAD_T_REF fixed), recompute every resampled row's adjusted value (unrounded), refit the second-stage slope.
Sensitivity S2 (serial correlation): week-block bootstrap (resample 7-day calendar blocks instead of days; same draws and seed) for both stages as in the primary.
"Materially wider": S1 half-width / primary half-width > 1.2 (same rule for S2). If so both intervals are shown and the zero-inclusion wording follows the WIDER interval.
Failure rule: if more than 1% of draws fail or do not converge, that interval is INCONCLUSIVE (not published as a CI).
Disclosed limitation (unchanged): the existing `ci95` of this block bootstraps the OLS-adjusted slope of a different series (`cell_spread_loaded_p95_adj_mv`).
Output: `cellHealthTrend.huberSlopeCi95`, `huberSlopeCiFailedDraws`, `huberSlopeCiMethod` (text); S1 and S2 intervals in `spreadFitProvenance`.

## Validation (fixed now)
1. Calibration simulation (`tests/synthetic/test_huber_slope_ci.py`), for the PRIMARY and for S1: datasets of about 100 calendar days with the REAL drives-per-day distribution (resampled from the master), pack temperature and peak current that CO-TREND with time (a seasonal temperature path, so the first stage is not separable from the trend),
   day-level random effects, heavy-tailed noise and a planted trend. The point estimate recovers the planted slope within 2 bootstrap SE, and over 500 simulated datasets the nominal 95% interval covers the planted slope in [0.92, 0.98] of them (Monte-Carlo SE about 0.01).
   Failure path (pre-registered): S1 replaces the primary ONLY if S1 passes; if neither passes, NO interval is published and the dashboard says "no calibrated CI". Any replacement of the primary method requires a spec amendment and a new Director decision.
2. Determinism: two runs give byte-identical intervals (timestamp excluded).
3. Cross-check: the real-data primary interval equals the one in `analyses/M312_results.json` (same method and seed) up to display rounding; a blind audit reproduces it independently from `drive_master.csv` (claim and data path only).
4. Isolation diff: only `cellHealthTrend` (new keys `huberSlopeCi95`, `huberSlopeCiFailedDraws`, `huberSlopeCiMethod`), the new `spreadFitProvenance` block and its stamp, and the new `spread_fit_history.json` change; drive_master.csv and every other arrays key byte-identical (per-key deep diff);
   `release_check.py` (payload check for the new block, stage known), `node build_html.js`, `node validate_jsdom.js` green.
Decision rule: there is no accept/reject threshold on the physical claim. The interval is reported as computed. If it includes zero (the wider interval when they differ materially) the dashboard says "trend not established"; if it excludes zero it says only that the non-authoritative Huber check is positive and that the authoritative estimator governs.

## Dashboard
The M19 block prose on the Health tab shows the Huber slope with its interval(s), the method note and, when raised, the bT stability flag, all bound to payload keys (`S.cellHealthTrend.huberSlopeCi95`, `S.spreadFitProvenance`); no literals. No other figures change.

## Deviations
Recorded in the CHANGELOG M317 entry if any. The Director reviews the results JSON and the blind-audit JSON before merge (a new estimator output needs both).
