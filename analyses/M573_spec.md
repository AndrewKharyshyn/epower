# M573 spec (DRAFT, not frozen): step versus trend in the loaded p95 cell-spread slope

Status: draft opened 2026-11-02, number assigned by Andrii (chat) as M569 and renumbered to M573 the same day (Andrii: the table-to-chart conversion starts at M569; M568 is merged). Starts only after the parallel session (M557-M561 on origin) has finished;
rebase onto the then-current `main` first and renumber nothing. No code, payload, dashboard or CHANGELOG change yet.

## Question
`degradationTrends.cellSpread` (cluster-robust OLS, `y ~ months + T + I`, day clusters, t(G-1)) turned positive in the last weeks of the
window (drive_master 606 rows, 2026-05-11..10-17). Is this a steady trend or a level step (seasonal, thermal-gradient, balancing or pack-state
effect), and can real imbalance growth be separated from it?

## Origin (exploratory, ad-hoc scripts, not committed; their figures are NOT repo figures)
Opus research-director review: decision "revise", no Andrii sign-off needed at this stage. Ranking: (1) seasonal / thermal-gradient
confound plus an October step read as a trend; (2) real imbalance growth, not excludable; (3) balancing / pack state; (4) drive mix;
(5) logger cadence; (6) leverage of late long drives. Pack-level SOC was tested as a covariate: it is a real driver of spread but does not
absorb the slope or the October step, so it drops out as the explanation; it stays in the model as a control.

## Planned analyses (one tool under `tools/`, outputs to JSON, all numbers script-written)
1. Step versus trend: linear months vs month fixed effects vs months + October dummy; AIC and day-blocked cross-validation.
2. Covariates: add pack-level SOC (`rf_socmean_wtd_pct`, SOC range) to T and peak I; report with and without.
3. Dependence: leave-one-week-out slopes, ISO-week-clustered interval t(G-1), week-block bootstrap (seed 42, 4000), residAutocorrLag1.
4. Matched-state contrast: October vs May-September drives matched on pack T, peak I, SOC band and distance class; inter-cell or battery
   thermal gradient and ambient if logged.
4b. Cold-start and equal-length segments: per-sensor start temperatures (`[BMS] HV Battery Temperature Sensor 1-4`, integer degC; mean, range,
   front/rear pair gradient) for first drives after >4 h rest; early-drive max-min cell voltage in 0-2 and 2-10 min windows; and the loaded p95 over the
   first 20 min of every drive (equal length), Sep vs Oct 10-17, adjusted for start T and current. Exploratory finding to test, not a result:
   the Oct 10-17 excess is absent at the cold start and builds under load. Covariates to add to the main model: rest time since the previous drive,
   first-drive-after-rest flag, SOC mean and range.
5. Logger cadence: samples per second by month (`n_raw_rows / duration_s` varies by month, unexplained).
6. Re-test after winter and at matched spring temperature (ingestion-gated).

## Constraints
Released estimator unchanged (additive block only). Wording: "estimated loaded p95 cell-spread trend (model-derived, short window)";
never "degradation detected" or "imbalance growing"; a CI excluding 0 is not established degradation. Blind audit (Sonnet) and Director
decision before any payload or dashboard figure; no article figure without Opus audit and Andrii's sign-off. Language rules go through
`language_gate.py` with the ledger id.
