# M324 spec rev 2 (pre-registered 2026-10-02, before any code): GateA2 = amendment 2 of the M308 input-plausibility gate
Status: rev 2 = rev 1 + Director spec-review changes (decision 'revise', 2026-10-02; see 'Director changes' at the end). Not yet implemented. Owner decision (Andrii, 2026-10-01): GO, small, flag-only (never repairs), lands after M320-M323 and BEFORE the next ingestion.
Ledger origin: C13.2 (P2), C01, C3.1 (audit_v3). Milestone number is a proposal (M323 is taken; the F03 follow-up of the Director's re-ruling shifts to M325).

## Problem (verified on disk)
M308 R2 pools the Max and Min cell-voltage columns before computing the minimum positive step. A file with one coarse channel (0.1 V grid) and one fine channel
passes R2 because the fine channel dominates the pooled minimum. In the corpus scan (analyses/M308_corpus_scan.json) 6 of the 9 flagged files trip R1+R2 (pooled minStepV 0.1) and
3 trip R1 only (53.0 V value, pooled minStepV 0.001). The audit calls all 9 'coarse-channel logs'; whether the 3 R1-only files have one coarse channel is NOT established on disk
(open question, answered by the scan below, not assumed). The pooled statistic can in principle miss a mixed-grid file that lacks the 53.0 V sentinel.
Also, the representation of each new file (grid, cadence, range, support, fingerprint) is not recorded anywhere, so a later change in logger resolution cannot be detected or
audited per channel (audit C13 "track observed signal representation").

## Changes (two, nothing else)
A. R2 per channel. `tools/plausibility_gate.py`: apply the existing R2 test (minimum positive difference between sorted distinct values >= 0.05 V, needs >= 5 distinct values)
   to `[BMS] Max Cell Voltage (V)` and `[BMS] Min Cell Voltage (V)` SEPARATELY (each matched column tested on its own, including duplicate/suffixed columns); emit ONE
   `R2_quantisation` flag carrying a `channels` list if ANY channel trips (the existing tests assert exact rule lists). Per channel, the result also reports a status:
   tested / untested (all-NaN, non-numeric after coercion, or < 5 distinct values); `ingest_core` lists partially checked files in the report (visibility, not a quarantine).
   Stated residual false negatives: a partly coarse channel (statistic is the minimum positive step) and a channel with < 5 distinct values (short files) still pass. R1 unchanged (range, pooled is fine).
   Threshold 0.05 V and MIN_DISTINCT = 5 are NOT changed; no new threshold is introduced. G01..Gnn group voltages stay out of scope (Amendment 1).
B. Per-file signal-representation record. New module `tools/signal_representation.py` and a stage `signal_representation` (after the gate, before analyze_bytes) in `tools/ingest_stages.json`.
   For every NEW file it writes an entry to `signal_representation.json` (repo root, additive, atomic write, never rewrites or deletes an existing entry; a differing sha256 for an existing key aborts):
   - file key (master 'file' key), sha256, normHash (corpus_manifest._norm_hash definition), header fingerprint (sha256 of the ordered column-name list), schema_version, gate version and verdict,
     n_rows, the timestamp column used, first/last timestamp, native cadence (median and p95 of positive non-null timestamp differences, ms);
   - per numeric channel: n_nonnull, n_distinct, min, max, grid_step (minimum positive difference of sorted distinct values; null if < 5 distinct), max_decimals (largest number of decimals in the raw text of any value),
     decimals histogram (share of values by number of decimals) and share of values on a 0.1 grid (exposes partly coarse files without a new rule).
   Commit point: the sidecar entry is written at the ingestion commit (after the master write), not before; a failed later stage leaves no orphan entry. A sha256 conflict for an existing key fails closed;
   a legitimate re-export is handled by an explicit, documented `--supersede KEY` path that keeps the old entry under `superseded` (never silent overwrite). Output uses sorted keys and fixed float format so reruns are byte-identical.
   No pipeline/build reader consumes the file in this milestone.
   The record is descriptive ("grid of this CSV copy", never "sensor resolution" or "rounding rule"). It adds NO quarantine rule beyond A; it is informational and feeds M326+ resolution tables.
   Existing corpus: NO backfill in this milestone (retroactive inventory is a separate read-only task; the gate is never applied to the published master).

## Pre-registered known-answer and decision rules (fixed now)
1. Synthetic: Max on a 0.1 V grid (>= 5 distinct), Min fine -> flags `R2_quantisation[Max]` (the pooled M308 rule does NOT flag it: test documents the old miss). Mirror case flags `[Min]`. Both fine -> no flag. < 5 distinct values in a channel -> that channel not tested. Boundary: step 0.0499 passes, 0.05 flags (per channel).
2. Informational corpus scan with per-channel R2 on the 441 checked files (not applied retroactively): report the number of R2_quantisation flags (R1 is counted separately), the list, and per-file the channels that tripped.
   Pre-registered expectation: the 6 known R1+R2 files (2026-06-09 13-20-41, 06-10 09-41-00, 06-11 06-11-20, 06-18 12-46-11, 06-27 08-52-19, 07-23 11-37-24) flag R2; the 3 R1-only files (05-15 22-22-40, 05-23 11-33-05, 06-25 12-28-50) are an OPEN question: report whether
   they flag, no stop. False-positive sets: (a) the 113 manifest-matching hash-verified files, (b) the 333 M323 originals (they are the published-era content), (c) the 43 new drives.
   DECISION RULE (R2 flags only): STOP and send to the Director if (i) any file in the false-positive sets flags R2, or (ii) any of the 6 known files fails to flag R2, or (iii) any R2 flag appears outside the known 9. Thresholds are NOT tuned to make numbers agree.
3. signal_representation: re-running the stage on the same file is a no-op (idempotent, byte-identical JSON); a changed sha256 for a recorded key aborts; a power-failure-style interrupted write leaves the previous file intact (tested like M303 atomic writes).
   Values are written by script only (no typed numbers). A known-answer fixture (hand-checkable 5-row CSV) fixes grid_step, max_decimals and cadence.
4. Isolation: drive_master.csv, summary_arrays.json, raw/ and raw_manifest.json byte-identical before and after (MD5 verified); ingest_core fail-closed behaviour and the TOCTOU guard unchanged (existing tests/synthetic/test_plausibility_gate.py must still pass untouched, plus new tests).
5. Release gate (`python release_check.py`) green; CHANGELOG entry via tools/changelog_draft.py; docs/script_index.md updated.
Review: blind reproduction of rules 1-2 by analytical-auditor (Sonnet, high) from the written rule text and the raw/ directory only; Director spec review BEFORE implementation and decision after. Andrii confirms the amendment text at the PR (gate amendments need his sign-off).
Out of scope: R3 (current multiple-of-0.5 A; rejected in Amendment 1), grid-change auto-quarantine, retroactive application, repairs of any kind.

## Director changes applied (rev 2, 2026-10-02)
One R2 flag with a channels list (tests assert exact rule lists); per-channel tested/untested status and partial-check reporting; the 3 R1-only files are an open question, not 'verified' coarse; decision rule counts R2 flags only and stops on any R2 flag outside the 9;
false-positive sets = 113 hash-verified + 333 originals + 43 new; sidecar commit point after the master write, fail-closed sha conflict with a documented `--supersede` path, byte-identical reruns, schema_version, header fingerprint;
optional additions adopted: decimals histogram and 0.1-grid share, gate verdict/version, timestamp column named; residual false negatives stated.
