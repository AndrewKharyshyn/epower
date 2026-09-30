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

## Result (2026-09-29, M302) - known-answer test in a scratch copy
- Held-out last drive re-ingested into a 445-row master: resulting `drive_master.csv` MD5 == published `0bcfc400...`; 0/16 ML diffs; 0 pre-existing-row diffs; 446 rows.
- Manifest: only the held-out record's sha256/normHash differ from published (disclosed raw-copy mismatch); order fixed to published order.
- Arrays: incremental ingest vs a full-master control build differ only in post-step labels (determinism scope) and crossVehicle (not injected in control): 0 numeric leaf diffs.
- NOT reproduced: published `summary_arrays.json` vs a fresh build in this checkout differ in ~1,130 non-stamp leaves (both the control and the ingest run), e.g. accelDecelEnvelopes, highSocRegen, crawlStopGo, mountainPattern, energyUncertaintyMC, thermalFuelPenalty. Cause not established (candidates: raw copies not byte-identical to the originals, library versions, carried-forward blocks). Post-ingest results are therefore internally consistent but not proven identical to the M299 publication. Blind audit + Director review still pending before ingesting real new drives.
- Runtime of the arrays step: ~35 min.

## Blind audit (2026-09-29, Sonnet auditor, verdict: revise)
- Master known-answer reproduced independently: MD5 0bcfc400..., 0 ML16 diffs, 0 pre-existing-row diffs. Scope: master CSV only.
- ingest_core review: gates strict (CSV-text compare), no held-out leakage into ML16 restore. Fixed after audit: atomic writes (tmp+replace),
  BaseException rollback (tested by injected KeyboardInterrupt after master+manifest were written: all 4 files restored identical),
  redundant branch in master_key. Open (documented, not fixed): report file / raw_cache side effects are not rolled back; manifest
  hashes for old records fail on-disk verification, so corpusHash/contentHash attest nothing about raw/.
- Reproduction gap cause (confirmed, reproduced by the author too): raw copies whose sha256 FAILS the manifest (333/446 in the auditor's
  count) do not reproduce the published per-drive master values (15 sampled: 442 differing cells; 15 sampled hash-matching files: 0 diffs).
  So today's raw/ is not the raw content the published master/arrays were built from. Incremental == full-master control in all raw-pass keys.
  This contradicts the 2026-09-29 owner decision "raw/ treated as original" -> escalated to Andrii and the Director.
