import sys, numpy as np, pandas as pd
d = pd.read_pickle(sys.argv[1]); d['dec'] = d.vprev - d.speed
pd.set_option('display.width', 200)
slow = d.cadence == 'slow'
def e(g): return 100*g.cap.sum()/g.ke.sum()
# fresh flags: native sample inside the step second bin (age<=1) for current speed / previous-row speed / all other channels
d['fresh_cur'] = d.age_spd <= 1; d['fresh_prev'] = d.age_spd_prev <= 1; d['fresh_oth'] = d[['age_I','age_V','age_rpm']].max(axis=1) <= 1
t = d.groupby(['cadence','fresh_cur','fresh_prev','fresh_oth']).apply(lambda g: pd.Series({'n': len(g), 'eff': e(g), 'dec': g.dec.mean(), 'ke_Wh': 1000*g.ke.mean(), 'zero_cap': (g.cap==0).mean()}), include_groups=False)
print(t.round(2))
# within-drive paired: per drive eff for amax<=1 vs 1<amax<=2 vs (2,5], KE-weighted across drives having both
for (lo, hi, nm) in [(1, 2, '1-2'), (2, 5, '2-5')]:
    a = d[d.amax <= 1].groupby('k'); b = d[(d.amax > lo) & (d.amax <= hi)].groupby('k')
    A = a.agg(cap0=('cap','sum'), ke0=('ke','sum'), n0=('cap','size')); Bm = b.agg(cap1=('cap','sum'), ke1=('ke','sum'), n1=('cap','size'))
    J = A.join(Bm, how='inner'); J = J[(J.n0 >= 30) & (J.n1 >= 30 if nm == '1-2' else J.n1 >= 3)]
    # pooled within-drive: weight by ke1
    print(f'within-drive pair (<=1 vs {nm}): drives {len(J)}  eff<=1 (ke1-weighted) {100*(J.cap0/J.ke0*J.ke1).sum()/J.ke1.sum():.2f} vs eff {nm} {100*J.cap1.sum()/J.ke1.sum():.2f}  n1 steps {int(J.n1.sum())}')
# all-channel fresh check vs temperature: do removed steps differ in T?
print('mean Tpack removed(2,5] vs kept', d.Tpack[(d.amax>2)&(d.amax<=5)].mean(), d.Tpack[d.amax<=2].mean())
# time-of-drive / what the age>2 gaps look like: gap between consecutive grid rows kept (gap col)
print('gap dist among age(2,5] steps:', d.gap[(d.amax>2)&(d.amax<=5)].value_counts().head(5).to_dict())
# share of removed(2,5] by day
r = d[(d.amax>2)&(d.amax<=5)]; print('days with removed', r.day.nunique(), 'top day share', r.day.value_counts(normalize=True).head(3).round(3).to_dict())
# drives: share of slow drives that have any removed
print('slow drives with any age>2:', d[slow & (d.amax>2)].k.nunique(), 'of', d[slow].k.nunique(), '; fast:', d[(d.cadence=='fast') & (d.amax>2)].k.nunique(), 'of', d[d.cadence=='fast'].k.nunique())
# speed-dependence of V2(2) removal
d['spb'] = pd.cut(d.speed,[0,10,20,40,60,80,200])
print((d.assign(rm=d.amax>2).groupby('spb',observed=True).rm.mean()*100).round(2).to_dict())
