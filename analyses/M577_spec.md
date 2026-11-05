# M577 spec Rev 1 (2026-11-05): cell-spread level after the M575 ingestion: temperature, logger regime and PID-set change (follow-up of M573/M574)

Status: Rev 1, frozen before any code or result of this spec (Director review of Rev 0: "revise"; all seven required revisions, the cut and both additions applied below). Base: `main` at M576 (`f48b6e7`), `drive_master.csv` MD5 `1e599176dafd8575dc7addede8d79358` (621 drives).
Owner prompt (Andrii, chat 2026-11-05): "I noticed that cell spread voltage has risen heavily with ingested drives. Is that a correct estimation?"; "Continue as suggested".

## Disclosure of what was seen before this spec (not pre-registered evidence)
Before writing, the author read (a) the M575 previous-CI check (35 cell-spread estimates inside their previous CIs), (b) monthly medians of `cell_spread_loaded_p95_adj_mv` (Sep 21.9, Oct 24.4, Nov 27.15 mV),
(c) medians by drive-mean pack-temperature band, 15 new vs older drives (10-14 C band, 6 new drives: 26.4 vs 24.3 mV; the 14-18, 18-22 and 22-30 C bands have 4, 2 and 2 new drives). These looks are descriptive,
uncorrected and used the adjusted column; they motivated the questions, no threshold below is tuned to them. The cold subset (model C) is next to the seen 10-14 C band; its edges are therefore fixed by the quantile rule below, not by the seen band.

## What is already pre-registered (not re-specified, not pre-empted)
- M574 confirmatory block (`cellSpreadStep.confirmatory`): drives after 2026-10-17 against the pre-step model, floor >= 10 drives on >= 5 days; now `awaiting data` (14 drives, 3 days). It stays the primary answer to "level shift persists?".
  M577 contains NO hold-out or persistence look at the new batch (the Rev 0 model D is cut; 3 days would give t(2) and no information).
- Step date 2026-10-01 fixed, post hoc, never re-picked. Regime rule: slow = `I_sample_period_s >= 1.05 s` (M379a).

## Questions (model-derived, conditional on the stated covariates)
Q1 Temperature: is the post-step excess in loaded p95 spread still present at equal drive-mean pack temperature, current and SOC covariates?
Q2 Logger regime: is the slow-vs-fast term distinguishable from zero with the step present?
Q3 PID-set change (Intake Air Temperature PID removed, one VCM PID added, both 2026-11-03): identification check and a sensitivity, no inference.

## Frame and covariates (copied from `tools/m573_cell_spread_step.py::build_frame`, the released estimator's frame; not redefined)
y = `cell_spread_loaded_p95_mv` (YCOL; the adjusted column `cell_spread_loaded_p95_adj_mv` is a labelled sensitivity run of model A only). T = `T_pack_mean_avg` (drive mean); I = `peak_I_discharge`; soc = `rf_socmean_wtd_pct`;
socr = `soc_max` - `soc_min`; lrest = log1p(clip(rest_h, 0, 200)) with rest_h the gap from the previous drive end; first = (rest_h > 4); months = months since 2026-05-15 as in M573; step S = (date >= 2026-10-01);
slow R = (`I_sample_period_s` >= 1.05); eligibility = `degradation_trends._prep` (canonical-clean, `ens_outlier_v2` excluded) with `dropna(T, I, soc, socr, lrest)`. The calendar day is the cluster. Frame at writing: 590 drives, 120 days, 2026-05-15..2026-11-03.

## Support
Temperature support is the common support of the two S arms: the interval [max(min T | S=0, min T | S=1), min(max T | S=0, max T | S=1)] of drive-mean T, written by the script. The 9 C figure of the M119 fit basis is reported as a flagged include-sensitivity, not the rule.
Drives outside the common support are listed by S (exclusion tracks S by construction), n and days per arm, and run once as an include-sensitivity of model A. No level is reported below the common support.

