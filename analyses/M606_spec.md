# M606 spec (Rev 1 after Director review; Rev 0 written before any code or result): ambient and thermal provenance, coverage and dropout flags (independent audit, roadmap row "Ambient and thermal provenance")

Status: Rev 1, 2026-11-07 (section 0 supersedes any conflicting clause below). Owner request: Andrii, chat 2026-11-07 ("continue"). Source: `xtrail_epower_independent_audit.pdf`, roadmap page 12: "Add timestamped
source, freshness and per-channel dropout flags. Report outcome and coverage by month/cadence and keep engine coolant, HV coolant and intake air separate."
Already implemented (audit): manual ambient ledger, four probes, supported warm-up and right-censoring checks. This milestone adds provenance and coverage only.
No new estimator, no change to any thermal class, cohort or published figure, no `drive_master.csv` write.

## 0. Rev 1 (Director REVISE, frozen; supersedes conflicting clauses below)
Checked on disk: the raw files are sparse-wide (one or a few PIDs per row; e.g. `raw/2026-09-22 11-55-57.csv`: 16,734 rows, 62 valid HV-battery intake-air samples, 77 HV coolant, 123 engine coolant,
615 engine intake air), so a row-based valid share would flag every drive. Coverage is therefore defined on time.
R1. Coverage on time: drive span = first to last timestamp of any PID (pipeline time parser, midnight crossing handled, duplicate timestamps collapsed). Bins = consecutive 10 s bins from the first
    timestamp. `coverageShare` = share of bins that contain at least one valid sample of the channel. Raw `nValid` and the native median inter-sample interval (per channel, per stratum) are kept.
R2. Edges count: `leadGapS` (drive start to first valid), `trailGapS` (last valid to drive end) and interior gaps all enter `longestGapS`; a channel that stops mid-drive is caught. Flags: absent,
    empty, partial (coverageShare < 0.5), gappy (longestGapS > 60 s with coverageShare >= 0.5), ok. Gap thresholds are not cadence-invariant: counts are reported per cadence stratum and never pooled;
    sensitivities coverage 0.25 / 0.75 and gap 30 / 120 s.
