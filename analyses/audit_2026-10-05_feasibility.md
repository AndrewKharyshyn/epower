# Feasibility assessment: `epower_deep_audit_2026-10-05.pdf` (31 pages)

Basis: the full PDF was read (text layer via pypdf; figures on pp. 5, 11, 12 viewed as images, they only restate numbers already in the text).
Repo state: branch `claude/next-milestone`, CHANGELOG head M380, master MD5 `7c3bc988...`, 524 drives.
"Verified" = checked against the live repo/payload in this session by grep/JSON walk. "Audit-only" = taken from the audit, not re-run.
Nothing has been implemented. Milestone numbers are proposals; renumber from the CHANGELOG head.

Legend. Verdict: **GO** (implement as tooling/text change), **SPEC** (needs `new-analysis` spec + blind audit first),
**LATER** (valid, large or needs new data), **NO** (reject or conflicts with a standing rule), **HAVE** (already done).
Effort: S <0.5 d, M 0.5-2 d, L >2 d. Speed: effect on runtime. Risk: risk to published figures/precision.

## 1. Findings register F01-F26

| ID | Audit claim | Verified in repo | Verdict | Effort | Speed | Risk | Notes / rules |
|---|---|---|---|---|---|---|---|
| F01 | "Raw originals" history false in Conclusions | CONFIRMED at [xtrail_summary.jsx:11881](xtrail_summary.jsx:11881) (the audit line number is right; my first grep missed it because the text says "original-era") and in `/masterRefitProvenance/interpretation` + `limits[0]` ("No original bytes are available"). **Done in M382.** | GO | S | none | none | Bind to `rawManifest`/F03 status (489/489 matched after M366) and move the old sentence to history. Language gate: add OLD wording as a rule with ledger id. |
| F02 | Historic refit exclusion sets called identical | CONFIRMED at [xtrail_summary.jsx:11881](xtrail_summary.jsx:11881): "canonical exclusion sets ... with identical file identities" against `masterRefitAudit.exclusionSets` (`identicalFileSetOnCommonRows:false`; ens_outlier_v2 published 2 / rebuilt 3; ens_extreme 24 / 20; generatedAt 2026-09-25). CORRECTION: `/determinism/note` is accurately scoped (two seeded runs of the same master) and was not changed. **Done in M382.** | GO | S | none | none | The determinism harness covers only the ML16 stage; word it that way, show the audit date, show the false set-equality fields separately. |
| F03 | MC quality note: two drives "literal 0.0 kWh" | CONFIRMED. `/energyUncertaintyMC/grossThroughputMC/dataQualityNote` (and `independentIntegrationCheck`) still say 20260610_094100 / 20260515_222240 contribute literal 0.0 kWh; audit gives 9.905 / 2.9667 kWh in the current master. | GO | S-M | none | none | Generate the sentence from the current tolerance-grid nominal energy plus the contributor ledger; no fixed inference. Producer is in `energy_uncertainty_mc.py`/`energy_mc_precompute.py`. |
| F04 | Glossary eta 0.355 / 0.329 stale | CONFIRMED. `generatorTractionRecon.glossary[3,4]` = 0.355 / 0.329; `corpus.etaEng/etaBus` = 0.351 / 0.325. | GO | S | none | none | Bind glossary values to `corpus.etaEng/etaBus`. Anti-pattern per CLAUDE.md (hardcoded literal). |
| F05 | EV eligibility 435 / 8563.0 km vs 434 / 8542.3 | PARTLY. `/eligibility/families[3].n = 435` present; the 434 estimator support is audit-only. | GO | S-M | none | low | One predicate (canonical-clean AND ev_valid) producing one support object consumed by both. Run the predicate to confirm 434 before changing anything. |
| F06 | Computed-provenance stamps describe carried-forward blocks | PARTLY. Blocks carry `carriedBasis`/`computationStatusNote`, but every stamped key gets `computationStatus: computed` and the stamping-pass `generatedAt` unless it self-reports `recomputeMode`/`frozenBasis`. Notes are typed per ingestion through `tools/restamp_blocks.py` (root cause of F07). | SPEC (schema split); generated GTR note done in M382 (`tools/stamp_notes.py`) | M | none | none | Split `computedAt/inputBasis` from `includedInReleaseAt` in `_artifactStamps`. Historical basis stays honest. |
| F07 | GTR closure stamp says 257 drives | CONFIRMED. `/_artifactStamps/generatorTractionRecon/computationStatusNote` says "gtrClosure numbers carried at the M372 set (257 drives ...)" while `gtrClosure.scope` is 292 drives / 54 days. | GO | S | none | none | Generate the note from the producer record. |
| F08 | ~22% missing RPM and universal 1 Hz | CONFIRMED at [xtrail_summary.jsx:12259](xtrail_summary.jsx:12259). The data contradict it: `ev_cov_rpm` (share of one-second grid seconds with an RPM sample) has median 1.0, mean 0.985, 21 of 523 drives below 0.9. **Done in M382** (new `eligibility.dataCoverage`). The other "1 Hz grid" mentions (JSX 1266 / 3813 / 4831) are detector/grid definitions and were left. | GO | M | none | none | Per-family coverage + timeline fields (denominator, max sample age, unknown-state share) from the producers; primary energy uses native I and nearest V. Note the 1 Hz mentions at 1266/3813/4831 are detector/grid definitions and may be legitimate; review each. |
| F09 | "One-pass rebuild" and "sign verified on every energy file" | CONFIRMED at [xtrail_summary.jsx:12360](xtrail_summary.jsx:12360) ("reprocessed from raw logs in one pass ... verified via torque co-check on every file"); master `sign_check`: ok 503, not_testable 9, missing 12 (matches the audit). **Done in M382.** | GO | S-M | none | none | Locate the string, then derive counts from `sign_check`. Distinguish additive publication from a full refit. |
| F10 | Unknown requested stage silently succeeds | CONFIRMED. [tools/run_ingest.py:33-37](tools/run_ingest.py:33) filters the list; `--only typo` runs zero stages and exits 0. | GO | S | none | none | Validate `--only/--from/--skip` against IDs, reject empty selection; unit test. |
| F11 | Core recomputation is not a publication replay | Audit-only (consistent with the open clean-room item). | LATER | L | none | n/a | Needs a release manifest (repair ledger + frozen ML16/M119 state + dependency versions) and a pinned replay. This is the "clean-room" open item; do after the architecture waves. Never overwrite the master with a refit. |
| F12 | Generator node does not close under its rule | Matches the repo (`gtrClosure`, +6.75 %, 18 infeasible). | HAVE (disclosure) | S | none | none | Keep the failed-closure disclosure prominent. Add dual-charge attribution bounds to the headline panel if missing; do not tune BSFC to erase it. |
| F13 | BSFC map and aux load insufficiently calibrated | Matches CLAUDE.md language rules (assumed/modeled). | LATER | L | none | n/a | Needs held-out fuel + generator/DC-bus data that do not exist. Label-only part (classify unmeasured regimes as assumed/anchor-based): GO, S. |
| F14 | SoC-anchored offset is conditional on the ledger | Audit-only; method independently reproduced (-0.384939 A). | GO (rename) / SPEC (stratified tests) | S / M | none | none | Rename to "SoC-ledger residual-balance offset" everywhere via language gate. Stratification by SoC/temperature/engine state/logger regime is a new analysis (spec + blind audit). Keep uncorrected totals primary. |
| F15 | Aging equivalence bounds hypothetical | Audit-only; consistent with CLAUDE.md (TOST "not established"). | SPEC | M | none | low | Keep the unresolved conclusion. Margin-sensitivity table is cheap; "justified pack-relevant margins" needs the Director. |
| F16 | Capacity-normalized metrics depend on unverified 2.1 kWh | Matches CLAUDE.md (`CAP_KWH=2.1`, `verified:false`). | GO (wording) | S | none | none | Terminal kWh primary; 1.8 kWh scenario explicit; deprecate capacity-observable wording; do not change `CAP_KWH`. |
| F17 | Cadence uncertainty outside the throughput MC | M381 (cadence emulation) is in progress and already addresses part of this. | SPEC (inside M381 / follow-up) | M-L | none | none | Add paired common-support tolerance checks, causal/backward alignment, left-hold interpolation scenario (+4.52 % gross). Keep it a scenario view, separate from the MC interval. |
| F18 | Historical cross-validation measures correlation, not agreement | Audit-only; `crossval_gtr.py` carries shipped values (CLAUDE.md already says stale/historical). | GO (archive label + Bland-Altman/log-ratio view from stored outputs) / LATER (recover model) | S-M / L | none | none | Cheap part: relabel as historical internal comparison and add limits-of-agreement. Real validation needs the lost Path A coefficients. |
| F19 | Cold-season / thermal estimates are selected | Consistent with the repo (Cold below support suppressed). | GO (coverage indicators) / SPEC (censoring-aware time-to-threshold) | S / M | none | low | Add censoring/rejection profile to warmup (9 of 135) and lag (111 crossings); survival-style summaries are a new analysis. |
| F20 | Downstream failure can leave hybrid artifact versions | Plausible: 31 serial stages, many write `summary_arrays.json`. | SPEC | L | slight (can parallelize) | low | Stage into `runs/<ts>/`, validate, publish atomically; failure-injection test. |
| F21 | 3 parses + duplicated channel extraction | CONFIRMED in part. `recon_engine.load_drive` assigns `s=` twice ([recon_engine.py:30-31](recon_engine.py:30)). `drive_raw_cache.py` already pre-parses `time` with the `%H:%M:%S.%f` fast path. Remaining slow paths: `recon_engine.py:25` (no format) and `compute_drive_summary_v6.py` 528/1278/1452 (`format='mixed'`). | GO | M | high (parser 3.1x, loader 3.7x at component scale, audit-only) | low | All-channel parity on all 524 drives; keep the dateutil fallback for other forms/rollover. |
| F22 | DataFrame concat inside ratio bootstraps | Audit-only; `tools/gtr_closure_diag.py:56` has the `pd.concat` per draw pattern. | GO | M | high (618x for the 292-drive closure ratio) | none | Day sufficient statistics; same draws; seed 42 / 4000 draws unchanged. Additive ratios only. |
| F23 | Throughput MC builds drive x draw matrices | CONFIRMED. [energy_uncertainty_mc.py:123-136](energy_uncertainty_mc.py:123) comment claims interpolation is not linear in the sum; it is (shared grid, shared tau). Same at line 258 (net). | GO | S-M | memory (about 82 MB per float64 array at 510x20000), moderate time | none | Sum curves, interpolate once. Realized result differs only at float rounding; check paired totals and re-run the MC known-answer audit. Keep the independent quantization draw stream unchanged. |
| F24 | Milestone scripts and repeated splices obscure producers | Matches the script index (15 `mNNN*` files at root, `post_steps`, `post_splices`). | LATER | L | modest | medium | One producer per block. Do in increments behind the leaf-level arrays parity check. |
| F25 | Standalone MC file and stage descriptions historical | `energy_uncertainty_mc.json` exists beside the payload; stage `desc` fields in `tools/ingest_stages.json` are empty. | GO | S | none | none | Regenerate/label the sidecar from the same release object; fill stage descriptions. |
| F26 | Refresh command executes on import | CONFIRMED. [refresh_gtr_headline.py:21](refresh_gtr_headline.py:21) loads `summary_arrays.json` at module level. | GO | S | none | none | Pure `build()` + `main(argv)` behind `__name__`. |

