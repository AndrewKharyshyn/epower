"""M435 audit: observable-marker check of independent key-off (temperature progress at 120/300 s vs subsequent stopping), and ffill-0 population change.
Usage: python -X utf8 review2.py <rec.csv> <diag.csv> <out.json>"""
import sys, json, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import analyze as A
from scipy import stats as ss
import statsmodels.api as sm
r = pd.read_csv(sys.argv[1], encoding='utf-8', low_memory=False)
dg = pd.read_csv(sys.argv[2], encoding='utf-8', low_memory=False)
out = {}
out['ff0_vs_ff3_status'] = pd.crosstab(r.ff3_status, r.ff0_status).to_dict()
# why ff0 drops: valid coolant seconds under ff0 for the 13 dropped
dropped = r[(r.ff3_status == 'cold') & (r.ff0_status != 'cold')]
out['ff0_dropped'] = dict(n=len(dropped), ncool_ff0_range=[int(dropped.ff0_ncool.min()), int(dropped.ff0_ncool.max())], ncool_ff3_median=float(dropped.ff3_ncool.median()))
for fl, thr, hs in (('cool', 80, ((120, 300), (300, 600), (600, 900))), ('oil', 70, ((120, 300), (300, 600), (600, 900)))):
    base = A.prep(r, 3, fl, thr).merge(dg, on='file', how='left')
    o = {}
    for h0, h1 in hs:
        v = base[f'{fl}_v{h0}'] if f'{fl}_v{h0}' in base else None
        if v is None: continue
        # at risk at h0: observed to h0 (t >= h0). event at exactly h0 counted as at risk
        m = (base.t >= h0) & v.notna() & ~((base.ev == 1) & (base.t <= h0))
        b = base[m].copy(); b['v'] = v[m]; b['gain'] = b.v - b.startc
        b['out'] = np.where((b.ev == 0) & (b.t < h1), 'stop', np.where((b.ev == 1) & (b.t <= h1), 'reach', 'cont'))
        res = {k: dict(n=int(len(g)), v_med=float(g.v.median()), gain_med=float(g.gain.median())) for k, g in b.groupby('out')}
        # logistic: stop in (h0,h1] vs not stop, among at risk, on current temp and start temp
        y = (b.out == 'stop').astype(float)
        X = sm.add_constant(b[['v', 'startc']].astype(float))
        try:
            fit = sm.Logit(y, X).fit(disp=0)
            res['logit_stop_on_v_and_start'] = dict(coef_v=float(fit.params['v']), p_v=float(fit.pvalues['v']), coef_start=float(fit.params['startc']), p_start=float(fit.pvalues['startc']))
        except Exception as e:
            res['logit_err'] = repr(e)
        # day-cluster robust
        try:
            fit = sm.Logit(y, X).fit(disp=0, cov_type='cluster', cov_kwds={'groups': pd.factorize(b.day)[0]})
            res['logit_cluster_p_v'] = float(fit.pvalues['v'])
        except Exception as e:
            res['logit_cluster_err'] = repr(e)
        # gain: short trips vs long trips (eventual distance) at the same elapsed time
        b['short'] = b.dist < 5
        res['by_distance_lt5km'] = {str(k): dict(n=int(len(g)), gain_med=float(g.gain.median())) for k, g in b.groupby('short')}
        o[f'{h0}->{h1}'] = res
    # trips that stop: how many are short by distance
    out[f'{fl}{thr}'] = o
    c = base[base.ev == 0]
    out[f'{fl}{thr}_censored_dist_lt5km_share'] = float((c.dist < 5).mean())
    out[f'{fl}{thr}_reached_dist_lt5km_share'] = float((base[base.ev == 1].dist < 5).mean())
json.dump(out, open(sys.argv[3], 'w', encoding='utf-8'), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
