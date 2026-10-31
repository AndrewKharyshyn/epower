# M544 spec (Rev 1, DRAFT for Director review): wave 3-0 of the engine-on migration: evidence for the `_RawAccum` blocks (engine-on duration, engine-on by speed, turbo / boost) under the rule, no payload change

Status: PRE-REGISTERED DRAFT, 2026-10-31, before any code or run. Owner: Andrii (delegation in the M538 / M539 CHANGELOG entries). Programme: `analyses/M539_spec.md` Rev 2; merged M540-M543 (`engineOnRule`, display, cohort split, `rpmOptBand` rule leaves). Director conditions carried from M543 (`analyses/M543_spec.md` section 11): spec before any code; run-boundary shifts and every integer flip pre-registered; known answers from a wave-0 script; the Highway-vs-city boost sentences first; start-rate keeps the name 'RPM onset'; `engineStateMachine` its own wave; `crosscheck_events` inventoried; retire rules without hitting stored-bin text; blind-audit drive sample drawn before the run; any value outside its previous interval escalates. Rule: `tools/engine_on_rule.py` (rpm > 400, strict; closed band [300, 400]).

## 1. Why this wave is evidence only, and the plan it opens
The remaining engine-on blocks are produced inside `_RawAccum.add` (`compute_summary_arrays.py`): the thresholds `rr > 300` (line about 4033, `engineOnDuration`) and `rp > 300` (about 4051 `engineOnBySpeed`, about 4198 `turboByRpm` / `turboBySpeedCtx`, about 4414 the per-class turbo block) are inline literals, and the blocks are rebuilt at every ingestion. Unlike M540-M543, a threshold change moves RUN BOUNDARIES (a segment ends where rpm falls to 400 instead of 300), so the effect on `engineOnDuration` (segment counts, medians, quantiles) is not a recount of seconds and cannot be predicted from the seconds histogram. Therefore, as in M536 (wave 0), the shifts are measured first and pre-registered for the build:
- **M544 (this spec): evidence only.** A read-only what-if tool computes the stored blocks under both thresholds on the same corpus. Output `analyses/M544_evidence.json`; no payload key, no JSX, no dashboard change.
- **M545 (own spec, after this evidence): build** the additive Rule siblings of the affected blocks through a sidecar stage (design options in section 6), with the pre-registered expected values taken from this evidence.
- **M546 (own spec): wave 2c** `engineStateMachine` (`_ESM_EDGES[0]` 400, `rpm >= 400` to `> 400`, expected 0.015 h of exact-400 seconds), with its delta report.

## 2. Blocks covered (inventory)
| Block (payload key) | Threshold site | Basis | Cohort variants |
|---|---|---|---|
| `engineOnDuration` (4 classes: n segments, min, median, p10, p90, max, onFraction, segsPer10min) | `eon = (rr > 300) & valid`, run-length on the 1 Hz grid `hz['eng_rpm']` (NaN breaks a run) | per drive class (`cond_class`) | `seasonalCharts` `EngineOnDuration` (warm / shoulder / cold), `engineOnDuration.byStratum` (cadence strata) |
| `engineOnBySpeed` (7 speed zones, % of rows) | `eng = rp > 300` on native rows, zone from `Z_ENGINE` | row counts | `seasonalCharts` `EngineOnBySpeed` |
| `turboByRpm`, `turboBySpeedCtx` | `eng = rp > 300` on native rows, boost > 0.1 bar | native samples | `seasonalCharts` `TurboByRpm` |
| per-class turbo (`hvcTurbo` accumulator, `HvcEngine80C` consumers) | `m = (rp > 300) & ~isnan(bo)` | native samples | cohort variants where present |
| engine-start rate (`engine_start_rate`, `EngineStartsByType`) | `on = nan_to_num(er) > 300`, run >= 2 s | event detector | cohort variants |
| `engineStateMachine` | `_ESM_EDGES = [400, ...]`, `rpm >= 400` | 1 Hz grid | cohort variants | 
| `crosscheck_events` | docstring / description text only (no code comparison found in the M539 registry) | none | none |
Decisions already taken (M539 Q3, M543): the engine-start rate KEEPS its own name 'RPM onset (> 300 rpm, run >= 2 s)'; its > 400 version is reported here as a sensitivity only and is never called engine-on or engine start. `engineStateMachine` moves in M546. `crosscheck_events` is inventoried: expected result "text only, relabel in M545".

