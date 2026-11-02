# Table-to-chart feasibility audit (dashboard `xtrail_summary.jsx`)

Scope: read-only inventory of every `<table>` in `xtrail_summary.jsx` (78 sites, drive_master MD5 5556a0c6..., 606 drives).
Method: header/shape inspection of each site and comparison with the chart already shown beside it. Line numbers are
from the working tree on 2026-11-02 and will drift. No code was changed.

Existing drawing primitives (all hand-written SVG, no chart library): `FxPlot` (scatter), `FxLines`, `FxStack`,
`MiniHist`, `CatBars`, `RTBarChart`, `CmpBars`, `CmpLines`, `TempIntervalPlot` (interval plot), `CiGlyph`.

Selection test: convert only if (1) the table's message is a comparison, trend, ordering or distribution over >= 4 rows,
(2) the numbers are same-unit, and (3) the CI, n (drives, days) and support status can stay visible. Every converted
section keeps a "show table" toggle so exact values stay one click away.

## Tier 1: convert (clear gain in comprehension)

| # | Section (component, approx. line) | Table shape | Chart | Reuse | Note |
|---|---|---|---|---|---|
| 1 | Detector sensitivity (`DetectorSensitivityPanel`, 7515) | one-axis-at-a-time paired effect pp with 95 % day-clustered CI | forest plot, zero line | `TempIntervalPlot` | Role column becomes marker style; support lost/gained stays as text |
| 2 | Regen sensitivity note (`RegenSensitivityNote`, 3038) | rule changed vs legacy bar, difference pp with CI | forest plot | `TempIntervalPlot` | Language rule `M446-stratified-display` applies to labels |
| 3 | Window caveat (`WindowCaveatPanel`, 5368) | cutoff day vs slope mV/month [95 %] | interval plot over cutoff (sequence) | `TempIntervalPlot` | Shows whether slope is stable as the window grows |
| 4 | Rolling origin (`RollingOriginPanel`, 5426) | origin/test window vs skill with CI, O/E with CI | skill-vs-origin line with band, reference line at 0 | `CmpLines` | Largest gain: 8 columns collapse to one picture |
| 5 | Out-of-time models (`OutOfTimePanel`, 5398) | model vs log-loss skill (CI), O/E (CI), PR-AUC | small-multiple forest (skill, O/E) | `TempIntervalPlot` | Keep D1/D2/D3 flags as table |
| 6 | Dependence panels (`DependencePanel` 5555, `SerialDependencePanel` 5478/5547) | estimate with day-cluster vs week-block interval, width ratio | paired interval plot per quantity | `TempIntervalPlot` | Direct visual of "interval width depends on method" |
| 7 | Power-duration (`PowerDurationView` 5028, `...Uninterrupted` 5053) | window length vs discharge/charge median and p95 kW | line chart over window, median and p95, discharge and charge | `FxLines` | Natural curve; table is currently unreadable |
| 8 | Fuel vs trip length (`FuelVsTripLength`, 8638) | distance band vs pooled L/100 km with CI | bars/points with CI over band, overlays the existing scatter | `FxPlot` + interval | Scatter exists; the pooled CI table is the missing summary |
| 9 | Fuel distribution trend (`FuelDistributionTrend`, 8684/8686) | q10..q90 per window; pooled L/100 km by window start | (dropped in M570: the ECDF and the windowed pooled rate with CI are already drawn above the two tables) | | |
| 10 | Time-to-threshold (`TimeToThresholdPanel`, 8974, 9012) | seconds vs observed share, Kaplan-Meier (CI), Manski bounds, tilt | step curve with CI band and worst-case bound | `FxLines` | Both curves already ordered in time |
| 11 | Engine start rate (`EngineStartRate`, 1248/1255) | group vs onsets/100 km with CI; onsets by coolant band | interval plot by group; bar by coolant band | `CatBars`, `TempIntervalPlot` | 1255 is share per band: bar is enough |
| 12 | Drive-type regime transition matrix (inline, 12197) | row/column probabilities with counts | heatmap (shade = probability, count in cell) | new `Heatmap` | Currently a number grid; top reader gain per effort |
| 13 | GTR drive-type breakdown (`GeneratorTractionRecon`, 5825) | drive type vs gen+batt discharge / charges+drives / gen alone / fully banked | stacked horizontal bars | `FxStack` | Check shares sum to 100 % before drawing |
| 14 | GTR Warm vs Shoulder difference (`GtrSankeyMultiples`, 11784) | flow vs warm, shoulder, delta | diverging bar of delta, or dumbbell | `CmpBars` | Sankey remains; this replaces the delta table only |
| 15 | (removed by owner, 2026-11-02: the nine cross-vehicle tables stay as tables) | | | | |
| 16 | Energy packets / window use (`EnergyPacketsView` 5005, `WindowUseView` 5077) | median / p90 / p99 (p95) per stratum | quantile range bars (median dot, p90-p99 whisker), log axis for energy | `TempIntervalPlot` | Needs a log axis: check quantile spacing |

