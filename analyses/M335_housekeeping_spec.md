# M335 housekeeping: retire unused tracked files (pre-registered plan)

Scope: remove tracked files with no consumer; no figure, payload, gate or pipeline behaviour changes.

Retire (git rm): `_det1/`, `_det2/` (8 files; test artefacts of `test_seasonal.py` t15), `ambient_samples_backup.json`,
`energy_flows_per100km_backup.json`, `energy_mc_precompute_backup.json`, `mc_corpus_backup.json`, `sensitivity_backup.json`,
`m294_patch.py`, `kpi_ci.py`, `kpi_ci3_extract.py`, `kpi_ci3_splice.py`, `kpi_ci_splice.py`, `kpi_ci_splice2.py`, `chart_registry.json`.

Keep (explicitly): `apply_m284_post.sh`, `patch_m284_data.py`, `m295*`/`m296*`, `m297_comparison_cube.py`, `soc_patterns.json`,
`f01_perdrive_correction.csv`, `highspeed_130_runlength_check.csv`.

Verification rules:
1. Consumer scan (grep outside `analyses/`, `CHANGELOG.md`, generated artefacts): the only live consumer is `test_seasonal.py` t15 (`_det1/_det2`);
   it is first moved to `tempfile.TemporaryDirectory()` and re-run (114 passed, 0 failed with PYTHONUTF8=1).
2. sha256 and size of every retired file recorded before removal: `analyses/M335_retired_files_manifest.json` (recoverable from the base commit).
3. `drive_master.csv` MD5 unchanged (bd9d1072...); `release_check.py` green; CHANGELOG `M335` entry.
Stop condition: any consumer found outside the allowed set, or any gate change, aborts the removal.
