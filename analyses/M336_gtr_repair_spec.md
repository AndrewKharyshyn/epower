# M336 GTR repair (audit F04/F20; proposed number, was M329): pre-registered spec rev 1 (work in progress: Director review pending)

## Diagnosis (read-only, `fuel_recon_master.csv`, distance-weighted, 259 drives with generator + both branches, 2017.8 km; script-free exploratory, to be re-run by a tool in step 1)
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
