# M369 spec: raw-cache and ingest-environment defects found in M366 (handoff item C)

Status: tooling only (Sonnet, medium per the effort table; known-answer test, no blind audit, no Director review: no figure, estimator or payload value changes). Not a method change.

## Defects (confirmed in code this session)
1. `drive_raw_cache.add_missing` defaulted to `verify_md5=False` and kept entries by NAME; `make_frame_loader` never compared the entry's `src_md5` with the raw file, so a changed raw file was served from stale frames (M366: "frames ready in 0.1 s").
2. `tools/regen_seasonal_raw.py` result caches (`catB_*`, `b_*` pickles under `%TEMP%/m341_cache`) were keyed by cohort name, row count and an md5 of the file LIST: a changed raw file (or changed builder code) did not change the key.
3. `tools/run_ingest.py` used `env.setdefault("XT_RAW_DIR", raw/)`: an inherited `XT_RAW_DIR=raw_only` (the staged view omits the two `comparison_only` files) kept winning and failed preflight.

## Changes
1. `add_missing(verify_md5=True)` by default. `make_frame_loader(raw_dir=...)`: an entry whose recorded `src_md5` differs from the md5 of the raw file on disk is treated as missing (like a stale schema), md5 memoised per (path, size, mtime). Without `raw_dir` behaviour is unchanged (documented). `ingest_core.py` and `regen_seasonal_raw.py` pass their raw dir.
2. `drive_raw_cache.content_key(files, code_paths)`: md5 over (file name, recorded raw md5) of every file plus the bytes of the cached code (`compute_summary_arrays.py`, `drive_raw_cache.py`); used for both regen result-cache keys.
3. `run_ingest.py` forces `XT_RAW_DIR=raw/` and prints a NOTE when it overrides a different inherited value; per-stage `env` in `ingest_stages.json` (fuel_recon, fuel_contract) still sets `raw_only` where needed.

## Controls
`tests/synthetic/test_m369_raw_cache.py` (known answers: a changed raw file is not served; default `add_missing` re-adds it; content key changes with a raw-file change and with a code change, is deterministic; an unchanged file is skipped; `run_ingest` source forces raw/). Read-only audit of the real cache: 489 manifest entries vs `raw_only/`: 0 stale, 0 missing sources. `release_check.py`; payload and `drive_master.csv` byte-identical.

## Out of scope / residual
Other loaders (`engine_start_rate.py`, `m356_splice.py`, `m362_splice.py`) call `make_frame_loader()` without `raw_dir` and keep the old behaviour; they run after `add_missing(verify)` in the ingest chain. Passing `raw_dir` there is a follow-up if they are ever run standalone after a raw change.
