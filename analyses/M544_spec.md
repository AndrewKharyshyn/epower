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
