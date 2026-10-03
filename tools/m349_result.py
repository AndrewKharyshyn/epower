"""M349 result: allow-list + known-answer verification of the NaN-offset control build (reads analyses/M349_deepdiff.json,
analyses/M349_effect.json, fuel_recon_offset_report.json, current artefacts); writes analyses/M349_result.json. Exit 1 on any failure."""
import hashlib, json, re, sys
import pandas as pd
diff = json.load(open('analyses/M349_deepdiff.json', encoding='utf-8'))
eff = json.load(open('analyses/M349_effect.json', encoding='utf-8'))
rep = json.load(open('fuel_recon_offset_report.json', encoding='utf-8'))
arr = json.load(open('summary_arrays.json', encoding='utf-8'))
V = eff['variants']['offset_corpus_constant']
allow = re.compile(r'^/(generatorTractionRecon/(corpus|flows|driveTypeSplit\[0\])/|generatorTractionRecon/glossary\[(0|8)\]/value$|seasonalCharts/charts/GeneratorTractionRecon/data/(all|warm)/(corpus|flows|driveTypeSplit\[0\])/|fuelContract/inputs/fuelReconMasterMd5$|_artifactStamps/fuelContract/(generatedAt|upstreamHashes/fuelReconMasterMd5)$)')
bad = [d[0] for d in diff if not allow.match(d[0])]
R = arr['generatorTractionRecon']
checks = {
 'allLeafDifferencesAllowListed': not bad, 'disallowedLeaves': bad, 'nLeafDifferences': len(diff),
 'headlineEqualsEffectTable': (R['corpus']['fGen'] == round(V['corpus']['fGen'], 3) and R['corpus']['tractionGross'] == V['corpus']['tractionGross']
                               and R['flows']['genToTraction'] == V['genToTraction'] and R['flows']['battToTraction'] == V['battToTraction']),
 'shoulderUnchanged': not any('/data/shoulder/' in d[0] for d in diff),
 'gtrClosureUnchanged': not any('gtrClosure' in d[0] for d in diff),
 'driveMasterMd5': hashlib.md5(open('drive_master.csv', 'rb').read()).hexdigest(),
}
checks['driveMasterMd5Unchanged'] = checks['driveMasterMd5'] == 'bd9d10726bb064d857cf9ff98d2b7338'
fr = pd.read_csv('fuel_recon_master.csv')
checks['rowsBatt0Fgen1After'] = fr.loc[(fr['batt_to_traction_kWh_100'] == 0) & (fr['f_gen'] == 1), 'file'].tolist()
checks['offsetReport'] = rep
checks['fGenBootstrap'] = {k: eff['variants'][k]['fGenBoot'] for k in eff['variants']}
checks['ok'] = bool(checks['allLeafDifferencesAllowListed'] and checks['headlineEqualsEffectTable'] and checks['shoulderUnchanged'] and checks['gtrClosureUnchanged']
                    and checks['driveMasterMd5Unchanged'] and not checks['rowsBatt0Fgen1After'] and rep['nDistinctOffsets'] == 1 and rep['nCalibrated'] == 475)
json.dump(checks, open('analyses/M349_result.json', 'w', encoding='utf-8', newline='\n'), indent=1)
print(json.dumps({k: checks[k] for k in checks if k not in ('fGenBootstrap', 'offsetReport')}, indent=1))
sys.exit(0 if checks['ok'] else 1)
