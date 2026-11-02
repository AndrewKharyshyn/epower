# M572 spec: table-to-chart conversion, batch 4 (out-of-time evaluation and inference-procedure intervals)

Status: opened 2026-11-02 after M571 (merged, tag M571). Presentation only: no estimator, payload key or number changes. Same rules as
M569-M571: every plotted value is the one the table or the sentence beside it prints, the table stays in the DOM under "Show table", no interval is
invented. Inventory: `analyses/table_to_chart_audit.md` items 5 and 6.

## Scope (3 sites)
| Site | Component | Binds to | Chart |
|---|---|---|---|
| A | `OutOfTimePanel` model table | `S.socHysteresisV2.outOfTimeEvaluation[start|stop]` (`skillVsB0`, `OE`, `inSupport`, `outOfSupport` with their 95 % intervals) | two interval plots: skill vs the basis-rate constant (reference 0), and O/E pooled / in-support / out-of-support per model (reference 1) |
| B | `DependencePanel` procedure table, per series | `S.dependenceSensitivity.trendSlopes[series]` (`cr1`, `cr2`, wild bootstrap-t, day-cluster and week-block pairs bootstrap) | one interval row per procedure on the series' unit axis; the released CR1 row carries its slope as the dot; the other procedures are intervals the table prints without a point estimate |
| C | `SerialDependencePanel` procedure table, per series | `S.serialDependence.trendSlopes[series]` (HAC, moving-block bootstrap, AR(1) GLS) | same, GLS row with its slope as the dot |

Out of scope (reasons recorded in the audit): the thesis-quantities table (`kdefs`: mixed units, one axis would mislead), the energy-packets and
window-use tables (percentiles spanning orders of magnitude need a log axis, three rows each, little gain), the regime transition matrix (cells are
already shaded by probability, so it already is a heatmap), the simulation-harness coverage table.

## Design
- `intervalForestModel` (M569) gains two opt-in features, both tested in `test_interval_forest.js`: a row flagged `range:true` with `lo <= hi` and no
  estimate is drawn as an interval without a dot (kind `range`; never for an unflagged row), and an option `ref` (a reference value, e.g. 1 for O/E) that
  widens the axis and is drawn as the dashed line instead of zero. Existing behaviour is unchanged.
- The caption states "a line without a dot is an interval the table prints without a point estimate" whenever such rows are drawn, and the dashed line is
  named ("zero", "observed equals expected").
- The reading sentences under each table (procedure-dependent, lower bound changes sign) are unchanged; the chart adds no verdict.

## Language
Axis and caption wording reuses the table headers ("95% interval (mV/month)", "O/E (95% CI)", "Log-loss skill vs basis-rate constant (95% CI)").
Dependence charts keep the existing cautions (a non-detection with few day clusters is not equivalence; no stability or SOH claim). `semantic_gate.py`
A2 must stay green.

## Acceptance
`node test_interval_forest.js` passes with the new checks; build; jsdom check (marks equal table rows, no NaN); `release_check.py` and `semantic_gate.py`
green; CHANGELOG `M572`; dashboard rendered; PR; merge only on green CI.
