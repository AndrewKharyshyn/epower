# M780 spec: "Battery Temperature - Observed Range" (Thermal tab): ambient axis over the whole observed range, sub-zero-safe extrema and axis (descriptive, display and payload binning)

Rev 1. Committed BEFORE any result of this milestone exists. Owner request (Andrii, chat, 2026-11-27): "Verify if Battery Temperature - Observed Range section is stale as it still shows Cool ambient (<20 C). The dataset already has near-zero temperatures and will soon have sub-zero ones. So this chart should be updated to include all temperature ranges."

## 0. Verified state (read from the repository, nothing recomputed)
- `S.batteryTempRanges` (`compute_summary_arrays.py` `_battery_temp_ranges`, M51/M213) has three fixed ambient rows: "Cool ambient (<20 C)" (edges -99 to 20; 439 of the drives with a recorded ambient, battery Sensor-1 extrema 1 to 49 C), "Mild ambient (20-26 C)", "Hot ambient (>=26 C)". The recorded ambient spans below 0 C (the audit saw -15 to 32 C); the cool row therefore mixes near-freezing and 19 C drives, and the thermal cohort view already separates Cold, Shoulder and Warm.
- `lo = int(min(mins))` and `hi = int(max(peaks))` truncate toward zero: identical to floor for non-negative values, but for a negative value `int(-2.7) = -2` hides part of the range.
- The JSX plot `TempIntervalPlot` draws from 0 to `max` (x = v / max), the shared scale is `max(50, hi)`, ticks start at 0: a negative value would be drawn left of the plot. The prose under the chart says "the median peak rises steadily across the three ambient bins" (typed, would be stale with other bins).

## 1. Constraints
- Descriptive only: observed extrema, median and interquartile range of the per-drive Sensor-1 peak; no inference, no temperature effect. Ambient is a manual per-drive field (mean of the recorded start and end pair, as before). Only drives with a recorded ambient enter the ambient axis (n < total drives by construction).
- `drive_master.csv` (MD5 `d514d6009d6d9a0a168ad4fb09b9bb98`) unchanged; the class, duration and record rows keep their values; only the ambient rows and the extrema convention change (additive splice of the `batteryTempRanges` key, deep-diff guarded).
- Language: "recorded ambient", "Sensor 1 (the hottest of the four pack probes)", observed extrema; no "typical", "optimal", "safe", no causal reading; the corpus record callout unchanged.
- Not an article figure; the Opus audit and Andrii's sign-off rule applies if it ever becomes one.

## 2. Definitions (frozen)
- Ambient axis: bins of 5 C width anchored at 0 C, half-open [a, a+5), on the mean of the recorded [start, end] ambient pair (`_ambient_reader().mean_reading`, unchanged). Rows are created for every bin that holds at least one drive, from the lowest to the highest observed bin: no -99/99 catch-all, no merged ends, no bin dropped for low support (the section shows observed extrema, which a support floor does not gate). Each row carries `n` (drives); a row with fewer than 5 drives is labelled "few drives" in the chart and the table. Labels are generated from the edges: "-5 to 0 C", "0 to 5 C", ..., "25 to 30 C". Row order: coldest first.
- Extrema: `lo` = floor of the minimum over the group of the per-drive Sensor-1 minimum, `hi` = floor of the maximum of the per-drive Sensor-1 peak (floor, not truncation toward zero: identical to the published values for every non-negative value, correct for negative values). `medPeak` keeps `int(round(...))` semantics; `p25Peak` and `p75Peak` unchanged.
- The class, duration and record groups are computed exactly as before.
- Chart axis: one shared scale for all panels from `floor(min(lo)/10)*10` to `ceil(max(hi)/10)*10` (at least 0 to 50 as before), ticks every 10 C including negative ticks, a dashed 0 C line labelled "0 C" whenever the scale spans zero; a value below zero is drawn left of that line. The scale is computed from the payload, not typed.
- Prose under the chart is generated: the ordering sentence about ambient bins is stated only from the payload (whether the median peak rises across the displayed bins, counting the bins with at least 5 drives; otherwise "no ordering is stated"), never typed.

