# M561 blind audit brief (analytical-auditor)

Task: from the RAW CSVs, reproduce for each drive in `analyses/M561_audit_sample.json` (22 drives, field `files[].file` = master name, e.g. `20261013_200405.csv` = raw `raw/2026-10-13 20-04-05.csv`) the highest mean power observed over a window of length W with no change of power direction, W in {5, 10, 30, 60, 120} s, both directions. You are blind to the author's code and results.
FORBIDDEN (do not open): `tools/power_duration_uninterrupted.py`, `tests/synthetic/test_power_duration_uninterrupted.py`, `analyses/M561_check*.json`, `duration_cache/` files starting `u561_` or `_u561`, `summary_arrays.json` key `powerDurationUninterrupted`, `STATE.md`, `CHANGELOG.md`. Do NOT open `tools/power_duration.py` or `analyses/M552_*` (the net-mean estimator) either: you must implement the window kernel yourself. Allowed: this brief, the sample file, the raw CSVs, and the pairing helper only: `tools/energy_packets.py` function `pair_stream(df, t)` after `compute_drive_summary_v6._prep_bytes(csv_bytes)` (returns ts seconds, P kW with discharge positive, |I| A). Set `PYTHONUTF8=1` and `XT_RAW_DIR`.

## Definitions
Power P(t): piecewise linear between the pair-stream samples (ts, P). A raw step greater than 5 s is a GAP: it ends the segment; nothing is bridged and no window spans a gap. A segment is a maximal chain of samples with steps 0..5 s (duplicate timestamps allowed; they carry no time and make P jump).
Runs: inside a segment, a DISCHARGE RUN is a maximal interval on which P >= 0; a CHARGE RUN is a maximal interval on which P <= 0 (work with q = -P and report a magnitude). Closed: P = 0 is allowed inside and at the ends. A strict sign change on an interval of positive length is cut at the linear zero crossing (a zero knot is inserted there). On a zero-duration step (duplicate timestamp) with opposite signs the run ends at that timestamp. A knot with P = 0 whose two neighbours have opposite signs is a run boundary (the run ends or starts at it); a knot P = 0 between same-sign neighbours does not split. Treat -0.0 as 0. A run needs at least two knots; its length is last minus first time.
Window mean over [s, s + W] = (1/W) x the integral of P (a trapezoid per interval, exact for piecewise linear P). A window is admitted only if it lies inside ONE run (of the direction being evaluated).
Per drive, W and direction report:
- `exact`: the exact continuous-start maximum over admitted windows of the window mean (q for charge), over all runs of length >= W. Candidates are the starts at which s or s + W meets a knot, the run ends s = start and s + W = end, and the interior vertices of the piecewise-quadratic window mean (root of P(s + W) = P(s)). If no run has length >= W report `null`.
- `grid`: the same maximum restricted to starts s = run_start + k (k = 0, 1, 2, ... integer seconds, s + W <= run_end), maximum over runs; `null` if no run has such a start.
- `noInterp`: as `exact` but runs are chains of consecutive KNOTS with q >= 0 with no zero knot inserted (a run ends at its last same-sign sample), `null` if none.
- `nRuns`: number of runs with length >= W in this direction.
Also per drive, direction: the list of run lengths (all runs with length > 0).
Drives with a missing pair stream: report `no_pairs`.

## Return
Write your own script `audit/m561_audit.py` and the result `analyses/M561_audit_result.json`: `{file: {W: {dis: {exact, grid, noInterp, nRuns}, chg: {...}}}, "runLengths": {file: {dis: [...], chg: [...]}}}` with full-precision numbers, plus every rule you found ambiguous. Tolerance for the later comparison: 0.01 kW exact and noInterp, 1e-6 kW grid. Do not look for or ask for the author's numbers.
