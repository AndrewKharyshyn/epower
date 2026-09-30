# M307 spec (pre-registered, written BEFORE any F1-F3/F5 result exists): F03 cell-spread provenance follow-ups

Status: PRE-REGISTERED 2026-09-30. Director decision that triggers this: analyses/F03/README.md (downgrade_to_sensitivity). Andrii approved
F1-F3, F5 and the dashboard flag on 2026-09-30.

## Common definitions
- Estimand: monthly slope of `cell_spread_loaded_p95_mv` (mV/month) with covariates T (`T_pack_mean_avg`) and I (`peak_I_discharge`), exactly as
  `degradation_trends._analyse` (canonical-clean: `ens_outlier_v2` False; calendar day = cluster; cluster-robust OLS with t(G-1) reference; mixed
  effects reported alongside, per M155 acceptance gate). No new estimator; `degradation_trends._analyse` is called unchanged.
- Datasets: P = published `drive_master.csv` (reference of record); A = fresh master (scratch), B = fresh master with ML16 restored from P.
- Every estimate reports nObs, nDays, slope, SE, 95% CI, primaryEstimator, degenerate flag. Window = 4.27 months; no trend claim is made from any
  subset shorter than 2 months.

## F1 - stable-subset refit
Subset S = drives whose `cell_spread_loaded_p95_mv` is identical (|diff| <= 1e-9) in P and A (expected 347 drives; whichever number, report it).
Fit on S using P values (== A values on S). Primary outcome: slope and CI vs published P slope (+0.0115, CI [-0.289,+0.312]).
Interpretation rule (fixed now): if S-slope CI contains the published slope AND overlaps 0 -> "published trend not contradicted on the
provenance-stable subset". If S-slope CI excludes the published slope -> the published result is provenance-sensitive beyond the altered files;
escalate to Director. S is selected on the outcome-difference itself, so F1 is descriptive (selection on an outcome-related quantity), never a
confirmatory test; this limit is stated with the result.

## F2 - leave-one-month-out and early-window exclusion
For each of P, A, B: refit dropping each calendar month in turn (May, Jun, Jul, Aug, Sep = 5 fits); and refit excluding May-Jun (window shrinks to
Jul-Sep, ~2.7 months). Report slope/CI and the maximum absolute change of the slope across the leave-one-out fits (influence). Decision rule: a
subset fit is "stable" if its CI contains the published slope; the number of unstable fits is reported per dataset. Month = calendar month of
`date`.

## F3 - per-file inspection of the altered drives (diagnostic, no estimand)
Drives D = those whose spread differs between P and A (expected 99). For each of D and a matched comparison set C (hash-verified drives, plus
hash-failing drives with identical spread), compute from today's raw file: decimal precision/quantisation of cell-voltage columns, sentinel/spike
counts, NaN pattern, duplicated timestamps, monotonicity of time, row count vs manifest, per-drive p95 loaded spread recomputed two ways, and the
per-column value distributions. Report which raw-file property separates D from C (single best discriminator by AUC, with n). Cannot identify the
true original; can only characterise today's copies. Any explanation offered must be labelled a hypothesis unless a property perfectly separates D
from C. No values are edited or "repaired".

## F5 - estimator-fallback gate
(a) Diagnose why the mixed-effects fit is singular on A/B but not P (groupVar, boundary, LinAlg location, data differences on identical days).
(b) Gate: for each `degradationTrends.<metric>`, `primaryEstimator` and `mixedEffects.degenerate` of a new arrays build are compared with the
previous arrays; a change (e.g. mixedEffects -> clusterRobustOLS) makes `tools/ingest_core.py` abort with a Gate error and restore its outputs
unless run with `--ack-estimator-change "<reason>"` (the reason is written to the ingest report). `release_check.py` gains a WARN when any metric is
`degenerate`. Known-answer test: synthetic previous/fresh arrays with a flipped primaryEstimator must abort; unchanged must pass.

## Dashboard flag
New computed key `S.provenanceSensitivity` (built by an idempotent post-pass script from analyses/F03 result JSON, listed in
`apply_m284_post.sh`), containing: counts (hash-failing/total raw files), affected metric list, wording strings approved by the Director, source
file hashes. The degradation tab (`degradationTrends.cellSpread`, `cellHealthTrend`) renders a flag/notice bound to that key (no literals). Must
pass build_html gates, jsdom, semantic_gate (forbidden-wording) and release_check.

