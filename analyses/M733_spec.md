# M731 spec: cloud tyre pressure as an auxiliary covariate (descriptive, report-only)

Rev 1, committed BEFORE the study tool was written or run. Disclosure: a one-line exploratory look at 379 drives (rear mean pressure against settled ambient, slope about +0.6 kPa per degree C) was done while answering a chat question on 2026-11-21; it is not used to set any threshold below.

Owner decisions: cloud data is auxiliary, OBD primary; the order of work agreed in chat is clock offset (M730), then tyre pressure. Language: "displayed/logged by the vehicle cloud"; pressure is a proxy covariate, never a measured rolling resistance.

## Data
- M729 store `Vehicle_Information` (four corner pressures, axle cold targets 250/230, ambient) and `System_Safety_Alerts` (wheel-state codes). Corner fields are read as tenths of kPa (raw / 10); this scale is UNVALIDATED until a dash or gauge reading with its time is supplied.
- A snapshot = a timestamp with all four corners non-blank. Drive join = M729 padded window (60 s); minutes into the drive = snapshot time minus drive start.
- Puncture epoch: front-right wheel-state code 2 observations and the 14 Jul 2026 incident; their snapshots (front-right and, to be safe, all corners from the first code-2 time to the first later snapshot with the front-right pressure back within 20 kPa of its earlier level) are excluded from E1-E5 and listed.
- Drive ambient = M729 settled in-drive mean (samples after 180 s); if absent, no ambient is assigned (the snapshot is excluded from E2 only).

## Estimands (pre-registered)
- E1 level: per corner, median and IQR of pressure divided by the axle cold target (front 250, rear 230), and the same for the axle mean. Reading rule: if both axle medians lie in 0.90-1.20 the tenths-of-kPa reading is called "plausible, not validated"; otherwise "scale unresolved". Nothing is called validated without a gauge reading.
- E2 temperature response: ordinary least squares of the drive-level axle-mean pressure (kPa) on settled ambient (degree C) with minutes into the drive as a covariate, separately for front and rear, one snapshot per drive (the last one in the window), day-clustered percentile bootstrap (seed 42, 4000 draws), n drives and n days reported. Reference: ideal-gas sealed-volume slope = (cold target + 101.3 kPa) / (273.15 + 20) per degree C (about 1.1 kPa per degree C); the ratio of the estimated slope to the reference is reported. A ratio well below 1 is expected for late-drive warm snapshots and is not an error by itself.
- E3 steps and epochs: per corner, daily median of the ambient-adjusted pressure (E2 slope applied to a 15 C reference); a step is a change of at least 20 kPa between consecutive days' medians that persists (median of the next five snapshots within 10 kPa of the new level). The count and dates of steps, excluding the puncture window, are listed; these mark inflation, tyre swap or leak candidates, never confirmed events.
- E4 corner asymmetry: median left-minus-right difference per axle with a day-clustered interval; flags only.
- E5 feasibility as a rolling-resistance covariate (counts only, no effect estimate): drives with a snapshot per epoch and month; drive pairs with the same screened start and end positions within 300 m and at least 3 km, with axle-mean pressure difference of at least 15 kPa and absolute settled-ambient difference of at most 5 degrees C. This sizes a later paired comparison of energy per km; it is not that comparison.

## Decision rules
- E2 is reported as supported only if the interval of the slope excludes zero; the sign and the ratio to the ideal-gas reference are always shown.
- Pressure may enter a later model as a covariate only through temperature-normalised or target-relative deviation (never raw), and only after a separate spec; E5 must show at least 30 qualifying pairs on at least 15 days for that spec to be worth writing, otherwise the covariate stays descriptive.

## Out of scope
Rolling-resistance coefficient estimation, energy-per-km effects, payload interaction, and any change to OBD-derived figures. No payload, dashboard or frozen-file change. Outputs: `analyses/M731_tyre_pressure.json` and `analyses/M731_tyre_snapshots.csv`; tool `tools/mynissan_tyre.py`; a blind reproduction is requested after the first run.