## 3. Method of the evidence tool (`tools/engine_on_wave3_evidence.py`, evidence only)
- Per drive, the SAME code as the pipeline: `_RawAccum` is instantiated twice per drive (threshold 300 and threshold 400) by exec of its source with the four inline literals replaced by a threshold variable (the tool never edits `compute_summary_arrays.py`); drive class, speed, boost and rpm series come from the class itself. Raw files via `ah_throughput.raw_loader` (sha256-verified originals; `raw/` unchanged).
- **Faithfulness gate G0 (STOP otherwise):** the threshold-300 instance reproduces the STORED blocks exactly: `engineOnDuration` (all fields incl. nSegments and quantiles, by class), `engineOnBySpeed` (7 percentages), `turboByRpm`, `turboBySpeedCtx`. If any stored value differs beyond its stored rounding, the tool stops and reports; nothing is adjusted to agree. (Note: the stored blocks include the 606-drive corpus; the tool must use the same drive set and order.)
- **What-if outputs at threshold 400** and the shift against 300 for every stored field: segment counts and the full duration vector summary per class (pooled quantiles from the concatenated segment vectors), onFraction, segsPer10min; per-zone percentages; per-band n, activePct, meanActive, maxBoost; per-class turbo counts. The run-boundary shift is reported as: segments merged (a 300-400 rpm dip no longer splits a run), segments dropped (a run entirely inside 300-400 rpm vanishes), segments shortened, and the net change of count per class.
- Sensitivities (not migrations): engine-start rate at > 400 (count change, no rename); the same duration summaries under the 'last' aggregator are NOT computed (grid hold limits untested, wave 2c).
- Day-clustered intervals: the stored blocks are descriptive without intervals; the evidence adds, for each class, a day-clustered percentile bootstrap (calendar day, seed 42, 4000 draws) of the pooled median segment length at 300 and at 400 so that the shift can be judged against sampling variation; cold and any class with fewer than 10 days is flagged exploratory.
- Cadence strata (fast / slow polled) are reported descriptively with no contrast.

## 4. Pre-registered expectations, tolerances and escalation
- G0: exact reproduction of the stored `engineOnDuration` / `engineOnBySpeed` / `turboByRpm` / `turboBySpeedCtx` (STOP otherwise).
- E1 (seconds): engine-on seconds under the rule are 98.2808 h against 99.8678 h for the stored basis (M540); `onFraction` per class falls by about the class share of the 1.587 h band (small); the tool's pooled values must be consistent with `engineOnRule` within 0.001 h on the same grid definition (it is not the same grid: `hz` here, `grid_rpm` there; the difference is reported, not forced).
- E2 (run boundaries): shifts are NOT predicted from seconds; they are the main result. Pre-registered reading rules: a class median moving by less than 5 % and a segment-count change of less than 5 % is "small"; larger values escalate to the Director before M545 and are shown with the day-clustered interval of the shift.
- E3 (by speed): a zone percentage changes by at most the share of 300-400 rpm native rows in that zone; the integer flips are listed zone by zone (the display shows integers).
- E4 (turbo): bands at 1500 rpm and above are unchanged (boost samples exist only when the engine is on and the lowest band is `<1500`); the lowest band's n, activePct and maxBoost may change; every integer flip listed.
- Escalate to the Director if G0 fails, if any class median or count moves by 5 % or more, if an integer displayed value flips outside the list, or if the rule seconds disagree with `engineOnRule` by more than the reported grid difference.
- Blind audit: >= 20 drives drawn BEFORE the run (seed 42, stratified by class and cadence), per-drive segment counts, segment lengths summary (median) and by-speed row counts at 300 and 400; the auditor states the grid convention (floor-to-second, MEAN, native ffill 15 rows, grid ffill 15 s).
- No master / ML16 / regeneration-proxy change, no article figure, no payload or display change.

## 5. Language
"engine-on (rpm > 400, 1 Hz grid)" for the rule; "rpm > 300 gate" where the stored block states it; "run boundary shift" = a deterministic re-definition on the same data; "RPM onset (> 300 rpm, run >= 2 s)" unchanged; never "corrected", "false engine-on", "artefact", "off-time" for the 300-400 rpm band.

## 6. Design options for the build wave M545 (for the Director's early view, to be decided in the M545 spec)
A. Parametrize `_RawAccum` with an `eng_on_rpm` attribute (default 300, behaviour byte-identical, proven by the G0 style identity test) and run a second accumulator at 400 for the affected sub-blocks in a sidecar stage with per-drive cached state merged by summation (the cohort chart variants come out of the same merge). B. Re-implement the four sub-blocks in a new tool with identity gates at 300 (faithful but duplicated code). C. Change the pipeline threshold itself (a method change of the stored blocks with a no-new-drive control build): rejected unless the Director rules otherwise (it moves published stored blocks and the M299 reference).

