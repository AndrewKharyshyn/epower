# M417 spec (Rev 1): pinned replay of drive_master.csv from the raw drive files (audit F11, owner decision 2026-10-12)

Status: tooling and verification milestone (no figure, payload, dashboard or master change). Branch `claude/next-milestone` from `main` (6b5786b, M416). Origin: deep audit 2026-10-11 F11 ("publication replay unverified"; `release_check.py` printed "NOT COVERED: raw CSV -> drive_master.csv rebuild"), FEASIBILITY.md row F11, owner direction 2026-10-12 ("F20/F11 - OK", read as the recommendation: a pinned replay package on the frozen ML state, not a claim of full reproducibility from raw).

## Scope: what is replayed and what is frozen
- **Raw-derived columns** (functions of one raw file and the versioned builder, `compute_drive_summary_v6.analyze_bytes`): replayed per drive.
- **Master-level columns** (`postprocess_master` over the corpus, which REFITS the machine-learning columns): the replay applies the same freeze/restore as an ingestion (`tools/ingest_core.py`): the 16 ML/domain columns (ML16) of pre-existing rows are restored from the published master, the Huber adjustment is re-applied, and everything else is compared. The ML16 values are therefore inputs of the replay, not outputs: the replay does NOT verify them, and says so. The clean-room refit of the ML columns (differs from the published values) stays an open item (`master_refit_audit.py`, `masterRefitAudit.json`, last run on 446 rows).
- **Manual or repaired columns** that no builder produces (the distance-repair ledger: `distance_endpoint_raw_km`, `distance_reset_repaired`, `distance_source`) are listed as published-only and are not replayed.

## Two tiers (`tools/replay_master.py`, never writes the master)
- **Sample tier (seconds; in CI and in `release_check.py`):** the pinned stratified sample `analyses/replay/replay_sample.json` (24 drives, seed 417, every drive type and every month of the corpus; the raw files equal `raw_manifest.json` sha256, tested) is rebuilt with `analyze_bytes`; every column the builder produces (64-157 per drive) must equal the published master (numbers to 1e-9, strings, flags and null patterns exactly). No exception is registered. Measured 2026-10-12: 0 differences.
- **Full tier (about 1 minute with 10 workers on this machine; on demand and before a release that touches the builder):** all 554 rows rebuilt, postprocess, ML16 restored, Huber adjustment, compared through CSV text with the published master. Measured 2026-10-12 (Python 3.12.10, numpy 2.4.4, pandas 3.0.2, scipy 1.17.1, sklearn 1.8.0, Windows): **178 of 186 shared columns identical**; 8 differ, all registered in `analyses/replay/replay_expected.json` with reasons and caps:
  - distance repair of one reset-odometer drive (`20260906_122920.csv`, trip-meter repair, 2.94 km): `distance_km`, `net_draw_per100km`, `net_draw_per100km_corr`;
  - the frozen two-pass current offset (published constant -0.3834 A on all rows; a refit on the current corpus differs in the fourth decimal, <= 3e-4 A): `I_offset_2p_A_applied` and, following it, `offset_2p_kwh_removed`, `net_draw_kwh_corr2p`, `energy_residual_kwh_corr2p` (<= 4e-4 kWh) and `net_draw_per100km_corr2p`.
  Anything outside the registered columns, more rows, a larger difference or another file fails (`check_expected`, tested with known-answer mutations).
- Every report records the environment (python and package versions), the code hashes, the raw-manifest sha256 and the published master MD5, so a report is tied to one master state. `release_check.py` prints whether the last full report is for the current master (STALE otherwise; informational, not a failure: the full tier is on demand).

## Non-goals and limits (disclosed)
- Not a statement that the published master is "reproducible from raw data" (CLAUDE.md wording rule): the ML16 columns and the frozen offset are inputs. Allowed wording: "all raw-derived columns reproduce from the sha256-verified raw files with the versioned builder; the ML16 columns are a frozen historic fit restored from the published master; the two-pass offset is frozen at the last acknowledged recalibration".
- The replay environment (Python 3.12 on Windows) differs from the one that originally built the master (earlier audits: Python 3.11.15); the identical result is evidence of environment-insensitivity for these columns, not a proof.
- The summary payload (`summary_arrays.json`) is not replayed here: its control builds (M414/M415) take about 25 minutes and compare against a second build, not against the raw files.
- The sample is 24 of 554 drives; the full tier covers all.

## Acceptance
Sample tier 0 differences; full tier only the registered differences; negative controls and mutations fail as expected; `release_check.py` and CI green; CHANGELOG `M417`. The Director's review of this scope is not required (verification tooling; the wording restrictions above follow the standing Director wording of 2026-09-29/10-02).
