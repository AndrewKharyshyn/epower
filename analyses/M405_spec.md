# M405 spec (Rev 1): content-keyed run fingerprint (audit N05) and register status update

Status: Rev 1, written before the change. Origin: deep audit 2026-10-11 N05 ("No-change fingerprint omits input content/path": same-size raw byte changes and `XT_RAW_DIR` do not invalidate), feasibility register `analyses/audit_feasibility_2026-10-11/FEASIBILITY.md` (phase P3, S-M part). Branch `claude/next-milestone` restarted from `main` (1bd3745, M404). `drive_master.csv` MD5 `64dfd0cbff3db404d9b83e180f777525`, `summary_arrays.json` and the dashboard unchanged.

## Facts read from disk (2026-10-11)
- `tools/run_fingerprint.py::components` hashes the raw listing as sorted `(name, size)` of `root/raw` only, and the environment hash explicitly excludes `XT_RAW_DIR`: a changed byte with the same size, or a run pointed at another raw directory, leaves the fingerprint equal and `--skip-unchanged` would skip every analysis stage on different inputs.
- The fingerprint is opt-in (`run_ingest --skip-unchanged`); the gate stages are never skipped; the ledger is `runs/last_green_fingerprint.json` (version 1).
- Hashing all 565 raw files (1.18 GB) takes about 6 s on this machine.

## Change
`FP_VERSION = 2` (an old ledger is discarded, the next run runs everything). Components `rawListing` = sorted `(name, size, sha256 of the bytes)` of the files in the resolved raw directory, and new `rawDir` = identity of the resolved raw directory (XT_RAW_DIR when set else `root/raw`, symlinks and `..` resolved BEFORE hashing; relative to the repository root when inside it, so a clone elsewhere keeps its ledger; the resolved absolute path otherwise). Nothing else changes: sources, stage list, lock, analyses/, declared outputs, master, manifest and environment components are as before.

## Acceptance
Known-answer tests in `tests/synthetic/test_run_fingerprint.py` (in CI): same-size changed raw bytes invalidate (and fail on the previous implementation); a different `XT_RAW_DIR`, even with identical content, invalidates and names `rawDir`; an equivalent spelling of the default directory does not; restoring the input allows the skip again. CI unit list and `python release_check.py` green; CHANGELOG `M405`.

## Out of scope
Per-drive and per-stage content keys / stage DAG (F24, needs the owner decision on the "seasonal recomputed every ingestion" rule), shared fitted-state files as explicit components (they are covered through declared outputs and analyses/), F20 / F11 (owner decisions pending), F06.
