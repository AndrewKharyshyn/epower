# M517 spec (Rev 1): per-class supported engine-on rate with its interval and bracket (follow-up of M512; Director follow-up list)

Status: Rev 1, written 2026-10-26 BEFORE any M517 computation. Origin: the M512 Director decision listed "show the per-class supported rate with its interval" and "the class table and the conclusion line do not show the per-class supported rate with its interval or the bracket" as deviations/follow-ups. Reporting extension of the `engineRuntime` block (M512 spec Rev 2 R1-R9 stay in force); no estimand, population or time base changes.

## Question
For each drive class (urban, mixed, mixed_highway, highway): how many hours was the engine on inside RPM-supported intervals, what is the hard bracket for the engine-rotating time over the elapsed span, and what is the supported-basis rate per 10,000 km with a day-clustered interval, next to the duration-scaled (imputed) rate that the legacy table shows?

## Definitions (unchanged from M512)
Per class, over the drives of that class (master `drive_type`, the legacy `CLASS_ORDER`; drives of other types are not in a class row): supportedOnHours, supportedHours, elapsedHours, unsupportedHours, bracketHours = [supportedOn, supportedOn + unsupported], scaledImputedHours, supported-basis rate = supportedOn / km (drives with an RPM series) x 10,000, imputed rate likewise. Population: all master drives of the class (unfiltered exposure total, M512 R4).

## Addition
For each class row, a day-clustered ratio-of-sums percentile bootstrap (calendar day = cluster, seed 42, 4000 draws, the M512 `_dayboot_ratio`) of (a) the supported on-time rate and (b) the duration-scaled rate, with nDays. A class with fewer than 10 calendar days gets `ci95: null` and `fewDays: true` (a rate is still shown as a point; no interval). A class with fewer than 20 drives gets `fewDrives: true` (point and interval shown, flagged). The hour totals stay exact (no interval). The payload keys are additive inside `engineRuntime.byClass[*]`: `supportedOnPer10kKmCi95`, `scaledImputedPer10kKmCi95`, `nDaysWithRpm`, `fewDays`, `fewDrives`.

## Display
Inside the existing M512 panel (Highway vs City, engine hours): a compact table per class with drives, days, supported on-time (h), RPM-supported time (h), unsupported (h), bracket (h), supported rate [95 % CI] (h per 10,000 km), duration-scaled rate [95 % CI]; a one-line reading bound to the payload: "classes differ in the supported rate; the intervals overlap / do not overlap" is NOT drawn (no contrast statement; the table reports each class). The conclusion line keeps the corpus total from M512. All numbers bind to `S.engineRuntime.byClass`; none typed.

## Controls and tests
(1) The class rows sum to the population totals for supportedOnHours, supportedHours, elapsedHours over classified drives (drives of unclassified type reported as `nUnclassified` with their hours); (2) the interval of the corpus-level rate (existing `rateIntervals`) is unchanged; (3) every class row's point rate equals its bootstrap point ratio; (4) the bootstrap is deterministic (second run equal); (5) known-answer: a two-class synthetic table reproduces hand-computed class rates and an interval that brackets the point; (6) a class with fewer than 10 days has `ci95` null and `fewDays` true; (7) isolation: only `/engineRuntime/byClass` and the stamp change in `summary_arrays.json`; every other leaf (including the corpus totals and `rateIntervals`) is byte-identical. Blind audit (analytical-auditor, claim + data path only): class supported rates and day intervals for the four classes from raw (same time base as M512). Director decision.

## Language
"engine-on time inside RPM-supported intervals", "duration-scaled (imputed)", "95 % day-clustered interval"; no contrast between classes is drawn; never "measured", "corrected", "total engine runtime". Existing rule M512-A04 stays.

## Out of scope
The other engine-hours sites (inventory milestone M519); the clean-set sensitivity display; changing the class definition.
