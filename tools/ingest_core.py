#!/usr/bin/env python3
"""Ingestion core (protocol steps 1-5) - NOT YET IMPLEMENTED.

Deliberately fails loudly (exit 3, stage status 'not_implemented') instead of guessing APIs. Implement in the first Code
session by reading the real signatures with grep (do not read whole files), following docs/workflow-and-tools.md:

 1. Archive the 16 ML/domain columns of drive_master.csv -> analyze_bytes(csv_bytes, filename) for each NEW raw file
    (compute_drive_summary_v6.analyze_bytes; canonical 'file' key form 'YYYYMMDD_HHMMSS.csv') -> append + sort by
    (date, time_start) -> postprocess_master(dm) -> restore the 16 ML columns byte-exact for pre-existing rows (0/16 diffs
    required; abort otherwise). Never call run_pipeline().
 2. csa.build_summary_arrays(dm, loader, with_raw=True, raw_dir=RAW, prev_arrays=<current summary_arrays.json>,
    recompute_energy_mc=True, recompute_m119v2=False, odometer_km/seasonal_cfg/ambient_by_drive/session_cfg from
    summary_config.json as run_pipeline does), frame_loader/raw_loader from drive_raw_cache.py.
 3. crosscheck_vehicles.inject() and crosscheck_events.inject() (both MD5-assert drive_master.csv unchanged).
 4. corpus_manifest.build() (use a clean raw_only/ directory: 446 canonical + 2 comparison + 9 e-4ORCE, masters excluded;
    corpus_manifest._classify has a known e4orce_master/ambient misclassification).
 5. determinism_check.py regeneration written to BOTH summary_config.json.auditMetadata.determinism AND
    summary_arrays.json.determinism in the same step.
Then seasonal recompute (compute_seasonal.py -> seasonal_drive_master.csv/seasonal_arrays.json; cohort_arrays.py;
speed_split.py; battery_temp_extremes.py; refresh_gtr_headline.py after `fuel_recon.py --all`), which apply_m284_post.sh
partly covers - reconcile the order against that script.

Requirements: writes only the intended files; asserts drive_master.csv MD5 changes only by the appended rows; exits 0 on
success. Also emit tools/ingest_core_report.json (new files, rows before/after, MD5 before/after, ML16 diffs).
"""
import sys
sys.stderr.write("ingest_core: not implemented (see module docstring)\n")
sys.exit(3)
