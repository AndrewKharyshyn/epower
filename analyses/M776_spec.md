# M776 spec: monthly OBD distance beside cloud-supported movement outside the OBD logs (dashboard chart, auxiliary)

Rev 1. Committed BEFORE any result of this milestone exists. Source: independent audit `xtrail-epower-deep-audit.md` (sections 4 P0 and 5, quoted for motivation only: no audit number is typed into the repo or used as a target other than for the blind reproduction check in section 6).

## 0. Why, and what is already known
- The published panel "Between-drive logged share by month" (M683, `S.betweenDriveLogging`) uses the OBD app-distance counter only. It says 100 % for October, which a reader reads as "nothing was missed". The cloud export (MyNISSAN, auxiliary since M729) shows movement outside the OBD windows in every month. A reader needs the two distances side by side by month.
- Owner decisions (Andrii, chat, 2026-11-25): cloud stays an auxiliary source but is complementary to OBD (same car, same drives); distance is counted once; 17/18 October and the following unlogged weeks are real drives that the cloud tracked. The KPI "Logged share of lifetime odometer" (total logged km / dash ODO, owner 2026-10-03) is NOT touched.
- Already established and not re-opened here: M739 (audit and Director decision on file) found the cloud step rule reconstructs a logged drive's distance with a median absolute relative error of about 2 % but an aggregate signed bias of about -6 % (interval -10 % to -3 %), verdict "not met" against 5 %: cloud kilometres are NOT carried as a reconstructed distance. This milestone therefore reports them as "at least" values (a lower bound under a stated rule), never as a total or a share.

## 1. Constraints
- OBD stays primary; the cloud never replaces or rescales an OBD value. Distance is counted once: cloud movement inside a padded OBD window is not added.
- Language: "reconstructed / estimated"; "speed-supported cloud movement outside the OBD logs"; never "measured", never "the missed distance is X" (it is "at least X"), never a logged share for a month that includes cloud kilometres (the denominator is not a census, section 4 D3).
- No published figure changes: `drive_master.csv` (MD5 `d514d6009d6d9a0a168ad4fb09b9bb98`) unchanged; the M683 panel and its numbers stay, moved behind a disclosure titled "Continuity of the app-distance counter". New payload block `cloudMonthlyCoverage` is additive (new key, nothing else in `summary_arrays.json` changes; isolation diff).
- Privacy: aggregates only: no coordinates, no per-drive tracks, no VIN in the payload.
- Time: every timestamp is parsed to UTC from the full local timestamp before interval arithmetic; the Kyiv calendar month and date are derived from UTC afterwards (zoneinfo Europe/Kyiv). Both DST folds and midnight are tested.

## 2. Data (read-only)
`drive_master.csv` (windows: Kyiv start time + `duration_s`), the cloud store (`XT_CLOUD_STORE`; Odometer, Trip_Information speed streams), `analyses/M739_unlogged_exposure.json` (cloud missingness, quoted by reference), `tools/mynissan_unlogged.accepted_steps` as the step builder (reused code, not re-derived). Export span: first to last odometer sample; drives outside it are excluded from the OBD column and listed.

## 3. Definitions (frozen)
- OBD window: a master drive's [start, start + duration_s], padded by P seconds at each end (primary P = 45 s).
- Accepted cloud step (primary rule): two successive odometer samples at most 35 s apart, positive increment, step-implied speed at most 180 km/h, a speed sample within 25 s of the step midpoint with speed above 2 km/h. A step is "outside" when it does not overlap any padded OBD window at all. Month = Kyiv calendar month of BOTH endpoints; a step whose endpoints are in different months is counted in the category "month unknown" (kept visible, not assigned).
- Gap increment: a positive odometer increment across more than 35 s (any length) that the step rule does not accept. Class G1: its interval overlaps no padded OBD window (movement of unresolved timing and route, outside the logs). Class G2: its interval overlaps an OBD window (it may include logged driving; never counted as missed). Month rule as above.
- Rejected steps are counted, not dropped silently: negative increment, non-monotonic or conflicting timestamp, implied speed above 180 km/h, no speed support.
- OBD distance by month: sum of master `distance_km` of drives whose start (Kyiv) is in the month and inside the export span. Partial months are flagged (first and last month of the span).
- Cloud reporting gaps: dates inside the span with no odometer and no speed row, and holes of at least 24 h, listed by date (from the stream, rechecked here).

