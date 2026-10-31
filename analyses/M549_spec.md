# M549 spec Rev 1 (2026-10-31, before any code): temperature-probe ranking tie policy (audit 2026-10-29 F01)

Status: PRE-REGISTERED DRAFT for Director review. Nothing implemented. Tier B (number-changing): spec, blind audit, Director decision. Branch base: `main` at M548 (`6767cbd`). Ledger id prefix `AUD29-F01`.
Origin: `epower_audit_2026-10-29.html` F01 (P1) and its "Temperature ranking" wording row. The audit's own figures (first / fractional / unique hottest 89.30 / 67.44 / 48.56 %, hottest ties 41.45 % of time, coldest 75.64 / 85.05 / 75.64 %, 407 drives, 122.4 h) come from a different, fresh support and are external corroboration only, never a target and never typed into the repo. Every reported figure is written by a script from the corpus.

## 1. Inventory (read from the code at M548)
| Item | Site | Fact | Decision |
|---|---|---|---|
| accumulator | `_RawAccum.add`, "sensorSummary" block: `np.argmax` / `np.argmin` over the columns [T1..T4] of the rows with all four probes valid | the first index wins every tie; counts are ROWS at the native cadence after the per-column native `ffill(limit=15)` (up to 16 rows per sparse reading), not elapsed time | keep as the legacy "first-index row share"; add a new block beside it |
| `sensorSummary[*].role` | builder strings "Hottest probe — reads highest in {hotpct}% of samples" (T1), "Coldest probe — reads lowest in {coldpct}% of samples" (T4) | rounded legacy shares in a payload TEXT leaf; also in `cohort_arrays.json` (`SensorSummary` per cohort) | text leaves regenerated from the new block (keys never renamed) |
| `eolBaselines.s1Delta.hottestPct` | same counters | numeric legacy share, shown in the Health reference sentence ("Sensor 1 is hottest probe in X % of samples") | key and value unchanged and relabelled "first-index row share"; the displayed sentence also states unique and tied time |
| display | `xtrail_summary.jsx` `BatteryThermalChart` (sensor roles), the eol baselines reference line | role text only | roles read the new block through a guarded accessor |

Not in scope: any other thermal block, the probe lo/hi ranges, intake air, the seasonal cohorts' definition, the master and ML16, any article figure.

## 2. Estimands (per probe p in {T1..T4}; hot = maximum, cold = minimum over the four probes of a valid second)
For a valid second let M = max over probes (m = min for cold) and K = {p : value_p = M}, k = |K|.
- `unique(p)`: seconds with K = {p} (k = 1) divided by valid seconds.
- `tied(p)`: seconds with p in K and k >= 2 divided by valid seconds. `unique(p) + tied(p)` = the share of seconds in which p is at the extreme (any tie).
- `fractional(p)`: sum over seconds with p in K of 1/k, divided by valid seconds. The four fractional shares sum to 100 %.
- `tieTime`: seconds with k >= 2 divided by valid seconds (the share of time with no unique extreme), reported for hot and cold.
- `firstIndex(p)`: the legacy rule (argmax / argmin, lowest index wins), recomputed on the same seconds as a diagnostic of the bias, labelled "tie-biased, not a physical share".
Permutation invariance: reordering the probe columns must not change any named-probe result (only `firstIndex` is order-dependent, and it is labelled).

## 3. Weights, population, freshness
- Primary population: the pipeline 1 Hz grid of `_RawAccum.add` (`hz`, conventions of record section 3), one grid second = one second of elapsed time (this is the elapsed-time weighting the audit asks for: native rows are NOT equal-time under the sparse and the fast polling regimes), seconds with all four probes valid, plausibility mask unchanged (-40..90 C).
- Value used for a tie: the grid second's value of each probe after the pipeline aggregation. Probe readings are logged at coarse resolution, so equality of the grid values is the tie test (exact float equality on the aggregated value). Sensitivity S1: the M542 `last` aggregator (value of the natively filled series at the last native row inside the second), because a MEAN over several native readings can break or create ties that the native readings did not have.
- Freshness: the pipeline grid carries values forward by up to 15 native rows and up to 15 grid seconds, so a "valid" second may rest on a stale reading. Primary population: no freshness filter (identical to the legacy support, so the comparison with the legacy share isolates the tie rule). Sensitivity S2: only seconds in which every probe has a native (unfilled) reading within the preceding 5 s. Both are reported with their seconds, drives and days; the displayed role text uses the primary and states the S2 support share.
- Cohorts: pooled, and the three thermal regimes (warm, shoulder, cold) with the same `thermal_regime` map as `cohort_arrays.json`; cold is exploratory (2 days, no interval) as elsewhere.

