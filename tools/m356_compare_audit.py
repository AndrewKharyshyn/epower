"""M356: script-written comparison of the author's phaseEnergy (analyses/M356_check.json) with the blind audit (analyses/M356_audit/result.json). Writes analyses/M356_audit/comparison.json."""
import json
M = json.load(open('analyses/M356_check.json', encoding='utf-8'))['phaseEnergy']; R = json.load(open('analyses/M356_audit/result.json', encoding='utf-8'))
out = {'auditSpeedSource': R['speed_src'], 'auditDrivesUsed': R['drives_used'], 'netEqDisMinusRegViolations': R['net_ne_dis_minus_reg'], 'cohorts': {}}
for c in ('all', 'warm', 'shoulder'):
    m, a = M[c], R[c]; row = {'nCycles': {'author': m['nCycles'], 'audit': a['n_cycles']}, 'additiveShare': {'author': m['additiveShare'], 'audit': a['additiveShare']}, 'windows': {}}
    for w in ('launch', 'creep', 'approach', 'cycle'):
        for k, ak in (('netWh', 'net'), ('dischargeWh', 'dis'), ('regenWh', 'reg')):
            e = m[w][k]; x = a[f'{w}_{ak}']
            row['windows'][f'{w}.{k}'] = {'authorMedian': e.get('median'), 'auditMedian': x['med'], 'absDiffWh': (None if e.get('median') is None else round(abs(e['median'] - x['med']), 2)),
                                           'authorIQR': [e.get('p25'), e.get('p75')], 'auditIQR': [x['p25'], x['p75']], 'authorN': e.get('n'), 'auditN': x['n']}
    out['cohorts'][c] = row
d = [v['absDiffWh'] for r in out['cohorts'].values() for v in r['windows'].values() if v['absDiffWh'] is not None]
out['maxAbsMedianDiffWh'] = max(d); out['medianAbsMedianDiffWh'] = sorted(d)[len(d) // 2]
out['bootCycleNetCI'] = {'author': M['all']['cycle']['netWh']['bootMedian']['ci95'], 'audit': R['boot_median_cycle_net']}
json.dump(out, open('analyses/M356_audit/comparison.json', 'w', encoding='utf-8', newline='\n'), indent=1)
print(json.dumps({k: out[k] for k in ('maxAbsMedianDiffWh', 'medianAbsMedianDiffWh', 'bootCycleNetCI')}), {c: out['cohorts'][c]['nCycles'] for c in out['cohorts']})

# ---- --splice: store the audit disagreement in the payload (script-written, never typed; reported, not tuned) ----
import sys
if "--splice" in sys.argv:
    A = json.load(open('summary_arrays.json', encoding='utf-8'))
    def blk(c):
        r = out['cohorts'][c]
        return {'source': 'analyses/M356_audit (blind Sonnet reproduction, own 1 Hz resampling: bin mean + forward-fill limit 3 s, midnight wrap)',
                'nCycles': r['nCycles'], 'additiveShare': r['additiveShare'], 'maxAbsMedianDiffWh': max(v['absDiffWh'] for v in r['windows'].values() if v['absDiffWh'] is not None),
                'cycleNetBootCI95': (out['bootCycleNetCI'] if c == 'all' else None), 'netEqDischargeMinusRegViolations': out['netEqDisMinusRegViolations'],
                'note': 'Disagreement is reported, not tuned: differences come from resampling and segmentation edge handling; the audit rounds additiveShare to 2 dp and includes 9 cycles of the 2 below-support Cold drives in All.'}
    A['crawlStopGo']['phaseEnergy']['blindAudit'] = blk('all')
    for c in ('all', 'warm', 'shoulder'):
        A['seasonalCharts']['charts']['CrawlStopGo']['data'][c]['phaseEnergy']['blindAudit'] = blk(c)
    with open('summary_arrays.json', 'w', encoding='utf-8', newline='\n') as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
    print('blindAudit spliced')
