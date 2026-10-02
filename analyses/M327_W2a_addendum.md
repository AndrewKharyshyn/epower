# M327 (= wording sweep W2a) addendum, committed BEFORE any edit: thermal cohort, Cold counts, ambient/pack-temperature literals
Spec: analyses/M326_spec.md rev 2 (wave W2). Numbers are proposals; M326 (W0) is merged. W2 is split: W2a (this PR) = strings that can be made payload-bound or removed without new keys; W2b = the rest (listed at the end).
Pure wording + generated text. NO payload key renamed or added; summary_arrays.json changes only in the declared builder-label leaf(s) (below). Isolation: drive_master.csv, raw/, raw_manifest.json unchanged.

## Verified data facts used for binding (disk, 2026-10-02)
- Cold: S.cohortMeta.cold.nObserved = 2 (suppressed below minimum support 10); S.ambientTable.rows with c === "cold" = 2 rows, both date 2026-09-30, ambient m = 5 C; S.seasonalCharts._meta.cohortCounts.cold = 0 is the ELIGIBLE/inference count, not the observed count.
- Pack-probe minimum: records row metric "Battery temp min" = "11°C" (row-wise min over sensors 1-4). S.batteryThermalMeta has NO tMinC key (the jsx used a literal fallback ?? 12).
- Ambient below 15 C does exist: the 2 Cold drives (5 C, driver-recorded) and the 10-15 C bin of the HVAC chart.

## Helpers added to xtrail_summary.jsx (no new payload keys)
H1 `function coldObservedInfo()` returns {n: S.cohortMeta?.cold?.nObserved ?? cold ambientTable rows, dates: distinct dates of the cold rows, ambC: their ambient values}.
H2 M294.coldNote (string) = `${n} observed ${n===1?"drive":"drives"}${dates? ` on ${dates.length} ${dates.length===1?"date":"dates"} (${dates.join(", ")})`:""}, below the minimum support (descriptive only, no statistics)`.
H3 M294.packTempMin = the "Battery temp min" record value.

## Exact replacements
E1 cohort selector label: `>Season</span>` -> `>Thermal cohort</span>` (C11.2, p20.2).
E2 badge: "All-data reference · season filter does not apply" -> "All-data reference · thermal-cohort filter does not apply" (C11.2, D-20).
E3 selector note: "Season filter applies only to sections without an <em>All-data reference</em> tag; tagged sections, narrative, records and provenance are corpus-wide. A cohort view needs ≥{COHORT_MIN_SUPPORT_DRIVES} drives (Cold: {cohortCount("cold")})."
   -> "The thermal-cohort filter (ambient classes, not calendar seasons) applies only to sections without an <em>All-data reference</em> tag; tagged sections, narrative, records and provenance are corpus-wide. A cohort view needs ≥{COHORT_MIN_SUPPORT_DRIVES} drives (Cold: {coldObservedInfo().n} observed, below support)." (D-20, F08.r2, p20.6)
E4 ColdNoData: for the Cold class show "{label} cohort: {M294.coldNote}; the cohort view requires at least {N} drives, so no curves, no statistics and no winter inference are shown. The all-data figures are not substituted." For other classes keep the count sentence but drop "-season drives are logged" -> "drives are logged" (p21.13, F13.8, p20.6).
E5 seven "; no Cold" literals (jsx L4462, 11238, 11312, 11356, 11376, 11502, 11647): "({M294.regimesObserved}; no Cold)" -> "({M294.regimesObserved} analysed; Cold: {M294.coldNote})" (template-literal forms use ${...}); "(... regimes; no Cold)" -> "(... regimes analysed; Cold: ...)" (F13.8, D-3, F24).
E6 "no sub-15" literals:
  a (L1840) "Assumption-heavy seasonal reweight; no sub-15 °C pack data." -> `Assumption-heavy seasonal reweight; the lowest logged pack-probe reading is ${M294.packTempMin}.`
  b (L2809) "No sub-15°C pack data exists; the cold tail is assumption-driven" -> "The lowest logged pack-probe reading is {M294.packTempMin}; the cold tail below it is assumption-driven"
  c (L6679) "No sub-15°C data exists (warm-season corpus); the 10–15°C bin has only {bins[0]?.n ?? "few"} drives." -> "Ambient below 15 °C is thinly observed: the 10–15 °C bin has only {bins[0]?.n ?? "few"} drives, and the Cold class is {M294.coldNote}." (self-contradictory before)
  d (L7453) "No sub-15 °C ambient data exists, so this is warm-season cold-starts." -> "Ambient below 15 °C is observed only for the Cold class ({M294.coldNote}), so these are mild-ambient cold-starts."
  (D-2, F24, p21.10)
E7 "the whole corpus is warm-season, so pack thermal exposure is characterised directly" (L2809) -> "the logged corpus spans the {M294.regimesObserved} ambient classes ({M294.dateRange}), so pack thermal exposure is characterised directly" (p21.10)
E8 "Warm-season data only." (L11591 footer of the health indicators) -> "Data span {M294.dateRange} ({M294.regimesObserved} ambient classes analysed; Cold: {M294.coldNote})." (p21.10)
E9 builder build_assumptions_registry.py label 'Seasonal cohort thresholds' -> 'Ambient thermal regime thresholds' and the matching payload leaf in assumptionsRegistry (exact-string leaf splice, idempotent; thresholds unchanged) (p20.2). Only if the label exists exactly once in the payload; otherwise W2b.
E10 glossary (p20.4, F24.r1, p25.7): one short Methods block "Terms" with static definitions, no numbers: ambient thermal cohort (Warm/Shoulder/Cold classes of ambient temperature, not calendar seasons); pack temperature (row-wise mean/min over the logged probes, as labelled per chart); engine thermal state; cold soak (verified only where the logged gap supports it); "cold ambient, cold pack, cold engine start and verified cold soak are different states and are not interchanged". Plus the limit: "Winter consumption and ageing cannot be inferred: Cold is observed on {M294.coldNote}" (bound).

## Language gate additions (W2a rules, regex on normalised text)
W2-nocold: r"\bno cold\b(?! (?:pack|soak|start|season|ambient|cohort|temperature))" (does not hit 'no cold-pack thermal behaviour observed'); W2-sub15: r"\bno sub 15\b"; W2-seasonlabel: r"\bseason filter\b"; W2-warmseason-corpus: r"\bwhole corpus is warm season\b|\bwarm season data only\b".
REQUIRED (payload-bound): the rendered Conclusions/Health text contains `Cold: ` + the observed count and date from the payload (2 observed drive(s), 2026-09-30); the selector label reads "Thermal cohort"; the HVAC caveat contains the 10–15 °C bin count from the payload.
Tests: language-gate known-answer fixtures for the new rules (incl. the 'no cold-pack' near-miss), release_check, jsdom 0 console errors.

## Deferred to W2b (not in this PR)
DATA/payload: F08, p20.3, Cs-43 (cohortCounts observed vs eligible schema; M327 arrays), Cs-53, Cs-55, Cs-58 (hand-typed rows, ambient provenance per drive), B-fam-11 (F09 sidecar), F10 (pulled out). Wording needing separate care: F12.4, F25.r3, p20.9, p21.16, Cs-26, Cs-29, Cs-44, Cs-50, Cs-72, B-fam-12, B-fam-13, Cs-6, F27, D-12/R2 (coolant-loop topology in summary_config.json), D-L6, and the remaining 'warm-season' mentions (L1837, 2259, 2310, 3809, 7277, 7329, 7588).
Isolation: arrays deep-diff limited to the E9 leaf (if applied); jsdom text diff limited to replaced strings; release_check green.
