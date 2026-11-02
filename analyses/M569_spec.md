# M569 spec: table-to-chart conversion, batch 1 (interval / forest plots)

Status: opened 2026-11-02, number assigned by Andrii (chat: the conversion starts at M569, M568 is merged). Presentation change only:
no estimator, no payload key, no new number. The previous M569 draft (cell-spread step versus trend) is renumbered M573
(`analyses/M573_spec.md`). Inventory and selection rules: `analyses/table_to_chart_audit.md`.
Batch plan: M569 interval plots (this spec), M570 curves with bands, M571 fuel and GTR charts, M572 heatmap and packets.

## Scope (4 sites)
| Site | Component | Binds to | Row = | Interval |
|---|---|---|---|---|
| A | `EngineStartRate` group table | `S.engineStartRate` (`primary.*`, `byClass.*`) | cohort or drive class | `e.ci95` (point only when absent, as the table says "points only") |
| B | `WindowCaveatPanel` cutoff table | `S.windowCaveat` (`cutoffs`, `leaveLastK`) | cutoff day | `ci95` where `status==="ok"`; other statuses keep the table's text |
| C | `RegenSensitivityNote` rule table | `S.regenLegacySensitivity.cohorts[coh].variants` | extraction rule | `deltaCi95` of the largest-difference bin; point only when absent |
| D | `DetectorSensitivityPanel` axis table | `S.evTraction.detectorSensitivity.oneAtATime` | detector setting | `detectorPpCi95` |

Out of scope: dependence panels (5478/5547/5555), out-of-time models (5398), all curve, heatmap and stacked-bar items; the nine
cross-vehicle tables stay tables (Andrii, 2026-11-02).

## Design
- One pure model `intervalForestModel(rows, opts)` (marker pair `M569-MODEL-BEGIN/END`, known-answer test `test_interval_forest.js`):
  row kind `interval` (est + lo <= est <= hi), `point` (est only, or interval invalid), `none` (no estimate: text only); axis range covers all
  drawn values and zero when `zero` is set; 1-2-5 ticks. It never invents an interval and never clips one.
- One component `IntervalForest` draws it as SVG (dot = estimate, line = interval, dashed line = zero); a native `<details>` ("Show table")
  keeps the original table, unchanged, in the DOM below the chart, so exact values, support and n stay one click away and existing
  table-targeting tests keep working.
- n (drives, days) and support text are printed beside each row where the table had them. Rows the table marks not comparable / outside the
  range are drawn muted, not hidden.
- No figure is typed: every plotted value is read from the same payload field the table prints.

## Language
No new claims. Axis and caption wording reuses the table headers (e.g. "Paired effect, pp (95% day-clustered CI)", "Slope [95% interval]
(mV/month)", "onsets/100 km, 95% CI"). Site C stays "a range over declared conventions"; no replacement value. Language gate (`semantic_gate.py`
A2) must stay green.

## Acceptance
1. `node test_interval_forest.js` passes (known answers: axis incl. zero, kinds, ticks, invalid interval, empty input).
2. `node build_html.js` builds; the jsdom tab dump shows, for every site, an SVG chart with one row per table row and the original table
   inside `<details>`; row counts equal.
3. `python release_check.py` green; `semantic_gate.py` A2 green; `drive_master.csv` MD5 unchanged (5556a0c6...).
4. CHANGELOG `M569` entry via `tools/changelog_draft.py`; dashboard rendered to Andrii; committed with `xtrail_summary.jsx`,
   `summary_arrays.json`, `cohort_arrays.json` on the session branch; PR per the Version control rules.
