# M308 spec (DRAFT, needs Andrii's sign-off before implementation): input-plausibility gate for NEW drives
Origin: Director decision on M307 (2026-09-30). Purpose: prevent silently ingesting corrupted or precision-reduced exports (F03 mechanism candidates).
Scope: NEW raw files only, at ingestion (`tools/ingest_core.py`, before analyze_bytes). Never applied retroactively to the published master (that would be a method change needing its own spec).
Thresholds fixed now, before any new data is seen:
1. Cell-voltage range: any non-null value of a cell-voltage column (`Max/Min Cell Voltage`, `G* Cell Voltage`) outside [2.5, 4.3] V -> flag.
2. Quantisation: minimum positive difference between sorted distinct cell-voltage values >= 0.05 V -> flag (published-era files use 0.001 V).
3. Precision loss: every value of `peak`-relevant current column (HV battery current) is a multiple of 0.5 A while the published-era columns carry finer resolution -> flag (rule refined in the implementation with a known-answer test on the 6 known-affected files and on hash-verified files).
Action on a flag: the file is quarantined (not ingested), listed in the ingest report with the reasons; nothing is repaired or edited; Andrii decides.
Tests: known-answer on (a) the 6 drives with 0.1 V quantisation and a 53.0 V value (must flag), (b) hash-verified files (must pass), (c) synthetic values just inside/outside each threshold.
Escalation: any flagged file goes to the Director before any decision to ingest it.
