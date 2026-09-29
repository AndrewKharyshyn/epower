# F03 sensitivity: fresh raw->master rebuild from today's raw/ vs published drive_master.csv (2026-09-29)
Produced by master_refit_audit.rebuild/compare (clean-room, drive_master.csv not modified), 446 rows, file set identical.
- `refit_today_vs_published.json`: column-level comparison. Today: 70/186 columns identical, 116 drifted. M293 baseline (original-era raw): 162/186 identical, 24 drifted.
- `per_file_drift.json`: drive -> drifted columns (all 446 drives drift in >=1 column, dominated by the known ML-refit columns and the corpus-level offset-derived `_corr` columns; per-drive counts are not a measure of provenance alone).
- 92 columns drift now that did not at M293 (energy/charge splits, peaks, cell spread, accel, odo...) = raw-content effect.
- Aggregate effect on corpus sums (published -> fresh): gross_throughput +0.004%, gross_discharge +0.01%, gross_charge -0.002%, gtc +0.004%, fce +0.004%, distance_km -0.03%, net_draw_kwh -0.20%, energy_residual_kwh -0.35% (sums over 446 drives).
- Canonical exclusion sets differ: ens_invalid / ens_outlier_v2 2 -> 3 drives (1 only in fresh), ens_extreme 24 -> 27. ESCALATE to Director (may change the canonical-clean population).
- Not done: per-headline-key delta vs published day-clustered CI (needs the headline KPI list in tools/kpi_paths.json and a fresh arrays build from the fresh master, ~35 min).
Language: this is "provenance sensitivity", not a correction.
