# M426 spec: ingestion of the 24 drives of 2026-10-09..13 (corpus 554 -> 578) and the three tooling items it needed

Written before the second tooling commit; every number in the CHANGELOG entry comes from a script output of the ingestion run.

## Stops met and rulings
1. `gtr_family_refresh` (P3 / Q2 escalation band, M377 spec): simultaneity `mixed_highway` charges-and-drives moved -5.6 pp (band 5.0 pp), cause: two long 2026-10-10 drives (5 -> 7 drives). Blind audit (analytical-auditor, independence partial) reproduced the rows; Director: accept as small-n reweighting, no reading flip; owner acceptance in chat 2026-10-13. Record: `analyses/M426_gtr_band_ruling.json`. Tooling (commit ba33fbb): `XT_ACK_GTR_BAND` acknowledges ONLY the band stop, bound to the master MD5, the sha256 of the O simultaneity rows and the exact breach list; band values unchanged; reading flips, key sets, n_days, BASE and the allow-list are never acknowledgeable.
2. `leaf_guard`: 31 lost leaves, all caused by the new data (the cold cohort passed the pre-registered support rule: 7 -> 12 drives, 3 -> 5 days; a shoulder `mixed_highway` placeholder row became observed; two `cellSpread` rows left `rowsIncludingZero`; `corpusTotalKwh` was written only after the guard). Director ruling (this session): rules A-C are acceptable only as data-conditioned rules with three NEW registered conditions; D is a producer defect.

## Changes
- `tools/leaf_guard.py`: conditions `cohort_min_support_crossed`, `placeholder_row_observed`, `moved_to_complement_list` (docstrings state what each verifies); 13 rules in `analyses/leaf_guard_rules.json` (milestone M426). No wildcard beyond `{i}`/`{key}`; a rule never fires unless its own data condition holds (unchanged support rule, not available before, available now with eligibleForCohortView >= min drives and nDaysObserved >= min days, absent from the suppressed list; placeholder row -> the same classKey observed with count >= 1; names moved to the complement list, same name union, same classification).
- Known-answer tests (`tests/synthetic/test_leaf_guard.py`): pass; n < min; days < min; threshold changed; still suppressed; reverse direction; already available before; renamed group missing; placeholder still placeholder / other class / no value / zero count / row vanished / a real leaf may never vanish; reordered rows; classification flip; names dropped; union changed.
- `energy_uncertainty_mc.py`: the producer writes `dataQualityNote.corpusTotalKwh` (same rounding as the finding text); `tests/synthetic/test_mc_dq_corpus_total.py` asserts field == number in the text. No payload number changes (the field existed in the committed payload).
- Cold-cohort consistency: `tools/cold_support_sync.py` (new stage `cold_support_sync` after `engine_start_rate`) rewrites ONLY the hand-written cold markers (status 'unavailable', coverage 'no_observations', EfficiencyBands.coldStatus) of charts whose cold view is not built, when the cold cohort meets the support rule, to `support_met_view_not_built` with the live counts; it builds no cold view and adds no figure. `m297_comparison_cube.py`: the urbanContrast caveat no longer states "Cold not observed." when the cold cohort has >= 10 drives. Test: `tests/synthetic/test_cold_support_sync.py`.

## Not done here (named follow-ups)
- Per-chart cold VIEWS for the 46 charts that hard-code `data.cold = None` (m296_refresh_master_seasonal.py, tools/regen_seasonal_raw.py): a separate milestone with its own blind audit; until then the markers say 'view not built'.
- `loggerCadence.stratified.cohortByRegime` (cold_insufficient, regime-stratified support) and `warmVsColdContrast` are a separate analysis with its own support rule; unchanged.
- Cold-cohort figures (n=12 drives, 5 days, 3-5 C) carry low-cluster CIs: no cold-versus-warm claim; article use needs an Opus audit and Andrii's sign-off.
- Director follow-ups: per-row `nDays` and a low-n flag in the simultaneity table (display milestone; would trip the key-set stop).

## Acceptance
Run `tools/run_ingest.py` end to end with `XT_ACK_GTR_BAND`; `release_check.py` green; scoped blind audit of the cold numbers (n, days, ambient range, EnergyIntensity value and interval, leave-one-day-out) before the dashboard is presented.