## 7. Gates
py_compile, the evidence tool's own gates, a known-answer unit test on a synthetic trace for the run-length logic (dip to 350 rpm inside a run; run entirely inside 300-400 rpm; run ending at exactly 400), `release_check.py`, local CI unit list, CHANGELOG (spec SHA-256 before code, evidence hash, blind audit, Director decision), PR with the gated merge. No dashboard change, so no dashboard rule.

## 8. Questions for the Director
Q1 Is the evidence-first split (M544 evidence, M545 build, M546 state machine) right? Q2 Is the exec-with-substituted-literal method acceptable for an evidence-only tool given the G0 identity gate, or must the tool call a parametrized `_RawAccum`? Q3 Are the 5 % reading rules and the escalation list right? Q4 Should the engine-start rate sensitivity at > 400 be part of this evidence (kept, never renamed)? Q5 Early view on design A vs B vs C for M545?

## 9. Rev 2 (2026-10-31): Director review (revise); incorporated. Rev 1 SHA-256 recorded before the edit: 2215ad7d1bab2d210745803f8435bf931d07d568d81fccb2c68a5acc22134bc2
- **Q1** the sequence M544 evidence -> M545 build -> M546 `engineStateMachine` is right and the three milestones run strictly one after another (`summary_arrays.json` conflicts across parallel branches); the run-boundary shift cannot be derived from seconds.
- **Q2 conditions adopted for the exec-with-substituted-literal method:** (a) substitute ONLY at the registry anchors (lines about 4033, 4051, 4198, 4414), assert the occurrence count of each, record the source SHA-256 and the substitution diff in the evidence file; the regeneration proxy (about 4317, `rp <= 300`, owner decision (g)) and the onset detector (about 4387) stay unchanged unless the onset sensitivity switch is on; (b) before any comparison with stored values, the exec'd copy at threshold 300 must equal the imported `C._RawAccum` per drive (accumulator state equality), STOP otherwise; (c) every `finalize` key outside the targeted blocks must be byte-identical between the 300 and 400 copies; (d) the tool uses the pipeline loader (`drive_raw_cache` frame loader, category-B order and skip behaviour), NOT `ah_throughput.raw_loader`.
- **Q3:** 5 % is a materiality threshold, never "negligible"; the rule applies to EVERY displayed field (min / p10 / median / p90 / max / onFraction / segsPer10min / nSegments), not only median and count; escalation also when a shift falls outside the day-clustered interval of the 300 estimate (M543 condition 6). E3 and E4 become exact IDENTITY gates: the change in each engineOnBySpeed zone count equals the count of rows with rpm in (300, 400]; turbo bands at 1500 rpm and above are identical at 300 and 400.
- **Q4:** the engine-start rate at > 400 is included as a sensitivity only, keeping the name 'RPM onset'; its dependants (`hvcEngineTriggerSoC`, `hvcEngineStopSoC`, `socBands` and the cohort `SocBands`, label "trigger (engine ON)") are reported as COUNTS only, not recomputed as values.
- **Q5 (design for M545, early view):** hybrid of A and B: move the four sub-blocks into module-level pure functions with a threshold argument, called at 300 by `_RawAccum` (identity proven at 300) and at 400 by the sidecar stage; per-drive sufficient statistics cached so cohorts merge by summation; C rejected.
- **Run-boundary taxonomy corrected:** raising the threshold shrinks the on-set, so a run can SPLIT (a dip into 300-400 rpm inside a run), DROP (a run entirely inside 300-400 rpm) or SHORTEN (an end or start trimmed); a run can never MERGE. Section 3 is read this way and the synthetic test is: a dip to 350 rpm splits a run; a run entirely at 350 drops; a run ending exactly at 400 shortens (strict >).
- **Consumers added to the inventory:** `hvc_turbo` feeds `hvcTurboActivity`, which feeds the highwayVsCity row "Turbo activity ... % of engine-on time" (about line 4988): the first display site, together with the Highway-vs-city boost sentences (M543 condition 1); `HvcEngine80C` is coolant-based and NOT affected. The "byStratum" of Rev 1 is `crossVehicle.eventDetectors` (`crosscheck_events.py`, lines about 107-175 and its turbo payload), a CODE consumer that runs `_RawAccum` on the e-4ORCE aux frames and compares it with the primary `engineOnDuration` / `turboByRpm`: both sides must use the same basis (the evidence reports it; the build handles it). `engineOnDuration` itself has no cadence `byStratum`; cadence strata are reported descriptively from `cadence_regime.csv`.
- **G0 extended** to the seasonal cohort charts (all / warm / shoulder / cold, `regen_seasonal_raw` category B) of `EngineOnDuration`, `EngineOnBySpeed`, `TurboByRpm`.
- **E1 corrected:** `tools/engine_on_rule_block.py` states that `grid_rpm` is byte-faithful to `_RawAccum.add`; therefore the rule engine-on seconds (> 400) are expected to equal the `engineOnRule` per-drive seconds EXACTLY (not "within 0.001 h"); any difference is explained, never forced.
- **E4 pre-registered:** `turboBySpeedCtx` zones and `hvcTurboActivity` classes can change in every zone / class (the speed and class partitions are independent of rpm); only the rpm-band split of `turboByRpm` has the identity at 1500 rpm and above.
- **Language:** `engineOnBySpeed` and the turbo blocks are native-row shares: write "rpm > 400, native rows", not "1 Hz grid". The `language_gate.py` retire rules (condition 5) come in M545.
- **Missing sites added:** `compute_summary_arrays.py` about 4317 (regen `rp <= 300`, excluded by decision (g)), about 4387 (onset), about 4988 (`hvcTurboActivity`); `crosscheck_events.py` 107-175; `rpmDistribution.params.engineOnThresholdRpm` (text, 300); JSX about 11040 (`EngineOnBySpeed` title) and about 5927-5929 (`TurboByRpm`); `engineHoursByType` / `engineOnFrac` (master `engine_on_pct`, > 400) shown beside the > 300 turbo row in one table: not affected, mixed basis to be labelled in M545.
- **Risks recorded:** an unanchored replacement could hit the regen / onset literals (anchors asserted); `max_label` in `hvcTurboActivity` depends on drive order (the loader order is fixed); the run is tied to the master MD5 5556a0c6 (recorded); the day bootstrap covers the pooled median only (segsPer10min and onFraction get no interval); cold is exploratory.


