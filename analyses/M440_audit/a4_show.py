import json,sys
r=json.load(open(sys.argv[1], encoding='utf-8'))
f=lambda x: 'NA' if x is None else f'{x:.2f}'
for v in ['V1','V2_2','V2_5','V2_10','V3','V5']:
    x=r[v]; print(v,'removed',x['steps_removed'],'ret share %.4f'%x['steps_retained_share'],'KE ret %.4f'%x['ke_retained_share'],'drives w removed',x['drives_with_removed'],x.get('cadence_retained_share'))
    for sec in ['temp','speed']:
        for l,c in x[sec].items():
            if c['n0']<10: continue
            print('  ',sec,l,'n0',c['n0'],'n',c['n'],f(c['eff0']),'->',f(c['eff']),'D',f(c['delta']),'rem',c.get('n_removed'),'effrem',f(c.get('eff_removed')),'ci',None if not c.get('ci') else [round(z,2) for z in c['ci']],'nd',c.get('ndays'),'idErr',c.get('identity_err'))
x=r['V4']; print('V4',x['share_steps_change_bin'],x['ke_moved_up'],x['ke_moved_down'])
for l,c in x['speed'].items(): print('  ',l,c['n0'],c['n'],f(c['eff0']),'->',f(c['eff']),'D',f(c['delta']),c.get('ci'))
x=r['V6']
for sec in ['temp','speed']:
    for l,c in x[sec].items(): print('V6',sec,l,f(c['eff0']),'->',f(c['eff']),'shift',f(c['shift_pp']),c.get('ci'))
print(r['VCa_exclusions']['retained_share'])
for l,c in r['VCa_exclusions']['temp'].items(): print('VCa',l,f(c['delta']),c.get('ci'))
