# M567 blind audit brief (analytical-auditor)

Task: from the RAW CSVs, reproduce for each drive in `analyses/M567_audit_sample.json` (24 drives, `files[].file` = master name e.g. `20261013_200405.csv` or `2026-10-14_09-29-12.csv`; raw file in `raw/` has spaces instead of the underscore between date and time, e.g. `raw/2026-10-13 20-04-05.csv`) the time and pack temperature (Sensor 1, "T1") at the drive's CURRENT-PEAK charge sample, and the timing tier. You are blind to the author's code and results.
FORBIDDEN (do not open): `tools/power_peak_temp.py`, `tests/synthetic/test_power_peak_temp*.py`, `tests/synthetic/test_ac_view*.py`, `analyses/M550_check*.json`, `analyses/M567_check*.json`, `powerpeak_cache/`, `summary_arrays.json` keys `powerPeakTemperature` and `cRatePointsAK`/`cRatePoints`, `STATE.md`, `CHANGELOG.md`, `analyses/M550_audit_*`. Allowed: this brief, the sample, the raw CSVs, and the master's loading helpers in `compute_drive_summary_v6.py`: `_prep_bytes(csv_bytes)` -> (df, t), `_series(df, t, name, lo=, hi=)`, `_asof(left, right, col, tol)`, constants `V_ALIGN_TOL`, `ENG_ALIGN_TOL`. (Set `PYTHONUTF8=1`, `XT_RAW_DIR`.)

## Definitions
Frame e (as the master builds it): I = `_series(df, t, "I")` filtered to |v| < 900; V = `_series(df, t, "V", lo=200, hi=450)`; e = `_asof(I, V, "V", V_ALIGN_TOL)` rows with V present; then `_asof(e, eng, "eng_rpm", ENG_ALIGN_TOL)` where eng = `_series(df, t, "eng_rpm", lo=0)`; Id = -v (charge is NEGATIVE Id); e is sorted by time (rows in time order; `idxmin` takes the first row among equal minima).
engine-on = eng_rpm (missing treated as 0) > 400. Candidates for the current peak (take every candidate that has at least one row):
- reg: engine-off rows with Id < -30; peak row = row of the minimum Id.
- egc: engine-on rows with Id < -50; peak row = row of the minimum Id.
- dual: tq = `_series(df, t, "target_torque")` asof-joined to e with tolerance "1500ms" (column tq); rows with engine-on and tq (missing as 0) < -15 and Id < -10; peak row = row of the minimum Id.
The drive's current-peak sample = the candidate peak row with the smallest Id (most negative); if several candidates tie on Id take the order reg, egc, dual. Its timestamp is tPeakI. A drive with no candidate row has NO current peak (report null).
T1 = `_series(df, t, "T1", lo=-40, hi=90)` sorted by time. T1 at tPeakI = the NEAREST native T1 sample in time (no interpolation; if two samples are equally near take the earlier); signed age = T1 sample time minus tPeakI in seconds; report the value and age of that nearest sample irrespective of distance (null if the drive has no T1 samples).
Tier by absolute age: cotimed <= 1.0 s, nearby <= 3.0 s, late <= 10.0 s, none otherwise (boundaries inclusive).

## Return
Write your own script `audit/m567_audit.py` and the result `analyses/M567_audit_result.json`: per drive `{tPeakI (ISO string), channel (reg/egc/dual/null), IdAtPeak, T1Nearest, ageSignedS, tier}` full precision, plus every rule you found ambiguous. Do not look for or ask for the author's numbers.