## 2. Page-level recommendations (not in the F-register)

| Page | Recommendation | Verdict | Effort | Notes |
|---|---|---|---|---|
| 2 | Remove false history; demote hypothetical lifetime horizons, transferred damage weights, historical cross-validation to sensitivity/history views | SPEC (Director decision on demotion) | M | Dashboard content change: Dashboard change rule applies (render, commit, push with sources). |
| 2 | "No whole-pipeline multiplier can be inferred from the 618x result" | ACCEPT | - | We will not quote one. Need a pinned baseline first. |
| 3 | Treat the 14 rows without gross energy per metric (12 no/too-few current, 2 no aligned pairs) | HAVE (partial) | S | Verify that support identity (null never formatted as zero) holds everywhere; see gate G3. |
| 4 | Independent agreement at published precision | HAVE | - | Keep as audit evidence; the audit scripts are not part of the repo. Optionally add the independent integrator as a known-answer test (tools/, S). |
| 5 | Alternative-integration sensitivities (>5 s discard -0.098 %, backward-only V -0.003 %, left-hold +4.52 %) | SPEC (as part of F17) | M | Scenario table, never replacing the primary total. |
| 6 | Paired common-support tolerance checks, sample-age distributions, causal alignment, alternative interpolation, cadence thinning; report support gained/lost | SPEC | M-L | With F17. |
| 6 | Correlated global calibration parameters stay common across drives; do not average away | ACCEPT | - | The MC already uses one shared tolerance draw; keep it. This is a constraint on any F23 variant. |
| 7 | Stratify the offset by start/end SoC, temperature, boundaries, engine state, logger regime; key-on/off jumps; relaxed periods; external zero-current reference | SPEC (stratify) / LATER (external reference) | M / L | The external reference needs new measurements. |
| 8 | De-emphasize or remove `cap_ah_est` as a health observable | GO (schema/wording) | S-M | Check consumers first (grep for `cap_ah_est`); retain as a named normalization calculation. |
| 8 | Demote squared-DoD weights, fixed SoC stress factors, gross-turnover thresholds; deprecate end-of-life crossing years | SPEC | M | Overlaps page 2; Director decision. |
| 8 | BLAST-Lite scenario framework | LATER | L | Needs matched cell/pack data; not feasible now. |
| 9 | Report unknown-RPM omitted volume dynamically; keep denominators explicit (269-trip FUEL-12 vs 294) | GO | S | Bind to producer fields. |
| 9 | Classify cold correction as scenario; prefer oil state over "every restart cold" | SPEC | M | Method change to the cold-penalty model: blind audit. |
| 10 | Retain failed closure, alpha*, 18 infeasible, interval/bounds; no BSFC tuning | HAVE | - | Already in the repo and CLAUDE.md language. |
| 10 | "Majority battery-buffer contribution is a point estimate, not established" | GO (wording check) | S | Check the f_gen = 0.459 interval [0.379, 0.540] wording in the Sankey/closure block and the thesis statement in the dashboard. |
| 11 | Bland-Altman / log-ratio agreement for the 82 historical outputs | GO (F18) | S | From stored outputs only. |
| 12 | Cluster-t df / small-cluster sensitivity next to CR1 normal intervals | SPEC | M | New estimator variant: known-answer test + audit. |
| 12 | Huber second-stage vs refit nuisance model are different estimands | HAVE (disclosure) | S | Verify both are labeled. |
| 13 | Margin sensitivity for TOST | SPEC | M | Cheap compute; margins need Director sign-off. |
| 13 | Week/block resampling as a persistence sensitivity | SPEC | M | M317 calibration retained. |
| 13 | Grouped-by-day and rolling-origin validation; preprocessing inside training folds | HAVE (day-blocked CV is in CLAUDE.md) / SPEC for rolling-origin | M | Check each predictive model for leakage. |
| 13 | Declare primary questions, label exploratory analyses, multiplicity control | SPEC | M | Method-level decision for the Director; affects every tab label. |
| 13 | Bootstrap proportion of positive slopes is not a p-value/posterior | GO (wording) | S | Add to language gate. |
| 13 | Selection/temporal confounding: matched windows, nonlinear temperature, selection-aware reporting | LATER | L | Research; needs more data. |
| 13 | Validate the T^-1.5 detection-horizon by simulation before presenting it as a duration requirement | SPEC | M | Until then label as planning approximation. |
| 14 | Coverage governs narrative: intake-air channel missing (254 unavailable, last valid Aug 24) disclosed; warmup 9/135, lag 111 crossings; start-rate not cold-start | GO (coverage indicators and disclosure check) | S-M | Tied to F19 and F08. |
| 14 | Keep nine e-4ORCE files auxiliary | HAVE | - | Manifest roles already do this. |
| 14 | More winter/repeat-route/consistent PID logging; external reference | LATER (data collection) | - | Owner action, not code. |
| 15 | Publish a stable anonymized data dictionary, corpus versions, release replay | LATER | M-L | Data dictionary is S-M and independent; the replay is F11. |
| 15 | Align every tab with "capacity fade unidentifiable, generator output modeled" | GO | M | Sweep through the language gate rules; blocked on the F01-F09 fixes. |

