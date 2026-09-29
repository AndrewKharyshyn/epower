# M300 spec: implement `tools/ingest_core.py` (ingestion protocol steps 1-5)

Status: DRAFT, pre-implementation. Not implemented on purpose; needs (a) byte-verified raw originals, (b) Director review.

## Goal
Deterministic, idempotent, additive ingestion of new raw drive CSVs. Reads real signatures (grep) of
`compute_drive_summary_v6.analyze_bytes/postprocess_master`, `compute_summary_arrays.build_summary_arrays`,
`crosscheck_vehicles.inject`, `crosscheck_events.inject`, `corpus_manifest.build`, `determinism_check.py`. Never calls `run_pipeline()`.

## Acceptance (all must hold, else abort with nonzero exit and no partial writes)
1. No new files -> exit 0, nothing written (no-op).
2. Existing rows of `drive_master.csv` unchanged except the 16 ML/domain columns restored byte-exact (0/16 diffs).
3. MD5 changes only by appended rows; `tools/ingest_core_report.json` records new files, rows before/after, MD5 before/after.
4. `summary_arrays.json` change set == additive splice of intended keys (deep-diff, leaf level).
5. `crosscheck_*.inject` MD5-assert master unchanged; corpus manifest 1:1 canonical; determinism written to BOTH config and arrays.
6. `release_check.py` green (see blocker below).

## Test plan
- Known-answer: ingest 1 held-out existing raw file into a master with that row removed (scratch copy); result must equal the
  published row byte-for-byte on non-ML columns; ML16 restored 0/16 diffs.
- Idempotence: second run is a no-op. Determinism: two runs, identical outputs.
- Blind audit (`analytical-auditor`), then `research-director` decision. Method change flag: none (plumbing only).

## Blockers (verified this session)
- Raw copies in the repo: 335/457 fail sha256/normHash vs `raw_manifest.json` (row counts match). Originals required.
- `release_check.py`: "post-step is a no-op on shipped summary_arrays.json" fails because `patch_m284_data.py` re-stamps
  `_artifactStamps` (fullConfigHash, M284 notes overwrite M293 notes). Needs a Director-reviewed fix.
