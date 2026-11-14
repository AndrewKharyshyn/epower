# M646 pre-registered spec (Rev 0): Cold-minus-Warm and Shoulder-minus-Warm contrast in the Compare charts

Status: Rev 0, written BEFORE any M646 result exists (2026-11-14; master 665 drives, MD5 77bbe275f8c22eaf62d8636867764af3). Gate NA: spec, `research-director` review, blind audit (`analytical-auditor`) before any payload or dashboard change.

## 0. Owner decision (recorded verbatim, 2026-11-14, Andrii, in chat)
"I think I misunderstood last time and I want that cold-warm contrast back". Scope answer (AskUserQuestion): "Compare charts only (Recommended)" = a Cold-minus-Warm difference with a day-clustered bootstrap interval for the Compare metrics, plus an adjusted version that standardises route mix; the regeneration view keeps its per-stratum bars. On the article: "Article is my own responsibility." (CLAUDE.md article rule is not edited by this milestone; the dashboard shows the contrast and the article decision is the owner's.) This supersedes ONLY the clause "no cold-versus-warm contrast" in the 2026-11-10 (M608) owner decision for the Compare charts. Fast-versus-slow stays undrawn, the B6 cadence-invariance check stays FAILED and shown, regeneration is untouched.

## 0b. Rev 1 (Director review 2026-11-14, research-director; supersedes any conflicting clause below)
Verdict: revise (minor), go once Rev 1 is frozen and hashed before any run. Answers: (a) ratio-of-sums D_raw with a joint day bootstrap is primary, route-only D_adj secondary; season cannot be matched out (Cold and Warm are separate calendar periods, so season, period, load and ECU/tyre epoch are confounded with the class and nothing in this data separates them: stated in the block, not attempted); (b) M1-M3 only, fuel deferred to its own spec; (c) floors kept plus R3/R4; (d) labelling sufficient if the caption is on every row (R8).
Required changes, all adopted:
- R1 Strata below 5 % weight are excluded from D_adj and the remaining weights are renormalised to sum to 1; the excluded km share is reported.
- R2 Sensitivity (vi) is removed.
- R3 Effective-days rule: a contrast whose smaller cohort has fewer than 10 effective days (1 / sum(day km share^2)) is labelled exploratory and the interval ladder is not applied (point and interval shown, no verdict wording).
- R4 Drop-rate rule: if more than 1 % of replicates are dropped for a metric and contrast, that row is "not estimable" (conditional dropping biases the interval); the drop rate is always reported.
- R5 Section 7 reproduction applies to M1, M2 and M3 against `cohortSupport`/the cohort distributions to 4 decimals. Engine-on = `engine_on_pct` of `drive_master.csv` as stored (version and rpm threshold stated from the M538-M546 option A basis, read from the payload's own provenance, not typed); M3 denominator uses only drives with a defined `ev_dist_km`.
- R6 The 12 intervals (3 metrics x 2 contrasts x raw/adjusted) are descriptive, with no multiplicity correction; the word "significant" is never used.
- R7 The CLAUDE.md change is additive and limited to Compare: the 2026-11-10 regeneration clause "no cold-versus-warm contrast" stays in force for the regeneration view.
- R8 Language rules (id M646) also forbid: winter penalty, seasonal penalty, due to cold, cold increases / raises, temperature-adjusted, controlled for confounding, "no difference" as a reading of an interval including zero. Required wording: "route-mix standardised (urban/non-urban only)". The caption "difference between thermal classes (season, route, load, period move together), not a temperature effect" is on every row.
- R9 Each row shows "not an article figure; article use requires the Opus audit and the owner's sign-off per the project rule" (the owner's statement "Article is my own responsibility" is recorded; the standing rule in CLAUDE.md is not edited here, and the owner may change it separately).
Optional, adopted: the Cold and Warm calendar windows are shown beside each contrast; the leave-one-day-out min/max is shown next to the interval.
Limits stated in the block: few clusters make the percentile interval unreliable; season, period, load and epoch are confounded.

## 1. Problem
The Compare charts overlay Cold, Warm, Shoulder and All but draw no difference, so a reader subtracts by eye. Two things make a naive difference misleading, and both are disclosed rather than hidden: (a) the cohorts are thermal classes (assigned `thermal_regime`, after the M426 reassignment) that are not matched on route mix (Shoulder and Cold are mostly urban; Warm has more non-urban km); (b) a thermal class is also a calendar period, so "Cold minus Warm" is a difference between thermal classes (season, route, load, logging period), never an identified temperature effect.

## 2. Population and metrics
Population: canonical-clean drives (`ens_outlier_v2` False; a missing flag is never clean, per `eligibility.py`), `distance_km` > 0, with the metric's own eligibility. Cohort = `thermal_regime` of `seasonal_drive_master.csv` (assigned class; the physical-threshold class is a sensitivity). Primary metrics (ratio-of-sums, same definitions as `cohortSupport.metrics` and `cohort_distributions.py`):
- M1 gross pack throughput per 100 km = 100 x sum(gross_throughput_kwh) / sum(distance_km), drives with distance >= 1 km (as in the cohort support block).
- M2 engine-on share of time = sum(engine_on_pct/100 x duration_s) / sum(duration_s).
- M3 EV distance share = sum(ev_dist_km) / sum(distance_km), drives with a defined `ev_dist_km`.
Deferred (not in Rev 0): fuel L/100 km (separate source `fuel_recon_master.csv`, partly instrumented; Director to decide whether to add), regen share of charge (weighting ambiguous), every metric whose Compare spec carries only a precomputed cohort summary without per-drive values. Those frames show no difference and say so.

## 3. Estimands
For metric m and contrast cohort c in {cold, shoulder} against warm:
- D_raw(c) = R_c - R_warm, R = the cohort ratio of sums (unadjusted).
- D_adj(c) = sum_s w_s (R_{c,s} - R_{warm,s}), s in {urban, non-urban} (drive_type collapsed as in M639; highway has too few drives), w_s = km share of stratum s in the canonical-clean reference set (ALL cohorts, fixed, script-derived, never per contrast). R_{c,s} is the cohort-by-stratum ratio of sums. D_adj answers "same route mix"; it does not remove season, load, tyre/ECU epoch or logging period.
- Also reported: relative difference D/R_warm for M1 only.
- D_raw and D_adj are reported side by side. If their signs disagree, or one interval excludes zero and the other does not, the block says "the contrast depends on route mix" (method disagreement is reported, not tuned away).

## 4. Support rules (pre-registered)
A cohort-by-stratum cell is SUPPORTED with >= 10 drives on >= 5 calendar days (the project floor). D_adj for a contrast is computed only if both cohorts' cells in every stratum with w_s >= 5 % are supported; otherwise D_adj is "not estimable" with the reason, and only D_raw is shown. D_raw needs each cohort to have >= 10 drives on >= 5 days. No interval and no difference is drawn below those floors.

## 5. Uncertainty
Day-clustered percentile bootstrap, seed 42, 4000 draws. The cluster is the calendar day, resampled JOINTLY over the union of days (a day can hold drives of two cohorts, so the cohort estimates are dependent; each replicate recomputes both cohort ratios from the same resampled days, with the reference weights FIXED). A replicate in which a needed cell is empty is dropped and the drop rate is reported per metric and contrast. Interval = 2.5/97.5 percentiles; effective number of days (1/sum share^2 over day km) reported. No p-value and no TOST (windows differ and the contrast is descriptive); the decision wording ladder is "interval excludes zero" / "interval includes zero (not distinguished at this support)" - the second never read as "no difference".

## 6. Sensitivities (pre-registered, never tuned)
(i) physical-threshold cohort labels instead of assigned; (ii) leave-one-day-out range of D_raw and D_adj; (iii) without the largest drive of each cohort; (iv) 4-stratum drive_type instead of 2 (flagged extrapolative if a cell is unsupported); (v) km-weighted per-drive means instead of ratio of sums for M2 and M3; (vi) removed in Rev 1 (R2).

## 7. Falsification and acceptance
The block is a failed implementation, not a finding, if: the cohort ratios do not reproduce `cohortSupport.assigned.<c>.metrics.grossKwhPer100km.value` (M1) to 4 decimals; D_raw differs from R_c - R_warm computed from `cohortSupport`; the bootstrap is not deterministic with the seed; or the blind audit does not reproduce the estimates and intervals to the displayed digits from the spec definition alone.

## 8. Implementation, isolation, language
- Tool `tools/m646_cohort_contrast.py` emits the new top-level payload key `cohortContrast` (strata table, supports, estimates, intervals, drop rates, sensitivities, provenance: master MD5, script sha, spec hash) by additive splice; deep diff shows only that key plus its `_artifactStamps` entry. Known-answer test under `tests/synthetic/` (synthetic cohorts with known ratios, exact D_raw and D_adj, deterministic seed, unsupported cell flagged). Ingestion stage `cohort_contrast` (`verified:false` until the first full run).
- Dashboard: a "Difference from Warm" frame under the Compare charts for M1-M3, bound to `S.cohortContrast`; point difference with interval and n (drives, days) per contrast; unadjusted and route-adjusted rows; the disclosure "difference between thermal classes (season, route, load and logging period move together), not a temperature effect". No difference drawn for frames without per-drive support. Language rules with the M646 id: forbidden "cold penalty", "effect of cold", "cold-temperature effect" (as a reading of this difference), "controlled seasonal contrast"; the Warm - Shoulder caption already denies controlled contrast and stays.
- The 2026-11-10 wording "no cold-versus-warm contrast" in `CLAUDE.md` is replaced by the M646 owner decision in the CHANGELOG entry; CLAUDE.md gets the owner-decision line in the same commit.

## 9. Decisions requested from the Director
(a) Is the ratio-of-sums D_raw with a joint day bootstrap the right primary, and D_adj (route only) an adequate adjustment, or must season/period be handled (e.g. within-month matching) before display? (b) Are M1-M3 the right first set, and should fuel L/100 km be added now? (c) Support floors and the "not estimable" rule as written? (d) Is the labelling sufficient for a contrast between thermal classes that are also calendar periods? (e) Any required change before implementation.

## 10. Rev 1.1: deviations recorded after the first run and the blind audit (2026-11-14; no estimand changed)
- The "drive distance >= 1 km" clause of section 2 (M1) contradicted section 7 (M1 must reproduce `cohortSupport`, which has no 1 km filter: warm 17.2050, shoulder 19.5827, cold 19.8374). The implementation follows the reproduction rule; the >= 1 km basis (the `cohortDistributions` basis) is reported as the sensitivity `driveKmAtLeast1`. The blind auditor followed the literal 1 km clause; its point estimates equal that sensitivity exactly (cold raw 2.5132, shoulder raw 2.2889 and adjusted -0.8306).
- `distance_km > 0` is applied to every metric (section 2); the first run missed it for M2 (found by the blind audit: warm M2 43.4514 -> 43.6074 after the fix).
- Eligibility: a drive is excluded only when `ens_outlier_v2` or `ens_invalid` is explicitly True (the `cohort_support.py` / `cohort_arrays.py` convention; 12 early drives carry no flag and no energy integral). The strict reading of section 2 (a missing flag is never clean) is the sensitivity `missingEnsFlagNotClean` (M1 ratios identical; reference weights urban 0.320 -> 0.324).
- Sensitivity adjusted values are withheld whenever the adjusted contrast is not estimable (an unsupported route cell).
- Reproduction of M2 and M3: `cohortSupport` carries no M2/M3 ratio; they are reproduced by the blind audit instead (agreement to the displayed digits for the point estimates; intervals agree to within 0.1 of the interval width at a second random seed, as the RNG construction differs).
- Owner note (2026-11-14, in chat): "Cold data will arrive later as we move forward. If today data is thin, this would change with adding new drives during cold months. The same will apply to shoulder as March-May data is still expected." Consequence: nothing in the block is hard-coded to the current support. The stage `cohort_contrast` recomputes at every ingestion; the floors (10 drives on 5 days, 10 effective days, 1 % drop rate) are re-evaluated on the new data, so the Cold exploratory state and the not-estimable route-standardised version lift automatically once the support allows. Two cautions carried by the block: the Shoulder cohort will then pool autumn and spring periods (its calendar windows are printed so the pooling is visible), and every re-run changes the displayed numbers, so a figure quoted from an earlier run must cite its run (corpus size, master MD5 in `_provenance`).