## 3. Dashboard text policy (p.16-18)

| Item | Verdict | Effort | Notes |
|---|---|---|---|
| Producer-to-UI contract (units, denominator, cohort, method class, basis) | SPEC | L | The cleanest long-term fix; start with the F01-F09 blocks only. |
| Remove silent quantitative fallbacks (missing required key -> historical number): show unavailable or fail the build | GO | M | Find `|| <number>` fallbacks in JSX; fail the required-block build. |
| Retain declared parameters (2.1 kWh, BSFC floor, support minimums) in one assumptions registry | HAVE/GO | S-M | `constantProvenance` and `AssumptionsRegistryTable` exist; check for gaps. |
| Retain odometer 45028 as an external observation with as-of date | HAVE | S | Matches the "logged share of odometer" rule. |
| Presentation constants (colors, axes, rounding) stay | ACCEPT | - | The audit's 8,657 presentation literals are not defects. |
| 24,899 JSX literals / 2,344 config leaves: finish migration using the inventory CSV | LATER | L | Bulk of the 9,880 "needs context" and 6,251 narrative entries cannot be triaged mechanically. Use it as a worklist for quantitative literals only. The inventory CSVs are in the audit bundle (not in the repo); request the bundle. |
| Generated sentences consume the same typed statistic and support object | SPEC | L | Truth-aware generation is the real fix (see F03). |
| Move historical milestones to an audit-history view with original dates | SPEC | M | Content change. |

