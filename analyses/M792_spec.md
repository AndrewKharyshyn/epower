# M792 spec: three-state strip by speed band (Battery & driving tab, "When the battery helps at highway speed"; audit Wave C item 9)

Rev 2 (Director review of Rev 1: "revise", all binding changes applied below; R1-R4 answered in section 9). Committed BEFORE any result of this milestone exists. Owner plan 2026-11-27/28 (audit item 9, "three-state strip or grouped bars by speed for engine turning and battery discharging, engine turning with other battery flow, and other supported state"; owner answered "Wave C spec" on 2026-11-28). New payload, so: spec, Director review of this spec, implementation, blind audit, Director decision (skill `new-analysis`).

## 0. Verified state (read from the repository, nothing recomputed)
- `S.engineOnBySpeed` (`_RawAccum`, `engine_on_by_speed`, zones 0-20, 20-40, 40-60, 60-80, 80-100, 100-120, 120+) carries only the engine-on percentage per zone (rounded integer, pooled over seconds, threshold `ENGINE_ON_STORED_RPM`). It has no battery-current split, so the discharging versus other-flow partition cannot be drawn from it.
- `S.highwayShare` (M597, `tools/highway_share.py`, sidecar `highway_share.csv`) holds, for the single 80-120 km/h band, per drive B (band seconds), E (engine turning, logged rpm above 400), D (engine turning and discharge, Id > 0, Id = -I of the pack current). Primary per-drive mean joint share 48.75 % (95 % interval 46.69 to 50.51; 116 drives, 55 days). Zero-tolerance reconciliation with the master (`band_80_120_s`, `deficit_80_120_s`) exists and is the model for this milestone.
- `S.highSpeedCensus` (thresholds 130/140/150/160 km/h: total grid-seconds, drives reaching, longest streak) already exists; the adjacent "130+ coverage and longest streak" chart of the audit is a display of it (no new payload).
- The audit's directly annotated power-burst line trace is a trace payload (a separate Wave C item) and is NOT part of this milestone.

