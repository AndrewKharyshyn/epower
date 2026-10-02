# M336 step 2 result (script-written: `tools/gtr_interval_sens.py` -> `M336_step2_result.json`)

Scope: fuel-PID subset only (259 drives, 50 days, 2003.0 km; 224 drives without fuel PID are outside), raw/ basis (F03: provenance-sensitive), day-clustered bootstrap (seed 42, 4000), corpus ratio-of-sums. Logger median dt 0.886 s.

- Baseline f_gen = 0.467, 95% CI 0.383 to 0.545. The CI already contains 0.5, so a "CI newly contains 0.5" trigger cannot fire; the point estimate is below 0.5 in all 19 variants (range 0.435 to 0.491; highest: corner_high_G 0.491, bsfc x0.94 0.487, paux 1.2 0.489, anchor off 0.452). Pre-registered stop condition: NOT triggered. Neither "generator majority" nor "battery majority" is established: the CI straddles 0.5.
- Interval test (2a): excess interval X = [-10.4%, +6.4%] of generator electricity, 0 inside it in every variant, hence "consistent within the dual bracket" (the +/-5% point rule on the upper branch alone stays "not closed", as in step 1). Implied dual allocation alpha* = 0.62 (CI 0.59 to 0.64); across variants 0.21 to 0.76, always in [0,1] at corpus level; 7 to 36 drives per variant have alpha* outside [0,1] (15 at baseline).
- Independent per-sample check: within dual samples (n=9203) the model generator power could supply 61.1% of the battery charge energy, close to alpha* (0.62); Pgen_t > 0 in 95.1% of dual samples. Association of two model-based quantities, not validation.
- Largest levers on alpha*: lag (-5 s: 0.21), aux load (1.2 kW: 0.76), BSFC scale (0.52 to 0.67). Per-drive lag descriptor (flow vs rpm): median 0 s, IQR -1 to 0 s, so large lags are not supported by the data.
- Strata: urban only evaluable (50 days): f_gen 0.375 (0.351 to 0.396); highway/mixed/mixed_highway have <10 days, not evaluable.
- 2c reconciliation (sensitivity only, circular weights): 87% of the adjustment falls on gen->traction and the implied f_gen is 0.419; this is equivalent to tuning f_gen and is not used.
- Caveats: offset variants use per-sample class-energy ratios (approximation); BSFC/eta/paux ranges are `model_constants.py` literature-anchored spans (no cited source verified this session).
