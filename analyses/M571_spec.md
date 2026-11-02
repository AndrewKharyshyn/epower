# M571 spec: table-to-chart conversion, batch 3 (fuel bands, generator state mix, Warm-Shoulder flows)

Status: opened 2026-11-02 after M570 (merged, tag M570). Presentation only: no estimator, payload key or number changes. Same rules as
M569/M570 (`analyses/M569_spec.md`, `analyses/M570_spec.md`): every plotted value is the one the table prints, the table stays in the DOM under
"Show table", no interval is invented. Inventory: `analyses/table_to_chart_audit.md` items 8, 13, 14.

## Scope (3 sites)
| Site | Component | Binds to | Chart |
|---|---|---|---|
| A | `FuelVsTripLength` distance-band table | `S.fuelAnalytics.fuel11` `bands[].pooledL100` (est, ci95) and `pooledAll` | interval plot (M569 `IntervalForest`), one row per band plus "all >= 0.5 km"; a band without `pooledL100` ("points only") is a text row, never drawn |
| B | `GeneratorTractionRecon` simultaneity table | `R.simultaneity[]` (`genPlusBattDischarge`, `chargesAndDrives`, `genAloneNeutral`, `fullyBanked`, `type`, `nDrives`, `engineOnHours`) | one stacked 100 % bar per drive type; segments are the printed point shares, never rescaled; a row whose shares do not sum to 100 +- 1 is flagged in the bar's tooltip; the table's "point share, no interval" caveat is repeated |
| C | `GtrSankeyMultiples` difference table | `cohortData flows` Warm, Shoulder, Cold for the five kWh/100 km flows | dumbbell per flow (Warm and Shoulder dots on one kWh/100 km axis, Cold as a third dot only when the table shows it); the difference is printed as in the table; the net traction/fuel index row (a different unit) stays table-only |

Out of scope: `FuelStates` (stacked bars already drawn), the GTR accounting tables and the Sankey itself.

## Design
- Pure models `shareStackModel` and `dumbbellModel` (marker pair `M571-MODEL-BEGIN/END`, test `test_share_charts.js`): invalid or missing
  values are skipped, not zeroed; the axes never extend beyond the data except to include zero (dumbbell) or the fixed 0-100 % (stack).
- Components `ShareStack` and `DumbbellPlot`, wrapped in `ChartWithTable` (M569).

## Language
Reuses the table wording: "Gen+batt discharge", "Charges+drives", "Gen alone", "Fully banked", "Difference (Warm - Shoulder, kWh/100 km)".
Site B keeps "time share of generator-active seconds, a state-mix description, not a validation of the generator split"; site C keeps "Warm-Shoulder
conflates season with route, not a controlled seasonal contrast" and "Cold is exploratory: point values only, no interval and no difference".
`semantic_gate.py` A2 must stay green.

## Acceptance
`node test_share_charts.js` passes; build; jsdom check (marks equal table cells, no NaN); `release_check.py` and `semantic_gate.py` green; CHANGELOG
`M571`; dashboard rendered; PR; merge only on green CI.
