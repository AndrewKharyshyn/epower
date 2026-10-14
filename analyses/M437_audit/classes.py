"""Reading classes (M435 C4) at h=600 per F and headline cell, from own records + own bootstrap (seed 42, 4000, per-cell day resamples).
Usage: python -X utf8 classes.py <rec437.csv> <out.json>"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'M435_audit'))
import numpy as np, pandas as pd
import analyze as A
r = pd.read_csv(sys.argv[1], encoding='utf-8', low_memory=False)

def prep(F, fl, thr):
    p = f'f{F}_'; c = f'{p}{fl}{thr}_'
    d = r[r[p + 'status'] == 'cold']; d = d[d[c + 'ev'].notna()]
    ev = d[c + 'ev'].values.astype(int)
    return pd.DataFrame(dict(day=d.date.astype(str).values, ev=ev, t=np.where(ev == 1, d[c + 'T'].values, d[c + 'last'].values)))
out = {}
for F in (0, 3, 6):
    for fl, thr in (('cool', 80), ('oil', 70)):
        d = prep(F, fl, thr)
        pt = A.stats(d.t.values, d.ev.values, 600)
        B = A.boot(d, (600,))[600]
        ci = lambda k: [round(float(np.percentile(B[k], 2.5)), 4), round(float(np.percentile(B[k], 97.5)), 4)]
        o = dict(point={k: round(float(pt[k]), 4) for k in ('F_km', 'F_low', 'F_high', 'F_theta0.5', 'F_theta2')},
                 ci={k: ci(k) for k in ('F_km', 'F_low', 'F_high', 'F_theta0.5', 'F_theta2')})
        Rp_bounds = o['ci']['F_high'][1] < 0.5
        Rp_theta = o['ci']['F_theta2'][1] < 0.5
        Rm_bounds = o['ci']['F_low'][0] >= 0.5
        Rm_theta = o['ci']['F_theta0.5'][0] >= 0.5
        o['R+ (F<0.5)'] = 'bounds' if Rp_bounds else ('theta0.5-2' if Rp_theta else 'depends')
        o['R- (F>=0.5)'] = 'bounds' if Rm_bounds else ('theta0.5-2' if Rm_theta else 'depends')
        out[f'F{F}_{fl}{thr}'] = o
        print(F, fl, thr, json.dumps(o))
json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), indent=1)
