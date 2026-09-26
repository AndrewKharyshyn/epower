"""
M255: wire generatorTractionRecon (§4b) into the season/thermal-regime cohort
system. Verified aggregation method (reverse-derived from the M248 CHANGELOG
entry and confirmed byte-exact against the shipped corpus-wide headline
before being applied to cohort subsets):
  - "clean" = f_gen not NaN.
  - absolute-energy figures + efficiency ratios: distance-weighted mean
    (equivalently, ratio-of-sums: sum(rate_i*dist_i)/sum(dist_i)).
  - f_gen itself: ratio-of-sums of gen_to_traction / traction_gross
    (NOT the distance-weighted mean of the per-drive f_gen column — those
    differ, 0.602 vs 0.613 on the corpus-wide set).
  - genToBatt/regenToBatt: same distance-weighted mean, but computed on the
    subset with those two columns additionally non-null (2 extra NaNs each
    in the corpus-wide set).
  - etaTankToTraction: wavg(traction_net) / wavg(fuel_chem).
  - engineBrake = fuelChem * etaEng; engineLoss = fuelChem - engineBrake;
    genpeLoss = engineBrake - generatorElec (generatorElec == corpus.generator).
Reproduces the shipped corpus-wide figures (135/138, 1391.2 km; generator
15.92, tractionGross 23.88, fGen 0.602, etc.) to the last shipped digit.
"""
import json, pandas as pd

fr = pd.read_csv('fuel_recon_master.csv')
sdm = pd.read_csv('seasonal_drive_master.csv')[['file', 'thermal_regime']]
merged = fr.merge(sdm, on='file', how='left')
assert merged['thermal_regime'].isna().sum() == 0, "unmatched fuel-recon drives"

d = json.load(open('summary_arrays.json'))
cohort_counts = d['seasonalCharts']['_meta']['cohortCounts']

def wavg(frame, col):
    w = frame['distance_km']
    return (frame[col] * w).sum() / w.sum()

def aggregate(subset, cohort_label, corpus_total_n):
    nProduction = len(subset)
    clean = subset[subset['f_gen'].notna()].copy()
    nDrives = len(clean)
    if nDrives == 0:
        return None
    km = round(clean['distance_km'].sum(), 1)

    generator = round(wavg(clean, 'generator_kWh_100'), 2)
    tractionGross = round(wavg(clean, 'traction_gross_kWh_100'), 2)
    genToTraction = round(wavg(clean, 'gen_to_traction_kWh_100'), 2)
    battToTraction = round(wavg(clean, 'batt_to_traction_kWh_100'), 2)
    fuelL = round(wavg(clean, 'fuel_L_per_100km'), 2)
    fuelChem = round(wavg(clean, 'fuel_chem_kWh_100'), 2)
    etaEng = round(wavg(clean, 'eta_eng'), 3)
    etaBus = round(wavg(clean, 'eta_fuel_bus'), 3)
    tractionNet = wavg(clean, 'traction_net_kWh_100')
    etaTankToTraction = round(tractionNet / wavg(clean, 'fuel_chem_kWh_100'), 3)

    sum_g2t = (clean['gen_to_traction_kWh_100'] * clean['distance_km']).sum()
    sum_tg = (clean['traction_gross_kWh_100'] * clean['distance_km']).sum()
    fGen = round(sum_g2t / sum_tg, 3)

    gb = clean.dropna(subset=['gen_to_batt_kWh_100', 'regen_to_batt_kWh_100'])
    genToBatt = round(wavg(gb, 'gen_to_batt_kWh_100'), 2) if len(gb) else None
    regenToBatt = round(wavg(gb, 'regen_to_batt_kWh_100'), 2) if len(gb) else None

    engineBrake = round(fuelChem * etaEng, 2)
    engineLoss = round(fuelChem - engineBrake, 2)
    generatorElec = generator
    genpeLoss = round(engineBrake - generatorElec, 2)

    corpus = dict(generator=generator, tractionGross=tractionGross, fGen=fGen,
                  fuelL=fuelL, fuelChem=fuelChem, etaEng=etaEng, etaBus=etaBus)
    flows = dict(fuelChem=fuelChem, engineBrake=engineBrake, engineLoss=engineLoss,
                 generatorElec=generatorElec, genpeLoss=genpeLoss,
                 genToTraction=genToTraction, battToTraction=battToTraction,
                 tractionGross=tractionGross, genToBatt=genToBatt,
                 regenToBatt=regenToBatt, etaTankToTraction=etaTankToTraction)

    dts = []
    for typ, g in clean.groupby('drive_type'):
        n = len(g)
        kmT = round(g['distance_km'].sum(), 1)
        tg = wavg(g, 'traction_gross_kWh_100')
        g2t = wavg(g, 'gen_to_traction_kWh_100')
        b2t = wavg(g, 'batt_to_traction_kWh_100')
        s_g2t = (g['gen_to_traction_kWh_100'] * g['distance_km']).sum()
        s_tg = (g['traction_gross_kWh_100'] * g['distance_km']).sum()
        dts.append(dict(type=typ, n=n, km=kmT, tractionGross=round(tg, 2),
                         genToTraction=round(g2t, 2), battToTraction=round(b2t, 2),
                         fGen=round(s_g2t / s_tg, 4)))
    order = {'urban': 0, 'mixed': 1, 'mixed_highway': 2, 'highway': 3}
    dts.sort(key=lambda x: order.get(x['type'], 9))

    basis = (f"Path B (fuel flow \u2192 RPM/load-conditioned BSFC surface \u2192 "
             f"generator \u2192 DC-bus balance), {nDrives} clean / {nProduction} "
             f"fuel-instrumented drives, {km} km \u2014 {cohort_label} cohort "
             f"({corpus_total_n} drives in cohort corpus-wide).")

    return dict(nProduction=nProduction, nDrives=nDrives, kmProduction=km,
                corpus=corpus, flows=flows, driveTypeSplit=dts, basis=basis,
                productionCheck=dict(distWtGenerator=generator, nAll=corpus_total_n))

R = d['generatorTractionRecon']
data_all = dict(nProduction=R['nProduction'], nDrives=R['nDrives'],
                 kmProduction=R['kmProduction'], corpus=R['corpus'], flows=R['flows'],
                 driveTypeSplit=R['driveTypeSplit'], basis=R['basis'],
                 productionCheck=R['productionCheck'])

data_warm = aggregate(merged[merged['thermal_regime'] == 'warm'], 'Warm', cohort_counts['warm'])
data_shoulder = aggregate(merged[merged['thermal_regime'] == 'shoulder'], 'Shoulder', cohort_counts['shoulder'])
# no cold drives anywhere in the corpus yet (cohortCounts.cold == 0) -- explicit
# null with the same convention ColdNoData/ cohortOr expect, not a fabricated zero.
data_cold = None

entry = dict(
    dependencyClass="thermal",
    pipelineClass="master",
    statisticalUnit=("Fuel/BSFC-reconstructed generator\u2192traction electrical energy "
                      "(Path B, model-derived, not measured); f_gen = generator-coincident "
                      "share of gross traction demand; clean = f_gen not NaN."),
    data=dict(all=data_all, warm=data_warm, shoulder=data_shoulder, cold=data_cold),
)

d['seasonalCharts']['charts']['GeneratorTractionRecon'] = entry
print('warm:', json.dumps(data_warm, indent=2))
print()
print('shoulder:', json.dumps(data_shoulder, indent=2))

with open('summary_arrays.json', 'w') as f:
    json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
print()
print('seasonalCharts.charts now has', len(d['seasonalCharts']['charts']), 'entries')
