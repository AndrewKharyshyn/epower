# Conventions of record (M546)

Written from the code (no figure in this document). Purpose: a blind auditor can be given this text instead of the code and still reproduce the engine-on blocks exactly. Each convention names its code location. Code location names are searched, not line numbers.

## 1. Engine-on rule
Engine-on = logged engine speed (`eng_rpm`, app-reported, not measured) strictly greater than 400 rpm. NaN is never engine-on. The closed band [300, 400] rpm is reported separately as the low-rpm rotation band. Stored (legacy) blocks keep the gate 300 (`ENGINE_ON_STORED_RPM` in `compute_summary_arrays.py`, kernels in `tools/engine_on_blocks.py`); the rule siblings (`...Rule` payload keys) use 400. The regeneration proxy keeps its own 300 (owner decision (g)); the engine-start detector keeps the name 'RPM onset (> 300 rpm, run >= 2 s)'.

## 2. Raw column handling (pipeline, `_RawAccum.add`)
1. Speed source: `_apply_speed_priority` resolves ONE speed column: the native VCM channel ('[VCM] Vehicle Speed (km/h)') if it carries at least the minimum number of non-null samples, otherwise the OBD-generic channel. The resolved series replaces the VCM-named column before the rename map is applied.
2. Per-column native forward fill, limit 15 rows (`col()` in `_RawAccum.add`): `to_numeric(errors='coerce').ffill(limit=15)`; one filled value therefore covers up to 16 rows of a sparse PID. Plausibility masks after the fill: speed 0 to 260, rpm >= 0 (negatives to NaN), SoC 0 to 100, voltage 200 to 450, temperatures per channel.
3. Time stamps: `fast_time(df['time'], mixed=True)` (drive_raw_cache); rows with unparseable time are dropped from the grid frame.

## 3. The pipeline 1 Hz grid (`hz` in `_RawAccum.add`)
Built from the native-filled columns (section 2): index = time, `resample('1s').mean()`, then `ffill(limit=15)` on the grid. The resample bins are floors of the ABSOLUTE clock second (not of the time since the first row); the aggregator is the MEAN of the native values inside the bin ('last' is the sensitivity aggregator of M542: last value of the natively filled series per bin). A grid second without any value after the 15 s hold is NaN. NaN = not on. Grid blocks (engine-on run lengths, `rpmDistribution`, `engineOnRule`) use this grid; they do not use native rows.

## 4. Native-row blocks
Native-row blocks use the native-filled rows of section 2, not the grid:
- `engineOnBySpeed`: a zone total counts rows with a valid speed AND a valid (forward-filled) rpm; engine-on counts rows of that total with rpm above the gate. Zones by speed (km/h): 0-20, 20-40, 40-60, 60-80, 80-100, 100-120, 120 and above.
- turbo blocks: only engine-on rows with a valid boost value are counted. Active boost = boost > 0.1 bar. Negative boost values stay in the count `n` (they are valid values); the maximum boost is floored at 0.0. rpm bands (>= lo, < hi): below 1500, 1500-2000, 2000-2500, 2500-3000, 3000-3500, 3500-4000, 4000 and above. Speed zones (km/h): 0-40, 40-60, 60-80, 80-100, 100-120, 120-160.
- `hvcTurboActivity`: per drive type, engine-on rows with a valid boost value; a drive without such rows contributes nothing (null entry when the class has none).
- Native-row figures are shares of logged samples at the native cadence, NOT time-weighted (M521).

## 5. The state-machine grid (`_esm_grid`, a DIFFERENT grid)
Raw rows read through the frame loader (columns restricted to the state-machine set), speed priority applied, `resample('1s').mean()` and then `ffill(limit=3)`; no native forward fill. Rows with NaN rpm are dropped before classification; a drive needs at least 20 rows and 20 classified seconds. State limits: off, low (400 to 1400), loadPoint (1400 to 2300), mid (2300 to 3200), high (3200 and above); the lower limit of 'low' is `>=` 400 for the stored block and `>` 400 for the Rule sibling (`strict_off`); the other limits are `>=` in both. The pooled occupancy comes from the row sums of the transition matrix, which exclude the last classified second of each drive. `engineDwellSurvival` re-uses the classifier with its default (stored boundary).

