# M545 spec (Rev 2, Director review incorporated; Rev 1 text below, superseded where section 12 says so): wave 3 of the engine-on migration: rule-based sibling leaves for the `_RawAccum` engine-on blocks, display rebind, `crosscheck_events` identity

Status: PRE-REGISTERED DRAFT, 2026-10-31, before any code. Owner: Andrii (delegation in the M538 / M539 CHANGELOG entries: engine-on = logged rpm > 400, strict, 1 Hz grid; closed 300-400 rpm band reported separately). Programme: `analyses/M539_spec.md` Rev 2. Merged: M540 (`engineOnRule`), M541, M542, M543, M544 (evidence only, `analyses/M544_spec.md` sections 10-11, `analyses/M544_evidence.json`, `analyses/M544_evidence_addendum.json`). This spec carries the eight Director conditions of the M544 decision (section 11 of the M544 spec) as binding requirements; each is mapped in section 8.

## 1. Scope and non-scope
In scope (stored > 300 keys stay unchanged; every new leaf is a `Rule` sibling):
| Block | Stored site (`compute_summary_arrays.py`) | Rule sibling |
|---|---|---|
| `engineOnDuration` (4 classes, `byStratum`, cohort chart `EngineOnDuration`) | `eon = (rr > 300) & valid`, 1 Hz grid | `engineOnDurationRule` (same fields, classes, strata) |
| `engineOnBySpeed` (7 zones, cohort chart `EngineOnBySpeed`) | `eng = rp > 300`, native rows | `engineOnBySpeedRule` (percent of native rows, zone counts) |
| `turboByRpm` (cohort chart `TurboByRpm`), `turboBySpeedCtx` | `eng = rp > 300`, native rows, boost > 0.1 bar | `turboByRpmRule`, `turboBySpeedCtxRule` |
| `hvcTurboActivity` (per class, Highway-vs-city) | `m = (rp > 300) & ~isnan(bo)`, native rows | `hvcTurboActivityRule` (counts, share, max, string) |
| `crosscheck_events` e-4ORCE side | docstring text only (M539 registry) | identity test and docstring (section 5) |

Not in scope: `engineStateMachine` (M546, own wave after this merge), the engine-start detector (keeps its name 'RPM onset (> 300 rpm, run >= 2 s)'), the regeneration proxy at 300 rpm (owner decision (g)), `rpmDistribution` bins, `rpmModeCentres`, `motoredShare` (invariant, M543), the master and ML16.

## 2. Design (Director condition 1: hybrid)
- A new module `tools/engine_on_blocks.py` holds module-level PURE functions with an explicit threshold argument and strict comparison (`>`): `engine_on_runs(grid_rpm, thr)` (run lengths on the 1 Hz grid; NaN breaks a run), `engine_on_by_speed(sp, rp, thr)` (zone counts on native rows), `turbo_by_rpm_band(...)`, `turbo_by_speed_zone(...)`, `hvc_turbo_counts(...)`. Same array semantics as the stored code (native-row blocks use native rows; the grid block uses the M543 grid convention of record: ffill 15 rows before, floor-to-second mean resample, ffill 15 s after, negatives to NaN, NaN = off).
- `_RawAccum` calls these functions at thr = 300 in place of the inline expressions (G0: the stored payload is BYTE-IDENTICAL; proven by a test that runs the old inline code and the new call on synthetic and real frames, and by an arrays diff of the full payload). The four literals 300 at the registry anchors move into one named constant `ENGINE_ON_STORED_RPM = 300`; the registry tripwire `tools/engine_on_sites.py` is updated to know the constant.
- The Rule siblings come from a NEW sidecar stage `engine_on_blocks` (`tools/engine_on_blocks_stage.py`, placed in `tools/ingest_stages.json` after `engine_on_rule` and before `rpm_opt_band`). It loads each drive once (raw_cache frame loader, `drc.add_missing`), computes per-drive sufficient statistics at thr = 400, and writes a tracked per-drive sidecar keyed by the raw SHA-256 and a row-function hash (only new drives are computed on ingestion). Sufficient statistics: per drive and class the run lengths (merged by concatenation, since medians and percentiles need the lengths, not sums), the on / valid / segment counts, per-zone on / total native counts, per-band and per-zone turbo n / act / sumAct / max, per-class hvc n / act / max / label. Cohorts (all / warm / shoulder / cold) and cadence strata merge by concatenation or summation; aggregation never rereads raw CSVs.
- Option C (changing the stored threshold) stays rejected.

