# M437 spec (Rev 2) - forward-fill and trip-end-tolerance sensitivity of the time-to-threshold analysis (M435 follow-up)

Status: PRE-REGISTERED, written before any result of this study exists. Rev 2, 2026-10-14 (Rev 1 reviewed by the research-director: "revise", blocking items B1-B6, all adopted; changes in section 8). Owner: Andrii. Origin: M435 Director ruling (follow-up: "script-written fill / tolerance sensitivity leaf; clarify what the audit's '35 reclassified' counts") and the M435 blind audit (the cold-start population depends on the 3 s forward fill; fill and tolerance are coupled). Branch `claude/next-milestone` from `main` after M436. `drive_master.csv` MD5 `a641f34d7528d004b900c151cbde3d6d`.

## 1. Question

The M435 time-to-threshold block rests on two declared planning choices that are not part of the released M418 estimator: the 1 Hz grid forward-fills missing values (the released `_twl_grid`: `resample('1s').mean().ffill(limit=3)`), and a drive is classified as trip-end censored when its last valid fluid second is within 10 s of the end of the grid (otherwise channel loss). How much do the headline readings move when these two choices vary over a declared range?

Not an estimand: any change of the released M418 / `thermalWarmupLag` estimator (it keeps limit 3); any new physical claim. The result is a sensitivity range over declared conventions: not a confidence interval, not a bound on the true quantity, and it does not select a convention (B6).

## 2. What the fill can and cannot change (B1, B2)

`ffill(limit=F)` copies the previous valid value into at most the first F seconds of every gap; the remaining seconds of a longer gap stay NaN (a 4 s gap at F = 3 gets 3 filled seconds and 1 NaN; a 7 s gap at F = 6 gets 6 filled seconds and 1 NaN). A filled second repeats an earlier value, so the first second at which a fluid value is >= the threshold is always a SAMPLED second (the M435 clarification C2): the fill cannot move an event time. It acts only through (i) the cold-start population (the rule needs at least 30 valid coolant seconds, filled seconds counted), (ii) the censoring time (the last valid second moves later by at most the extra fill), and (iii) therefore the trip-end / channel-loss split. Consequently the expected paired result is `eventTimeChanged = 0`; any nonzero value is a defect and stops the run (it is not reported as a finding). The trip-end tolerance X enters no estimate: it only decides the label tripEnd versus channelLoss (and so the reason counts), never n, events, censoring times, E1 or the Kaplan-Meier estimate.

## 3. Variant grid (declared before any result; the released/M435 setting S0 = (F = 3, X = 10) is starred) (B4)

- F, forward-fill limit (grid seconds): {0, 3*, 6}: THREE fill settings, each a full re-estimation (population, records, estimates, bootstrap). F = 3 reproduces `compute_summary_arrays._twl_grid` exactly (KAT).
- X, trip-end tolerance (s): {5, 10*, 30}, applied at every F; it changes only the reason split, so it is reported as a reason-count table (the split depends on about X and F together), not as estimate variants. Nothing is tuned or selected.

## 4. Quantities (headline cells declared in M435: cohort all, coolant 80 C and oil 70 C, h = 600 s; no other cell)

Per F and headline cell: n cold starts, days, reached, censored by reason at each X, the observed share before key-off E1(600) (equals F_low), the Kaplan-Meier (product-limit) estimate E2(600), the worst-case bound F_high(600), the hazard-tilt rows theta = 0.5 and 2, the two readings (F(600) < 0.5; F(600) >= 0.5) with their M435 classes (first match), the Kaplan-Meier median, the support at 600 s. The M435 estimators, the day-clustered bootstrap (B = 4000, seed 42, one resample set per F and cohort; the sets differ between settings, so ranges compare point estimates), no tipping points for variants, the M435 support rule. The median sample interval and its 95th percentile of the coolant and the oil channels are reported (cohort all).