## 4. Estimands and rules (pre-registered)
- E1 per month: OBD km, drives, days (census).
- E2 per month: speed-supported cloud km outside the OBD logs under the primary rule, with the number of steps and the number of days.
- E3 per month: G1 km (unresolved timing) and G2 km, each listed separately and NOT stacked on E1 or E2.
- E4 range per month: lower value = E2; upper value = E2 + G1. The range is a definition range, not a confidence interval, and carries a different mark.
- Sensitivity (reported as the min-max of E2 per month): P in {30, 45, 60} s; cloud-to-OBD alignment shift in {-16, 0, +16} s applied to the cloud (shifting moves the cloud, not the windows); speed-support window in {20, 25} s; speed floor in {0, 2} km/h. The primary value stays the primary rule's.
- D1 (display): the chart is displayed iff (a) the audit-independent reproduction (section 6) matches each month's E1 within 1 km and E2 within 1 km or 1 %, whichever is larger, and (b) the E2 sensitivity range for every month with E2 above 50 km is within +-10 % of the primary value; otherwise only the table with the range is shown.
- D2 (reading): E2 is called "at least"; the M739 distance bias (cloud distance of a logged drive about 6 % below OBD) is stated beside it as the reason the figure is a lower bound.
- D3 (no percentage): no monthly or overall percentage that mixes OBD and cloud km is published. The M683 percentages stay on their own basis and are labelled "counter continuity".
- D4 (day check): for every calendar day, E2 + G1 is listed in the tool output, and the audit cases are tested: a day with no OBD log but cloud movement (the 18 October case) must appear as a day of cloud-confirmed movement outside the logs; a day with a very long gap increment (the 17 October case) must put it in G2, not in E2.
- Falsification: the claim "the OBD logs miss measurable movement in a month" is falsified for a month when E2 and E4's upper value are both below the stated resolution (5 km). The claim "OBD plus cloud is complementary" is not tested by this milestone beyond D1 to D4.

## 5. Validation (reported, not gating)
- V3 capture check: the same step rule applied INSIDE the OBD windows: cloud km inside windows divided by the OBD km of those windows, per month (a transport check of the cloud rule; cross-check with the M739 aggregate, bias about -6 %). Reported beside the chart in the method note.
- Cross-reference: the total E2 against the M739 strict-unit total (about 1,918 km over the full span); a difference above 5 % is explained in the tool output (different padding and joining rules) or reported as a deviation.

## 6. Gates
1. `drive_master.csv` MD5 unchanged before and after; isolation diff: only the new `cloudMonthlyCoverage` key (and its stamp) added to the payload.
2. Known-answer tests: constructed odometer and speed series on a synthetic master: a step fully outside a window is counted; a step overlapping a padded window is not; a step across a month boundary goes to "month unknown"; a negative step is rejected and counted; a G1 and a G2 gap increment are separated; a DST-fold timestamp and midnight crossing land on the right local date; planted month totals are recovered exactly; the tool skips cleanly without a store.
3. Every number in the payload is written by the script from the live corpus; the dashboard binds to `S.cloudMonthlyCoverage` only (no typed number).
4. Blind audit (claim and data paths only, no code): reproduces E1, E2 and the G1/G2 split per month and the two audit days, from the raw OBD drive files and the raw cloud store, with its own implementation.
5. Director decision; CHANGELOG entry with this spec's sha256 and the master MD5.

## 7. Display (after gates 1 to 5)
Overview tab, in place of the M683 panel: title "Driving logged and missed, by month". Paired horizontal bars in km per month (OBD km; cloud-supported km outside the logs as "at least"), a thin range mark for E4 with its own legend entry, partial months labelled, a small calendar strip of cloud reporting gaps, and a detail row per month for G1 and G2 with the status "timing unresolved". Headline sentence bound to the month with the largest E2: "In {month}, OBD recorded {E1} km. MyNISSAN shows at least {E2} km of movement outside those logs." Source tags OBD / MyNISSAN in the legend. The old M683 panel and the existing cloud cross-check notes move into a disclosure; no numbers in them change.

## 8. Out of scope
Any change to a logged figure, the KPI, the thermal or energy analyses; imputing unlogged drives anywhere; the clock normalisation fix of the audit (P1, separate milestone); coordinates, grade, terrain; the ingestion-stage hook (added only after the Director decision, as a separate step).

## 9. Questions for the Director
(a) Is reporting the cloud km as "at least" beside OBD km, with a definition range, consistent with the M739 ruling that cloud distance is not carried (bias about -6 %)? (b) Are the primary rule (P = 45 s, midpoint speed above 2 km/h) and the sensitivity grid defensible, and is the D1 +-10 % criterion sensible? (c) Is the G1/G2 split a sound way to bound unresolved movement without stacking? (d) Any wording that conflicts with the language gate or the owner's "cloud complementary" decision?
