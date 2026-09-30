# M308 spec (APPROVED by Andrii 2026-09-30; implementation pending): input-plausibility gate for NEW drives
Origin: Director decision on M307 (2026-09-30). Purpose: prevent silently ingesting corrupted or precision-reduced exports (F03 mechanism candidates).
Scope: NEW raw files only, at ingestion (`tools/ingest_core.py`, before analyze_bytes). Never applied retroactively to the published master (that would be a method change needing its own spec).
Thresholds fixed now, before any new data is seen:
1. Cell-voltage range: any non-null value of a cell-voltage column (`Max/Min Cell Voltage`, `G* Cell Voltage`) outside [2.5, 4.3] V -> flag.
2. Quantisation: minimum positive difference between sorted distinct cell-voltage values >= 0.05 V -> flag (published-era files use 0.001 V).
3. Precision loss: every value of `peak`-relevant current column (HV battery current) is a multiple of 0.5 A while the published-era columns carry finer resolution -> flag (rule refined in the implementation with a known-answer test on the 6 known-affected files and on hash-verified files).
Action on a flag: the file is quarantined (not ingested), listed in the ingest report with the reasons; nothing is repaired or edited; Andrii decides.
Tests: known-answer on (a) the 6 drives with 0.1 V quantisation and a 53.0 V value (must flag), (b) hash-verified files (must pass), (c) synthetic values just inside/outside each threshold.
Escalation: any flagged file goes to the Director before any decision to ingest it.

## Sign-off
Andrii approved the policy and thresholds above on 2026-09-30 ("Approve"). F03 remains OPEN (not reclassified). Implementation is the next milestone (M308) and must pass the known-answer tests listed before any ingestion.

## Amendment 1 (2026-09-30, before any new drive is ingested; from the corpus scan of existing files, analyses/M308_corpus_scan.json)
Two deviations from the approved text, both forced by data; flagged to Andrii in the M308 report:
1. R1/R2 apply to the single-cell columns `[BMS] Max Cell Voltage (V)` / `[BMS] Min Cell Voltage (V)` only. `G01..Gnn Cell Voltage` are two-cell GROUP voltages (G01 ~ 7.4-8.2 V, present from mid-August); applying [2.5, 4.3] V to them flags every file from that date, including all 113 hash-verified files. R2 additionally requires >= 5 distinct values (guards tiny files).
2. R3 (all current values multiples of 0.5 A) is NOT implemented: 415 of 446 corpus files, including 105 of 113 hash-verified files, have every current value at a 0.5 A multiple, so it is the normal resolution and the rule would quarantine everything. No discriminating precision rule exists in the available data; the peak_I 0.5 A differences remain a hypothesis about altered copies, not a gateable property.
Result on the existing corpus (informational, the gate is not applied retroactively): 9 of 441 checked files flag (3 R1 only: 53.0 V value; 6 R1+R2: 0.1 V quantised + 53.0 V), all 9 hash-failing, 0 of 113 hash-verified flag.
Action on a flag (implemented): `tools/ingest_core.py` stops the WHOLE ingestion (fail closed), writes nothing, reports status `quarantined` with the flags (exit 1).

## Full-chain validation (2026-09-30, scratch copy, held-out real drive 2026-09-22 22-14-10)
`tools/run_ingest.py --from ingest_core` (ingest_core, stage_raw, compute_seasonal, fuel_recon, refresh_gtr_headline, post_steps): all stages ok (ingest_core 35 min; the rest < 2 min). Rebuilt master MD5 == published 0bcfc400..., 0/16 ML diffs, 0 pre-existing-row diffs, plausibility gate 1 file checked / 0 flagged / 0 unchecked, top-level arrays keys identical to the published file. Expected consequence disclosed: `records` grows 39 -> 41 rows because battery_temp_extremes.csv (published copy stale at 410 rows) now covers the whole corpus and the two battery-temperature-minimum rows are no longer silently omitted. Not covered by this run: build_html / jsdom / release_check on the ingested output, cohort_arrays.
