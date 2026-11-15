# M672 spec (Rev 1.1): N-05 monthly between-drive logged share (descriptive, payload only)

Status: pre-registered before any result is computed. Backlog item N-05 (`analyses/self_audit_2026-11-11/backlog.json`), the analysable part only.

## 1. Question and non-claims
How complete is the logged record, month by month? The table reports, per calendar month, how much of the odometer advance between consecutive logged drives is covered by logged distance, and how many calendar days carry at least one logged drive.

Non-claims. The table is descriptive: counts and sums, no estimate, no interval, no test, no extrapolation. It does not estimate driving outside the logged window, does not estimate parked-state behaviour, and does not change the Overview KPI (total logged km / dash ODO, owner rule 2026-10-03). It reports completeness of the record, not battery condition. A month with no gap is not "complete driving data" (the logger can be off for whole trips; a trip made while the logger was off advances the odometer between two logged drives and is counted as an unlogged gap, but a trip before the first or after the last logged drive of the window is invisible).

Out of scope here (they need new logging or an owner action, so they stay open in N-05): logging parking context (garage or street), a local ambient logger, and the parked-state / chain model. This milestone does not touch them.

## 2. Data
`drive_master.csv` only (corpus anchor MD5 recorded in the block; no raw file is read). Columns used: `file`, `date`, `time_start`, `odo_start`, `odo_end`, `distance_km`. Drives are ordered by (`date`, `time_start`) exactly as `tools/odometer_check.py` does.

Eligibility of a between-drive step (previous drive end to next drive start):
- the step is an odometer-anomaly step when `tools/odometer_check.continuity_anomalies` flags the next drive with R2, R3 or R4 (backward step, reset regime, forward jump over 500 km). Anomaly steps are excluded from the gap sum and counted in `nAnomalySteps` per month with their rule ids. The odometer reset regime of 2026-08-16 is one such step. The master is not edited.
- every other step has gap = `odo_start(next) - odo_end(prev)`; a gap within +-0.05 km counts as 0 (the odometer resolution of the continuity rules); a gap between 0.05 km and 200 km is an unlogged gap; a gap above 200 km and below the R4 limit is listed separately as `nLargeGapSteps` and kept out of the sum (a rule-free large step is a finding to report, never to hide).
- the month of a step is the month of the NEXT drive (the drive that reveals the gap).

## 3. Quantities (per calendar month, plus the whole window)
- `nDrives`, `nDrivingDays` (distinct dates with at least one drive), `nCalendarDays` (days of the month inside the window from the first to the last logged date), `drivingDayShare` = nDrivingDays / nCalendarDays.
- `loggedKm` = sum of `distance_km` of the month's drives; `odometerAdvanceKm` = sum over the month's drives of (`odo_end - odo_start`) for drives without an R1 flag.
- `unloggedGapKm` = sum of eligible gaps of the month; `nUnloggedGapSteps` (count of steps with a gap above 0.05 km); `largestGapKm`.
- `completeness` = loggedKm / (loggedKm + unloggedGapKm), reported as a share with its two inputs beside it; null when the denominator is 0.
- `nAnomalySteps`, `anomalyRules`, `nLargeGapSteps`.
- Window row: the same sums over all drives, with `firstDate`, `lastDate`.
- Reconciliation line (counts only): window `loggedKm`, window `odometerAdvanceKm`, and their difference, so a reader sees how closely the per-drive distance and the odometer agree.

## 4. Support and labels
No interval is drawn, so no resampling rule applies. A month with fewer than 5 driving days is labelled `thin month (fewer than 5 driving days)`; a first or last month that starts or ends inside the window is labelled `partial month`. Neither label hides the row.

## 5. Validity rules (any failure stops the build, nothing is written)
V1 sum over months of `nDrives` equals the master row count. V2 sum of monthly `loggedKm` equals the master `distance_km` sum to 1e-6. V3 each drive appears in exactly one month. V4 the anomaly steps found equal the ledger `odometer_anomalies.json` entries (the existing release gate already requires it). V5 re-running gives a byte-identical block.

## 6. Implementation and tests
`tools/n05_between_drive_logging.py` computes the block `betweenDriveLogging` from `drive_master.csv`, splices it additively into `summary_arrays.json` with the standard stamp, ingestion stage `between_drive_logging` after `seasonal_fits`. Known-answer test `tests/synthetic/test_m672_between_drive_logging.py` on a constructed drive set: planted gaps of 0, 0.04, 3.2 and 150 km, an R2 step, an R3 reset, a 300 km step without a rule flag, a month with 3 driving days, and a month boundary; checks every sum, the label rules, V1 to V5, and determinism.

