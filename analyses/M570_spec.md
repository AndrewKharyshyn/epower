# M570 spec: table-to-chart conversion, batch 2 (curves with intervals)

Status: opened 2026-11-02 after M569 (merged, tag M569). Presentation only: no estimator, payload key or number changes.
Inventory and selection rules: `analyses/table_to_chart_audit.md`. Same rules as M569: every plotted value is the one the table prints,
the table stays in the DOM under "Show table", no interval is invented, display rules of the payload (`showP95`, `showCell`, `supported`) decide
which points are drawn.

## Scope (5 sites)
| Site | Component | Binds to | x | Series (per point: estimate, 95 % interval) |
|---|---|---|---|---|
| A | `PowerDurationView` | `S.powerDuration.strata[s].byW` | window length (s), log axis | discharge and charge, median and p95 (`exact.p50`, `exact.p95`) |
| B | `PowerDurationUninterruptedView` | `S.powerDurationUninterrupted.strata[s].byW` | window length (s), log axis | discharge / charge p95 without reversal (interval, only where `displayRule.showP95`) and the net p95 on the same drives (point, only where `showCell`) |
| C | `RollingOriginPanel` | `S.socHysteresisV2.rollingOriginEvaluation[start|stop].origins` | origin (ordinal) | skill vs constant baseline (reference 0) and O/E (reference 1), evaluable origins only |
| D | `TimeToThresholdPanel` per cell | `S.thermalSupportLedger.timeToThreshold.cohorts[c][fluid][t].horizons` | horizon (s) | observed share before key-off (CI), Kaplan-Meier estimate (CI), worst-case identification bounds as a grey bar (not an interval); unsupported horizons are gaps |

Dropped from the audit list: `FuelDistributionTrend` already draws the empirical distribution and the windowed pooled rate with its CI; the
two tables below it are the numeric companions (kept as they are).

## Design
- Pure model `bandSeriesModel(series, opts)` (marker pair `M570-MODEL-BEGIN/END`, test `test_band_series.js`): point kinds `interval` / `point` /
  `none` as in M569; optional `bound:[lo,hi]` per point (drawn as a grey bar, widens the axis, never an interval); x either linear or log
  (non-positive x on a log axis is dropped, not clamped); optional reference line `ref` and fixed `ylim`; ticks 1-2-5; x ticks at the actual x values.
- Component `BandSeries`: connected line through consecutive drawn points (broken at gaps, never interpolated across an unsupported
  horizon), interval whisker and dot per point, series dodged horizontally so intervals do not overlap, legend above.
- Wrapped in `ChartWithTable` (M569).

## Language
Axis, legend and caption wording reuses the table headers ("Observed share before key-off (95% CI)", "Kaplan-Meier (product-limit) estimate",
"Worst-case (Manski) identification bounds", "p95", "median"). Captions repeat the existing cautions: percentiles across drives are observed
extrema of these logs, cadence strata not pooled; identification bounds are not confidence intervals; rolling-origin intervals are conditional on
each fold's fitted model. `semantic_gate.py` A2 must stay green.

## Acceptance
`node test_band_series.js` passes; build; jsdom check (series and points drawn equal the table's supported cells, no NaN); `release_check.py`
green; `semantic_gate.py` green; CHANGELOG `M570`; dashboard rendered; PR; merge only on green CI.
