# M471 spec (pre-registered): energy-consistent corpus efficiency reducer for the GTR headline (audit 2026-10-21, F01)

Status: METHOD CHANGE of a headline reducer. Gates: pre-registered spec (this file), blind audit (analytical-auditor, claim + data path only), Director ruling, owner awareness (GTR figures change by about 0.4 % relative). Not article-bound.

## Defect (confirmed on disk this session)
`wire_gtr_seasonal.aggregate` sets `etaEng = round(wavg(eta_eng), 3)` and `etaBus = round(wavg(eta_fuel_bus), 3)` (distance-weighted MEANS of per-drive ratios) and then `engineBrake = fuelChem * etaEng`. A mean of per-drive ratios is not the ratio of corpus energy totals. `fGen` is already a ratio of sums (kept), `etaTankToTraction = wavg(traction_net)/wavg(fuel_chem)` is already a ratio of totals (kept; its key stays, see below).

## Estimands (definitions, distance-weighted sums are the energy totals per 100 km x km)
- eta_eng = sum_i E_engine,i / sum_i E_fuel,i, with E_engine,i/100km = eta_eng,i x fuel_chem,i (the per-drive CSV column `engine_brake_kWh_100` when present, else this product; eta_eng,i carries 4 decimals in `fuel_recon_master.csv`, relative error about 1e-4, 40x below the effect).
- eta_bus (generator bus / chemical fuel) = sum_i E_gen,i / sum_i E_fuel,i.
- engine brake kWh/100 km = etaEng (unrounded) x the headline fuel rate (a ratio estimator: the complete-case ratio is applied to the drives with a null per-drive engine ratio; Director ruling); engineLoss = fuel - engine brake; genpeLoss = engine brake - generator (all from unrounded values, rounded once for display).
- Complete-case rule (blind audit): eta_eng_i is null on 30 of 376 eligible drives (engine energy unknown, not zero). etaEng uses only drives with a per-drive ratio (346 drives / 65 days / 3696.1 km); etaBus uses the headline support (376 / 67 days / 3723.6 km). The two supports are stated beside the values (`commonSupport`).
- `etaTankToTraction` keeps its key (no payload-key rename, M326 rule). It is the NET traction-bus / chemical-fuel index (ratio of totals); a new `estimands` block names it explicitly and adds `grossTractionBusPerFuel` (= tractionGross / fuelChem, a different quantity), so a consumer cannot misread the key. Wheel efficiency is not measured.
- `commonSupport`: headline support (drives, km) beside the support of the battery branches (genToBatt / regenToBatt: drives with both non-null), and the dropped drives/km, so branch rates are not compared as one conserved network.

## Known-answer targets (audit reconstruction from the published per-drive table, 376 canonical-clean drives, 3723.6 km; audit rounding remainder tolerated at 5e-4 absolute)
| quantity | shipped | target |
|---|---|---|
| engine brake / chemical fuel | 0.356 | 0.35469 |
| generator bus / chemical fuel | 0.330 | 0.32854 |
| engine brake kWh/100 km | 17.23 | 17.16275 |
| fGen | 0.518 | 0.518 (unchanged, ratio of sums) |
| net traction-bus / fuel | 0.287 | 0.28654 (unchanged definition) |
Independent reproduction this session from `fuel_recon_master.csv` (script, not typed): 0.354695, 0.328538, 17.162749, 0.286540 — equal to the audit's values.

## Scope
1. `wire_gtr_seasonal.py`: reducers + `estimands` + `commonSupport` in `aggregate()` (headline "all", Warm, Shoulder, Cold use the SAME reducer).
2. `sensitivity_gtr.py` and `tools/m373_point.py` (live O-run): per-axis `etaBus` becomes the ratio of sums so the sensitivity BASE equals the live headline (the BASE gate of `tools/gtr_family_refresh_splice.py` compares them); the frozen one-off `tools/m375_expected.py` is NOT edited.
3. `refresh_gtr_headline.py` re-run on the live merged frame; glossary rows stay bound to `corpus.etaEng` / `corpus.etaBus`.
4. Dashboard: a small common-support table beside the flow sketch (additive; the Sankey stays visible by default, owner decision 2026-10-21 / M360); wording per the language gate.
5. Tests: two-drive known-answer (different fuel per km and efficiency: mean-of-ratios != ratio-of-sums), the 376-drive targets, cohort consistency (every cohort uses the same reducer), invariance of fGen and etaTankToTraction.

## Not in scope
`fuel_recon.py --all` regeneration of the master (the reducer derives engine energy from existing columns; adding an unrounded `engine_brake_kWh_100` column is a follow-up at the next regeneration), the Path A crossval (carried, historic), any change of BSFC, offsets or eligibility.

## Escalation
Blind audit (independent reproduction of the targets and of the cohort values from the CSV, resampling not involved: deterministic arithmetic). Director: confirm "ratio of sums" as the estimand, the display rounding, the common-support presentation, and that no CI is attached (point reducers, as before). Any GTR estimate leaving its previous CI, or a flipped reading (sensitivity f_gen >= 0.5 acknowledgements are frozen and bound to the O-axes hash) goes to the Director; the f_gen axis values must NOT change.

## Addendum: audit and ruling (recorded in the CHANGELOG M471 entry)
- Blind audit (analytical-auditor, claim + data path only, own script): every headline and regime value reproduced (whole set 0.3547 / 0.3285 / 17.1627 / 31.2246 / 1.2657 / 0.2865 / 0.3780 / 0.5181; warm 0.3576 / 0.3312; shoulder 0.3512 / 0.3253 / 16.9258; cold 0.3581 / 0.3317 / 19.5938). Concern raised and resolved: eta_eng null on 30 drives (the numerator would skip them while the denominator kept them) -> complete-case rule above, rounded values unchanged. NaN ens_outlier_v2 (12 rows) is treated as not excluded, as in `eligibility.py`.
- Director ruling: ACCEPT. Conditions met: supports stated (drives, days, km) beside the values; the engineBrake estimator named in `estimands`; f_gen axis values and the frozen O-axes acknowledgement unchanged (checked leaf by leaf by `tools/m471_etabus_splice.py`); cold stays exploratory without an interval; point reducers carry no CI (a deviation from the standing CI+n rule, follow-up: day-clustered bootstrap, seed 42, 4000 draws, new spec). Wording: 'ratio of corpus energy totals' / 'reducer change (estimand made energy-consistent)', never 'corrected' or 'error'; etaBus is the generator-bus/fuel ratio, not a traction index.
- Follow-ups (not in M471): unrounded `engine_brake_kWh_100` at the next `fuel_recon.py --all`; root cause of the null eta_eng drives; CI for the three ratios.
