# M511 spec (Rev 1): canonical-clean eligibility for the SoC-balanced fuel population (audit 2026-10-25 A03)

Status: Rev 1, written 2026-10-25 BEFORE any M511 computation. Origin: independent audit 2026-10-25, finding A03: `_soc_balanced_fuel` (`compute_summary_arrays.py`, module H) loops over every row of the supplied master and never applies the canonical exclusion (`ens_outlier_v2` == `ens_invalid`, helper `_canonical_bad`) that the comparable fuel analytics and the generator families use. The audit's counts and values are known-answer targets for the reproduction check only; they are not typed into code or payload, and the result JSON records whether the script reproduces them.

## Question
How does applying the project's canonical-clean eligibility to the SoC-balanced-fuel population change the headline balanced consumption (eta = 0.30), the raw fleet consumption, the other eta rows, the day-clustered interval and the descriptive regression, and which files are affected?

## Estimand and population
Unchanged estimand: ratio-of-sums fleet consumption, L/100 km, raw and SoC-balanced (dFuel = dE / (eta x LHV), dE = dSoC/100 x CAP_KWH, CAP_KWH = 2.1 `verified:false`, eta in {0.25, 0.30, 0.35}, headline 0.30).
Primary population (new): master rows with a usable fuel accumulator (existing `_hf_perdrive` acceptance, unchanged) AND NOT `_canonical_bad(dm)` (rows with a missing flag are not excluded, as everywhere in the builder).
Sensitivity population (the former one): all master rows with a usable accumulator, i.e. the primary population plus the canonical-invalid trips.
Decision, with its reason: the energy-rate rule in CLAUDE.md says energy rates use canonical-clean eligibility, and fuel is a rate of the same family. Invalid pack telemetry does not automatically invalidate the fuel accumulator; that scientific question is NOT decided here. The former population is kept as a labelled matched sensitivity so that the difference is visible rather than silent. If the Director prefers a named exception instead, the code change is limited to which population is primary.

## Method (no new estimator)
1. Compute the canonical-bad mask once and filter the loop before `_hf_perdrive`. Nothing else in the producer changes (same acceptance, same integrals, same constants, bootstrap: day cluster, seed 42, 4000 draws).
2. Run the producer twice on the same master: primary (filtered) and sensitivity (unfiltered). Emit the sensitivity as an additive nested block `socBalancedFuel.allMasterSensitivity` with: nDrives, nDays, the headline balanced and raw fleet values, the day-bootstrap interval, `extraFiles` (exact file names of trips present only in the sensitivity population, with their ens flags) and a `populationLabel`.
3. Add `socBalancedFuel.eligibility` = {"rule": "canonical-clean (ens_outlier_v2 == ens_invalid False or missing)", "nExcludedByRule", "excludedFiles"}; the methodology string states the rule.
4. Payload keys of the existing block keep their names; only values change (nDrives, nDays, totals, fleet values, intervals, dSoC summary, regression). The array update uses the additive-splice pattern for the single key `socBalancedFuel` (compute only that key, deep-diff, leaf splice). No master column, no other key changes.
5. Provenance: master MD5, script sha256, spec sha256, in the result JSON `analyses/M511_result.json`.

## Primary and sensitivity analyses, decision rules
Report as is: primary vs sensitivity headline, delta in L/100 km, delta relative to the primary interval half-width, delta in nDrives and nDays, the extra files and their flags. Acceptance for the change (not a statistical test): (a) the excluded set equals the set of accepted-accumulator trips with a True canonical flag, verified from the master independently of the producer; (b) every other numeric leaf of other payload keys is byte-identical in the isolation diff; (c) the primary headline stays inside the previous interval or the Director is told. Escalation: if the headline leaves its previous CI, or the number of excluded trips exceeds a handful, stop and report to the Director. No result is tuned; the sign or size of the delta does not select the population.

## Falsification
The change is wrong if the excluded files are not exactly the canonical-bad accumulator trips, if any other payload key moves, if the filtered producer is not reproducible run to run, or if the sensitivity block does not reproduce the former headline exactly (the sensitivity run must equal the pre-change payload leaf by leaf).

## Language
"canonical-clean population", "matched sensitivity (all accepted accumulator trips)". Never "corrected", "error", "bug fix" in payload or dashboard text; the CHANGELOG records it as an eligibility-policy alignment. Fuel is "logged / app-calculated", CAP_KWH stays `verified:false`.