Paired comparison of each F with S0, per headline cell (B2, B3, B5):
- `dropped` (cold starts in S0 but not in the variant) and `added` (in the variant but not in S0), each split into: reached by 600 s, censored before 600 s (censoring time < 600), at risk at 600 s;
- `eventTimeChanged` for drives in both (expected 0; nonzero stops the run);
- `censoringTimeChanged` for drives in both (count; the maximum shift, which must be <= |dF|);
- `reasonChanged` versus S0 (count by direction tripEnd -> channelLoss and back): this is the quantity the M435 audit reported as "reclassified" (the audit's 13 and 35 are known-answer targets for the blind audit only and are not typed anywhere in the repo).
- Nesting checks: `added = 0` at F = 0 (every F = 0 cold start is an S0 cold start) and `dropped = 0` at F = 6.

## 5. Decision rules and statement (B6)

S0 stays the record; no variant is chosen. The script writes, per headline cell, the statement "the reading class is the same in all 3 fill settings" or the list of settings where it differs; an unsupported horizon in a setting does not count as the same class. The M435 sentence "the headline classes are unchanged" is replaced by this script-written statement. Any setting with a different class, or any failed check (nesting, event time, G1), goes to the Director before display. The ranges of E1(600) and E2(600) over the three settings (min, max, and the setting that attains each) are reported. Never "robust", "insensitive", "stable", "bound", "does not depend on the fill". No article use.

## 6. Gates and tests

- G1: the F = 3 setting equals the M435 block for the same cells (counts, E1, E2, F_high, classes, medians); the reason table at (F = 3, X = 10) equals the M435 reason counts; nesting checks hold; `eventTimeChanged = 0`.
- G2: every new leaf under ONE additive key `thermalSupportLedger.timeToThreshold.fillSensitivity`, produced by the ledger stage in the same pass over the frames (the grid is built once per F per frame; the stage seconds it adds are reported in the CHANGELOG); deep diff: nothing else changes.
- G3: a second run is byte-identical.
- Known-answer tests (criteria declared here): (i) the grid function with F = 3 equals `_twl_grid` on synthetic frames with gaps of 1, 3, 4 and 8 s, and a 4 s gap at F = 3 gives 3 filled + 1 NaN; (ii) F = 0 never fills; F = 6 fills a 6 s gap completely and a 7 s gap gets 6 filled + 1 NaN; (iii) a drive with 20 valid coolant seconds and gaps of <= 3 s that make 33 filled-or-valid seconds is a cold start at F = 3 and not at F = 0 (hand-computed count); (iv) event times are EQUAL across F on random synthetic series whenever the drive is a cold start in both (equality, not monotone); (v) X = 5 / 10 / 30 on drives whose last valid second is 3, 8, 20 and 40 s before the grid end give tripEnd / channelLoss as hand-computed; (vi) the paired counts `dropped`, `added` (each split by status), `censoringTimeChanged` and `reasonChanged` on a 6-drive synthetic set equal the hand-computed values.
- Blind audit (analytical-auditor): reproduce the cold-start counts, E1 and E2 at F in {0, 6} for coolant 80 C and oil 70 C from the raw files and the rules above; the Director rules on the wording before the dashboard text.

## 7. Wording and limits

Required next to the table: "Sensitivity of the observed share and the Kaplan-Meier (product-limit) estimate to the forward-fill limit (0, 3, 6 s); range over declared conventions, not a confidence interval; the trip-end tolerance changes only the reason split." Language rule M435-thermal-tte, extended if the Director requires. Limits (disclosed in advance): the fill grid is a declared planning choice; a logger interval above 1 s couples fill and tolerance; ranges are of point estimates (the bootstrap resample sets differ between settings); at F = 0 the 30 valid-second rule counts raw samples; the sensitivity does not address informative censoring (the M435 bounds and tilt rows do); cohorts warm and shoulder and non-headline cells are not covered; single vehicle, one driver, May-October.

## 8. Changes from Rev 1

Fill rule restated and KAT (i)/(ii) corrected (B1); `eventTimeChanged` expected 0 and a stop condition, KAT (iv) an equality test, nesting checks and `censoringTimeChanged` added (B2); `reasonChanged` added, the audit's counts only as known-answer targets (B3); "3 fill settings", the reason split reported separately (B4); dropped/added split by status (B5); S0 stays the record, script-written statement, Director escalation, wording (B6); stage seconds, no tipping points, sample-interval median/p95 (Director follow-ups).
