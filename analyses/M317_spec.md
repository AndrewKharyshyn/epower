# M317 pre-registered spec: fit provenance for the M19 Huber block + a bootstrap CI for the Huber-adjusted slope

Status: written BEFORE any M317 result exists (2026-09-30; master 489 drives, MD5 bd9d10726bb064d857cf9ff98d2b7338; main at cb20165, tag M314).
Origin: follow-ups from the Director's M312 decision ("store the pipeline slope, coefficients and keep-set hash with every published fit"; "a CI for the Huber-adjusted slope, separate spec"; "watch the bT instability").
Wording: model-adjusted / estimated, never measured. The block is non-authoritative (`authoritative:false`); `degradationTrends.cellSpread` governs headline claims. Not article-eligible (F03).
No master value, no adj_hub value and no other estimator changes in this milestone.

## Part A. Fit provenance (metadata only, no estimator change)
Problem: the M312 comparison against the published values (baseline B2) could not evaluate the pipeline slope and coefficient criteria because those were never stored.
Change: every ingestion records the M19b fit in an append-only file `spread_fit_history.json` (one record per distinct master MD5, written by `tools/record_spread_fit.py`, new ingestion stage, idempotent) and publishes the latest record in a new arrays block `spreadFitProvenance`.
Record fields (all computed from `compute_drive_summary_v6.m19b_huber_adjust` and the master, none typed): master MD5, n_rows, n_days, exclusion column, keep-set hash (sha256 of the sorted kept file ids), n_clean, Huber coefficients (intercept at T_ref, bT, bI, I_ref), pipeline slope (i) with its M19 bootstrap CI, second-stage Huber slope (ii) with the Part B CI, bootstrap settings (draws, seed, epsilon), and a stability diagnostic: the same first-stage fit refit leaving the last 8 calendar days out (coefficients and their difference from the full fit; reported only, no threshold; this is the standing "watch bT" item).
Acceptance: the record of the current master reproduces the M312 values (coefficients, slope (i) 0.151, n 465, I_ref 101.9) and is deterministic (two runs identical). The history file is additive: existing records are never rewritten.

## Part B. Bootstrap CI for `huberSlopeMvPerMo` (new estimator output)
Estimand: the linear trend (mV per month) of the Huber-adjusted loaded cell spread (`cell_spread_loaded_p95_adj_hub_mv`), second-stage Huber regression of the adjusted series on months since the first kept drive (months = days / 30.4375), exactly as `cellHealthTrend.huberSlopeMvPerMo` is computed today.
Population and eligibility: canonical-clean rows (`~ens_outlier_v2`) with non-null adjusted value and date (n = 465 on the current master, 100 days).
Method (primary): day-clustered percentile bootstrap, conditional on the first-stage fit (the adjusted series is held fixed): resample calendar days with replacement (4000 draws, seed 42), refit the second-stage `HuberRegressor` (default epsilon 1.35) on the resampled rows, report the 2.5 / 97.5 percentiles, the number of failed or non-converged draws and n_days. Resampling unit: calendar day (drives within a day are not independent replicates).
Sensitivity S1 (two-stage bootstrap): resample days, refit the FIRST-stage Huber (T and peak current, epsilon 1.35, max_iter 500) on the resampled kept rows, recompute each row's adjusted value, refit the second-stage slope. S1 is reported beside the primary interval; if S1 is materially wider the dashboard states the conditional nature of the primary interval.
Disclosed limitation (unchanged): the existing `ci95` of this block bootstraps the OLS-adjusted slope of a different series (`cell_spread_loaded_p95_adj_mv`); the new interval is for the Huber series and is the first interval that belongs to `huberSlopeMvPerMo`.
Output: `cellHealthTrend.huberSlopeCi95`, `huberSlopeCiFailedDraws`, `huberSlopeCiMethod` (text), and the S1 interval in `spreadFitProvenance`.

## Validation (fixed now)
1. Known-answer test (`tests/synthetic/test_huber_slope_ci.py`): synthetic drives with a planted slope, day-level random effects and heavy-tailed noise; the point estimate recovers the planted slope within 2 bootstrap SE; over 200 simulated datasets the nominal 95% interval covers the planted slope in [0.88, 0.99] of them (calibration). If coverage falls outside, the primary method is NOT published and the Director decides (S1 may replace it).
2. Determinism: two runs give byte-identical intervals.
3. Cross-check: the real-data primary interval equals the interval already computed in `analyses/M312_results.json` (same method and seed) up to display rounding; a blind audit reproduces it independently from `drive_master.csv` (claim and data path only).
4. Isolation diff: only `cellHealthTrend` (new keys `huberSlopeCi95`, `huberSlopeCiFailedDraws`, `huberSlopeCiMethod`), the new `spreadFitProvenance` block and its stamp, and `spread_fit_history.json` change; drive_master.csv and every other arrays key byte-identical (per-key deep diff); `release_check.py`, `node build_html.js`, `node validate_jsdom.js` green.
Decision rule: there is no accept/reject threshold on the physical claim. The interval is reported as computed. If it includes zero the dashboard says "trend not established"; if it excludes zero it says only that the non-authoritative Huber check is positive and that the authoritative estimator (`degradationTrends.cellSpread`) governs.

## Dashboard
The M19 block prose on the Health tab shows the Huber slope together with its interval and method note, bound to `S.cellHealthTrend.huberSlopeCi95` (no literals). No other figures change.

## Deviations
Recorded in the CHANGELOG M317 entry if any. The Director reviews this spec, the results JSON and the blind-audit JSON before merge.
