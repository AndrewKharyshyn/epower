# M568 blind audit brief (analytical-auditor)

Task: from the RAW CSVs, reproduce for each drive in `analyses/M568_audit_sample.json` (17 drives, `files[].file` = master name e.g. `20260619_122407.csv`; raw file in `raw/` has a space between date and time, e.g. `raw/2026-06-19 12-24-07.csv`) the drive's PEAK DISCHARGE POWER sample, the pack temperature (Sensor 1, "T1") at the nearest logged sample, and the timing tier. You are blind to the author's code and results.
FORBIDDEN (do not open): `tools/power_peak_temp.py`, `tests/synthetic/test_power_peak_temp*.py`, `tests/synthetic/test_ac_view_tiers.py`, `tests/synthetic/test_od_power_note.py`, `analyses/M550_check*.json`, `analyses/M567_*`, `analyses/M568_check*.json`, `powerpeak_cache/`, `summary_arrays.json` keys `powerPeakTemperature`, `cRatePointsAK`, `officialDisclosureCorrelation`, `STATE.md`, `CHANGELOG.md`, `analyses/M550_audit_*`. Allowed: this brief, the sample, the raw CSVs, and the master's loading helpers in `compute_drive_summary_v6.py`: `_prep_bytes(csv_bytes)` -> (df, t), `_series(df, t, name, lo=, hi=)`, `_asof(left, right, col, tol)`, constants `V_ALIGN_TOL`. Set `PYTHONUTF8=1`, `XT_RAW_DIR`. Your earlier script `audit/m567_audit.py` may be reused for the loading.

## Definitions
Frame e (as the master builds it): I = `_series(df, t, "I")` filtered to |v| < 900; V = `_series(df, t, "V", lo=200, hi=450)`; e = `_asof(I, V, "V", V_ALIGN_TOL)` rows with V present, in time order; Id = -v (charge is NEGATIVE Id, discharge positive); P = Id * V / 1000 (kW; discharge positive).
Peak discharge power sample = the row of the MAXIMUM P (the first row in time order among exactly equal maxima). Report its timestamp `tPeakDis`, the maximum `maxP` (kW, rounded to 0.1) and the number of rows tied at the maximum.
T1 = `_series(df, t, "T1", lo=-40, hi=90)` sorted by time. T1 at tPeakDis = the NEAREST native T1 sample in time (no interpolation; if two samples are equally near take the earlier); signed age = T1 sample time minus tPeakDis in seconds; report that sample's value and age irrespective of distance (null if the drive has no T1 samples).
Tier by absolute age: cotimed <= 1.0 s, nearby <= 3.0 s, late <= 10.0 s, none otherwise (boundaries inclusive).

## Return
Write your own script `audit/m568_audit.py` and the result `analyses/M568_audit_result.json`: per drive `{tPeakDis, maxP, nTies, T1Nearest, ageSignedS, tier}` full precision, plus every rule you found ambiguous. Do not look for or ask for the author's numbers.
