# M604 spec (Rev 1 after Director review; Rev 0 written before any change): regeneration in Compare mode (independent audit, roadmap row "Regen context")

Status: Rev 0, 2026-11-07. Owner request: Andrii, chat 2026-11-07 ("continue"). Source: `xtrail_epower_independent_audit.pdf`, page "Regen context"
("Compare still uses a disclosed legacy extraction. Use common cadence and support in Compare, or suppress direct numeric contrast. Preserve the existing
chart. Add event support ...") and the per-claim note on Charts -> Apparent kinetic-energy recovery ("In Compare, say explicitly when the legacy extraction
is active. Leave empty bins visible as unavailable.").

## 0. Rev 1 (Director REVISE, frozen; supersedes conflicting clauses below)
Chosen: Option A as a stratum-locked variant. The Compare table shows ONE polling stratum at a time (slow-polled default, a Fast-polled button; the two strata
never share a table), cohorts Warm / Shoulder / Cold as columns, the All-SOC rows of the chosen view as rows (by speed primary, by pack temperature second), with an
Observed (default) / SOC-standardized basis switch. The legacy charts stay below with a stronger note. Required changes applied:
1. `massRange` is the assumed-mass range and is labelled so; the resolution bracket `b_nat` is a separate labelled quantity; neither is combined with the day interval.
2. Stratum `totals.eff` (all speeds pooled) is NOT displayed; `totals` supplies only the support row (drives, days, status, ciSuppressed). Cohorts differ in speed
   mix, so a pooled level would mostly reflect speed mix.
3. SOC-standardized rows come from the existing `standardized[view]` bars (one fixed all-cohort mix, All-SOC only, availability note shown when unavailable); no
   standardized total exists and none is shown.
4. `stratumSpeedDtMedianS` is shown per cohort (cadence still differs across cohorts inside a stratum).
5. The B6 cadence-invariance FAILED notice is shown beside the table. No difference column, no pooled row.
6. Exploratory / no-interval comes from `design.days < 5`, `status` and `ciSuppressed`, never from the cohort name; the spec does not type a day count.
7. Note wording: cohorts are read side by side within one polling group; no difference is computed; a cohort is a display band, not a temperature or season effect.
8. The old Compare note wording is added to `language_gate.py` RULES (ledger M604, rule `M604-regen-compare-note`).
9. Binding path: `S.regenDisplayV2.cohorts[c].strata[s]` (design, totals, views, standardized). Blind audit not required (rebinding only, JSX does no arithmetic);
   instead a semantic-gate check A4 compares every rendered supported or thin cell and the exploratory notes with the payload.
The M451 estimator, `regenDisplayV2` and the single-cohort view are unchanged. Option C and a collapsed legacy block (optional) were not adopted: the owner rule of
2026-11-06 forbids new collapsibles.

## 1. Problem
With one cohort selected, the regeneration section draws the cadence-stratified native v2 estimate (`regenDisplayV2`, M451: fast- and slow-polled drives in
separate strata, per-stratum resolution bracket, no pooled bar, no contrast between strata). In Compare mode (Warm / Shoulder / Cold side by side)
`xtrail_summary.jsx` (~line 3502) instead draws the four LEGACY charts (`RegenCaptureMeasured`, `RegenByTempMeasured`, `RegenByType`, `RegenByZone`)
through `CompareMulti`, with a note saying the legacy extraction is active. The legacy extraction depends on logger sampling, and the cadence mix differs by
cohort (fast-polled share by cohort is read from the payload, not typed), so the side-by-side bars confound cohort with cadence. A note does not remove that.
Empty temperature bins already read "not observed (n=0) - null, not zero" and stay as they are.

## 2. Decision to take (options)
- Option A (additive): above the legacy charts, show a compact, text-visible table "Apparent KE recovery by thermal cohort, one cadence stratum at a time"
  with, for each stratum (slow-polled first, then fast-polled) and each cohort (Warm, Shoulder, Cold): apparent recovery (%), 95% day-clustered interval or
  "no interval (support)", resolution bracket `massRange`, drives, days and the support status, all bound to
  `S.regenDisplayV2.cohorts[c].strata[s].totals`. The legacy charts stay under it with a stronger note ("not comparable across cohorts: the cohorts differ in
  logging cadence; compare cohorts inside one stratum in the table above"). No tab or control change; nothing collapses.
- Option B (replace): the table replaces the four legacy charts in Compare; the legacy charts remain reachable only through each single-cohort view where they
  already stay under the stratified display for payloads without `regenDisplayV2`. Loses the temperature-bin and speed-zone views in Compare.
- Option C (suppress): in Compare the regen section shows only a statement plus the per-cohort support line (drives, days, status), with no numbers side by side.
Recommendation: Option A. It uses the audit's "common cadence and support" route, preserves the existing chart as the audit asks, and adds no estimator.

## 3. Method and data
No new estimator, no new payload key, no change to `drive_master.csv` or `regenDisplayV2`. The table reads existing keys only. Compare numbers across cohorts are
shown only within one stratum (same cadence rule); the two strata are never contrasted (M451 rule `M446-stratified-display`). Cold in either stratum has
4 days (support floor 5 days): its row shows the estimate as exploratory with the interval suppressed, exactly as the single-cohort view does today.
No cohort-minus-cohort difference is computed or printed in this change. If a difference were wanted it needs its own spec (day-clustered, same stratum).

## 4. Tests
- A new node/jsdom assertion (or a python check on the rendered tab dump) that every number in the Compare table equals the payload value it binds to
  (estimate, interval ends, drives, days, status) for the 6 cohort x stratum cells, and that the Cold cells show no interval.
- The semantic gate A2 language rules apply to the new text: "cadence-stratified native apparent KE recovery (assumed mass)"; never true / more accurate level,
  cadence-corrected / -adjusted, G2 passed, total accuracy interval, optimal / peak temperature, "fast vs slow" (use "fast-polled" and "slow-polled" as strata names).
- Existing tests that assert the Compare note text are updated only if the wording they check changes (pure wording check), and reported.

## 5. Accept / reject
Accept if: the table is script-bound (no typed number), the Cold cells carry the support caveat, the old Compare note is replaced by the stronger one, the tab
dump shows the table in Compare and not in single-cohort modes, the semantic gate and jsdom validation pass, and the Director approves the option.
Reject / revert to the note-only state if any cell disagrees with its payload key or the wording gate fires.

## 6. Language and scope
Apparent kinetic-energy recovery, assumed mass, logged and estimated signals; not a regeneration efficiency of the drivetrain, not measured. Not article-bound.

## 7. Out of scope
The event-support, downhill-flag and mass/timing sensitivities named in the same audit row (they need data or a separate spec); changing `regenDisplayV2`;
any cohort contrast statistic.
