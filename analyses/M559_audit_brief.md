# M559 blind audit brief (analytical-auditor)

Task: reproduce, from the RAW CSV only, four per-second engine-context fields and the candidate labels for 58 short windows. You are blind to the author's code and results.
FORBIDDEN files (do not open): `tools/engine_context_fields.py`, `tests/synthetic/test_engine_context_fields.py`, `analyses/M559_check*.json`, `ecf_cache/`, `analyses/M559_spec.md`, `summary_arrays.json` key `engineContextFields`, `STATE.md`, `CHANGELOG.md`.
Allowed: this brief, `analyses/M559_audit_sample.json` (list of windows: file, stratum, category, startTime, endTime), the raw CSVs in `raw/` (file name `2026-10-13 20-04-05.csv` for master name `20261013_200405.csv`), and general repository code that does not belong to this milestone.

## Grid (identical for every window)
Columns (original names): rpm `Оберти двигуна (rpm)`; boost `Розрахунковий наддув (bar)`; load `Розрахункове значення навантаження на двигун (%)`; current `[BMS] HV Battery Current (A)` (charge-positive in the raw file: use I = -raw so that DISCHARGE is positive); SoC `[BMS] HV State of charge (%)`; speed `[VCM] Vehicle Speed (km/h)` (if it has fewer than 100 non-null samples use `Швидкість автомобіля (km/h)`); fuel rate `Витрати палива (L/h)`; coolant `Температура охолодної рідини (℃)`.
Convert the `time` column to timestamps (clock time, roll over midnight), take the 1 s mean of each column (`resample('1s').mean()`), forward-fill at most 3 s. COOLANT IS NOT FORWARD-FILLED ON THE GRID: for each grid second use the last NON-NULL raw coolant sample at or before that second, and its age in seconds.

## Fields for every grid second of a window with rpm > 400 (engine rotating); other seconds have no field values
- rot: `low` rpm < 1000; `mid` 1000 <= rpm < 2000; `high` rpm >= 2000.
- flow (I discharge-positive): `discharging` I > 2 A; `charging` I < -2 A; `neutral` |I| <= 2 A; `unknown` I missing.
- thermal: `unknown` when no coolant sample exists or its age is greater than 30 s; else `cold` coolant <= 60; `warming` 60 < coolant <= 80; `warm` > 80 (degrees C).
- comb: `no_signal` when the file has no boost column or no load column, or boost is missing at that second; `motored` boost < -0.70; `fuelled` boost >= -0.55; otherwise `ambiguous`.
- fuelFlag: the fuel-rate 1 s mean is > 0 (false when the fuel column is absent or is zero throughout the file).
- lowLoad: load (missing counted as 0) < 8.
- spin: true if an engine start or stop (rpm crosses 400 between consecutive grid seconds, either direction) lies within 3 s before or after this second.
- Labels (non-exclusive): `generation_net_charge` = comb fuelled AND fuelFlag AND load >= 8 AND flow charging; `generation_with_pack_discharge` = the same support AND flow discharging AND speed > 5 km/h; `thermal_context` = thermal is cold or warming; `dissipation_candidate` = comb motored AND lowLoad AND rpm >= 2000 (strictly rpm > 2000 in the legacy rule; report the second where rpm is exactly 2000 separately) AND NOT spin.
- A second with no label is `unresolved`.

## Return
A JSON file `analyses/M559_audit_result.json` (written by you, from your own script `audit/m559_audit.py`): for each window the per-second table summary: counts of each rot / flow / thermal / comb value, counts of each label, count of unresolved seconds, count of spin seconds, plus any second where you were unsure how to apply a rule. State every rule you found ambiguous. Do not look at or ask for the author's numbers.