## Scope and out of scope
In: the eligibility filter, the sensitivity block, the eligibility note, tests, CHANGELOG, dashboard rebuild with the new counts (content change: the Dashboard change rule applies). Out of scope: the false "no pure-highway fuel" and "warm-season only" sentences (M510, they are generated from accepted-row support counts there); CAP_KWH; eta choices; the counter-vs-rate FUEL-12 analysis; any change to other fuel families.

## Tests and gates
Known-answer test `tests/synthetic/test_soc_balanced_fuel_eligibility.py` on a synthetic master and a stub raw loader: a canonical-bad trip is excluded from the primary and present in the sensitivity; the sensitivity equals the unfiltered run; a row with a missing flag is kept; a hand-computed ratio of sums matches. Chain: py_compile, JSON round trip, isolation diff, `node build_html.js`, `node validate_jsdom.js`, `release_check.py`, CI unit list, semantic gate. Blind audit (analytical-auditor, claim + data path only: reproduce the primary and sensitivity populations and headline from raw and the master). Director decision on population and the exception alternative.


## Rev 2 (research-director ruling "revise", R1-R8; this section replaces any conflicting Rev 1 text above; written before any M511 computation)
Ruling: canonical-clean is the correct primary population, not a named exception: the balancing term dE = dSoC/100 x CAP_KWH uses BMS SoC (pack telemetry), so a canonical-invalid trip makes the balanced figure less trustworthy. The raw fleet figure does not depend on pack telemetry; the exclusion is justified by the balancing term and the common population is kept so both figures share one trip set. Eligibility-policy alignment; the estimand does not change.
R1: eligibility comes from `eligibility.py` (M375: `excluded_files` / `canonical_clean`), the rule the fuel/GTR family already uses, NOT `_canonical_bad`. A missing `ens_outlier_v2` flag, a missing master row or an `ens_invalid`/`ens_outlier_v2` disagreement for an accepted accumulator trip is a STOP (EligibilityError), never "kept". The Rev 1 statements that a missing flag is kept (population definition, test list) are void.
R2: rule string in the payload: "excluded if ens_invalid OR ens_outlier_v2 is True (eligibility.py, M375)".
R3: the sensitivity block is named `allAccumulatorSensitivity` (not `allMasterSensitivity`). `_hf_perdrive` runs once per trip; the primary population is a subset of that one pass, so the two are matched. Block fields: nDrives, nDays, dateSpan, rawFleetL100, byEta fleetL100, socBalancedFleetBoot, deltaVsPrimary (headline balanced and raw), extraFiles with their flags, populationLabel.
R4: control C0 BEFORE any filtering: the new code run unfiltered must equal the stored `socBalancedFuel` block leaf by leaf (methodology string excluded, as in M338). If not, STOP and report provenance drift; it is never mixed into M511.
R5: pre-registered escalation (replaces "a handful"): escalate to the Director if more than 5 trips or more than 2 days are excluded, if the headline or rawFleetL100 leaves its previous CI, if the sign of fleetDelta flips or if dateSpan changes. Leaving the CI additionally requires a blind audit pass before any merge.
R6: rerun `tools/fuel_contract.py` and diff `fuel_contract.json` `subsets.socBalanced` (its nDrives/nDays/dateSpan read the payload); `fuel_contract_flag.py` only checks the fuel_recon_master MD5, so add an assertion that `subsets.socBalanced` equals the `summary_arrays.socBalancedFuel` counts.
R7: JSX `SocBalancedFuel`: the KPI text and the section-title dateSpan rebind automatically; add one script-bound line from `S.socBalancedFuel.eligibility` (nExcludedByRule) and the sensitivity value, no literals. Run `language_gate` / `semantic_gate` A2 on the new strings. The "no pure-highway fuel" / "warm-season only" sentences stay M510.
R8: a test that the builder path (`arrays['socBalancedFuel']` in `compute_summary_arrays.py`) emits the eligibility and sensitivity blocks, so the next ingestion keeps them (testing only the splice tool is not enough). `drive_master.csv` MD5 recorded before and after.
Follow-up (inventory only, not changed in M511): `thermalFuelPenalty` accumulator subset may have the same gap.
