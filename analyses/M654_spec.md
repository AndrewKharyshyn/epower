# M654 spec Rev 1: UI-05 first slice, thermal group forests (gate L, display only)

No number, estimator or payload key changes; every plotted value is a ledger value the table beside it prints.

Audit item UI-05 lists the thermal group first. The six time-to-threshold tables already carry a banded chart each (BandSeries inside ChartWithTable, earlier milestones). This slice converts the three remaining thermal tables:
1. Forward-fill sensitivity, fills 0 / 3 / 6 s (`thermalSupportLedger.timeToThreshold.fillSensitivity`);
2. Longer fills 15 / 30 s (`fillSensitivity.extendedFills`, M648);
3. Start-temperature terciles per headline cell (`startStrata`).
Each becomes an `IntervalForest` (existing M569 primitive, pure model, never invents an interval) through the new `ShareForest`: two rows per setting (observed share blue, Kaplan-Meier (product-limit) estimate orange, 95 % day-clustered interval), n (cold starts / days / reached) on each row, an unsupported row printed as text "not supported", never a zero. The table stays behind ChartWithTable.

Not in this slice (stated): the remaining groups of the UI-05 priority order (lag distribution in minutes, median warm-up curves, cell-spread and step-sensitivity forests, heat-soak skill, warm-up fuel trajectory, fuel by speed state, drive-class dot strips, sessions calendar heatmap, methods tornado, cooling scatter, PID coverage heatmap, cross-vehicle companions). Ledgers, registries, records and per-drive listings stay tables by design.

Acceptance: `test_tte_forests.js` (jsdom): forest inside ChartWithTable for each block, two rows per setting, values equal the ledger at 3 dp, unsupported is text, table behind the toggle. Binds to `S.thermalSupportLedger.timeToThreshold.{fillSensitivity,fillSensitivity.extendedFills,startStrata}`.
