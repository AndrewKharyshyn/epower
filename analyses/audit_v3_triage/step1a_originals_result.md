# Step 1a result (2026-10-02, read-only) - 333 originals
Script: tools/originals_recover.py (untracked); report: originals_recovered_report.json. Copies in
`<Investigation>/originals_recovered/` (outside repo and raw/). raw/, raw_manifest.json, drive_master.csv MD5 unchanged.
- 333/333 failing canonical files recovered, sha256 == manifest (sources: 161 exported_records_full.zip, 143 loose, 29 other ZIPs).
- Same headers and same line counts in all 333 vs the raw/ copy; norm-equal in 0 (not an EOL/BOM issue).
- Content differs: raw/ copies carry coarser numeric precision than the originals (e.g. HV current -2.599999999999909 -> -3,
  voltage 353.71 -> 353.7, fuel L/h 154.75 -> 155, odometer 4.655722 -> 4.656). Precision varies by file/column (0/1/3 dp), so this
  is not a uniform round(x,3). Stratified sample (every 6th file, n=56): 1,540,584 differing cells, 100% numeric, 55/56 files with
  differences beyond 3-dp rounding.
- Implication (NOT yet decided): raw/ for these files is a lossy re-export; originals are full precision. Likely explains the 9
  coarse-grid voltage files (C01/F02) and the ML-column drift on fresh rebuild. Whether the published master was built from
  the originals or from raw/ is UNTESTED (step 1b).
Next: 1b stratified reproduction of master/arrays from originals (as M305), Director ruling, Andrii decides re-anchoring.
