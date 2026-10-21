# M468 spec: provenance stamps state each block's own input basis (audit 2026-10-21, F03)

Finding F03 (P1, metadata only; no numerical value is shown wrong): the generic stamp pass conflated "computed" with "included in this release". Evidence on the committed payload (checked by script this session):

1. `regenCaptureV2Study`, `regenCaptureV2HStudy`, `regenSocStandardizedStudy` are carried at the 578-drive basis (payload `masterMd5` a641f34d..., `upstreamHashes.driveMasterMd5` a641f34d...), but `inputBasis.masterMd5` held the live 606-drive master (5556a0c6...).
2. `socHysteresisV2` has `recomputeMode: fresh`, `corpusSizeAtRecompute: 606`, `frozenBasis: false` (M463 refit), but its stamp note still said "NOT recomputed in this build" and `inputBasis.masterMd5` was null.
3. Release gate WARN (unchanged by this milestone): `fullConfigHash` values (3 distinct) differ from `md5(summary_config.json)`. Not touched: the audit asks for an actual dependency explanation, not a blanket restamp.
4. Ten stamps carry the raw-manifest corpus hash of the 2026-09-25 snapshot (8 `computed`: ambientTable, assumptionsRegistry, cohortMeta, crossVehicle, generatorTractionRecon, provenanceSensitivity, seasonalCharts, spreadFitProvenance; plus the two carried master-refit blocks, legitimately). Now surfaced as a release_check WARN; explaining each needs a per-block dependency review (follow-up, Director).

Change (tools only; no producer, master or figure touched):
- `tools/stamp_basis.derive`: a carried stamp without a block-declared basis takes its master from the block (`masterMd5`, `studyBasis.masterMd5`, else the stamp's `upstreamHashes.driveMasterMd5`), never the stamping pass; a fresh `socHysteresisV2` is `computed`, its note is replaced, its input master is the live master.
- `tools/stamp_basis.check` (used by `semantic_gate`): fails a carried stamp whose master differs from the block's own or the upstream one, a carried smaller basis carrying the live master, a `computed` stamp whose note says "NOT recomputed", and `socHysteresisV2` status disagreeing with `recomputeMode`.
- `release_check.py`: WARN listing `computed` stamps whose raw-manifest corpus hash differs from the live one.
- Test: `tests/synthetic/test_stamp_basis.py` (known-answer + mutation controls). Writes only `/_artifactStamps/*` (existing assertion of the tool).

Acceptance: pre-fix payload fails `check()` on exactly the 4 stamps above, post-fix payload passes; `summary_arrays.json` diff is the 4 stamps only; `release_check.py` green; HTML rebuilt (no displayed content change).
Out of scope: re-running the three 578-basis regen studies (run-once, carried at their own basis by the M463/M466 decision; relabelling is what the audit asks for), the fullConfigHash dependency analysis, the snapshot-lag explanations.
