# M382 spec (Rev 1): audit 2026-10-05 text/facts wave (F01-F09, F25-part, F26) and tooling guards (F10)

Status: Rev 1, written before any edit. Origin: `analyses/audit_2026-10-05_feasibility.md` (feasibility matrix of `epower_deep_audit_2026-10-05.pdf`).
Branch: `claude/next-milestone` restarted from `main` (a733769, M380). M381 is parked on local branch `m381-wip` (818d152, not pushed, not for merge).
No headline figure, estimator, CI or published per-drive value changes. Allowed payload changes: the leaves listed below, nothing else (deep-diff allow-list).

## Facts read from disk (2026-10-06; master MD5 7c3bc9883f223e8a488b84ad053e13b5, 524 drives)
- F01/F02: `xtrail_summary.jsx:11881` (`ConclusionItem` "Canonical exclusion labels ... reproduce") states the clean-room rebuild reproduces the canonical exclusion sets "with identical file identities" and that "no original bytes are available". Payload: `masterRefitAudit` is the 446-row rebuild of 2026-09-25 (original-era raw); its `exclusionSets` give ens_invalid / ens_outlier_v2 published 2 vs rebuilt 3 (`identicalFileSetOnCommonRows:false`), ens_extreme 24 vs 20. `provenanceSensitivity.raw`: `nCanonicalHashFailing` 0 of 524, `originalsAvailable` true, `formerReexportsReplaced` 333 (M366). `masterRefitProvenance.interpretation` (producer `tools/build_refit_provenance.py`) still describes the pre-M366 state. `determinism.note` is correctly scoped (two runs of postprocess_master on the same master) and is NOT changed.
- F03: `energyUncertaintyMC.grossThroughputMC.dataQualityNote.finding` (producer `energy_uncertainty_mc.py`) says two named drives contribute "literal 0.0 kWh"; the current master holds 9.905 and 2.9667 kWh for them (audit; re-read from `drive_master.csv` by the splice, asserted).
- F04: `generatorTractionRecon.glossary` (terms "η_eng", "Net traction-bus/fuel index") carry 0.355 / 0.329; `corpus.etaEng` / `corpus.etaBus` are 0.351 / 0.325. `refresh_gtr_headline.py` already binds the f_gen glossary rows (M349), not these two.
- F05: `eligibility.families[3]` (EV traction census) uses `ev_valid` only: 435 drives / 8563.0 km; with the canonical-clean predicate (as the displayed 35.1% EV share): 434 / 8542.3 km.
- F07: `_artifactStamps.generatorTractionRecon.computationStatusNote` says gtrClosure is "carried at the M372 set (257 drives; scope.carriedAtIngestion)"; the live `gtrClosure.scope` is 292 drives / 54 days and has no `carriedAtIngestion` (refreshed in M377c).
- F08: `xtrail_summary.jsx:12259` fixes "~1 Hz, resampled to a uniform 1-second grid" and "RPM has ~22% missing samples". Master columns `I_sample_period_s`, `ev_cov_rpm`, `ev_rpm_dt_med_s`, `n_I_samples` allow the coverage to be computed.
- F09: `xtrail_summary.jsx:12360` states a one-pass reprocessing and sign verification "on every file carrying the HV-current PID — currently {gross_throughput notna} of {total}". Master `sign_check`: ok 503, not_testable 9, missing (NaN) 12.
- F10: `tools/run_ingest.py:33-37` filters stages by ID without validating them; an unknown `--only` runs zero stages and exits 0.
- F26: `refresh_gtr_headline.py` loads and writes `summary_arrays.json` at module level.

## Changes
1. F01/F02 JSX text rebuilt from payload fields: dated rebuild (generatedAt, nRowsRebuilt), `exclusionSets` rebuilt-vs-published counts, determinism re-run kept and labelled as seed-stability only, `provenanceSensitivity.raw` current counts, historical rebuild-from-former-re-exports labelled as such (M310/M311, before M366). The `masterRefitProvenance.interpretation` string is generated from the same facts in `tools/build_refit_provenance.py`.
2. F03: finding text generated from the current per-drive nominal energy and widening delta (producer `energy_uncertainty_mc.py`, contributor entries gain `nominalKwh_1500ms`; no cause is asserted).
3. F04: glossary rows bound to `corpus.etaEng` / `corpus.etaBus` in `refresh_gtr_headline.py` (3 decimals).
4. F05: EV family predicate = `ev_valid` AND canonical-clean (`_audit_eligibility`), basis string updated.
5. F07: stamp note regenerated from `gtrClosure.scope` and `refreshedBlocks` / `staleBlocks` (no inherited note).
6. F08/F09: additive `eligibility.dataCoverage` (sign_check categories, RPM coverage, current-PID sample period distribution; all computed from the master) and JSX text bound to it; fixed "~22%" / "1 Hz grid" / "one pass" / "every file" statements removed. Primary energy wording: native current timestamps, nearest voltage within 1.5 s, 5 s credit cap (read from `constantProvenance` where present).
7. F10 + F26: stage ID validation with a unit test; `refresh_gtr_headline.py` gets a pure `build()` and a `main()` guard (behaviour of the ingestion stage unchanged, checked by output-identity on a scratch copy).
8. Language gate: each replaced wording is added as an OLD-wording rule with its ledger id (F01, F02, F03, F04, F05, F07, F08, F09).
9. Fact-aware checks (new, in `tools/` and wired into `semantic_gate.py`): G4 text-vs-fact (e.g. "identical" file identities cannot render when `exclusionSets[*].identicalFileSetOnCommonRows` is false; "no original bytes" cannot render when `originalsAvailable`; "every file" sign claim cannot render when `sign_check` has `not_testable`/missing), G3 support identity (EV family n/km equals the n/km of the EV share estimator), G5 stamp freshness for the GTR note.

## Out of scope / deferred (recorded in `analyses/audit_2026-10-05_feasibility.md`)
F06 schema split (`computedAt` / `inputBasis` / `includedInReleaseAt`): needs a design decision (SPEC). F11, F13, F14-F19 analyses, F20, F24, performance wave (M383).

## Acceptance
- `drive_master.csv` MD5 unchanged; ML16 not touched; `python release_check.py` green on the rebuilt dashboard; all 10 tabs x 4 cohort modes render in jsdom with no console errors.
- Deep-diff of `summary_arrays.json` / `summary_config.json` before vs after: only the leaves named above change (EV family n/km/basis, glossary values, stamp note, MC finding text, `masterRefitProvenance.interpretation`, new `eligibility.dataCoverage`).
- New tests fail on the pre-fix payload (known-answer: the old strings) and pass after.
- Dashboard change rule: render with SendUserFile, commit with sources (`xtrail_summary.jsx`, `summary_arrays.json`, `cohort_arrays.json`) in one commit, open the PR itself, CHANGELOG `M382` entry via `tools/changelog_draft.py`.
