# M540 spec (Rev 1, DRAFT for Director review): wave 2a of the engine-on migration: the additive payload block `engineOnRule` (engine-on under the rule and the closed low-rpm band), no consumer rebound

Status: PRE-REGISTERED DRAFT, 2026-10-30, before any code. Owner: Andrii (delegation recorded in the M538 / M539 CHANGELOG entries). Programme: `analyses/M539_spec.md` Rev 2 (wave 2 split by the agent into 2a: this block, 2b: rebinding the consumers and the sibling blocks, 2c: the state-machine boundary; the split is a recorded refinement for the Director). Rule: `tools/engine_on_rule.py` (rpm > 400, strict; closed band [300, 400]).

## 1. What this wave does
One new top-level payload key `engineOnRule` (+ declared stamp) produced by a per-drive sidecar stage, so the next ingestion keeps it current (the `_RawAccum` blocks are rebuilt at ingestion; a splice into `rpmDistribution` would be overwritten). `rpmDistribution`, its 13 bins, `engineOnThresholdRpm` (300), every consumer, the JSX and the dashboard are NOT changed in this wave: the block is not displayed (`displayed: false`) and nothing is rebound (that is wave 2b).

## 2. Content (all numbers script-written; no typed values)
- `rule` {thresholdRpm 400, boundary "gt", bandClosedRpm [300, 400], names: "engine-on (rpm > 400, 1 Hz grid)", "low-rpm rotation band (logged rpm, 300-400 rpm)"}, `nanPolicy`.
- `pooled`: integer seconds and hours of: valid grid seconds, rpm >= 300 (the stored B1 basis), engine-on (rpm > 400), low-rpm band (closed), seconds at exactly 400; n drives, n days; shares: engine-on share of valid seconds and the band share of rpm >= 300 seconds, each with the day-clustered percentile bootstrap interval (calendar day, seed 42, 4000 draws, ratio of sums).
- `byClass` (urban, mixed, mixed_highway, highway; `drive_type` of the master): the same hours and shares.
- `bySpeed` and cohort splits are NOT in this wave (the cohort rpm histograms live in the regeneration / seasonal blocks that use the regeneration proxy; recorded).
- `identity` (T2): for every drive, engine-on seconds + band seconds == seconds with rpm >= 300; pooled hours of the rpm >= 300 basis equal the sum of `rpmDistribution.pooledHours[1:]` within 13 x 0.0005 h (the stored bins are rounded to 0.001 h; STOP otherwise); byClass likewise against `rpmDistribution.byClass[k].hours[1:]`.
- `faithfulness`: the 1 Hz grid is the byte-faithful grid of `rpm_opt_band.grid_rpm` / `_RawAccum.add` (hold limit 15 native rows and 15 grid seconds, negatives dropped); known answer: the engine-on seconds at rpm > 400 and the >= 300 seconds equal the phase-1 sidecar (`engine_on_evidence_sidecar.csv`, columns g_gt400, g_ge300) drive by drive (STOP otherwise); the integration cross-check (T4): `engineRuntime` supported-on hours minus pooled engine-on hours equals the integration term (0.751 % of > 400 seconds [0.642, 0.872] % in wave 0), flagged if outside.
- `limits`: logged rpm, not measured; the 300-400 band is loaded rotation (99 % positive app-calculated load) and is reported, not discarded; hold limit counts rows natively and seconds on the grid; convenience sample.

## 3. Implementation
`tools/engine_on_rule_block.py` (per-drive sidecar `engine_on_rule_sidecar.csv` keyed by the raw-file SHA-256 and by `engine_on_rule_sidecar.meta.json`: source hash of the row function, the rule module constants and the pipeline hold limits; mismatch rebuilds all; `raw/` = sha256-verified originals), additive splice with deep diff (only the new key and its stamp), `--check`, stage `engine_on_rule` in `tools/ingest_stages.json`, entry in `tools/stamp_dependencies.json` (readsRaw true), restamp policy entry, CI test `tests/synthetic/test_engine_on_rule_block.py`.

## 4. Acceptance, falsification, escalation
- A1 faithfulness and identity gates pass (STOP otherwise). A2 independent recomputation in the test from the phase-1 sidecar and the master (no producer helper). A3 splice is additive: every other payload key, `rpmDistribution` and the dashboard HTML byte-identical; `verify_declared` parity; the stamp coherent (computedAt <= includedInReleaseAt). A4 blind audit (Sonnet, raw files only, drive sample drawn BEFORE the run, seed 42, stratified fast / slow): >= 20 drives, seconds exact.
- Expected (pre-registered from M536 evidence, tolerances): pooled engine-on 98.2808 h (+-0.001), low-rpm band closed 1.587 h (+-0.001), >= 300 basis 99.8678 h; engine-on share of valid time and band share intervals reported. Escalate if any identity fails, if the integration cross-check is outside [0.642, 0.872] %, if the exact-400 seconds exceed 0.1 h, or if a class has fewer than 10 days.
- No dashboard change, no master / ML16 / regeneration-proxy change, no article figure.

## 5. Language
"engine-on (rpm > 400, 1 Hz grid)", "low-rpm rotation band (logged rpm, 300-400 rpm)", "shift" = deterministic re-definition on the same data; never "corrected", "false engine-on", "artefact", "off-time" for the band.

## 6. Gates
py_compile, known-answer test (synthetic trace with 299, 300, 400, 400.5, NaN), `node build_html.js`, `validate_jsdom.js`, `dump_tabs.js` then `semantic_gate.py` (dashboard byte-identical expected), `release_check.py`, local CI unit list, CHANGELOG (spec SHA-256 before code, sidecar hash, blind audit, Director decision), PR with gated merge.

## 7. Questions for the Director
Q1 Is the 2a / 2b / 2c split acceptable? Q2 Is a pooled + byClass block (no cohort / speed split) enough for 2a, or should bySpeed be included now (it is needed by wave 3)? Q3 Is the integration cross-check against `engineRuntime` the right T4 form? Q4 Should the block also carry the per-drive exact-400 seconds (boundary evidence)?
