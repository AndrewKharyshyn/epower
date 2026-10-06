# M385 spec (Rev 1): dependency-aware skipping of an unchanged ingestion run (opt-in)

Status: Rev 1. Origin: audit 2026-10-05 pp.22, 25-26 ("A genuine no-change run should validate cheap integrity and return without recomputing unchanged raw-derived domains"; "Do not skip a global fit merely because its per-drive inputs were cached"). Feasibility row: `analyses/audit_2026-10-05_feasibility.md` (dependency-aware skips: SPEC).

## Facts (read from disk, 2026-10-06)
- `tools/ingest_stages.json` has 31 stages and NO declared inputs (`outputs` only); most stages read and rewrite `summary_arrays.json`, so stage-level skipping on per-stage inputs cannot be made safe without reading every stage script (not done here).
- Run history (`runs/*/status.json`): the last full 524-drive ingestion spent 2,389 s in `ingest_core`; the stages after it ~1,300 s; the gate tail (`build_html`, `jsdom`, `release_check`, `state`) ~300-470 s.
- `run_ingest.py` has no run-level change detection; a run with no new raw file still executes every stage.

## Design (conservative, run-level)
Skip ONLY when the whole run would repeat on bit-identical inputs. `tools/run_fingerprint.py` hashes, as separate components: all sources (root and `tools/`: `.py .js .jsx .sh`), the stage list, the dependency lock (`requirements.pinned.txt`, `package-lock.json`), `analyses/` (specs, pins, records), the declared stage outputs (exact state the previous run left; the rendered dashboard excluded: rebuilt every run), `drive_master.csv`, `raw_manifest.json`, the raw file listing (name, size), and the environment (Python, package versions, `XT_*` variables except `XT_RAW_DIR`). The fingerprint is recorded in `runs/last_green_fingerprint.json` only after a FULL, fully executed, green run (no `--only/--from/--skip`, nothing skipped).
`run_ingest.py --skip-unchanged`: if the fingerprint equals the ledger, every stage except `preflight`, `build_html`, `jsdom`, `release_check`, `state` is recorded as `skipped_unchanged` (with the reason); otherwise everything runs and the reason names the changed components. Default behaviour (no flag) is unchanged. A skip never applies to partial runs.
Never skipped: integrity (`preflight`), rendering and gates. Global fits are inside the skipped set only because their inputs, code and outputs are all identical; a change to any of them runs the whole chain (no per-stage partial reuse; that needs declared stage inputs and is out of scope).

## Out of scope
Per-stage input declarations and partial rebuilds; a cache of per-drive features across runs; atomic staged release (F20); worker pools.

## Acceptance
- `tests/synthetic/test_run_fingerprint.py`: no ledger -> run all; equal -> skip exactly the non-gate stages; a change in any one component (source, tools source, analyses, output, master, manifest, raw listing, lock, environment, stage list) prevents the skip and is named; dashboard rewrite does not; restoring the input re-enables the skip.
- Measured in a scratch copy of the repo (no-new-files, pinned-environment caveats stated): cold full run (all stages), then `--skip-unchanged` run; report wall seconds per stage, and confirm the skipped run leaves every declared output byte-identical.
- `release_check.py` green; no change to any published value; CHANGELOG `M385`.

---
# Result (measured 2026-10-06 in a scratch copy of the repo at main a25f2cb, no new raw files; Python 3.12.10, numpy 2.4.4, pandas 3.0.2: NOT the pinned 3.11 environment)
- Cold run (`run_ingest.py`, all 31 stages): result ok, 2,330 s (38.8 min); largest stages: `refresh_raw_seasonal` 690 s, `release_check` 271 s, `fuel_analytics` 242 s, `refresh_master_seasonal` 228 s, `record_spread_fit` 218 s, `fuel_analytics2` 144 s, `gtr_closure_refresh` 141 s, `gtr_family_refresh` 104 s. The fingerprint ledger was written after it.
- `--skip-unchanged`: fingerprint equal -> 26 stages `skipped_unchanged`; `preflight`, `build_html`, `jsdom`, `release_check`, `state` ran and passed; 291 s wall (about 8x less than the cold run); `release_check` is now 90 % of it.
- Every declared stage output is byte-identical before and after the skipped run except `xtrail_dashboard.html` (rebuilt every run, excluded from the fingerprint by design).
- A real ingestion (new raw files) always changes the raw listing and the master, so it never skips; any source, spec, lock, output or environment change also prevents the skip (tests/synthetic/test_run_fingerprint.py).
- The cold run is the first fully green no-new-files ingestion; it required M383a (time-parse date regression, M377_PIN import) and M384 (parity guard) first.
Limits: single run per mode, one machine; timings are indicative, not a benchmark. Opt-in only (default behaviour unchanged).