## Identification (enforced by the script)
- PID indicator P = 1 only for drives dated 2026-11-03 (4 drives, 1 day): one cluster, no interval defined. Q3 is reported `not identified (P on 1 day)`, descriptive 4-drive median only. It becomes testable when P=1 spans >= 5 days and >= 10 drives.
- Because a PID-set change can alter the sampling period (R) and cell-scan timing, P can load onto R and S: the script reports `I_sample_period_s` (median, IQR, n) for 2026-11-01..02 versus 2026-11-03, and runs model A without the 2026-11-03 drives (sensitivity A-noP).
- Q2 is identified on the full frame (R varies across months: 2026-05 71 % slow, 06 and 07 100 %, 08 37 %, 09 83 %, 10 29 %), not on the 15 new drives; R's own VIF gates Q2 (VIF > 5 for R in model A: Q2 `not separable`, estimate shown, no label).
- S versus months collinearity (known from M573) has its own rule: the script reports the VIF of S and months and the correlation of S with months; no block on Q2, but the S label is reported with this VIF beside it.

## Models (calendar-day cluster; CR2 t(G-1) intervals; day-clustered percentile bootstrap seed 42, 4000 draws)
- A (primary): y ~ months + S + R + T + I + soc + socr + lrest + first (M5 plus R).
- B: A with T replaced by a natural cubic spline (3 df, knots at the 25/50/75 % quantiles of T within common support).
- C (cold subset): drives with T at or below the 25 % quantile of T in the common support (fixed by quantile, not by the seen band): y ~ S + R + I + soc + socr (no months term). Floor per S arm: >= 10 drives on >= 5 days, else `not evaluable`; the script reports the calendar months of the S=0 drives in C (seasonal confounding).
- E: A with the week-block bootstrap (M494 convention, seed 42, 4000 draws) and the leave-one-week-out range for S and R.
- A-noP and A-adj (see above), A-include (support sensitivity). Multiplicity: 2 terms (S, R) x 5 models (A, B, C, E and the sensitivities counted once) are reported uncorrected; no family-wise claim.

## Decision rules (script-written labels; precedence fixed)
Evaluated in this order for S and for R in A:
1. `not separable` / `not evaluable` / `not identified` when the corresponding rule above fires (model B, C or E not evaluable: the label is computed on the evaluable set and says which models were missing).
2. `procedure-dependent` if A's CR2 interval excludes zero but at least one of {day-cluster bootstrap, B, C, E week-block} includes zero or is of opposite sign.
3. `distinguishable from zero` if A, bootstrap, B, C and E all exclude zero with the same sign.
4. `not distinguishable from zero (not equivalence)` otherwise. The window is too short for equivalence; no TOST margin is set. The minimum detectable effect (80 % power from the CR2 SE) is reported beside every label.
Reading of non-results (wording fixed now): S including zero is "not supported at the stated MDE", never "falsified"; R including zero does not show the regime absent. The reference size for the MDE comparison is the lower bound of the M573 step CI (about 1.0 mV, M3 step term), cited, not tuned.
Language: "estimated / model-derived"; not used: degradation, drift, robust, confirmed, real imbalance growth, falsified, cadence-corrected. Cause unidentified; step size conditional on a post hoc date.

## Outputs and tests
- `tools/m577_cell_spread_levels.py` (new, analysis only) writes `analyses/M577_levels.json` (n drives, n days, G, estimates, CIs, labels, VIFs, support interval, seeds, master MD5, script sha256). No payload key, no dashboard change in this milestone.
- Known-answer test `tests/synthetic/test_m577_levels.py`: planted S=+3 mV: CR2 coverage >= 93 % in 200 replicates and the planted label; planted S=0: false-positive rate of the `distinguishable` label <= 8 % in 200 replicates; planted R with R-S collinearity above the VIF rule returns `not separable`; planted P on one day returns `not identified`.
- Blind audit (analytical-auditor, claim + data path only): reproduces A and C to 1e-4 and the S label. Director decision on result + audit.

## Out of scope and follow-up
Balancing mechanisms, cell-level resistance, any degradation claim, the M119-v2 refit, a payload or dashboard block, any article figure (Opus audit + Andrii's sign-off). Follow-up (separate spec): within-drive cell-scan simultaneity check (non-simultaneous reads can inflate loaded spread).
