# M336 step 2 design (pre-registered before any code; work in progress: Director review pending)

Inputs: step 1 result (`M336_step1_result.md`, `M336_closure_diag.json`). Same mask (259 drives, 50 days), same bootstrap (day cluster, seed 42, 4000).

## 2a. Interval representation (candidate B; primary)
- Generator branches: gen->traction G (model, unchanged), gen->battery in [L, U] with L = `charge_eng_only_kwh`, U = L + `charge_dual_kwh` (dual = engine on AND torque-verified regen, not allocable between generator and regen with the logged channels).
- Per drive and corpus: closure interval X = [G + L - E_gen, G + U - E_gen]; node "closed within the interval" iff 0 in X (point test), and the implied dual allocation alpha* = (E_gen - G - L)/dual with day-clustered CI; closed iff the CI of alpha* lies inside [0,1]. Report alpha* corpus and per drive-type; drives with dual < 0.05 kWh excluded from alpha* (undefined), counted.
- Battery node: B_in in [L + regen, U + regen] vs batt->trac (residual of the model); report the residual interval, labelled a residual, not a measurement.
- f_gen = G / trac_gross is unchanged by 2a (G and trac untouched): no thesis wording change from 2a. The 0.5 crossing is only addressed in 2b/2c.

## 2b. Pre-registered sensitivities that CAN move G (read-only, nothing is shipped from them)
- H5: re-run with kd = kc = 1 (no master anchoring) and with constant paux replaced by 0 and 2x; report delta in trac, G, f_gen.
- H6: shift the fuel-rate series by lag in {0, +2, +5} s (app-calculated rate lags HV current); report delta in G and f_gen.
- H7: I_offset_A_applied +/-1 A; report delta in G, trac, f_gen.
- Each reports f_gen with day-clustered CI and whether the CI crosses 0.5 (reported, never tuned). Disagreement between variants is reported as the method disagreement band.

## 2c. Constrained reconciliation (candidate A; sensitivity only, never primary)
Weighted least squares over (E_gen, G, gen->batt) with the node constraint G + gen->batt = E_gen; weights from the 2b spread (not assumed). Report where the adjustment lands (share on G vs gen->batt). If > 50% lands on G, flag "equivalent to tuning f_gen" and do not use.

## Decisions requested of the Director
1. Is alpha* in [0,1] an acceptable closure criterion, or should the interval alone (0 in X) be the rule? 2. Are the 2b variant ranges (lag 0/2/5 s, offset +/-1 A, paux 0/1x/2x) adequate? 3. May the Sankey be shown with an explicit "unallocated dual band" after the blind audit, or does it stay hidden until the F04/H5-H7 outcome is signed off by Andrii?

## Stop conditions
Any 2b variant that moves f_gen across 0.5 stops the milestone for Opus audit + Andrii sign-off before anything is shipped. Implementation (step 3) writes through additive splice only, with `fuel_recon.py --all` untouched.
