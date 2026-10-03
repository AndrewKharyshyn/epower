# M361 spec (Rev 1): HV battery intake-air temperature outage (T_intake, unavailable since 2026-08-24) - disclosure where it limits a figure

Status: work in progress, Director string review pending. Disclosure + one additive meta block; no calculation change. Owner question (2026-10-03): how does the outage influence the calculations?

## 1. Verified influence map (disk, script-checked this session)
- The raw channel returns a constant -100 degC from 2026-08-24 10:46:12 (CHANGELOG M319). `compute_drive_summary_v6.py` bounds T_intake to [-40, 90], so the sentinel becomes NaN; no -100 enters `drive_master.csv`, any mean, bin or record.
- **Not affected:** thermal cohorts (Warm/Shoulder/Cold are set by `ambient_time_mean_c`, the driver-recorded vehicle ambient readout, never by T_intake); all pack-sensor (S1-S4) statistics; energy, SoC, current, fuel, GTR; the ambient table.
- **Affected, time-limited (valid only up to 2026-08-24):** (a) Battery Thermal Pattern chart: the intake-air line and the pack-minus-intake plateau gap (`batteryThermalMeta.intakeGapPlateauC`) average over pre-outage drives only, while the four pack probes use all drives; (b) `eolBaselines.intakeBelowPackMedianC` (pack mean minus intake air) is a pre-outage, summer/early-autumn baseline; (c) Records row "Battery intake air temperature max" (already carries the M319 sentence); (d) seasonal `pack_engine_thermal_state` T_intake key and `batt_intake_*` columns are censored; (e) `warmupPoints[2]` cold-start flag (T_intake < 30) maps NaN to False = no data, not warm; the key is retained in the payload but no chart displays it (Chart 2 uses the distance-domain warm-up), so no displayed figure moves.
- Consequence for readers: any intake-air-based statement after 2026-08-24 is unavailable, not low or stable; the gap between pack and intake air has not been observed in colder conditions.

## 2. Change
- New script-written block `meta.intakeAir` (extend `tools/refresh_meta_sources.py`, read-only on the master, idempotent, in the post step): `{channel, status ("unavailable" if no valid value after lastValidDate), lastValidDate, lastValidDrive, nDrivesValid, nDrivesNoValue, nDaysAfterLastValid, firstDriveWithoutValue, source:"drive_master.csv T_intake (NaN = unavailable; sentinel -100 degC removed by the -40 bound)"}`. Counts from the master only; the -100 sentinel itself is cited from CHANGELOG M319 (raw-file observation), not recomputed.
- Disclosure sentence bound to `S.meta.intakeAir` in three places: (1) Battery Thermal Pattern caption (intake line and gap rest on the nDrivesValid drives up to lastValidDate; pack probes use all drives; gap unobserved after that date); (2) the sentence that quotes `intakeBelowPackMedianC` (pre-outage baseline); (3) Overview data-health line (one sentence, no figure moves). Wording: "unavailable since <date>", never "low", "stable" or "zero".
- `data_health.json` text: warmupPoints sentence kept.
- Gates: semantic gate A2 REQUIRED (sentence present in the Thermal and Records/Health dumps; numbers equal `meta.intakeAir`), `release_check` post-step presence of `meta.intakeAir`, test `tests/synthetic/test_intake_air_meta.py` (known-answer on a scripted master: NaN tail, valid head, last valid date, counts).

## 3. Out of scope
- Imputing intake air for the outage period (rejected: no independent proxy; would fabricate a channel). Reactivation of the channel is an owner action; when valid data return, `status` flips by script and a gap period is stated.
- No change to cold-start logic; a three-state cold flag is a possible later milestone (unused key today).

## 4. Questions for the Director
1. Three disclosure sites sufficient? Any figure that must be re-labelled beyond these?
2. Block name/shape acceptable, wording constraints?