## 4. Verification gates (p.26)

| Gate | Verdict | Effort | Would it have caught the audit's contradictions? |
|---|---|---|---|
| G1 Raw-to-release replay | LATER (needs F11) | L | Needed; keep the "NOT COVERED" release_check message visible until then. |
| G2 Energy conservation (gross = dis + chg; net = dis - chg; zero-crossing and gap fixtures) | GO | S | Known-answer test with synthetic fixtures under `tests/synthetic/`. |
| G3 Support identity (same file-ID support and denominator for estimator/chart/eligibility; null never as zero) | GO | M | Catches F05 and F03. Compute from the payload; fail on mismatch. |
| G4 Fact-aware narrative (originals status, closure failed, exclusion sets, sign check categories) | GO | M | Catches F01, F02, F07, F09. Do NOT assert sentence presence; assert text-vs-fact consistency (e.g. "identical" absent when `identicalFileSetOnCommonRows` false). Extends `semantic_gate.py`. |
| G5 Producer freshness (block input hash/basis/date match its producer; carried history keeps historical status) | GO | M | Catches F06/F07. |
| G6 Optimization parity (loader all-channel, bootstrap same multiplicities, MC paired totals, float64) | GO | S-M | Mandatory companion to Tier A speed work. |
| G7 Cache invalidation (source byte, parameter, dependency, adjacent-trip) | SPEC | M | With the cache-key redesign. |
| G8 Failure transaction | SPEC | M | With F20. |