## Acceptance / falsification
- F1/F2: results are reported as computed; no threshold is tuned to produce agreement. Disagreement between P, A and B is reported, not resolved.
- F3: falsified as "explanatory" if no raw-file property separates D from C (AUC < 0.9); then the mechanism is reported as unexplained.
- F5: gate must fail on the flipped-estimator synthetic and pass on the unchanged one.
- Blind audit (analytical-auditor) reproduces F1 and F2 for P from the master and spec only; Director decision before any wording changes.

---
## Amendment 1 (2026-09-30, BEFORE any F1/F2/F3 run; from Director spec review "revise")
Only a tool sanity check preceded this amendment: `tools/f03_followups.fit()` on the published master reproduced the published cellSpread record
(OLS slope 0.0115, CI [-0.2892, 0.3122], nObs 423, nDays 92, mixed slope -0.0163, pTOST 0.0772). No F1/F2/F3 output existed.
1. Decision estimator (all F1/F2/F1b rules): cluster-robust OLS with t(G-1) reference, whatever `primaryEstimator` says. Mixed effects is reported
   alongside with its `degenerate` flag and is never used to decide. CI method identical to the published one; NO day-bootstrap is used
   (deviation from the standing default, stated for comparability).
2. Exclusion: primary = P's `ens_outlier_v2` applied to P, A and B (A's own 3 excluded drives are ignored in the primary). Secondary = A with its
   own exclusion. Datasets reported: P, A(P-excl), A(own-excl), B.
3. F1 outcomes (in addition to those above): (i) S-CI contains the published slope but excludes 0; (ii) S-CI contains BOTH the published slope and
   the A-full slope -> "uninformative"; also report whether the S-CI contains the A-full slope. Report nDrives and nDays per calendar month for S.
   Wording: "subset where published and fresh values coincide" (not "provenance-stable"/"verified"); at most "not contradicted".
4. F2: each fit is reported against both the published slope and the dataset's own full-data slope. Influence = max|slope_LOMO - slope_full| /
   SE_full (pre-defined). Month is confounded with hash status (no hash-verified drives in May-Jul): a May-Jun effect cannot be split into a date
   effect and an alteration effect; stated with every F2 result.
5. F3: D = the drives with spread differences P vs A. Matched comparison C = hash-failing drives with identical spread in the SAME calendar months
   (matched by month, drawn without replacement, seed 42, ratio up to 1:1 per month). Hash-verified drives (Aug-Sep) are reported separately, not
   pooled into C. Pre-listed feature set (12 features, fixed now): (1) cell-voltage decimal digits (max, over the 4 cell-voltage-group columns), (2)
   distinct-value count of cell voltage, (3) quantisation step (min positive diff between sorted distinct values), (4) NaN fraction of cell voltage
   columns, (5) duplicated-timestamp count, (6) non-monotonic-time count, (7) row count minus manifest rows, (8) spike count (|z|>6 on cell
   spread), (9) p95 loaded spread recomputed as pipeline (analyze_bytes), (10) p95 loaded spread recomputed from a 3-sample median-filtered copy of each cell voltage, (11) fraction of samples with cell spread = 0, (12) file size/rows ratio. Definition of the two recomputations: (9) = the pipeline's own
   value from today's file; (10) = the same statistic after the 3-sample median filter. Discrimination test: AUC
   per feature; the best AUC is judged against a permutation null of the MAXIMUM AUC over the 12 features (1000 permutations, seed 42) and
   day-blocked CV. "Explains" requires max-AUC >= 0.9 AND permutation p < 0.05; any mechanism is worded "candidate mechanism (hypothesis)" even at
   AUC = 1 because the originals are unavailable.
6. F1b (outcome-blind subset S'): hash-verified drives PLUS hash-failing drives with zero P/A drift (tol 1e-9) on this column list, fixed now and
   excluding every cell-voltage-derived column: n_raw_rows, duration_s, distance_km, gross_throughput_kwh, gross_discharge_kwh, gross_charge_kwh,
   peak_discharge_kw, peak_charge_kw, peak_I_discharge, peak_I_charge, V_pack_median, net_draw_kwh. It does not condition on the outcome value but
   is correlated with the alteration mechanism: descriptive. Report the S vs S' overlap and the same outcomes as F1.
7. F4 (hash-verified-only): MDE only (no May-Jul coverage, no slope).
8. F5 gate also triggers on a change of the `degenerate` flag (implemented and tested: tests/synthetic/test_estimator_gate.py).
9. Blind audit also covers F1b and the F3 permutation null.
Language additions: "candidate mechanism (hypothesis)"; "provenance sensitivity"; keep "equivalence not established"; never "no degradation",
"balancing", "confirmed", "correct" or "original".