## 10. Evidence results and escalation (2026-10-31; all numbers read from analyses/M544_evidence.json, written by the tool)
- Gates: G0a per-drive state equality (606 drives), G0b stored blocks and the four cohort charts reproduced exactly, G0c only the five targeted finalize keys differ (engineOnDuration, engineOnBySpeed, turboByRpm, turboBySpeedCtx, hvcTurboActivity); the onset-sensitivity copy additionally changes engineStartsByType, hvcEngineTriggerSoC, hvcEngineStopSoC, socBands (counts only; the name 'RPM onset' is kept). Run: 606 of 606 drives, master MD5 5556a0c6c8bcde0f6c64b8b9655208ed, 239.5 s.
- engineOnDuration (all drives, rpm > 300 gate -> rpm > 400):
  - Urban: median 26.0 -> 25.0 (-3.846 %), p10 8.0 -> 7.0, p90 95.0 -> 92.0, nSegments 3109 -> 3197 (2.83 %), onFraction 30.1 -> 29.6
  - Mixed: median 30.0 -> 28.0 (-6.667 %), p10 7.0 -> 6.0, p90 87.4 -> 82.4, nSegments 647 -> 677 (4.637 %), onFraction 40.1 -> 39.5
  - Mixed Highway: median 24.0 -> 21.0 (-12.5 %), p10 6.0 -> 5.0, p90 91.0 -> 84.0, nSegments 2573 -> 2793 (8.55 %), onFraction 56.4 -> 55.4
  - Highway: median 30.0 -> 25.0 (-16.667 %), p10 6.0 -> 5.0, p90 156.0 -> 139.0, nSegments 1425 -> 1543 (8.281 %), onFraction 69.4 -> 68.7
