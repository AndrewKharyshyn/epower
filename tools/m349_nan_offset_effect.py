"""M349: effect of the NaN battery-current offset on the published fuel_recon rows (read-only; writes analyses/M349_effect.json only).
fuel_recon.py: float(master.get('I_offset_A_applied') or 0.0) keeps NaN -> NaN battery power -> zero in the traction sum -> f_gen = 1.
Variants for the affected published rows: published (control), exclude, offset = corpus constant, offset = 0.
The aggregation is the verified wire_gtr_seasonal.aggregate (its source is exec'd; importing the module would rewrite summary_arrays.json)."""
import ast, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
import fuel_recon as FR, recon_engine as RE

src = open('wire_gtr_seasonal.py', encoding='utf-8').read()
tree = ast.parse(src)
ns = {'pd': pd, 'json': json, 'np': np}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in ('wavg', 'aggregate'):
        exec(compile(ast.Module([node], []), 'wire_gtr_seasonal.py', 'exec'), ns)
aggregate = ns['aggregate']

dm = pd.read_csv(RE.BASE + 'drive_master.csv')
m = {r['file']: r for _, r in dm.iterrows()}
fr = pd.read_csv('fuel_recon_master.csv')
sdm = pd.read_csv('seasonal_drive_master.csv')[['file', 'thermal_regime']]
arr = json.load(open('summary_arrays.json', encoding='utf-8'))
cc = arr['seasonalCharts']['_meta']['cohortCounts']
stored = arr['generatorTractionRecon']['corpus']

nan_off = set(dm.loc[dm['I_offset_A_applied'].isna(), 'file'])
affected = [f for f in fr['file'] if f in nan_off]
const = float(dm['I_offset_A_applied'].dropna().median())
uniq = int(dm['I_offset_A_applied'].dropna().round(6).nunique())

def agg(frame, label='All'):
    mm = frame.merge(sdm, on='file', how='left')
    a = aggregate(mm, label, cc['all'])
    return {'nProduction': a['nProduction'], 'nDrives': a['nDrives'], 'km': a['kmProduction'], 'corpus': a['corpus'],
            'genToTraction': a['flows']['genToTraction'], 'battToTraction': a['flows']['battToTraction']}

out = {'affectedPublishedRows': affected, 'nanOffsetDrivesInMaster': len(nan_off), 'appliedOffsetDistinctValues': uniq,
       'corpusConstantOffsetA': const, 'storedCorpus': stored, 'variants': {}, 'perDrive': {}}
out['variants']['published_control'] = agg(fr)
out['variants']['exclude'] = agg(fr[~fr['file'].isin(affected)])
for lab, off in (('offset_corpus_constant', const), ('offset_zero', 0.0)):
    rows = []
    for f in affected:
        r = FR.reconstruct(f, m[f], off)
        out['perDrive'][f + '|' + lab] = None if r is None else {k: r[k] for k in ('distance_km', 'gen_to_traction_kWh_100', 'batt_to_traction_kWh_100', 'traction_gross_kWh_100', 'f_gen')}
        if r: rows.append(r)
    new = pd.concat([fr[~fr['file'].isin(affected)], pd.DataFrame(rows)], ignore_index=True)
    out['variants'][lab] = agg(new)
out['controlMatchesStored'] = all(abs(out['variants']['published_control']['corpus'][k] - stored[k]) < 1e-9 for k in stored)
for f in affected:
    r = fr[fr['file'] == f].iloc[0]
    out['perDrive'][f + '|published'] = {k: float(r[k]) for k in ('distance_km', 'gen_to_traction_kWh_100', 'batt_to_traction_kWh_100', 'traction_gross_kWh_100', 'f_gen')}
json.dump(out, open('analyses/M349_effect.json', 'w', encoding='utf-8', newline='\n'), indent=1)
print(json.dumps({'control': out['controlMatchesStored'], 'affected': affected, 'const': const, 'distinctOffsets': uniq}, indent=0))
for k, v in out['variants'].items(): print(k, v['nProduction'], v['nDrives'], v['km'], v['corpus']['fGen'], v['genToTraction'], v['battToTraction'], v['corpus']['tractionGross'])