## 3. Estimands, intervals and eligibility
- Same eligibility and drive set as the stored blocks (canonical-clean, `ens_outlier_v2` exclusion). STOP if the drive counts differ from the stored blocks.
- Point values are the same descriptive pooled quantities as stored (run-length median, p10, p90, max, onFraction, segsPer10min; percent of native rows; turbo active share). The day-clustered percentile bootstrap (seed 42, 4000 draws, calendar day as the cluster) is applied to the pooled median run length and to the active shares per class; every interval belongs to ONE definition. No 300-versus-400 contrast is drawn as a test and no interval of the difference is formed (condition 4). The 'unknown' class (2 segments, 3 days) is exploratory with no interval reading.
- Native-row blocks are labelled 'rpm > 400, native rows'; the grid block 'rpm > 400, 1 Hz grid'. Run-length figures are labelled 'run-boundary re-definition (rpm > 400, 1 Hz grid; deterministic, same data)' (condition 3).

## 4. Known answers (pre-registered from the M544 evidence; exact for counts, +-0.05 for rounded percentages)
- E3: engine-on rows of `engineOnBySpeedRule` per zone equal the stored rows minus the native rows with 300 < rpm <= 400; drops [6794, 7885, 15572, 19457, 14325, 5610, 394].
- E1: the Rule engine-on grid seconds per drive equal `engineOnRule` per-drive `engineOnSeconds` on 606 drives, 0 different.
- All-drives medians: Highway 30 -> 25 s, Mixed Highway 24 -> 21 s, Mixed 30 -> 28 s. Segment counts: Highway 1425 -> 1543, Mixed Highway 2573 -> 2793, Urban 3109 -> 3197, Mixed 647 -> 677. `engineOnBySpeed` 20-40 / 40-60 / 60-80 / 80-100: 26 -> 25, 46 -> 45, 57 -> 55, 81 -> 79. `turboByRpm` '<1500' n 261101 -> 204965. `turboBySpeedCtx` 120-160 activePct 35 -> 36. `hvcTurboActivity` urban n 1,223,556 -> 1,200,763. Any flip not in the complete list of `analyses/M544_evidence_addendum.json` (all-drives view and the four cohort charts) escalates.
- Run taxonomy (M544): a run changes by split, drop or shorten, never by merge. Tested on synthetic series and asserted on the real drives.

## 5. `crosscheck_events` (condition 5)
`crosscheck_events.py` has no code comparison at 300 or 400 today (registry: text only). Its e-4ORCE side is bound to the SAME function and basis as the primary side: it imports `engine_on_runs` / `engine_on_by_speed` from `tools/engine_on_blocks.py` wherever it counts engine-on, with an identity test (primary and e-4ORCE sides return identical values on the same frame) and a docstring stating 'rpm > 400, 1 Hz grid'. If the module on disk contains no engine-on count, the test asserts the text-only status and only the docstring is relabelled; no logic is added.

## 6. Onset sensitivity (condition 6)
The engine-start detector keeps 'RPM onset (> 300 rpm, run >= 2 s)'. The > 400 version is a sensitivity leaf `engineStartRate.onsetSensitivity400` with COUNTS ONLY, never displayed. Dependants (trigger / stop SoC, `socBands`) are not recomputed at 400 and never displayed. No engine-on or engine-start wording is attached to it.

## 7. Display (condition 2; order of rebinding)
1. Highway-vs-city boost sentences and the `hvcTurboActivity` row (Rule counts and shares, label 'rpm > 400, native rows'; the stored 300 share quoted once as a labelled secondary).
2. `EngineOnDuration`, `EngineOnBySpeed`, `TurboByRpm` (primary and the four cohort chart variants), `turboBySpeedCtx`, with the M541 cohort guard (cohort views quote cohort values, never pooled ones).
3. `engineHoursByType` mixed basis: labelled; no number changes.
4. Tab notes name which figures are on which basis. Every figure binds to a payload `S.*` key (`engineOnDurationRule`, `engineOnBySpeedRule`, `turboByRpmRule`, `turboBySpeedCtxRule`, `hvcTurboActivityRule`); no literals. The Highway-vs-city mixed-basis disclosure of M543 is removed only where the sentence now reads Rule leaves.
Dashboard change rule applies (SendUserFile render, one line with the `S.*` keys, sources committed together).

## 8. Director conditions, mapping
(1) section 2; (2) section 7; (3) sections 3 and 9; (4) section 3; (5) section 5; (6) section 6; (7) section 9; (8) M546 is out of scope and starts only after this PR is merged.

## 9. Language
New `language_gate.py` rules (ledger id M545) retire each old 'engine-on (rpm > 300)' wording in the sentences of section 7; scope dom / jsx / payload. Allowed: 'engine-on (rpm > 400, 1 Hz grid)', 'run-boundary re-definition', 'low-rpm rotation band (logged rpm, 300-400)'. Never: 'correction', 'false engine-on', 'artefact', 'merge' for a run change, a shift presented as a finding, 'significant' for a 300-versus-400 difference.

