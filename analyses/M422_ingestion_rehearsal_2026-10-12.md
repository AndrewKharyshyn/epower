# M422: ingestion rehearsal and performance profile (2026-10-12)

Measured data: `analyses/perf_profile_2026-10-12.json`. Method: `raw/` already holds 20 new drive exports (2026-10-09 to 2026-10-12, not yet in the corpus). A scratch copy of the repository at `main` (232b894) was ingested end to end with `tools/run_ingest.py --no-journal` (label M999, corpus 554 to 574), to measure stage times and to find what would stop a real ingestion. Python 3.12.10 (not the pinned 3.11), single runs: indicative. The live repository was not touched by the rehearsal.

## A. Ingestion blockers found (a real ingestion would have stopped at each)
| # | Stage | Finding | State |
|---|---|---|---|
| 1 | `ingest_core` | ExposureCoverageError: the arrays build normalises exposure on the rated 5 Ah reference (M415) and needs a sidecar Ah value for every master drive; the sidecar was built by the later `ah_throughput` stage, so 20 new drives had a finite legacy gtc and no Ah | FIXED in M422: `ingest_core` builds the sidecar (incremental, staged raw, manifest written first) before the arrays build; sidecar files added to the rollback list; the stage stays as an idempotent re-check |
| 2 | `leaf_guard` | 728 of 743 reported lost leaves were the M419 stamp fields: the arrays build recreates every stamp and `stamp_basis` only ran inside `restamp_ingest`, after the guard | FIXED in M422: stage `stamp_basis` before `leaf_guard` (728 -> 0) |
| 3 | `leaf_guard` | the 15 remaining losses are data-driven (shoulder-cohort class entries, `serialDependence` row lists, `dataQualityNote.corpusTotalKwh`) | OPEN, normal: acknowledgement rules at the real ingestion (M377a pattern) |
| 4 | `restamp_ingest` | `STAMP_POLICY` has no entry for the block `exposureBasis` (M415) and, more importantly, NO stage refreshes it: its populations, the factor (1.1587), the legacy-basis values of the switched headlines and `primaryExposure` are corpus-dependent and were spliced once from two control builds | OPEN: needs a design (refresh stage; the legacy values come from a legacy-basis build or from the builder's pinned legacy path) before the next ingestion |
| 5 | `build_ambient_table` | the owner-recorded ambient readouts (`summary_config.json` `ambientByDrive`) of the 20 new drives are missing (gate working as designed; the readouts must exist BEFORE `compute_seasonal`, otherwise the seasonal master marks them unavailable) | OPEN: owner input |
| 6 | `gtr_family_refresh` | Director stop: "simultaneity: a share moved by more than 5.0 pp" with the 20 new drives | OPEN, normal: Director decision at the real ingestion |
Not reached in the rehearsal: `restamp_ingest` onward (policy entry, CI anchor `verify_import --expect-master-md5`, `release_check`).

## B. Where the time goes (one ingestion of 20 new drives, about 4,036 s = 67 min if the segments are added)
`ingest_core` 1,467 s (36 %), `refresh_raw_seasonal` 1,020 s (25 %), `release_check` 280 s (7 %, last full run), `refresh_master_seasonal` 219 s, `record_spread_fit` 212 s, `gtr_closure_refresh` 109 s, `gtr_family_refresh` 109 s, `fuel_analytics2` 107 s, `raw_temp_pass` 82 s, `fuel_analytics` 61 s, `jsdom` 47 s, the remaining 25 stages 3 to 46 s each. The four largest stages are 68 % of the total.

### Arrays build (inside `ingest_core`; cProfile, 1,956 s under the profiler)
- Parsing and loading dominate by count: 21,991 frame-cache loads for 574 drives (38 per drive: every builder reloads every frame; zlib decompress 55 s, crc32 33 s, pickle 127 s cumulative), 4,371 raw `read_csv` calls (135 s), time-string parsing (strptime 65 s, `datetimes.__iter__` 93 s over 11.9 M items).
- Per-row pandas in a few builders: `_buffer_impulse_events` 275 s cumulative (3,175 calls; 3.8 M `DataFrame.__getitem__`), `fixed_interval_self_transition` inside `_engine_dwell_survival` 205 s (`resample().agg(lambda)`, 880 k Python calls), `_start_event_chain` 186 s, `_thermal_fuel_penalty` 153 s, `_ramp_latency_events` 138 s.
- `refresh_raw_seasonal` repeats the same builders for the all / warm / shoulder cohorts (37 charts x 3 calls, sequential, plus the parity guard), so these costs are paid again there.

## C. Candidate speed-ups (not done; each needs bit-parity against the published payload)
1. Process pool over charts and cohorts in `refresh_raw_seasonal` (12 cores; the builders are deterministic): no change to the standing rule that seasonal data is recomputed at every ingestion.
2. One in-process frame memo per run (frames loaded once per drive, copied or treated read-only): removes most of the ~215 s of cache decompression and pickle, in both stages.
3. Vectorise the three or four per-row builders above (numpy; known-answer tests plus the existing parity guards).
4. Fast gate tier for `release_check` (280 s).
The per-drive content-keyed cache that needs the amendment of the standing rule is NOT required for 1 to 3.
Expected gain (an estimate, not a measurement): tens of minutes per ingestion; to be measured per step against the 4,036 s baseline above.