## 4. Intervals
Calendar day is the resampling cluster. Each share is a ratio of sums (seconds in the numerator state / valid seconds), day-clustered percentile bootstrap, seed 42, 4000 draws, 95 %; every estimate carries seconds, drives and days. Fewer than 5 days: exploratory, no interval.

## 5. Known answers and expectations (pre-registered)
- KA1 (the audit acceptance test, synthetic): four equal probes for N seconds: unique = 0 for every probe, tieTime = 100 %, tied = 100 % for each probe, fractional = 25 % each, hot and cold alike.
- KA2 (permutation): every permutation of the four columns leaves unique, tied and fractional of each NAMED probe unchanged; `firstIndex` changes (asserted, so the diagnostic is proven order-dependent).
- KA3 (partition): per drive and pooled, sum over probes of fractional = 100 % exactly; sum over probes of unique + (seconds with k >= 2 weighted by 1) consistency: sum_p unique(p) + tieTime = 100 %.
- KA4 (G0, legacy reproduction): the legacy row rule on the legacy row population reproduces the stored `sensorSummary` role percentages and `eolBaselines.s1Delta.hottestPct` exactly before anything is added (the accumulator's own counters are read, not recomputed from memory).
- KA5 (ordering, expectation not a gate): `firstIndex >= fractional >= unique` for the probe that wins ties by index; if the ordering fails on the corpus the tie rule or the population is wrong and the milestone stops.
- KA6 (synthetic cadence): a frame with 4 s native gaps on one probe: the primary grid weights the stale seconds as the pipeline does; S2 drops them; the second counts equal the hand count.
- Corroboration only: the audit's direction (T1 hot: first > fractional > unique, large tie share) is stated as an expectation; no figure is matched or tuned. Disagreement with the audit is reported, not tuned away (the supports differ).

## 6. Implementation plan
Tool `tools/probe_ranking.py` (read-only over raw via the same loader and the same `hz` construction as `_RawAccum.add`, per-drive sufficient statistics cached by the raw sha256 and the extractor source hash; aggregation never rereads raw) writes payload key `temperatureProbeRanking` = `{rule, pooled, byCohort, sensitivity {last, fresh5s}, legacy {firstIndexRowShare, nRows}, detail, limits, provenance}`. Stage `probe_ranking` in `tools/ingest_stages.json` (recomputed at every ingestion; only new drives are extracted). Additive splice into `summary_arrays.json` and `cohort_arrays.json` of the new key and of the text leaves `sensorSummary[*].role` (pooled and per cohort), deep-diff equal to the declared leaves, `drive_master.csv` MD5 unchanged (`5556a0c6...`), ML16 untouched. `compute_summary_arrays.py` builder strings change to the same wording so a rebuild matches the splice. No payload key renamed.

## 7. Display and language
Roles become generated sentences: "Sensor 1: uniquely hottest in X % of observed time (95 % CI a-b, N drives on D days); tied-hottest in Y %; at the extreme in X+Y % (any tie)". T4 analogously for coldest. The legacy "reads highest in 88% of samples" wording is retired by `language_gate.py` rules (ledger id AUD29-F01): "reads highest in", "reads lowest in", "hottest probe in .* of samples" (dom, jsx, payload, config scopes as applicable); allowed: "often warmest", "uniquely hottest". The eol baselines reference sentence states the first-index row share only under that label. Compare mode keeps nothing of the old wording.

## 8. Acceptance, escalation, audit
- A0: `drive_master.csv` MD5 and ML16 untouched; G0 = KA4 before the producer is run (own commit).
- A1: blind audit (Sonnet, `analytical-auditor`) on a sample drawn and committed before any code or producer run (`analyses/M549_audit_sample.json`: 24 drives, seed 42, stratified by cadence regime x thermal regime, plus 4 drives with the highest legacy tie share); the auditor receives the claim, the conventions of record and the raw path only, reproduces unique / tied / fractional per drive from raw within 1 s per drive and the pooled shares to the displayed precision.
- A2: KA1-KA6 pass; payload additive; deep-diff equals the declared leaves.
- A3: escalate to the Director if KA5 fails, if the S1 or S2 sensitivity moves any displayed unique share by more than its day interval half-width, if any audit mismatch appears, or if T1's unique-hottest share differs in direction from the legacy ordering (T1 not the most frequent unique-hottest probe).
- A4: no article figure without the Opus audit and Andrii's sign-off (recorded in the CHANGELOG entry). Temperature probes are app-reported BMS channels: "logged", never "measured".

## 9. Questions for the Director
Q1 Is the pipeline 1 Hz grid (mean aggregation, one second = one second) the right primary population, with `last` as a sensitivity, or should the tie test run on the `last` aggregator primarily because MEAN can fabricate or break ties? Q2 Primary freshness: none (isolates the tie rule), with the 5 s filter as sensitivity: acceptable, or should the displayed role use the fresh support? Q3 Is the day-clustered ratio-of-sums interval the right reading for a descriptive share, and is a cohort split worth displaying for roles (cold exploratory)? Q4 Should the role sentence show unique and any-tie shares, or only unique plus the tie share? Q5 Is a stage in the ingestion list proportionate (new drives only, cached) for a descriptive role label, or should this be a one-off block refreshed only on a method change?

## 10. Rev 2 (2026-10-31): Director review (verdict revise); incorporated. Rev 1 SHA-256 before this edit: 74ea73888da5f8862c1a19b88b520b2d17b70d7840e8933c2d11fb1ee1bb7023
Where this section and sections 1-9 differ, this section governs.
- D1 (Q1; primary aggregator). The primary tie test runs on the `last` aggregator (value of the natively filled series at the last native row inside the grid second), which keeps each probe on its native quantisation so exact equality is a valid tie test. The per-second MEAN is sensitivity S1 (it can create or break ties). One grid second stays one second of elapsed time.
- D2 (three steps, the primary is NOT the legacy support). Reported in this order: (i) legacy row firstIndex on native rows (G0, KA4), (ii) grid firstIndex on the primary grid (the weighting effect), (iii) grid unique / tied / fractional (the tie effect). No step is presented as another.
- D3 (KA5 replaced by exact identities on the same seconds). Hot: firstIndex_hot(T1) = unique_hot(T1) + tied_hot(T1) (T1 has the lowest index, so it wins every tie it belongs to). Cold: firstIndex_cold(T4) = unique_cold(T4) (T4 has the highest index and wins only when strictly lowest). Any failure is a code bug: the milestone stops.
- D4 (Q2; S2). Freshness is defined per probe on the NATIVE rows before any fill (a probe is fresh in a second if it has a native reading within the preceding 5 s). The primary has no filter. S2 is reported per cadence stratum with its support share; a stratum that keeps less than 50 % of its seconds under S2 is labelled "S2 not interpretable" for that stratum.
- D5 (Q3, Q4; display). Role text shows the POOLED figure only: unique(p) and tied(p), each with its own day-clustered interval; the any-tie total only with its OWN bootstrap interval (never a sum of intervals) or with no interval. Fractional, regime and cadence splits go in the detail block with no contrast; cold has no interval.
- D6 (Q5). Ingestion stage (the role text lives in cohort_arrays, rebuilt at every ingestion). Flag in the stage report any unique share that leaves its previous interval.
- D7 (added gates). G-Q: per probe, read the observed value step and report the share of grid seconds whose MEAN value falls off that step (the size of the averaging artefact). KA7: synthetic 0.1 C readings that average to the same value are a tie under `last` only if the native values are equal (and not under MEAN-created equality). Detail block stratified by cadence regime. Escalate if the S1 tie share differs from the primary by more than the primary interval half-width.
