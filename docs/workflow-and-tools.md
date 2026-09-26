# Workflow and tools (imported from Claude memory `workflow-and-tools`, last updated 2026-09-22)

Ground truth for state is `python tools/state.py`. Statements here predate M299; where they conflict with disk/CHANGELOG, disk wins.

## Ingestion protocol (each batch)
1. Archive the 16 ML/domain columns -> `analyze_bytes` x N (new files) -> append/sort -> `postprocess_master` -> restore ML16 byte-exact (0/16 diffs required).
2. `build_summary_arrays` with `frame_loader` + `raw_loader` + `prev_arrays` carry-forward + `recompute_energy_mc=True` + `recompute_m119v2=False`.
3. `crosscheck_vehicles.inject()` + `crosscheck_events.inject()` (both MD5-assert `drive_master.csv` unchanged).
4. `corpus_manifest.build()` via the clean `raw_only/` directory workaround.
5. `determinism_check.py` regeneration written to BOTH `summary_config.json.auditMetadata.determinism` AND `summary_arrays.json.determinism` (prevents silent reversion).
6. `build_html.js` -> `validate_jsdom.js` (9/9 tabs, 0 console errors).
7. T-01..T-04 + T-01b acceptance tests.
8. Seasonal data recomputed on EVERY ingestion: `compute_seasonal.py` (`seasonal_drive_master.csv`/`seasonal_arrays.json`/`cohort_arrays.json`), refresh
   `summary_arrays.json.seasonalCharts._meta.cohortCounts` and `generatorTractionRecon`/`seasonalCharts.charts.GeneratorTractionRecon` (`refresh_gtr_headline.py`, after any
   `fuel_recon.py --all`), re-run `speed_split.py` + `battery_temp_extremes.py` (its row-count-match gate silently drops 2 `records` rows if its CSV lags the live corpus).
   `seasonalCharts.charts` has ~50 entries, all with confirmed generators (`category_A(dm)`/`category_B(dm, raw_loader)` cover 30; 16 more are `_xxx(dm, ...)` raw-pass
   functions; `_crawl_stop_go` and `_thermal_fuel_penalty` cost ~150-260 s/cohort and need pickle-checkpointed part1/part2 calls in a time-limited sandbox - not needed on a normal machine).
   Always verify each function's "all"-cohort output byte-exact against its non-cohort top-level `S.*` counterpart (JSON-round-trip both sides first) before trusting a Warm/Shoulder split;
   where no such anchor exists, an exact eligible-row-count match against the pre-refresh basis is the fallback standard.
- Andrii's standing instruction: seasonal data and the `seasonalCharts`-dependent side-scripts (`wire_gtr_seasonal.py`, `refresh_gtr_headline.py`, `battery_temp_extremes.py`, `speed_split.py`) are recomputed on every ingestion.

## Validation chain (per milestone)
`py_compile` -> JSON round-trip -> `build_html.js` (REQUIRED_BLOCKS + M94 stale-key gates) -> jsdom 9-tab click-through (0 errors, 0 semantic warnings) -> isolation diff (only intended keys changed) -> acceptance tests -> `release_check.py` (clean environment, authoritative) -> `semantic_gate.py` (M299).

## Conventions
- CHANGELOG: newest-first, M-prefixed, prepend via concatenation (never a boundary-spanning `str_replace` on a heading). Large insertions: two-step marker-then-body.
- Always prepend a CHANGELOG entry after changes are applied (standing rule; Andrii should not have to ask).
- Corpus-state verification: read from disk (grep CHANGELOG head, `drive_master.csv` rows + MD5, `summary_arrays.json` key count).
- Previously: "present every updated file for download and say if it need not be stored in Project Knowledge". In the repo workflow, git replaces file hand-off: report changed files and commit.

## Pipeline stack
- Python (pinned, see `requirements.pinned.txt`): pandas 3.0.2, numpy 2.4.4, rainflow 3.2.0, statsmodels 0.15.0, scikit-learn 1.8.0, scipy 1.17.1; Python 3.11.
- Node.js / Babel / React 18.2.0, jsdom 22.1.0, `@babel/core`, `@babel/preset-react`, acorn/acorn-jsx (see `package.json`, `package-lock.json`; `npm ci`).
- Headless Chrome (puppeteer) was used for screenshots in the old sandbox; not required for the gates.

## Key files
- Data: `drive_master.csv`, `summary_arrays.json`, `summary_config.json`, `raw_manifest.json`.
- Compute: `compute_summary_arrays.py` (~17.8k lines), `compute_drive_summary_v6.py`, `m119v2_model.py`, `energy_mc_precompute.py`, `energy_uncertainty_mc.py`.
- Dashboard/build: `xtrail_summary.jsx` (~11.5k lines), `build_html.js`, `validate_jsdom.js`, `dump_tabs.js`, `semantic_gate.py`, `release_check.py`.
- Degradation: `degradation_trends.py` (`degradation_trends.json` is an orphaned stale snapshot, never read by the pipeline).
- Caching: `drive_raw_cache.py` (slim frame cache; rebuild ~40-50 s; `raw_cache/` is git-ignored).
- Determinism: `determinism_check.py`, `ml16_determinism_check.py`. (Two copies of `determinism_check.json` existed in Project Knowledge; the repo copy is the newest, 2026-09-25.)
- e-4ORCE rail: `ingest_e4orce.py`, `e4orce_master.csv`, `e4orce_ambient.csv`. Cross-checks: `crosscheck_vehicles.py`, `crosscheck_events.py`, `corpus_manifest.py`.
- Path resolution: `project_paths.py` (env `XT_RAW_DIR`, `XT_PROJECT_DIR`, `XT_WORK_DIR`; cwd containing `drive_master.csv` counts as the project checkout). Some legacy scripts default to `/home/claude/work/...` (`XT_CODE`, `XT_RAW`, `XT_CACHE`): set them or fix when first used.

## Sandbox-era notes that no longer apply
The old chat sandbox had a ~270 s command limit, killed background processes, and read-only `/mnt/project`; chunked passes with pickle checkpoints and `timeout 270` were workarounds. On a normal machine run passes directly (the M119-v2 recompute is ~11 min).
`run_pipeline()` now forwards `raw_dir` (P0-2, 2026-09-11); the earlier "raw_dir not forwarded" finding (M247) is fixed in `compute_drive_summary_v6.py`.