## 5. Performance and architecture (p.20-25)

| Item | Verdict | Effort | Measured gain (audit) | Rule/Risk |
|---|---|---|---|---|
| Native-time loader: selected columns, explicit format, one extraction per PID, vectorized time-since-engine-start | GO | M | 3.1x parser / 3.7x fuel loader (component) | Parity on all 524 drives; keep fallback. `data-worker` for runs. |
| Read each file once for base / voltage-sag / EV metrics (three passes now) | GO | M-L | audit-only | Shared per-drive typed frame from `drive_raw_cache`. |
| Daily sufficient-statistic bootstrap for additive ratios | GO | M | 618x on one closure ratio | seed 42 / 4000 draws / percentile CI unchanged. |
| Summed-curve interpolation in throughput MC | GO | S-M | memory; time not measured | see F23. |
| Share one validated Huber bootstrap per unique input/method hash | GO | M | audit-only | Bit-identical; keep M317 calibration. |
| X'X / X'y per-day cache for linear regressions | LATER | M | audit-only | Only after the above. |
| Reuse the same day-draw matrix across related ratios | SPEC | S | small | Changes the realized random stream; only where scientifically appropriate and versioned. |
| Aggregate Gaussian for per-drive quantization draws | NO (for now) | - | modest | Changes the random stream; the Tier-A memory fix removes the large arrays anyway. |
| Dependency-aware skips with explicit reasons; no-change run validates cheap integrity and returns | SPEC | M-L | Largest end-to-end effect on no-change/one-drive runs | Do not skip a global fit just because per-drive inputs were cached. Cache key: source hash + loader/schema version + estimator parameters + alignment/gap policy + fitted-state version + adjacent-trip context. |
| Bounded worker pool for pure per-drive tasks | SPEC | M | audit-only | Deterministic order and per-file seed derivation. |
| Atomic staged release | SPEC | L | none | F20. |
| Preview mode with fewer draws | SPEC | S | large for dev loops | Must be visibly separate from publication outputs. |
| Baseline measurement: cold / warm-cache / one-new-drive / no-change; wall, CPU, RSS, parse/decompress count, cache hit/miss, bytes written per stage | **GO FIRST** | S-M | n/a | Pinned Python 3.11 environment; same machine. No performance target before this. |
| Collapse 31 stages to ~8-12 producers behind ingest/build/check | LATER | L | modest | Do per block with parity. Design target only. |
| Split `compute_summary_arrays.py` (18,116 lines) into domain builders | LATER | L | none by itself | Splitting without ownership change does nothing. |
| Move `mNNN`, `post_steps`, `post_splices` out of the production import graph | LATER | M-L | none | After the static/runtime dependency map (registry, imports, CI, shell). |
| Single global x cohort view generator | LATER | L | modest | Keep release compatibility adapters. |
| One dependency lock (`requirements.pinned.txt`) | GO | S | none | Name sets are identical; update CI and skill references. |
| Delete raw files / drop draw counts / downcast / drop rare events | NO | - | - | Raw is read-only; explicit in the audit as well. |
| Archive stale standalone MC / duplicate payload snapshots | GO | S | none | After checking no consumer reads them. |

## 6. Proposed sequence

0. Finish and merge M381 first (uncommitted M381 files are on this branch).
1. **Baseline** timing in the pinned environment (`data-worker`, low).
2. **M382 text/facts wave** (F01-F09, F25, F14/F16 wording, gates G3-G5, then G2): no figures change; verify with release_check and a rebuilt dashboard (Dashboard change rule applies).
3. **M383 tooling-speed wave** (F10, F26, F21, F22, F23, requirements lock, G6): paired old/new parity on all inputs; no published figure may change beyond float rounding.
4. **M384 dependency skips + shared bootstrap** (G7), then **atomic release** (F20, G8).
5. SPEC items one at a time via `new-analysis` (F14 stratification, F15/F17/F19 sensitivities, cluster-t, block bootstrap, multiplicity labeling).
6. LATER: F11 release replay, producer consolidation, data dictionary, external-data items.
