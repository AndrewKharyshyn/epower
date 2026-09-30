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
