# M541 spec (Rev 1, DRAFT for Director review): wave 2b-i of the engine-on migration: rebind the displayed engine-on totals to `engineOnRule` (JSX only, no producer change)

Status: PRE-REGISTERED DRAFT, 2026-10-30, before any code. Owner: Andrii (delegation in the M538 / M539 CHANGELOG entries). Programme: `analyses/M539_spec.md` Rev 2; block: `engineOnRule` (M540, merged, tag M540). Rule: engine-on = logged rpm > 400 on the 1 Hz grid (strict); closed low-rpm rotation band [300, 400] reported separately.

## 1. Refined split of wave 2b (recorded for the Director)
Wave 2b as written in M539 Q1 has two different kinds of work. This milestone is the first kind only.
- **2b-i (this spec, M541): display rebind.** The JSX sites that sum `rpmDistribution.pooledHours.slice(1)` (or the byClass / cohort equivalents) as "engine-on hours" read the new `engineOnRule` leaves instead (engine-on hours > 400, with the band disclosed beside it). No producer, sidecar, stage or payload key is added or changed; `rpmDistribution` and `engineOnThresholdRpm` (300) stay byte-identical.
- **2b-ii (next spec, M542): sibling blocks.** `rpmOptBand`, `rpmModeCentres`, `motoredShare` (denominator), `engineOnDuration` (`eon = rr > 300` in `compute_summary_arrays.py`) are recomputed under > 400 as additive siblings through their existing sidecar tools (own expected deltas; M536 wave-0 addendum gives rpmOptBand 64.092 [61.597, 66.407] vs 63.073). Their JSX bindings are rebound in that wave, not here.
- **2c: state machine** `engineStateMachine` >= 400 -> > 400 (0.015 h) stays a separate wave.

## 2. Sites in scope (from the registry and a grep; all line numbers are anchors, re-found by text)
1. `rpmBandOccupancyText` (about line 6013): the "% of engine-on time" denominator is `slice(1)` (rpm >= 300). The 300-floor band share it prints is a share of the >= 300 basis; it is relabelled "share of rpm >= 300 time" (basis unchanged, label made exact) and the engine-on (> 400) hours are quoted next to it from `engineOnRule.pooled`.
2. `rpmEngineOnHours` (about 11508) and `engineOnHoursAgreePct`: the cross-check against `S.engineOnHours` (supported intervals) is rebound to `engineOnRule.pooled.engineOnHours`; the band is shown as its own term (`lowRpmBandHours`); the previous >= 300 agreement stays visible as a labelled secondary line.
3. rpmDistribution chart text near 6098 / 6126 / 9646 / 12111 / 12112: the "of all gridded time / of engine-on time" shares: engine-on totals read `engineOnRule` (pooled, byClass); the 13 bins are still drawn as stored (bin 0 label "0 (engine off)" is revised to "0-300 rpm (below the band)" only where the text would call bin 0 the complete off-time; the bar data are untouched).
4. Cohort variants (`cohortOr("RpmDistribution", ...)`): no `engineOnRule` cohort leaf exists (M540 had no cohort split); cohort views keep the stored >= 300 basis and are labelled "rpm >= 300" in prose. This is stated, not hidden.

Sites not touched: everything produced by `_RawAccum` or the sidecar tools (2b-ii / wave 3), the regeneration proxy (300, decision (g)), the RPM-onset detector, GTR / capacity / fuel (already 400).

## 3. Change rules
- Every printed figure reads an `S.engineOnRule.*` leaf or an existing `S.*` key; no literal; missing input renders "n/a".
- Guard (like the bins[1] label guard): the new code reads the rule block only if `engineOnRule.rule.thresholdRpm === 400` and `boundary === "gt"`, else falls back to "n/a".
- Language gate: new rule `M541-engine-on-label` adding the OLD wording (engine-on described as "rpm >= 300" without a basis) with its ledger id; wording "engine-on (rpm > 400, 1 Hz grid)", "low-rpm rotation band (logged rpm, 300-400 rpm)", never off-time or artefact.
- Dashboard change rule applies: rebuild, `SendUserFile` render, commit with the sources (`xtrail_summary.jsx`, `summary_arrays.json`, `cohort_arrays.json` unchanged payloads).

## 4. Acceptance, falsification, escalation
- A1 byte identity: `summary_arrays.json` and `cohort_arrays.json` byte-identical to M540 (no payload change); only `xtrail_summary.jsx` and the rebuilt `xtrail_dashboard.html` differ.
- A2 tab dumps: a diff of all tab dumps against M540 shows only the pre-registered changed strings (a list of before / after strings is part of the delta report); every other tab dump line identical.
- A3 each rebound number equals the independently recomputed `engineOnRule` value (test reads the sidecar and the master, not the producer) and the rendered text (jsdom) contains it.
- A4 expected deltas (from M540): pooled engine-on 98.2808 h instead of 99.8678 h (-1.587 h, -1.59 %); engine-on share of valid time 42.6369 % [38.7513, 46.1924]; band 1.589 % of the >= 300 time [1.4583, 1.7457]; the agreement with supported-interval engine-on hours moves by the 0.7512 % integration term (inside [0.642, 0.872]). Escalate to the Director if any rebound figure leaves its previous interval, if a displayed claim flips wording class, or if a dump line outside the list changes.
- A5 T3 tripwire: a test greps the JSX for engine-on totals still built from `slice(1)` of the rpm histogram that are not on the allowed list (cohort variants, labelled >= 300 basis); failure fails CI.
- A6 blind audit (Sonnet): given the rendered Fuel / charts text and the raw-data path only, recompute 3 displayed figures for >= 20 drives (sample drawn BEFORE the build, seed 42, stratified); exact seconds.
- No master / ML16 / regeneration-proxy change, no article figure; sign-off triggers as in M539.

## 5. Gates
py_compile, `node build_html.js`, `validate_jsdom.js`, `dump_tabs.js` then `semantic_gate.py`, `release_check.py`, local CI unit list, CHANGELOG (spec SHA-256 before code, delta report, blind audit, Director decision), PR with the gated merge.

## 6. Questions for the Director
Q1 Is the 2b-i / 2b-ii split right (display rebind first, sibling recomputes second), or must the denominators move together with their displays? Q2 Cohort views stay on the labelled >= 300 basis because no cohort `engineOnRule` leaf exists: acceptable, or add the cohort split to the block first (a 2a-bis)? Q3 Is relabelling the band-share denominator ("share of rpm >= 300 time") sufficient while `rpmOptBand` / `motoredShare` still use the >= 300 denominator for one more wave, or does mixing 400 totals with 300 shares on one tab need a visible "basis" tag per figure? Q4 Bin 0 relabel: confined to prose sites, chart data untouched: agreed?
