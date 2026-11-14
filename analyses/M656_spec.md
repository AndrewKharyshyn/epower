# M656 spec Rev 1: UI-05 second slice, cell-spread step sensitivity forests (gate L, display only)

No number, estimator or payload key changes. The panel "Step Sensitivity of the Cell-Spread Trend (exploratory)" (Health tab, `S.cellSpreadStep`) printed seven models as one table (months slope with interval, level step with interval, AIC, day-blocked CV RMSE). Two interval forests now stand in front of that unchanged table (behind ChartWithTable):
1. months slope per model, mV/month, 95 % day-clustered interval, zero line; the model with calendar-month fixed effects has no months term and is text, never a zero; AIC and CV RMSE on each row;
2. level step per model that has a step term, mV, 95 % interval, zero line.
All models use the same frame (n drives, days printed in the caption). The result and scope sentences above the table stay; the exploratory label and the limits stay.

Not in this slice (stated): the remaining UI-05 groups (lag distribution in minutes and the median warm-up curves with IQR ribbons need per-drive arrays that the payload does not carry, so they are not drawable from existing S.* keys; heat-soak skill, warm-up fuel trajectory, fuel by speed state, drive-class dot strips, sessions calendar heatmap, methods tornado, cooling scatter, PID coverage heatmap).

Acceptance: `test_csstep_forests.js` (jsdom). Binds to `S.cellSpreadStep.models`.