## 10. Acceptance, falsification, escalation
- A0 (G0): stored payload byte-identical after the `_RawAccum` refactor (arrays diff empty apart from the declared new leaves); `drive_master.csv` MD5 `5556a0c6...` before and after; ML16 untouched.
- A1: independent recomputation of the Rule leaves in the test from the sidecar and from a direct frame computation (no producer helper) on a pre-registered drive sample; the section 4 known answers reproduce.
- A2: payload additive (only the declared Rule leaves and stamps); cohort arrays differ only in the declared Rule chart variants.
- A3: escalate to the Director if any pooled Rule value leaves the M544 evidence by more than the tolerance, if a displayed wording class flips, if a displayed interval excludes the stored value in a way not listed in the M544 addendum, or if the sample audit finds any mismatch.
- A4: blind audit (Sonnet), at least 20 drives drawn BEFORE the run (seed 42, drive type x cadence): per-drive run lengths, zone counts and turbo counts exact; rendered strings equal the payload leaves; cohort views quote cohort values.
- A5: tests: G0 inline-vs-function identity, split / drop / shorten synthetic test, `crosscheck_events` identity, registry tripwire, language rules, `test_encoding_guard`, CI list entries, `release_check.py` green.
- Falsification: the sidecar route is rejected if per-drive Rule values from the stage differ from the M544 evidence on any audited drive.
- No master / ML16 / regeneration-proxy change; no article figure (Opus audit and Andrii's sign-off first).

## 11. Questions for the Director
Q1: Is a per-drive sidecar of run-length lists acceptable (about 30 000 runs in total), or should it store run-length histograms (exact for integer-valued medians)? Q2: May `hvcTurboActivityRule` strings quote the stored 300 share once as a labelled secondary? Q3: Is the count-only onset 400 leaf in this wave or deferred to M546?

## 12. Rev 2 (2026-10-31): Director review (revise); incorporated. Rev 1 SHA-256 recorded before the edit: 22a2abdaf3efa773fbc43fe73c630c124c65c763d8eaf22c8eb908be8f73d975
Where this section and sections 1-11 differ, this section governs.
- Deviations stated (section 8 mapping): (cond. 1) run lengths merge by CONCATENATION, not summation, because exact medians, p10 and p90 need the lengths; counts, zone and turbo statistics merge by summation. (cond. 6) the count-only onset sensitivity is DEFERRED to M546 (Director Q3): section 6 is deleted from this wave, the stored name 'RPM onset (> 300 rpm, run >= 2 s)' is untouched, no `onsetSensitivity400` leaf is built here. (cond. 7) the retire rules are in section 9; the synthetic split / drop / shorten test sits in section 4 and A5.
- Language: Rule strings on native rows never say 'of engine-on time' (M521: a share of logged samples, native cadence, not time-weighted); they read 'share of engine-on native rows (rpm > 400, logged samples)'. The M545 retire rules are scoped to DOM / JSX (and payload leaves of the Rule siblings only), never to the stored > 300 payload strings, which stay byte-identical (G0); no key is renamed. Also forbidden: 'true' or 'more accurate' engine-on, and 'shift' or 'drop' presented as a finding.
- Q2 answer: the stored 300 share may be quoted once per row or sentence as 'stored basis (rpm > 300, native rows)', with no arrow, delta, percent change or difference interval.
- Q1 answer: run-length lists are accepted (about 30 000 integers, auditable).
- Order of work: G0 (the `_RawAccum` refactor to the pure functions, with the inline expressions frozen verbatim in the test) is its own commit BEFORE the stage; the arrays diff must be completely empty (not 'apart from new leaves').
- Sidecar: stores no drive class, cohort, cadence stratum or rendered label; these are joined from the master at aggregation so a refit cannot leave the cache stale. Cache key = raw SHA-256 + function hash + grid-convention version + loader version + threshold. Deterministic JSON, LF.
- Every Rule leaf carries n drives and n days. Each cohort view has a minimum-days floor: fewer than 5 days = exploratory, no interval reading. A day-clustered CI is added for the `engineOnBySpeedRule` zone percentages (the sidecar counts allow it).
- Known answers are pinned to master MD5 `5556a0c6c8bcde0f6c64b8b9655208ed` and 606 drives; STOP if an ingestion intervenes.
- A3 compares against the 300-definition interval exclusions already recorded in M544 section 10 (highway, mixed_highway; unknown has no reading). Internal tripwire only, never displayed.
- A4: a fresh sample with a recorded hash, drawn and committed before the run; strata drive type x cadence x cohort, including cold; the auditor reproduces one bootstrap CI; claim and data path only.
