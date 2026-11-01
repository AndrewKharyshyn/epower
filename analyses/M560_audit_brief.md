# M560 blind audit brief (analytical-auditor)

Task: from the RAW CSV only, reproduce six magnitudes (V0, V1, V3, V6, V7, V8) for 30 cell-spread rest windows. You are blind to the author's code and results.
FORBIDDEN (do not open): `tools/csr_sensitivity.py`, `tools/m560_window_keys.py`, `tests/synthetic/test_csr_sensitivity.py`, `analyses/M560_check*.json`, `analyses/M560_window_keys.json`, `csr_cache/`, `summary_arrays.json` keys `cellSpreadRelaxation` and `cellSpreadRelaxationSensitivity`, `STATE.md`, `CHANGELOG.md`, `analyses/M560_spec.md`.
Allowed: this brief, `analyses/M560_audit_sample.json` (30 windows: raw file, load-off timestamp `key`, stratum, category), the raw CSVs in `raw/` (master name `20261013_200405.csv` = raw `2026-10-13 20-04-05.csv`), and general repository code that is not part of this milestone. Tolerance 1e-9 mV.

## Channels and grid
Columns: `[BMS] Max Cell Voltage (V)`, `[BMS] Min Cell Voltage (V)`, `[BMS] HV Battery Current (A)`, `time` (clock time; roll over midnight). Sample times are the raw row times; a channel value exists only on rows where it is non-empty.
Grid G(fill_mm, fill_i): for each channel the mean of its samples in each whole second (`resample('1s').mean()`), then forward-fill at most `fill_mm` seconds for Max and Min and `fill_i` seconds for the current (limit 0 = no fill). `fresh` = the second holds a real sample of that channel. Published reference grid: fill_mm = 3, fill_i = 3.
Collapsed grid: drop every second where Max, Min or the current is missing AFTER the fill; the remaining rows are then treated as consecutive ROWS (index 0, 1, 2 ...) even if seconds were removed. spread = (Max - Min) x 1000 mV; cur = |current|. All counts below (5 rows, 3 rows, 5 values) are rows of this collapsed grid.

## Window rule (V0, on G(3,3))
A rest run = consecutive rows with cur < 5. A run starting at row i and ending before row j (length j - i >= 5) is a window when pre0 = max(0, i-3) satisfies i - pre0 >= 2 and mean(cur[pre0:i]) >= 20 and at least 5 finite spread values lie in spread[i:j]. onset = mean(spread[max(0,i-1):i+1]) (the last loaded row and the first rest row); asymptote = median of the last min(5, j-i) rest values; magnitude = onset - asymptote. The window is identified by the timestamp of row i (the first rest row) = `key` in the sample file.

## The six quantities per window (the window keyed in the sample on the V0 grid)
- V0: the magnitude above.
- V1: rebuild the grid with fill_mm = 0 and fill_i = 3, detect windows again with the same rule, and return the magnitude of the window with the same `key`, or `absent` if there is none.
- V3: keep the V0 window rows (i, j); replace the spread series by the polling-cycle pairing: pair each Max sample with the first Min sample at or after it and before the next Max sample, if that Min is within 1.5 s; the pair time is the later of the two sample times and the pair spread is (Max - Min) x 1000; take the 1 s mean of the pair spreads, forward fill at most 3 s, align to the V0 collapsed-grid timestamps (missing = NaN) and apply the same onset / asymptote rule (needs >= 5 finite values in the rest). `unavailable` if not.
- V6: report `fresh` (true/false): all of the rows used (the two onset rows and the last up-to-5 rest rows) hold a real sample of both Max and Min in their own second.
- V7: report `strict` (true/false): the timestamps of rows pre0..j-1 are consecutive seconds (no removed second inside).
- V8: native pair level on the same polling-cycle pairs, no 1 s mean: load-off T0 = the timestamp of row i (seconds); end T1 = the timestamp of row j-1 plus 1 s. onset = spread of the last pair whose two members both lie before T0; asymptote = median spread of the pairs with both members at or after T0 and the pair time < T1 and >= T1 - 5 s; magnitude = onset - asymptote; `unavailable` if either set is empty.

## Return
Write your own script `audit/m560_audit.py` and the result `analyses/M560_audit_result.json`: per window the six values (numbers to full precision, or the words above), plus every rule you found ambiguous. Do not look for or ask for the author's numbers.
