# Dashboard prose style (M594 Wave 2, owner request 2026-11-06)

Goal: a reader who is not a specialist can see what each result says, for which data, and what it cannot say, without losing any
scientific precision. Everything stays visible (no new buttons, no `aria-expanded`, no new collapsibles). Tabs, tab order, chart
positions and selectors do not change.

## Block pattern (applies to every dense paragraph in `xtrail_summary.jsx`)
1. **Result** (bold, one sentence, at most about 25 words): what was found, in plain words, bound to `S.*`.
2. **Scope** (one short line): population, denominator, evidence type, n drives / n days where the payload provides them.
3. **Reading** (at most 3 short sentences): what the figure does and does not show. Keep any limitation that changes the reading
   right here; do not push it to another place.
4. Methods that matter only to a specialist stay in the text but move to the END of the block as one short "Method:" sentence.

## Rules
- Short sentences (aim for 25 words or fewer), active voice, concrete nouns. Say "the battery supplied power" not "discharge-positive pack
  power contribution was observed".
- Define an abbreviation at first use in the block (SoC, CI, TOST, GTC, KE, BMS, PID). Prefer "95% interval" to "95% CI" in prose.
- Remove release-history fragments from reader-facing sentences ("M41 reframing, 2026-07-17", "superseded by", "formerly", "was hand-typed").
  Keep a milestone id only as a trailing "(M###)" tag when a test or the CHANGELOG needs it.
- Remove repeated caveats: one caveat once per block. A caveat that changes how the number is read stays beside the number.
- Do not delete a number, interval, n, or caveat that exists nowhere else in the same tab. Moving or shortening is fine; losing is not.
- Every figure comes from an existing `{S.*}` / `{...}` expression. Never type a new number that a payload key can supply. Definitional
  constants already in the text (80-120 km/h, +/-15 N m, 5 Ah) may stay as written.
- Wording discipline (CLAUDE.md, `language_gate.py`): generator, traction and fuel quantities are "estimated", "model-derived",
  "app-calculated" or "logged", never "measured". TOST "not established" is not "no degradation". Torque bins are "target-torque bins",
  not acceleration. "Apparent kinetic-energy recovery" for regeneration. Never "proven", "corrected", "errors" for provenance deltas.
  A confidence interval that excludes zero is described by the SIGN of the interval (positive / negative), never always "positive".
- Do not rename payload keys, `data-*` attributes, element ids or CSS class names (JS tests and gates use them).
- Keep JSX valid. After each batch of edits run `node build_html.js` (must print `wrote xtrail_dashboard.html`).
- Before removing or rewording a sentence, `grep -rn "<distinctive phrase>" tests tests/synthetic *.py *.js` to see whether a test or gate
  asserts it. If one does and the assertion is a pure wording check, update the assertion to the new wording and report it; if it checks
  a number or structure, keep the structure.

## Example (Highway power buffering)
Before: a 150-word paragraph mixing M41 history, the saturation screen, and the share definition.
After: **During 80-120 km/h driving, the engine was turning and the battery was supplying power for {S.deficitMeanPct}% of band time on the
average drive.** Scope: {S.deficitValidN} eligible drives; time with both engine rotation and battery discharge divided by all eligible
band time. Reading: the saturation screen found {S.saturTotalS} s of events in {S.saturCoverageN} screened drives, so the logs show the pack
helping, not a generator limit. Generator output is not observed.
