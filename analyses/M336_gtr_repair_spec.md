# M336 GTR repair (audit F04/F20; proposed number, was M329): pre-registered spec rev 2 (Director changes applied; work in progress)

## Diagnosis (read-only, `fuel_recon_master.csv`, distance-weighted, 259 drives with generator + both branches, 2017.8 km; script-free exploratory; these figures (15.77/16.78/1.02, r=0.38) are exploratory targets only, never quoted; step 1 regenerates them by script)
- generator 15.77 = modelled generator electricity (fuel volume x assumed BSFC/eta_gen/eta_pe, per drive, fuel subset).
- gen->traction 8.52 (model: min(Pgen, Ptrac+) on the bus) + gen->battery 8.26 (master `charge_eng_only_kwh + charge_dual_kwh`, battery-terminal charge while engine on) = 16.78; excess +1.02 (6.5% of generator).
- excess > 0 in 88% of drives, median +1.75; urban +1.43 (n=241), others 0.2-0.5 (n=18). Excess correlates with gen->battery (r=0.38), weakly with generator (0.13).
- Likely mechanisms (hypotheses, not findings): (H1) engine-on charge columns include regen/coasting charge that coincides with engine-on (dual), so it is not generator output; (H2) battery-terminal vs bus energy (charge efficiency, aux load) mixed at one node; (H3) the three terms come from three unreconciled sources (fuel model, traction-power model, battery integration), so closure is not constrained.
- Battery node: in 2.96 + 8.26 = 11.22 vs out 9.78 (batt->traction), residual +1.44 (net SoC gain plus losses/aux), shown in the accounting table since M3xx.

## Aim and non-aim
Replace the "physical flow" impression with a node-balanced accounting whose residual is explicit and bounded; decide whether a closed Sankey can be shown. Not to tune parameters until the branches agree (CLAUDE.md: report method disagreement). f_gen may move; thesis wording ("battery majority") stays out until Opus audit + Andrii sign-off.

## Steps (each gated)
1. Tool `tools/gtr_closure_diag.py` (script-written JSON): per-drive and corpus excess, drive-type strata, day-clustered bootstrap CI (seed 42, 4000), test of H1 (excess vs engine-on regen/dual charge share) and H2 (excess vs charge-efficiency scale). Known-answer: reproduces 1.02 +/- rounding.
2. Candidate repairs, compared, not chosen by closure: (A) constrained reconciliation on a common mask (least squares with source-uncertainty weights; residual reported); (B) interval/unknown-branch representation (unidentified allocation kept as an interval); (C) keep accounting table + hidden Sankey (status quo).
3. Blind audit (analytical-auditor, Opus for thesis-level) of the chosen method; Director decision; Andrii sign-off for any change to f_gen or Sankey reveal.
4. Implementation via additive splice, `fuel_recon.py --all` consistency, CHANGELOG, language gate, release_check.
Stop: if H1-H3 are not separable on available columns, stop at (C) and report.

## Rev 2 (Director verdict "revise": changes applied)
- Decision rule (pre-registered): a node counts as closed when the 95% day-clustered percentile-bootstrap CI (seed 42, 4000) of excess/E_gen lies inside +/-5% AND the same holds in each drive-type stratum with n>=10. "H1-H3 not separable" (stop rule): the day-clustered CIs of the excess explained by each hypothesis-specific term overlap pairwise, or the covariates are collinear (|r|>0.9 / VIF>10).
- Step 1 pre-checks, in order: (a) one generator definition: per drive, E_gen (vol_by_regime/BSFC) vs sum(Pgen_t*dt) (H4); (b) model-internal gen->batt = sum(Pgen_t*dt) - gen->trac (closes by construction; diagnostic only) next to master charge_eng_only+charge_dual; the gap between them is the F04 quantity; (c) document the master `charge_dual_kwh` definition (does it include regen with engine on?) before testing H1; (d) pin one common mask (fuel subset AND both branches) and show every total on it.
- Added hypotheses: H4 generator node defined two ways (regime-volume vs per-sample flow); H5 separate kd/kc anchoring scales and constant paux break the per-sample bus balance; H6 app-calculated fuel-rate lag vs HV current shrinks min(Pgen,Ptrac+) overlap; H7 open battery-current sign/offset item (M258+). Hint to test, not a finding: gen->batt = E_gen - gen->trac would cut the battery residual to about +0.4.
- Repair ranking (Director): B (interval/unknown branch) first; A (constrained LS) only as a sensitivity because assumed weights can land silently on gen->trac (= tuning f_gen); C is the fallback, not a repair.
- Thesis risk HIGH: batt->trac is a residual (trac_gross - gen->trac), "battery majority" rests on about 53/47; any change to Pgen_t scale or overlap (H4, H6) can cross f_gen 0.5; f_gen stays model-derived; Andrii sign-off required before any f_gen or Sankey change.