## 6. The onset-detector grid (`tools/engine_start_rate.py`, `build_hz`)
Native forward fill (limit 15) on the used columns, then `resample('1s').mean()` and `ffill(limit=15)` again on the grid (the fill is therefore applied twice; the second fill is load-bearing and can bridge gaps of about 15 to 30 s). On = rpm above the detector gate with NaN as off; a start is a run of at least 2 s (`MIN_ENGINE_START_S`). The detector of record uses 300; the count-only sensitivity uses 400 and is never displayed.

## 7. NaN policy per block
Run lengths and grid shares: NaN breaks a run and is not counted as valid time. Native-row blocks: a row needs the valid variables of that block. State machine: NaN rpm rows are dropped before classification (a gap is not a state). Onset detector: NaN is off.

## 8. Intervals and identifiers
Calendar day is the resampling cluster; day-clustered percentile bootstrap, seed 42, 4000 draws; shares are ratios of sums, run-length quantities are pooled medians. Fewer than 5 calendar days: exploratory, no interval reading. Drive keys are `drive_master.csv` file keys; the raw file matches by the digits of the name; `raw/` holds the sha256-verified originals (M366).

## 9. Additions after the M546 audit (gaps the blind auditor reported)
- Column: the engine speed is the raw PID 'Оберти двигуна (rpm)' (renamed to `rpm` on the state grid, `eng_rpm` in the pipeline).
- Resample origin: the 1 s bins are floors of the ABSOLUTE clock second of the time stamp (a bin never starts at the first row of the drive).
- State grid, negative values: no negative-rpm mask is applied on the state grid (a negative value is classified 'off'); the pipeline grid sets negative rpm to NaN.
- State sequence: after the rows with NaN rpm are dropped, the sequence is the remaining seconds in order. Transitions t to t+1 and spells are counted over THIS dropped sequence, so two seconds that were separated by a gap of dropped rows are adjacent (a gap is bridged, not a state).
- Drive eligibility on the state grid: at least 20 rows with a valid rpm and at least 20 classified seconds (every remaining second is classified).
- Per-drive off share used by the bootstrap: the off seconds divided by the classified seconds of the drive (the occupancy fraction of that drive); the interval is the day-clustered percentile bootstrap (calendar day) of the median over drives.
- Pooled-share denominator: the pooled occupancy of a state is the row sum of the transition matrix of that state divided by the total of all row sums; the row sums exclude the last classified second of each drive (it has no outgoing transition).
- Cohort membership: a drive belongs to the warm, shoulder or cold cohort by the `thermal_regime` column of `seasonal_drive_master.csv`; drives with another label are in the all-drives view only. A cohort view is computed over the drives of that label only.

## 10. Additions after the second blind pass (conventions the auditor had to choose without a claim)
- Time stamps are time-of-day only (HH:MM:SS.fraction, no date): they are parsed by `fast_time` and unwrapped by `clock_unwrap.unwrap_clock` (M467): one day is added at each backward step larger than 12 hours (midnight rollover); a smaller backward step is left untouched. Rows with an unparseable time are dropped from the grid frame.
- Bin mean: the 1 s mean skips NaN native values inside the bin (pandas default); a bin with no value is NaN.
- Empty seconds: the resample index is regular from the first to the last bin, so a second without any native row exists as a NaN row on that index before `ffill(limit=3)`; the hold can bridge such seconds (up to 3). A second still NaN after the hold is dropped from the state sequence (section 9).
- Exactly 400: float equality of the bin MEAN with 400.0 (a bin averaging several native values counts only when the mean equals 400.0).
- Median dwell: a dwell is the length of a maximal run of one state in classified seconds (the dropped sequence, section 9); the median is the plain median of the run lengths of that state within the scope (mean of the two middle values for an even count).
- Self-transition of a state = diagonal count / row sum of the transition matrix (no smoothing); null for an empty row.
- Column: of the rpm columns of a raw file, the engine speed is the PID named in `_ESM_COLS`; a second 'x1000 (rpm)' column exists in some files and is not used.
- Eligibility: a drive with fewer than 20 valid-rpm rows or fewer than 20 classified seconds is not part of the block (a per-drive output can still be written with an eligible flag).