## 1. Estimand
For each speed zone z (the seven `engineOnBySpeed` zones, same edges, half-open [lo, hi), last zone 120 and above) and each eligible drive, the logged seconds split into three mutually exclusive, exhaustive states (rows where speed, rpm and pack current are aligned as in M597):
- S1 "engine turning, battery supplying power": rpm > 400 and Id > 0.
- S2 "engine turning, battery not supplying power (charging, zero, or current not logged)": rpm > 400 and not (Id > 0); a missing Id falls here under the M597 masks (D1 needs this). Never worded as "idle" or as "the engine charging the battery": S2 also holds engine motoring (engine braking at high SoC). Missing-Id seconds per zone are counted and printed.
- S3 "engine not turning or rpm not logged": rpm <= 400 or rpm missing (M597 convention, `fillna(0)`; the audit's "other supported state"). Missing-rpm seconds per zone are printed. Starting/stopping transitions are inside S3 because the cutoff is a transition cutoff, not an identified engine state.
Shares s_k(drive, z) = seconds in S_k and zone z divided by all seconds in zone z (S1 + S2 + S3 = 100 % by construction). Reported estimates, both with day-clustered intervals:
- Primary (display): per-drive mean share (equal weight per eligible drive), consistent with the headline of the existing highway block.
- Secondary: pooled over time (seconds-weighted), the "share of covered time" the audit sentence describes. The two are shown side by side in the table; their disagreement is reported, not tuned.
This is a logged-signal control observable ("battery supplying power while the engine turns"), not generator output, not generator saturation and not a capability; Id is the logged pack current (app-calculated chain), the sign convention is the pipeline's (Id = -I).

## 2. Population and eligibility
- Drives with aligned speed (speed-priority helper), rpm and pack current, built exactly like `tools/highway_share.py extract_from_bytes` (same `_prep_bytes`, `_series`, `_asof`, `DT_CAP_S`, sample step in hours times 3600). Canonical exclusion `ens_outlier_v2` (== `ens_invalid`) applies to the master rows used for eligibility; raw files are read-only, `drive_master.csv` unchanged (MD5 recorded by the tool).
- Per-drive statistic of a zone requires at least 120 s in that zone on that drive (the M14 band floor of M597). Pooled estimates use all seconds of the drives that clear the floor in that zone (the same population as the per-drive mean; the all-drives pooled value is a sensitivity).
- Display floor per zone (borrowed from the regeneration support-floor decision (d) of 2026-10-14; a deviation, not an owner rule for this block): at least 10 drives on at least 5 calendar days clearing the 120 s floor. A zone below the floor is drawn as "not shown (not zero)", with its drive and day counts printed. The 120+ zone is expected to be near or below the floor; the tool never relaxes the floor to fill it.

## 3. Method
- New tool `tools/highway_states.py` (same pattern as `highway_share.py`): per-drive per-zone seconds (Bz, S1z, S2z, plus NaN-rpm seconds per zone) into the tracked sidecar `highway_states.csv` (keyed by raw sha256 and method version; incremental on ingestion; the only writer; `--rebuild`, `--check`), then an additive splice of the payload key `highwayStates` (deep-diff guard: only `/highwayStates` and its artifact stamp may change; every other key byte-identical). New ingestion stage `highway_states` in `tools/ingest_stages.json` after `highway_share`.
- Intervals: day-clustered percentile bootstrap, calendar day as the resampling cluster, seed 42, 4000 draws (`tools/day_bootstrap.py`). Per zone, the days resampled are that zone's eligible days; the pooled estimate is the ratio of resampled sums. The three states of a zone are bootstrapped from ONE shared draw set (the same resampled days); each state has its own interval; intervals are not forced to sum to 100 % (the strip draws point shares, the table prints the three intervals). Every estimate carries n drives and n days.
- Payload block `highwayStates`: definition strings, zones list, per zone {nDrives, nDays, seconds, perDriveMean{S1,S2,S3: est, lo, hi}, pooled{...}, shown:boolean, reasonNotShown}, `reconciliation`, `sensitivity`, provenance (master MD5, script sha256, sidecar sha256, specRev "analyses/M792_spec.md Rev 1").

## 4. Primary versus sensitivity analyses (all reported; disagreement shown, never tuned)
- P: rpm threshold 400, discharge Id > 0, floor 120 s, per-drive mean.
- Sa: rpm threshold 300 (as M597; this is also the threshold of the stored `S.engineOnBySpeed`, `ENGINE_ON_STORED_RPM` = 300).
- Sb: discharge dead band: S1 requires Id > 5 A (and a second variant 2 A if the logged current resolution allows); the near-zero band stays in S2 (tests whether the share is a current-noise artefact).
- Sc: zone floor 30 s and 300 s (mirrors the M597 sensitivity floors, which it names B300 and E30).
- Sd: all-eligible-drives pooled (no per-zone floor).
- Se: exclude seconds with missing rpm (S3 then holds only logged rpm <= 400); the number of dropped seconds is printed.
- Sf: logger cadence stratum (fast-polled versus slow-polled drives, as the regeneration programme splits them): report-only, to show whether time-weighted shares move with the sampling cadence; no cadence contrast is drawn in the dashboard.
- Flag (pre-registered): if Sb or Se falls outside the primary interval in an 80-120 zone, a note is shown next to the strip.
- Sg: pack-temperature class (Cold, Shoulder, Warm, report-only for the 80-120 zones, no contrast drawn, no causal wording).

## 5. Decision rules and gates (frozen before any result)
- D1 reconciliation with M597: for every drive, (Bz for 80-100) + (Bz for 100-120) plus the seconds at exactly 120.0 km/h (M597 band is inclusive at 120, the zones are half-open) must equal the sidecar B of `highway_share.csv` with ZERO tolerance, summing the UNROUNDED zone seconds first and applying round(., 1) once; same for S1 versus D and S1 + S2 versus E. The tool computes the exact-120 term itself; any residual other than that term is a defect. The pooled check runs on the M597 population (B >= 120 s on the inclusive [80, 120] band), not on the per-zone floored sets. The 80-120 pooled S1 share must equal `S.highwayShare.primary.joint.pooled` within the rounding of the published value on the same drive set (checked by the tool on the M597 population).
- D2 partition: S1 + S2 + S3 = zone seconds to 1e-6 s per drive and zone; shares sum to 1 per drive and zone; pooled shares sum to 100 % within 1e-9.
- D3 engine-on cross-check: `S.engineOnBySpeed` uses rpm > 300, so it is compared with the Sa variant (S1 + S2 at 300 rpm), never with the primary at 400; any text showing both thresholds names them. Pooled per zone, the published value is a rounded integer over a possibly larger drive set (no current series required): flag if |difference| exceeds 1 pp after restricting to the common drives; the comparison and the drive-set difference are printed, nothing is adjusted.
- D4 known-answer test `tests/synthetic/test_highway_states.py`: planted series with known seconds in each state and zone, a sample exactly at a zone edge (belongs to the upper zone), a sample at exactly 120.0 km/h, NaN rpm (counts as S3), Id exactly 0 (S2), a drive below the 120 s floor (excluded from the per-drive mean, present in the all-drive pooled sensitivity), and a 3-day bootstrap with a hand-checkable cluster resample. UTF-8 encoding in every open/read_text/write_text.
- D5 display rule: a zone is drawn only when it meets the display floor; zone rows carry no summary word. The headline sentence tests the merged inclusive 80-120 band (the audit claim's band, computed from the M597 population), generated from the payload, with three outcomes on the frozen 40-60 % range: both the per-drive-mean and pooled S1 intervals inside -> "about half"; any interval entirely outside -> falsified, the computed values are quoted; straddling -> inconclusive, values quoted, no summary word. Never typed numbers: every figure binds to `S.highwayStates`.
- Falsification: the audit claim "at 80-120 km/h the battery supplied power while the engine turned during about half of covered time" ("covered time" = logged time only) is tested on the merged inclusive 80-120 band by the three-outcome rule of D5; an interval entirely outside 40 to 60 % falsifies it and the displayed sentence changes to the computed values. The partition itself is falsified by any D1 or D2 failure (tool defect, no display).

## 6. Dashboard binding (display half; implemented only after the Director decision and the blind audit)
- Location: the "When the battery helps at highway speed" block (Battery & driving tab), above the existing M597 prose. One `ShareStrip` with seven rows (the speed zones, slowest first) and three coloured parts (S1, S2, S3) in a fixed order; interval ticks in the table beside it (`ChartWithTable`); a zone below the display floor prints "not shown (not zero)". Row order, colours and part order identical in every row (shared scale 0 to 100 %).
- Adjacent small chart: 130+ coverage (seconds, drives, longest streak) from `S.highSpeedCensus` thresholds, with the drive count and exposure stated.
- Interpretation sentence marked as interpretation: demand blending and charge management are readings of the telemetry, not observed controller states; the existing blend/steer shares (`S.blendShareMeanPct`, `S.steerShareMeanPct`) stay where they are.
- Language gate: "engine turning (logged rpm above 400)", "battery supplying power (logged discharge current)", "engine not turning (logged rpm 400 or lower, including starting and stopping)"; never "measured", "generator saturation", "capability", "typical", "optimal"; a new rule only if `language_gate.py` flags something.

## 7. Out of scope
- The annotated power-burst trace, per-drive histograms and any new trace payload (separate Wave C milestones).
- Any change to `S.highwayShare`, `S.engineOnBySpeed`, `S.deficitMeanPct` or their existing text (they stay; this block is additive).
- Not an article figure. An article use needs the Opus audit and Andrii's sign-off recorded in the CHANGELOG entry.

## 8. Gates and sequence
spec committed -> Director review of this spec (Rev 1 -> binding Rev) -> tool, tests, sidecar, splice, ingestion stage -> py_compile, JSON round-trip, `node build_html.js`, `node validate_jsdom.js`, isolation diff -> `python release_check.py` -> blind audit (`analytical-auditor`, claim and data path only, Sonnet high) -> Director decision on spec, result and audit JSON -> JSX display, JS test, CI line, CHANGELOG (`tools/changelog_draft.py`), release identity -> PR, merge, tag M792.

## 9. Director answers (Rev 1 review) and residual risks
- R1: per-drive mean stays primary with the time-pooled estimate beside it, both always labelled; the audit sentence is judged on both (D5).
- R2: missing rpm stays in S3 as primary (reconciles with master and M597); Se is a sensitivity; S3 is relabelled as above.
- R3: Id > 0 is the primary (reconciliation); Sb is a flagged sensitivity.
- R4: no merge of 120+ into 100+; 120+ shows "not shown (not zero)" with counts when below the floor, the 130+ census covers it; merging would break the D1 zone semantics.
- Risks to state in the text: S2 includes engine motoring; the 0-20 zone is dominated by standstill; Sf and Sg are report-only with no contrast or causal wording; not article-bound without the Opus audit and Andrii's sign-off.