R3. Windows (primary = the pipeline's own): HV battery intake air -40..90 (`col('T_intake', -40, 90)`); engine coolant -40..150 (`col('T_coolant', -40, 150)`, the M418 basis); HV coolant -40..120
    (`sane_max('T_coolant_max', 120)` upper bound, lower bound -40). Sensitivities: v6 bounds (-40..200) and the Rev 0 bounds (130 / 100). Out-of-window values are counted separately
    (`nOutOfWindow`, `nSentinel100` = value -100) so that empty (not logged) and sentinel-only are told apart.
R4. Reconciliation with `meta.intakeAir`: ordered by (date, time_start), not by date alone; same population (all master rows); `nValid > 0` is defined as the master does (`T_intake` not null).
    Any mismatch STOPS the tool (zero tolerance).
R5. Population = master rows only. `e4ORCE_*` and `comparison_only` files in `raw/` are excluded; a test asserts that the processed count equals the master row count.
R6. Outcome = the M418 `hvcEngine80C` classification, reused unchanged (`tools/thermal_support_ledger.raw_record`): accepted drives are `reached` (coolant >= WARM_ENGINE_C, 80 C) or `right-censored` (not reached);
    drives excluded by the rule (distance_km > 0, >= 1 valid coolant sample, class in CLASS_ORDER) are `not eligible`, with the reason carried. No cold-start gate: a warm restart counts as reached at about
    0 min (the rule's own statement). Outcome counts by month x stratum are shown with this rule named.
R7. Source class of the manual ledger lives only in the untracked `ambient_samples.json`. The payload and the sidecar never read it: the block states "source class not in the committed ledger"; the committed
    protocol (`tools/ambient_protocol.py`) is the source for the reading kinds. A test guards against any untracked input.
R8. Channels, all separate: HV battery intake air, engine coolant, HV coolant, and engine intake air (`Температура повітря, що всмоктується (℃)`, window -40..90, exploratory, never combined with the HV
    intake channel). The logger ambient PID `Температура оточуючого повітря (℃)` is coverage-only (not an ambient source).
R9. Display: the Thermal-tab line binds to `S.thermalProvenance` keys; its intake-air numbers must equal the M361 Overview line (semantic-gate check).
R10. Added tests: sparse-wide fixture, midnight crossing, the -100 sentinel, duplicate timestamps, edge gaps, same-day drive-order reconciliation, population/e4ORCE exclusion, cache-key determinism, no
    untracked input. Language-gate rule M606 forbids: "measured ambient", "fresh"/"stale" for the manual ledger, "sensor failure", "outage cause".

## 1. Question
How complete and how fresh is the temperature information each drive's thermal results rest on? Descriptive: which channel was logged, when did it drop out, how
many ambient readings did the driver record and with what time information, and how do outcome counts (reached / right-censored / not eligible) distribute over
month and logging cadence. It makes no claim about thermal behaviour.

## 2. Definitions (frozen here; every count is script-written)
Channels, kept separate and never combined: engine coolant (`Температура охолодної рідини (℃)`), HV coolant (`[VCM] HV Coolant Temperature (℃)`), HV battery intake air
(`[BMS] HV Battery Intake Air Temperature (℃)`; the pipeline's `T_intake`, NOT engine intake air). The logger ambient PID is reported as coverage only (its provenance text
already states it is too sparse to use) and is not an ambient source.
Per drive and channel, from the raw bytes (cached by raw sha256):
- `columnPresent` (header exists), `nValid` (numeric, finite and inside the pipeline plausibility window: engine coolant -40..130 C, HV coolant -40..100 C, intake air -40..90 C;
  the intake window is the pipeline's own `col('T_intake', -40, 90)`; the other two are pinned here and the audit checks them), `validShare` = nValid / n_raw_rows,
  `longestGapS` = longest run between consecutive valid samples (timestamp difference, seconds), `firstValidS` (seconds from drive start).
- Dropout flag (non-exclusive, descriptive): `absent` (column not logged), `empty` (column present, nValid = 0), `partial` (0 < validShare < 0.5), `gappy` (longestGapS > 60 s while
  validShare >= 0.5), `ok` otherwise. Thresholds are analysis bands, pre-registered, not fitted; sensitivities 0.25 / 0.75 and 30 / 120 s are reported.
- Channel epoch per channel: first and last drive date with `nValid > 0`, and the number of drives after the last valid date (reconciles to `meta.intakeAir` for intake air, zero tolerance).
Manual ambient ledger (`summary_config.json` `ambientByDrive`, driver-recorded dash readout): per drive `nReadings` (1 / 2 / 3+), kind (single / start-end pair / trapezoid), and
`timesInferred` = true for every reading (reading times are inferred, not logged; the committed ledger holds no timestamps). Freshness (age of a reading relative to the drive)
therefore cannot be observed and is reported as "not observable (inferred times)", never as a number. The source class (`vehicle_sensor`, `vehicle_uncalibrated`) is read from the
ledger/protocol and counted; drives with a legacy single value are counted separately.
Outcome coverage: per drive the status under the existing M418 warm-up rule(s) (`tools/thermal_support_ledger.py` classification: reached / right-censored / not eligible), reused
unchanged. Month = calendar month of the drive date; cadence stratum = `cadence_regime.csv` (fast / slow / unknown), never pooled.

## 3. Population
All 632 master drives with a raw file (canonical-clean flag reported beside, not used to drop rows: provenance covers every logged drive). Drives that cannot be read are counted.

## 4. Method and outputs
- Sidecar `thermal_provenance_sidecar.csv` (per drive: date, month, stratum, raw sha256, per-channel columnPresent / nValid / validShare / longestGapS / flag, nReadings, kind).
- Payload block `thermalProvenance` (additive): per channel the epoch and flag counts; per month x stratum the drive and day counts, flag counts per channel, manual-ledger kind counts and the
  outcome-status counts; sensitivities (validShare 0.25 / 0.75, gap 30 / 120 s). Counts only; no rate is tested, no interval is required (a descriptive share carries n drives and days).
- Display (pre-registered): ONE short table or line in the Thermal tab of channel epochs (first / last valid date, drives after the last valid date, flag counts) and one sentence on the manual
  ledger ("reading times inferred; freshness not observable"); the month x stratum matrix stays in the payload and `analyses/`. No new tab, no collapsible.

## 5. Known-answer tests (`tests/synthetic/test_thermal_provenance.py`, written before the tool)
1. validShare and flags on a hand-built series: absent / empty / partial / gappy / ok each reached; window edges inclusive (-40, 90 for intake) and NaN or out-of-window never valid.
2. longestGapS on a series with a known 75 s hole; a hole of exactly 60 s is not gappy, 60.1 s is.
3. Epoch: last valid date and drives-after count on a synthetic list (zero valid -> epoch undefined, counted as empty).
4. Manual-ledger kind from 1 / 2 / 3 readings; legacy single value counted separately.
5. Month x stratum aggregation: totals over cells equal the totals over drives (zero tolerance); strata never merged.
6. Reconciliation: intake-air nDrivesValid, nDrivesNoValue, lastValidDate and nDrivesAfterLastValid equal `meta.intakeAir` (zero tolerance).

## 6. Accept / reject
Accept if: tests pass, the intake-air epoch reconciles with `meta.intakeAir` exactly, a blind audit (claim + raw path + this spec, no author code) reproduces the per-channel epochs, flag counts
and month x stratum drive counts exactly, Director go. Reject / keep in analyses only if the Director judges the Thermal-tab line not worth the space. Falsification wording: a failed reconciliation
means "not established", never a silent adjustment.

## 7. Language and scope
"Logged", "driver-recorded", "inferred reading times"; never "measured ambient", never "fresh" or "stale" for the manual ledger (unobservable); dropout is a logging fact, not a sensor-fault finding; no
thermal conclusion. Not article-bound. HVAC state and a real timestamped ambient source need a new logging convention and driver input and are out of scope.
