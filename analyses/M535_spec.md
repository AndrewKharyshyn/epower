# M535 spec (Rev 1, DRAFT for Director review): recompute the distance-mix shares of the driving-mix note from the current master (script-written, day-clustered)

Status: PRE-REGISTERED DRAFT, 2026-10-28, before any result. Owner: Andrii (chat, 2026-10-28: "recomputing the distance-mix shares - OK"). Origin: M528 re-worded `summary_config.json` `drivingMixNote` as a dated snapshot; its percentages (~19 % pure highway, ~58 % mixed_highway, ~16 % urban, ~6 % mixed at the 2026-07-14 audit, 194 drives) are typed and never recomputed.

## 1. Question and estimand
Share of logged kilometres by `drive_type` (urban, mixed, mixed_highway, highway; `unknown` reported separately) over the canonical-clean drives of the current master (606 drives at the last ingestion; the count is read, not typed): share_t = sum(distance_km of type t) / sum(distance_km). Distance is `distance_km` (distance-source rules unchanged: `distance_source`, repaired resets as in the master). Also drive counts and day counts per type. The "highway-blended" share = highway + mixed_highway.

## 2. Method
- Ratio-of-sums by drive type; interval: day-clustered percentile bootstrap on the ratio (seed 42, 4000 draws, calendar-day cluster resample of whole days, share recomputed per draw), n drives and n days per type reported.
- Also the share by season cohort is NOT in scope (cohort mixes are a separate display); one all-corpus row plus the 194-drive-era comparison row restricted to drives dated up to 2026-07-14 (to reproduce the old audit's basis; a reproduction check, not a headline).
- Producer: a small script writing a sidecar (per-drive `distance_km`, `drive_type`, `date`) keyed to the master MD5, and a payload key `drivingMix` (additive), stage `driving_mix` in `tools/ingest_stages.json`; the dated config note is re-worded to read the shares from the payload (display binding via `S.drivingMix.*`), with the 2026-07-14 values kept as a labelled historical snapshot (rule with ledger id M535 forbids the bare old percentages as current).
- Drive type is a classification (M21 reclassification, `drive_type` column of the published master); it is read, not re-derived.

## 3. Acceptance, falsification, escalation
- A1 reproduction: restricted to 2026-07-14 and earlier, the recomputed shares are compared with the typed snapshot (19 / 58 / 16 / 6 %); a difference above 2 pp is reported (the old audit predates reclassification details) and is not tuned.
- A2 independent recomputation in the test (parses the master directly, no producer helper); shares sum to 100 % with `unknown` shown.
- A3 splice is additive: only the new key, the stage entry and the note text change; stamps / verify_declared parity as for earlier additive keys.
- Escalate to the Director if the highway-blended share lies outside its interval at the old audit date's recomputation by more than 10 pp, or if the realistic-blend scenario reading (55 / 30 / 15 % city / mixed / highway, a scenario input, not an estimate) is affected: it stays labelled a scenario and is NOT changed.
- No blind audit of new numbers beyond A2 unless the Director asks; no article figure.

## 4. Language
"share of logged km by drive type (day-clustered interval)", "as of the current master", "drive-type classification (M21)"; the 2026-07-14 percentages remain a dated snapshot; never "representative of real use".

## 5. Gates
py_compile, `node build_html.js`, `validate_jsdom.js`, `dump_tabs.js` then `semantic_gate.py`, release_check, CI unit list, CHANGELOG M535, dashboard change rule (SendUserFile), PR with gated merge.

## 6. Rev 2 (2026-10-28): Director review (revise); incorporated. Rev 1 SHA-256 recorded before the edit: f8e5ac5d43aa9fd15394daf94ba192dc48827464463b7f44e99d0143bf92aab1
- R1 primary population = ALL drives with a valid `distance_km` (the energy-rate exclusion `ens_outlier_v2` is not obviously right for a km mix); secondary row = canonical-clean; both reported, none chosen after the numbers. R2 the km share from repaired-distance drives (`distance_source`) is its own sensitivity row. R3 A4 replaced: escalate if (a) the typed snapshot falls outside the recomputed interval restricted to 2026-07-14 (reproduction failure) or (b) the current highway-blended share differs from the typed 77 % by more than 10 pp; either way the Director rules on the note wording. R4 binding: the `drivingMixNote` text is generated at build time from `S.drivingMix.*` (JSX template, named in the producer), no literals. R5 the M535 language rule targets the old numbers in a "current" context and allows them in the labelled snapshot. R6 no mapping of the 4 drive types onto the 55/30/15 scenario here. R7 stage `driving_mix` in `tools/ingest_stages.json` with verify_declared / release_check parity; the sidecar is keyed to the master MD5.
- Added tripwires: `unknown` drive_type above 2 % of km; fewer than 10 days for a type = interval flagged. Blind audit yes (Sonnet, light; shares and interval from the master path only). No Andrii sign-off. Language: "share of logged km by drive type (day-resampled interval, describes day-to-day heterogeneity, not representativeness)"; never "representative of real use"; do not conflate with the logged-share-of-odometer KPI.
