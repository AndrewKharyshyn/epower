# M472 spec (pre-registered): cohort support display, leave-one-day-out and boundary sensitivity (audit 2026-10-21, "Seasonal logic: support matters more than a label")

Status: NEW additive payload block `cohortSupport` (descriptive support accounting, no new inference). Gates: this spec, blind audit (analytical-auditor, claim + data path only), Director (presentation, flags, escalation rule). Owner decisions respected: the M426 boundary reassignment (2026-10-10_06-57-23.csv, ambient mean exactly 5.0 C, cold -> shoulder) is NOT reversed; the displayed cohorts are unchanged; the physical-threshold classification is an additive sensitivity beside it.

## Motivation (audit, confirmed on disk)
Cold = 13 drives on 5 days but 183.0 of 201.6 km (90.77 %) come from one drive (2026-10-14). Counts alone make the cohort look better supported than a distance-weighted contrast is. A bootstrap over 5 days does not create independent winter exposure.

## Definitions (all computed by `tools/cohort_support.py` from drive_master.csv, seasonal_drive_master.csv, fuel_recon_master.csv; nothing typed)
Cohorts by the ASSIGNED class `thermal_regime_raw` (after the M426 reassignment, before the support gate): all, warm, shoulder, cold. For each: drives, days (distinct `date`), km, hours (`duration_s`).
- largest drive: file, km, share of cohort km. Largest day: date, km, share.
- effective drives = 1 / sum_j s_j^2 and effective days = 1 / sum_d s_d^2 with s the km shares (the weights of the distance-weighted metrics).
- display flags (documented display thresholds, NOT identified limits): `dominatedByOneDrive` when the largest-drive share >= 0.5; `fewEffectiveDays` when effective days < 5.
- metrics (canonical-clean eligibility, `eligibility.py`): `grossKwhPer100km` = sum(gross_throughput_kwh) / sum(distance_km) x 100 over canonical-clean drives with an energy integral; `fuelLPer100km` = distance-weighted mean of `fuel_L_per_100km` over canonical-clean drives of fuel_recon_master. Each metric reports value, drives, days, km.
- leave-one-day-out (LODO): the metric recomputed without each single day; min, max, the days giving them, and the relative range (max - min) / value; also the metric without the largest drive.
- boundary sensitivity: for cold and shoulder, the same support fields and metrics under the PHYSICAL class (`thermal_regime_physical`, threshold class before any reassignment) next to the assigned class, the list of reassigned drives (file, date, ambient mean, km, assigned, physical) and the differences. No drive is reclassified in the displayed cohorts.

## Dashboard
A compact "Cohort support" table in the cohort/seasonal area: per cohort drives, days, km, largest-drive and largest-day share, effective days, the two flags, and per metric the value with its LODO range; the boundary-sensitivity line. Wording (language gate): 'descriptive support accounting, not an interval'; cold stays 'exploratory'; never 'validated', 'robust' or 'winter inference'.

## Tests (known answers)
(1) synthetic cohort where one drive holds 90 % of km: share, effective drives (about 1.2), flags; (2) two-day cohort with known LODO values; (3) the live block reproduced independently from the CSVs; (4) physical vs assigned lists equal on every drive except the one override; (5) additive splice writes only `/cohortSupport` and its stamp.

## Escalation
Blind audit reproduces every field from the CSVs. Director: confirm the flags/thresholds as display conventions, the metric choice, and the rule that a displayed cell changing its support status after a future ingestion goes to the Director (M446 O7 analogue). No article figure; no CI is attached because nothing here is an estimate of a population quantity.

## Addendum: blind audit and Director ruling (recorded in the CHANGELOG M472 entry)
- Blind audit (analytical-auditor, claim + data path only, own script): every item reproduced to 4 decimals (cold, shoulder, physical cold/shoulder, the single discordant drive). Concerns taken: cold is effectively one trip (labelled a single-trip descriptor, exploratory); LODO is descriptive, not an interval; the two metrics use different eligible sets (n shown per metric); values depend on the owner override (physical sensitivity shown).
- Director ruling: ACCEPT. Conditions met: each cold metric is shown only beside its leave-one-day-out range and its value without the largest drive; no cold-versus-other comparison; n (drives, days, km) per metric; flags are display conventions that never gate, hide or reweight data (changing 0.5 or 5 is a spec change needing the Director); language rule `M472-cold-single-trip`; no article figure.
- Escalation rule after each ingestion (to the Director): (a) any cohort's flag changes; (b) warm or shoulder effective days fall below 5; (c) cold drops both flags; (d) the list of reassigned drives changes; (e) the cohort assignment of a drive already in the corpus changes; (f) a warm or shoulder metric value leaves its previous leave-one-day-out range. Cold LODO changes are logged, not escalated, while the cold flags stay true.