- Day-clustered pooled median segment length (seed 42, 4000 draws), 300 [CI] -> 400 [CI]: highway: 30.0 [[26.0, 35.0]] -> 25.0 [[23.0, 32.0]] OUTSIDE CI300; mixed: 30.0 [[26.0, 34.0]] -> 28.0 [[24.0, 32.0]]; mixed_highway: 24.0 [[22.0, 27.0]] -> 21.0 [[19.0, 24.0]] OUTSIDE CI300; unknown: 74.5 [[74.5, 74.5]] -> 74.0 [[74.0, 74.0]] OUTSIDE CI300; urban: 26.0 [[24.0, 30.0]] -> 25.0 [[22.0, 28.0]].
- Run-boundary taxonomy (a run can split, drop or shorten, never merge): highway: unchanged 761, shortened 554, split 108, dropped 2 (runs 1425 -> sub-runs 1543); mixed: unchanged 343, shortened 276, split 28, dropped 0 (runs 647 -> sub-runs 677); mixed_highway: unchanged 1353, shortened 1018, split 201, dropped 1 (runs 2573 -> sub-runs 2793); unknown: unchanged 1, shortened 1, split 0, dropped 0 (runs 2 -> sub-runs 2); urban: unchanged 1643, shortened 1371, split 88, dropped 7 (runs 3109 -> sub-runs 3197).
- engineOnBySpeed (percent, displayed integers): 0-20 14 -> 14, 20-40 26 -> 25, 40-60 46 -> 45, 60-80 57 -> 55, 80-100 81 -> 79, 100-120 98 -> 98, 120+ 96 -> 96. Turbo: bands from 1500 rpm up identical (identity gate E4 True); the lowest band loses native rows; hvcTurboActivity strings change in every class.
- Escalation per the Rev 2 rules (materiality 5 percent on every displayed field; shift outside the 300 interval): TRIPPED for the highway and mixed_highway median segment length, for p10 / p90 / segsPer10min / nSegments of mixed_highway and highway, and for four displayed engineOnBySpeed integers. These are deterministic re-definitions of run boundaries on the same data, not tests or corrections. Decision requested from the Director before M545.
- Blind audit (analyses/M544_audit.json, analyses/M544_audit_script.py): 20/20 drives exact on segment count, sum and median at both thresholds and on the lowest-band turbo rows; taxonomy consistent (own 20-drive taxonomy: 353 unchanged, 297 shortened, 51 split, 0 dropped). Grid convention of the audit recorded: floor-to-second MEAN over every second first..last, no dropna, native ffill 15 rows before, grid ffill 15 s after.


## 11. Addendum (2026-10-31): Director decision (narrow revise) and the tool re-run
- Director decision on the evidence: narrow revise; deviations acceptable; no Director round trip needed unless a check fails. Required before any M545 code: (a) the E3 identity gate, (b) the exact E1 check, (c) the complete flip and materiality list. Delivered by a tool re-run (`analyses/M544_evidence_addendum.json`; the first evidence file `analyses/M544_evidence.json` is kept; the re-run reproduced the same gates).
- E3 identity (engineOnBySpeed): per speed zone the drop in engine-on rows from the 300 to the 400 gate equals the count of native rows with 300 < rpm <= 400: [6794.0, 7885.0, 15572.0, 19457.0, 14325.0, 5610.0, 394.0] (drops) = [6794.0, 7885.0, 15572.0, 19457.0, 14325.0, 5610.0, 394.0] (rows), equal: True.
- E1 exact: the rule engine-on seconds of the 400 copy equal `engineOnRule` per-drive seconds on 606 drives, 0 different (equal: True).
- Complete list, all-drives view (cohort charts are in the addendum file): material (>= 5 percent) fields 59 in total across cohorts; the non-material changed fields of the all-drives view:
  - engineOnDuration Urban median: 26.0 -> 25.0 (-3.846 %)
  - engineOnDuration Urban p90: 95.0 -> 92.0 (-3.158 %)
  - engineOnDuration Urban onFraction: 30.1 -> 29.6 (-1.661 %)
  - engineOnDuration Urban segsPer10min: 4.3 -> 4.4 (2.326 %)
  - engineOnDuration Urban nSegments: 3109 -> 3197 (2.83 %)
  - engineOnDuration Mixed max: 325.0 -> 323.0 (-0.615 %)
  - engineOnDuration Mixed onFraction: 40.1 -> 39.5 (-1.496 %)
  - engineOnDuration Mixed nSegments: 647 -> 677 (4.637 %)
  - engineOnDuration Mixed Highway onFraction: 56.4 -> 55.4 (-1.773 %)
  - engineOnDuration Highway onFraction: 69.4 -> 68.7 (-1.009 %)
  - engineOnBySpeed 20-40 pct: 26 -> 25 (-3.846 %)
  - engineOnBySpeed 40-60 pct: 46 -> 45 (-2.174 %)
  - engineOnBySpeed 60-80 pct: 57 -> 55 (-3.509 %)
  - engineOnBySpeed 80-100 pct: 81 -> 79 (-2.469 %)
  - turboBySpeedCtx 120-160 activePct: 35 -> 36 (2.857 %)
  - hvcTurboActivity urban string: 7.3% of engine-on time (n=1,223,556, >0.1 bar);  -> 7.4% of engine-on time (n=1,200,763, >0.1 bar); 
  - hvcTurboActivity mixed string: 3.0% of engine-on time (n=238,071, >0.1 bar); pe -> 3.1% of engine-on time (n=233,523, >0.1 bar); pe
  - hvcTurboActivity mixed_highway string: 13.6% of engine-on time (n=865,790, >0.1 bar); p -> 13.9% of engine-on time (n=847,918, >0.1 bar); p
  - hvcTurboActivity highway string: 13.5% of engine-on time (n=831,403, >0.1 bar); p -> 13.7% of engine-on time (n=820,480, >0.1 bar); p
  - hvcTurboActivity city string: 7.3% of engine-on time (n=1,223,556, >0.1 bar);  -> 7.4% of engine-on time (n=1,200,763, >0.1 bar); 
