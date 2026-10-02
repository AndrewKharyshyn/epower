# M336 step 2 design (pre-registered before any code; rev 2: Director changes applied; work in progress)

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

## Rev 2 (Director verdict "revise": changes applied; these override the text above where they conflict)
- Rule hierarchy: the rev-2 spec rule (CI of excess/E_gen inside +/-5%) still applies and its step 1 result stays "not closed" (+6.4%, CI 4.9 to 8.6%). 2a ADDS the interval test (0 in X, same +/-5% tolerance) as the primary 2a rule; its outcome is worded "consistent within the dual bracket", never "closed". alpha* is a descriptor of the implied allocation (point about 0.62 = 1.666/2.688, exploratory until regenerated), not an estimate of the generator share of dual: it absorbs any error in E_gen or G. Its CI in [0,1] across all 2b variants is a secondary robustness check; per-drive alpha* outside [0,1] (infeasible drives) are counted and reported.
- Primary basis is the corpus ratio-of-sums; the dual<0.05 kWh per-drive exclusion is dropped as a primary basis (per-drive values exploratory only). Strata need >=10 distinct days (not drives); "mixed" (9 days) is therefore not evaluable.
- 2b additions: (i) E_gen levers BSFC surface, eta_gen, eta_pe varied over bounded ranges with a cited source (5% on E_gen moves alpha* by about 0.3); (ii) lag: include negative values and a per-drive cross-correlation lag estimate; lags shorter than the logger sample interval are uninformative and not reported as findings; (iii) offset +/-1 A justified from the observed zero-current distribution and carried through L, dual and regen, not only G/trac; (iv) paux = 0 is marked a non-physical bound; (v) a combined worst-case corner for the 0.5 test (one-at-a-time variants can miss a crossing).
- Stop condition (precise): baseline f_gen with day-clustered CI is reported first; stop if any variant's f_gen point estimate crosses 0.5 OR its CI newly contains 0.5 where the baseline does not.
- Added check: per-sample generator share inside dual samples (model Pgen_t vs battery charge power), independent of the residual definition.
- 2c: weights from the 2b spread on the same data are circular; always report the implied f_gen; the ">50% on G" threshold is dropped.
- Sankey (Director Q3): stays hidden. The 2026-10-02 owner decision requires closed generator branches; an unallocated band brackets, it does not close. A band version may be built behind `GtrFlowGate` (no Compare bypass); revealing it needs the blind audit, the H5-H7/BSFC outcome and Andrii's explicit sign-off.
- Scope labels: fuel-PID subset only (259 of 489; 224 without fuel PID), not generalised to the full corpus; basis raw/ is "provenance-sensitive" (F03).
- Thesis risk HIGH: E_gen/G scale errors move alpha* and f_gen; "battery majority" (about 53/47, residual-based) is not supported by 2a. Andrii sign-off required.

## Rev 3 (blind audit verdict "partial": changes applied)
- Mask: drives with NaN `I_offset_A_applied` or NaN charge-class columns are excluded and listed (3 drives); the published-recon NaN-offset defect is disclosed, not corrected here.
- Stop rule re-specified: the CI arm is vacuous when the baseline CI contains 0.5. The rule is now on POINT estimates: any variant or corner whose f_gen point estimate crosses 0.5 stops the milestone for Opus audit and Andrii sign-off; separately, the headline wording must state that the CI straddles 0.5 whatever the point estimates.
- Added anchoring-off companions for lag and offset; BSFC floor clipping and the offset/corner calibration caveats are disclosed; sensitivities are descriptive (no multiplicity control); the dual-sample check is a consistency check, not independent.
