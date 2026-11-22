# M730 spec: cloud-to-OBD clock offset and speed agreement (auxiliary diagnostic, report-only)

Rev 1, written and committed BEFORE any result of this study was computed. Owner decision 2026-11-21: cloud data is auxiliary, OBD primary. Order of work agreed in chat: clock offset first, tyre pressure second.

## Question
By how many seconds does the cloud displayed-speed series lag the OBD speed, is the lag stable (month, DST, drive length), and does a single global offset do as well as a per-drive offset on held-out days? The result is a documented alignment parameter for later auxiliary joins; it changes no OBD value.

## Data and definitions
- OBD: raw drive CSVs in `raw/` (read-only), channel `Швидкість автомобіля (km/h)` (speed), row time = file date + logger time as Europe/Kyiv; midnight rollover handled. Cloud: M729 store, `SpeedDisplayedValueinkmh`, UTC.
- Eligible drive: master drive with a raw file, at least 8 qualifying cloud samples in the drive window (cloud speed >= 10 km/h, OBD speed valid within 3 s at the shifted time), and cloud speed standard deviation >= 3 km/h over the qualifying samples (a changing waveform; constant-speed stretches do not identify a lag).
- OBD speed is linearly interpolated only between valid observations at most 3 s apart. Offset convention: positive offset compares a cloud value at time t with the OBD value at t + offset.
- Search: integer offsets -60..+60 s. Criterion: median absolute error (km/h) over qualifying matches. Per-drive best offset = argmin; ties go to the smaller absolute offset.

## Estimands (all pre-registered)
1. Pooled best offset over all eligible matches (descriptive).
2. Per-drive best offsets: median, P10, P90 across drives.
3. Global offset estimated on TRAINING days (odd day-of-month) and evaluated on HELD-OUT days (even day-of-month): median absolute error at offset 0, at the global offset, and at each held-out drive's own best offset (the latter is an optimistic bound, reported but not recommended). Swapping the roles of the two day sets is reported too.
4. Stability: median of per-drive best offsets by month, by DST period (before / after 25 Oct 2026), and by drive duration tercile.
5. Uncertainty: day-clustered percentile bootstrap (seed 42, 4000 draws) of the median per-drive best offset; n drives and n days reported with every estimate.
6. Secondary channel (reported separately, never pooled with speed): accelerator opening against OBD pedal D at the speed-selected offset, median absolute difference in percentage points at offsets 0 and the global offset.
7. Sensitivity for later boundary classification: +-30, +-60, +-120 s are the pre-registered padding sensitivities; this study reports the share of drives whose best offset falls within +-30 and +-60 s.

## Decision rule
- Adopt a single global offset `d` as the recommended auxiliary alignment if the held-out median absolute error at `d` is lower than at 0 and within 0.25 km/h of the same-split per-drive-best bound, and the month-wise medians stay within +-5 s of `d`.
- Otherwise do not adopt a global offset; report the per-month values and recommend per-drive alignment only where the waveform gain is clear.
- A DST shift of about 3600 s would indicate a time-zone handling error in the join, not a lag; that is reported as a defect, not an offset.

## Language and scope
Cloud speed is "displayed/logged by the vehicle cloud"; the offset is an estimate with a CI, not a known constant; the lag mixes acquisition, export and sampling differences. No change to any frozen output, payload or figure. Tooling: `tools/mynissan_clock_offset.py`; outputs `analyses/M730_clock_offset.json` and `analyses/M730_clock_offset_drives.csv`. A blind reproduction is requested after the first run (analytical-auditor, definitions in words only).