- Material fields of the all-drives view (>= 5 percent):
  - engineOnDuration Urban p10: 8.0 -> 7.0 (-12.5 %)
  - engineOnDuration Mixed min: 2.0 -> 1.0 (-50.0 %)
  - engineOnDuration Mixed median: 30.0 -> 28.0 (-6.667 %)
  - engineOnDuration Mixed p10: 7.0 -> 6.0 (-14.286 %)
  - engineOnDuration Mixed p90: 87.4 -> 82.4 (-5.721 %)
  - engineOnDuration Mixed segsPer10min: 5.7 -> 6.0 (5.263 %)
  - engineOnDuration Mixed Highway median: 24.0 -> 21.0 (-12.5 %)
  - engineOnDuration Mixed Highway p10: 6.0 -> 5.0 (-16.667 %)
  - engineOnDuration Mixed Highway p90: 91.0 -> 84.0 (-7.692 %)
  - engineOnDuration Mixed Highway segsPer10min: 8.2 -> 8.9 (8.537 %)
  - engineOnDuration Mixed Highway nSegments: 2573 -> 2793 (8.55 %)
  - engineOnDuration Highway median: 30.0 -> 25.0 (-16.667 %)
  - engineOnDuration Highway p10: 6.0 -> 5.0 (-16.667 %)
  - engineOnDuration Highway p90: 156.0 -> 139.0 (-10.897 %)
  - engineOnDuration Highway segsPer10min: 6.3 -> 6.8 (7.937 %)
  - engineOnDuration Highway nSegments: 1425 -> 1543 (8.281 %)
  - turboByRpm <1500 n: 261101 -> 204965 (-21.5 %)
- Conditions for M545 (Director): (1) design = hybrid: module-level pure functions with a threshold argument, called at 300 by `_RawAccum` (byte-identical G0 test) and at 400 by a sidecar that caches per-drive sufficient statistics so cohorts (all / warm / shoulder / cold) merge by summation; rule siblings additive only, stored > 300 keys unchanged; option C stays rejected. (2) Rebind, each with a label, the Highway-vs-city boost sentences and the `hvcTurboActivity` row first, then `EngineOnDuration`, `EngineOnBySpeed`, `TurboByRpm` (primary and the four cohort charts), `turboBySpeedCtx`; label the `engineHoursByType` mixed basis. (3) Wording: run lengths are a 'run-boundary re-definition (rpm > 400, 1 Hz grid; deterministic, same data)', never 'correction', never a shift presented as a finding, never 'false engine-on'; native-row blocks say 'rpm > 400, native rows'. (4) The day-clustered interval belongs to each definition separately; no 300-versus-400 contrast is drawn as a test; the 'unknown' class (2 segments, 3 days) is exploratory with no interval reading. (5) `crosscheck_events`: the e-4ORCE side uses the same threshold function and basis as the primary side, with an identity test and updated docstring text. (6) Onset sensitivity: keep the name 'RPM onset (> 300 rpm, run >= 2 s)'; the > 400 version stays a sensitivity; dependants (trigger / stop SoC, `socBands`) are counts only and never displayed. (7) `language_gate.py` retire rules for each old 'engine-on (rpm > 300)' wording and the synthetic split / drop / shorten test as in Rev 2. (8) `engineStateMachine` (M546) stays a separate milestone, run after M545 is merged. No article figure.