## 7. Display
None in this milestone (payload only). A display (a monthly table, `ChartWithTable`) is a follow-up that needs the Director's approval of the rendered text, binding to `S.betweenDriveLogging`, and the language gate.

## 8. Risks recorded
R1 the 200 km cut-off is a rule fixed here, not tuned; the count of steps above it is reported. R2 `distance_km` and the odometer advance can disagree (the master repairs some distance resets, column `distance_reset_repaired`): the reconciliation line shows the difference instead of choosing one. R3 the table says nothing about trips before the first logged drive; the Overview KPI (logged km / dash ODO) remains the only statement about that.

## 9. Director review (2026-11-15, verdict revise, minor) and how each change is applied (Rev 1.1)
The Director's required changes override the matching text above where they differ.
1. Name and language: the quantity is the BETWEEN-DRIVE LOGGED SHARE ("bracketed" by two logged drives), never "driving completeness" or "measured unlogged driving"; `drivingDayShare` is the share of calendar days with a logged drive, not days driven. The word "completeness" in sections 1 to 8 is read as this quantity. The block states that gaps contain logger start/stop latency as well as missed trips.
2. Anomaly facts: `odometer_anomalies.json` holds four step anomalies (2026-08-13 R2; 2026-08-16 R2+R3, R3, R4) and one R1 (per-drive, 20260906_122920), not one reset step. V4 compares only the R2/R3/R4 subset with the ledger; R1 is checked per drive.
3. Backward steps in (-0.5, -0.05) km are not R2: counted as `nSmallBackwardSteps` per month, never summed.
4. Steps adjacent to an R1 drive (its `odo_end < odo_start` makes the next gap wrong): flagged `r1Adjacent`, listed separately, excluded from the gap sum.
5. Boundaries: gap in [-0.05, 0.05] km is zero; (0.05, 200] km is an unlogged gap; (200, 500] km without a rule flag is a large gap (R4 starts above 500 km). Inclusive at 200.
6. Gap size classes: gaps under 1 km and gaps of 1 km or more are reported separately (count and km) to separate logger latency from missed trips. The odometer resolution is read from the data (smallest nonzero difference of odometer readings, reported), not assumed.
7. Two bases side by side: `shareDistanceBasis` = loggedKm / (loggedKm + gapKm) and `shareOdometerBasis` = odometerAdvanceKm / (odometerAdvanceKm + gapKm); no single mixed basis is the headline.
8. Validity: V6 step accounting (nDrives - 1 = zero + gap + large + anomaly + smallBackward + r1Adjacent steps); V7 telescoping closure on the odometer scale within each regime segment (sum of odometer advances + gaps = last odo_end minus first odo_start, to 1e-6, per segment between anomaly steps).
9. Optional, adopted: the bridged distance across the reset regime (R4 start minus the last pre-regime end) is reported as a separate unsummed figure.
10. Known-answer test additions: a -0.3 km step, an R1 drive, exact 0.05 and 200 km boundaries, a cross-month gap, and a (date, time_start) tie.

## 10. Implementation record and blind audit (M672, 2026-11-15; Rev 1.2, wording only)
Implemented in `tools/n05_between_drive_logging.py` (block `betweenDriveLogging`, stage `between_drive_logging`) with every Rev 1.1 change. Rules made explicit after the blind audit (no number depends on them in this corpus): a step into or out of an R1 drive is `r1Adjacent`; classification order is anomaly (R2/R3/R4 on the next drive), r1Adjacent, zero, smallBackward, gap under 1 km, gap 1 to 200 km, large gap; a step falls in exactly one class (V6).
Blind audit (`analytical-auditor`, spec + claim + data path only): reproduced, 0 mismatches over 665 drives, 7 months and the window row. Audit concerns recorded in the block `reading`: the two share bases nearly coincide (odometer minus distance is 0.44 km); 7 of 13 gaps are under 1 km (latency or resolution); most of the 1 km or more gap sits in one month; anomaly and R1-adjacent steps hide any unlogged driving there.
Result (window): logged 10738.84 km, odometer advance 10738.4 km, gaps 83.7 km in 13 steps, share 0.9923; the bridged distance across the reset regime is 0.0 km (the odometer returned to the same scale). Descriptive: no Director verdict is needed beyond Rev 1.1; a display needs the Director's approval of the rendered text (section 7).
