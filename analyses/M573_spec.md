# M573 spec (DRAFT, not frozen): step versus trend in the loaded p95 cell-spread slope

Status: Rev 1, 2026-11-02, FROZEN before any code. Number M573 (Andrii: the table-to-chart conversion took M569-M572, merged to M572; the cell-spread
draft was renumbered M569 -> M573). Branch base: `main` at M572 (`55d8494`). Andrii, 2026-11-02: "Lets apply the update. Do not ingest any new drives."
This milestone is analysis only: NO ingestion, `drive_master.csv` (MD5 `5556a0c6...`) and `raw_manifest.json` untouched, no new column, released
estimator unchanged, no payload key and no dashboard change in this step (payload/display only after the blind audit and a Director decision).

## Rev 1 additions (frozen)
- Outputs: `tools/m573_cell_spread_step.py` writes `analyses/M573_step_vs_trend.json` (all numbers script-written, with input hashes) and
  nothing else; it reads `drive_master.csv` and raw CSVs read-only.
- External descriptive check (item 7): the nine un-ingested Nov 1-2 drive files that Andrii supplied (ambients +7 / +6 degC, driver-recorded) are
  read read-only from outside the repo with `compute_drive_summary_v6.analyze_bytes`; their sha256 is recorded; they are NOT merged into any fit,
  NOT copied into `raw/`, and are labelled "not ingested, descriptive". They never enter an interval.
- Known answers (tool test `test_m573_cell_spread_step.py`): KA1 synthetic linear trend with no step: the months slope is recovered and the step
  term interval covers 0; KA2 synthetic pure level step at a known date: the step is recovered, the months slope (with the step term) covers 0,
  the step model beats the linear model by AIC; KA3 week-block bootstrap on iid data has coverage near 95 %; KA4 the tool reproduces the released
  `degradationTrends.cellSpread.clusterRobustOLS` slope/SE/CI exactly from the master (to the payload rounding); KA5 `drive_master.csv` MD5 unchanged.
- Gates: A0 MD5 and ML16 unchanged; A1 blind audit (Sonnet) reproduces items 1, 3 and 4b from the claim + data path only; A2 KA1-KA5 pass;
  A3 Director decision before any payload/dashboard use; A4 no article figure. Escalate to the Director if the step model and the linear
  model disagree on whether the months interval covers 0 (expected, to be ruled), or if any item contradicts the exploratory ranking.
- Item 6 (re-test after winter / matched spring T) is ingestion-gated and out of this milestone.

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

## Rev 2 (2026-11-02): audit and Director ruling recorded; payload not yet built
- Blind audit (Sonnet, `analyses/M573_audit_result.json`): C1-C5 reproduced from the claim and data path only (slope 0.524 [0.266, 0.781]; step model
  months 0.157, step 2.263; with SOC and rest 0.021 / 2.084; equal-length first-20-min loaded p95 effect +3.06 [1.98, 4.14]); the two week-based lower
  bounds differ by about 0.02 (cluster small-sample correction). Verdict accept. Auditor files `audit/m573_audit.py`, `audit/m573_c5.py` (untracked).
- Director (Opus): decision REVISE with a GO for a follow-up additive payload block and a short methods note. needs_andrii_signoff: false.
  Revision applied here: the step term is now also reported with the polling-regime covariate (`item5_cadence.stepTermWithRegime`:
  +2.32 mV [1.06, 3.57]; regime term +0.71 [-0.30, 1.72]; months 0.19 [-0.08, 0.45]), so cadence is reported, not excluded.
- Required wording: "within the 5.1-month window, a level shift around late September / early October (date chosen post hoc) fits better
  than a steady linear trend (model-derived); the steady trend is not established once the shift is allowed; degradation and real imbalance growth
  are neither established nor excluded; the cause is unidentified." The step size is shown only as "conditional on a post hoc date, not adjusted
  for selection". Never: detected / confirmed change-point, step at Oct 1 as fact, degradation, imbalance growing, cadence or balancing ruled out,
  "measured". The old wording goes into `language_gate.py` with ledger id M573 in the payload milestone.
- Required caveats: step date post hoc (data-driven scan best 2026-09-27); AIC and CIs ignore date selection and multiplicity; residual lag-1
  autocorrelation about 0.27; late window 8 days, 23 week clusters; month fixed effects fit as well as the step (AIC 3095.8 vs 3104.7 for the step
  under the same covariates), so October is not uniquely supported; cold-start early-window intervals are wide ("not detected", not "excluded");
  the Nov 1-2 files (n=7 usable) stay outside every fit and interval.
- Pre-registered confirmatory test (fixed now): step date 2026-10-01, never re-picked. Prediction on drives ingested after 2026-10-17: the level
  stays raised relative to the pre-step model and the post-step slope is flat. A fall back to the pre-step level, or a continued rise, is reported as such.
- Next milestone (proposed, needs its own number from the CHANGELOG head): additive payload block (splice, script-written, n/days/CI on every item)
  and a wording-only cross-reference in the existing cellHealthTrend / degradationTrends text; released estimator unchanged.