## Tier 2: convert only as a companion (chart plus table)

| Section | Why not table-replacing |
|---|---|
| Regen v2 cells (`RegenV2Panel`, 3174) | A chart already exists; the table carries support and precision per cell. Keep. |
| Fuel states (`FuelStates`, 8722) | `FxStack` is drawn; the table adds CI and support. Keep as toggle. |
| Cohort comparison cube (`ComparisonCube`, 11061) | Compare mode already draws `CmpBars`; the cube is the audit view. |
| Urban season contrast block sensitivity (11103) | Interval per procedure could be a forest, but the verdict text depends on MC-error flags. Do after Tier 1. |
| Cycle projection tables (`CycleProjectionChart` 2705, 2836) | "window needed vs hypothetical fade" suits a line, but status-now column carries a verdict. Chart plus table. |
| Hours per drive-type class (12509/12514) | Bar of engine-on h per class works; the bracket and "few drives" flags must remain visible. |
| SoC by speed (`SocBySpeed`, 4315) | Box plot is already drawn; the table is the redundant companion. |

## Tier 3: keep as tables (a chart would lose information or mislead)

- Text and ledger tables: `AssumptionsRegistryTable` (652), `HealthStatusCard` (4963: mixed units, evidence levels), `CellObservabilityView` (5138),
  `SignalValidityView` (5159), `ChannelDependencyView` (5179/5185), `IntegrationScenarios` (598), evidence ledger (13766), coverage map (13654), glossary.
- Provenance and basis tables: `FuelBasisBanner` (8784/8789), `CohortSupportBlock` (11181), `AmbientTempTable` (500, per-drive ledger), `CsrSensitivityView` (5249).
- Cross-vehicle tables (`CrossVehicle`, nine tables, 10681-10992): owner decision 2026-11-02, not converted.
- Mixed-unit or one-off GTR tables: 5599, 5623, 5760, 5776, 5794, 5897.
- Sparse or exploratory data: cold cohort rows (2 days per stratum, no interval), 8999 (per-cell fill counts), 10345 (CrawlStopGo window mask).
- Model-skill diagnostics with many columns (12809): heat-style summary possible but the secondary and diagnostic columns would be lost.

## Rules a conversion must follow

1. Binds only to existing `S.*` keys; no new typed literals; any derived quantity (ratio, delta) is computed in the pipeline.
2. CI, n (drives, days) and support/exploratory status remain visible on the chart; no interval is invented where the table shows none.
3. A "show table" toggle under each chart keeps the exact values.
4. Wording passes `semantic_gate.py` A2 / `language_gate.py` (estimated / reconstructed / model-derived, never "measured"; no contrast where the spec forbids one).
5. One shared component set (forest/interval, line with band, heatmap, diverging bar); new primitives are written once and reused.
6. Per batch: CHANGELOG `M###`, green `release_check.py`, render the dashboard, commit with `xtrail_summary.jsx` + arrays on the milestone branch.

## Suggested order

1. Forest/interval batch: items 1, 2, 3, 5, 6, 11 (one primitive, highest density of CI tables).
2. Curves batch: items 4, 7, 9, 10 (one line-with-band primitive).
3. Fuel and GTR batch: items 8, 13, 14.
4. Heatmap batch: item 12, then packets (16).

Counts: Tier 1 = 15 groups covering roughly 21 of the 78 table sites; Tier 2 = 7; Tier 3 = the remainder.
Site counts are approximate: sites 2705-2836, 13654, 13766 and several CrossVehicle/inline tables were classified from
a one-line header peek, so confirm the exact columns when each batch is specified.