## 3. Decision rules
- D1 (fidelity): every non-ambient row and every non-negative extremum is byte-identical to the published block (isolation diff: only the three old ambient rows are replaced by the new ambient rows; `S.sensorSummary` untouched).
- D2 (coverage): the sum of the ambient rows' `n` equals the number of drives with a recorded ambient (the total of the old three rows, checked by the tool); the old "Cool ambient (<20 C)" count equals the sum of the new bins below 20 C and its extrema equal the min and max over those bins (consistency check); the old mild and hot rows (edge at 26 C, not a 5 C edge) are not reproduced and are not compared.
- D3 (sub-zero): the tool is tested with a planted negative minimum (extrema, bin edge at 0 and at -5, exact edge value placed in the upper bin) and the JS chart test draws a negative value left of the 0 C line.
- D4 (language): wording passes `language_gate.py`; no new rule is needed unless the gate flags; the ordering sentence is generated.
- Falsification: the section is "not stale" only if every observed ambient bin appears and the scale spans every observed value; a value outside the drawn scale falsifies it.

## 4. Gates
Known-answer test (`tests/synthetic/`), splice tool with isolation diff and idempotence, blind audit (claim and data paths only) reproducing every ambient row (n, lo, hi, medPeak, p25Peak, p75Peak) from the raw files and the recorded ambients, JS view test, jsdom, semantic gate, `release_check.py`, Director decision on the labels and the generated sentence, CHANGELOG with this spec's sha256, dashboard shown to the owner.

## 5. Out of scope
The class, duration and record rows; the other Thermal sections; any change to the ambient recording rule; any inference.

## 6. Questions for the Director
(a) Are 5 C bins from the lowest to the highest observed bin the right replacement for the three fixed bins, or should the rows follow the thermal cohort classes (Cold, Shoulder, Warm)? (b) Is the "few drives" label (n below 5) enough, given that extrema from a single drive are fragile? (c) Is the generated ordering sentence acceptable? (d) Does flooring the extrema change anything the project treats as published?

## 7. Rev 2 (Director review of Rev 1: decision "revise", five changes, all adopted; where it conflicts with sections 0 to 3 this section wins; written BEFORE any result exists)
Rev 1 file sha256 before this section: 5c7f8fae97d762a90e537d457996ec85420077740102633d91c5d3dcb1044706.
1. Section 0 correction: the per-drive `t1_min` and `t1_peak` are already `int(round())` values (`compute_summary_arrays.py` `_battery_temp_traj`), so `int()` of a group extremum and `floor` give the same value for every published row. The floor is a defensive change that moves no value; the "-2.7" example does not occur. Rounding stays per drive, unchanged. D1 (byte-identical non-ambient rows and non-negative extrema) holds by construction.
2. Edge closure: bins stay half-open [a, a+5) and labels show it ("0 to <5 C", "-5 to <0 C"). The project's thermal regime is Cold at temperature at or below 5.0 C, Shoulder above 5.0 and below 15.0, Warm at or above 15.0 (`seasonal_core.classify_thermal_regime`): a drive recorded at exactly 5.0 C is Cold but sits in the "5 to <10 C" row; the chart note says so, and each ambient row carries the regime of its lower edge as a tag (Cold below 5, Shoulder from 5 to below 15, Warm from 15, read from the same thresholds, not typed). These rows are NOT cohort counts (the cohort uses the drive-mean ambient and the regime override). The known-answer test includes drives at exactly 5.0, 15.0, 0.0 and -5.0.
3. Each ambient row carries `n` (drives) and `nDays` (distinct calendar days) and prints both.
4. A row with fewer than 5 drives is labelled "few drives" and draws no interquartile box; a row with one drive draws a single point labelled "single drive". Extrema keep no support floor.
5. The note under the chart says: extrema come from the unfiltered master (all drives with a recorded ambient, M51), not from the canonical-clean set; ambient is the mean of the recorded start and end pair.
6. Generated ordering sentence, strict rule: stated only if the median peak is strictly increasing across consecutive displayed rows that each have at least 5 drives and at least 3 days; any tie or reversal, or fewer than two such rows, gives "no ordering is stated". Wording: "the observed median peak is higher in each successive row (descriptive, no interval)"; never "rises with ambient" as an effect.
7. Not typed: the cohort tags come from `seasonal_core` thresholds, the scale from the payload. Risk noted: recorded ambients are mostly integers or half degrees, so many drives sit exactly on an edge and the closure convention moves counts between rows.
