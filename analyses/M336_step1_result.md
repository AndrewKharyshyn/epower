# M336 step 1 result (script-written: `tools/gtr_closure_diag.py` -> `M336_closure_diag.json`, `M336_closure_perdrive.csv`)

Basis: raw/ via XT_RAW_DIR (F03 published-pipeline basis), canonical-clean, fuel PID, one common mask: 259 drives, 50 days, 2003.0 km. kWh/100 km, ratio of sums; CIs day-clustered percentile bootstrap (seed 42, 4000).

| Quantity | Estimate | 95% CI | Closed (rule +/-5%)? |
|---|---|---|---|
| excess = gen->trac + gen->batt(master eng-only + dual) - generator, / generator | +6.4% (1.025) | 4.9 to 8.6% | no |
| same with gen->batt = eng-only only (dual removed) | -10.4% (-1.66) | -13.3 to -8.1% | no |
| generator node, regime-volume vs per-sample (H4) | 0.000 | 0 | yes: one definition |
| urban stratum (n=241) / mixed (n=11) | +8.9% / +3.3% | 7.7-10.4 / 2.5-4.0 | no / yes |

Findings: (1) H4 is rejected: E_gen equals sum(Pgen_t*dt) in every drive. (2) The master gen->batt term (8.32) contains 32% `charge_dual_kwh` (engine on AND torque-verified regen); per-drive excess correlates with the dual share (r=0.61, exploratory). (3) Excluding dual overshoots to -10.4%, so the generator share of dual lies between 0 and 100%: the F04 quantity is bracketed, not resolved, by the available columns; the model-internal gen->batt (7.30, closes by construction) lies inside the bracket and reduces the battery residual from +1.45 to +0.43. (4) Excess is positive in 88% of drives. Not yet tested: H5-H7. This supports the Director ranking: an interval/unknown-branch representation (B) with dual as the unallocated band; no f_gen change is proposed by step 1 (gen->trac is untouched).
