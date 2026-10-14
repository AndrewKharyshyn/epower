import sys, json, numpy as np, pandas as pd
d = pd.read_pickle(sys.argv[1]); drv = pd.read_pickle(sys.argv[2])
REPO = r"C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo"
dm = pd.read_csv(REPO + r'\drive_master.csv', encoding='utf-8')
pd.set_option('display.width', 220); pd.set_option('display.max_columns', 40)
R = {}
d['dec'] = d.vprev - d.speed
# exact removal shares
for k in [2, 5, 10]:
    keep = d.amax <= k
    print(f'V2({k}) steps removed {int((~keep).sum())} = {100*(~keep).mean():.3f}%  KE removed {100*d.ke[~keep].sum()/d.ke.sum():.3f}%')
keep3 = d.gap == 1; print('V3 steps removed', int((~keep3).sum()), f'{100*(~keep3).mean():.4f}% ; KE removed {100*d.ke[~keep3].sum()/d.ke.sum():.3f}%')
keep5 = d.nprobe == 4; print('V5 steps removed', int((~keep5).sum()), f'{100*(~keep5).mean():.3f}%  (of steps with Tpack: {100*(~keep5 & d.Tpack.notna()).sum()/d.Tpack.notna().sum():.3f}%)')
print('V1 removed', int(d.rpm_nan.sum()), 'drives', d.k[d.rpm_nan].nunique())
# (a) age 2-5 removed set
rem = (d.amax > 2) & (d.amax <= 5); print('\nremoved age(2,5] n', int(rem.sum()))
slow = d.cadence == 'slow'
print('share of removed on slow drives', (slow & rem).sum() / rem.sum(), ' ; share of all steps on slow drives', slow.mean())
print('removed age>5 n', int((d.amax > 5).sum()), 'share slow', float((slow & (d.amax > 5)).sum() / (d.amax > 5).sum()))
# which channel exceeds 2 s
for c in ['age_spd', 'age_spd_prev', 'age_I', 'age_V', 'age_rpm']:
    print(' channel', c, ' >2s:', int((d[c] > 2).sum()), ' only this channel:', int(((d[c] > 2) & (d[['age_spd', 'age_spd_prev', 'age_I', 'age_V', 'age_rpm']].drop(columns=c) <= 2).all(axis=1)).sum()))
# profile by age band
d['band'] = pd.cut(d.amax, [-1, 1, 2, 3, 4, 5, 1e8], labels=['<=1', '1-2', '2-3', '3-4', '4-5', '>5'])
def prof(g):
    return pd.Series({'n': len(g), 'eff': 100*g.cap.sum()/g.ke.sum(), 'speed': g.speed.mean(), 'decel_kmh': g.dec.mean(), 'ke_mean_Wh': 1000*g.ke.mean(), 'I_mean': g.I.mean(), 'frac_zero_cap': (g.cap == 0).mean(), 'nd': g.day.nunique()})
print('\nALL drives by max-age band'); print(d.groupby('band', observed=True).apply(prof, include_groups=False).round(3))
print('\nSLOW drives'); print(d[slow].groupby('band', observed=True).apply(prof, include_groups=False).round(3))
print('\nFAST drives'); print(d[d.cadence == 'fast'].groupby('band', observed=True).apply(prof, include_groups=False).round(3))
# within slow drives, same-drive paired control: drive-level eff retained vs removed (age2-5)
sl = d[slow]
print('\nslow drives overall eff', 100*sl.cap.sum()/sl.ke.sum(), ' fast overall eff', 100*d[d.cadence=='fast'].cap.sum()/d[d.cadence=='fast'].ke.sum())
print('slow drives: eff of steps with amax<=2', 100*sl.cap[sl.amax<=2].sum()/sl.ke[sl.amax<=2].sum(), ' eff of amax 2-5', 100*sl.cap[(sl.amax>2)&(sl.amax<=5)].sum()/sl.ke[(sl.amax>2)&(sl.amax<=5)].sum())
# per-channel eff of steps where only that channel is old (2<age<=5)
ages = ['age_spd', 'age_spd_prev', 'age_I', 'age_V', 'age_rpm']
for c in ages:
    oth = [x for x in ages if x != c]
    m = (d[c] > 2) & (d[c] <= 5) & (d[oth] <= 2).all(axis=1)
    if m.sum(): print(f' only {c} in (2,5]: n={m.sum()} eff={100*d.cap[m].sum()/d.ke[m].sum():.1f} meanI={d.I[m].mean():.1f} speed={d.speed[m].mean():.1f} dec={d.dec[m].mean():.2f}')
# drive level cadence stats
dr = drv.copy(); dr['regime'] = np.where(dm.ev_rpm_dt_med_s.values < 1.0, 'fast', 'slow')
print('\nnative median dt by regime (drives with steps)'); 
has = dr.k.isin(d.k.unique())
print(dr[has].groupby('regime')[['dt_speed', 'dt_rpm', 'dt_I', 'dt_V', 'p90dt_speed', 'p90dt_rpm', 'p90dt_I', 'p90dt_V']].median().round(3))
print(dr[has].groupby('regime').size())
# per-step cadence: which regime has amax>2 per drive; age distribution for slow drives
print('\nslow drives amax quantiles', sl.amax.quantile([.5, .75, .9, .95, .99]).round(2).tolist())
# (b) V4 decomposition of legacy bin 5
b5 = d[d.smid == 5]; A = b5[b5.vprev < 10]; B = b5[b5.vprev >= 10]
print('\nlegacy bin 5: n', len(b5), ' eff', 100*b5.cap.sum()/b5.ke.sum())
for nm, g in [('A start<10 (V4 bin5)', A), ('B start>=10 end<10', B)]:
    print(nm, 'n', len(g), 'KE share', g.ke.sum()/b5.ke.sum(), 'cap share', g.cap.sum()/b5.cap.sum(), 'eff', 100*g.cap.sum()/g.ke.sum(), 'mean vprev', g.vprev.mean(), 'mean drop', g.dec.mean())
print(' B start-speed distribution', B.vprev.describe().round(1).to_dict())
print(' share of B steps with start >=20', float((B.vprev >= 20).mean()), ' with zero cap', float((B.cap == 0).mean()), ' A zero cap', float((A.cap == 0).mean()))
print(' A: mean speed drop', A.dec.mean(), ' A: median ke Wh', 1000*A.ke.median(), ' frac of A with drop==1 kmh', float((A.dec.round(3) <= 1.0).mean()))
cap_off = np.maximum((d.I + (-0.3888)) * d.V / 1000.0, 0) / 3600.0
print(' V6 on A (V4 bin 5): eff', 100*A.cap.sum()/A.ke.sum(), '->', 100*cap_off[A.index].sum()/A.ke.sum())
# V4 bin 5 per-drive-type
# (c) rest and sign
print('\nSIGN: rest current (speed 0, engine off, grid): drive-weighted by seconds')
r = drv[drv.rest_n > 0]
tot = r.rest_n.sum(); print('rest seconds', tot, ' pooled mean I', (r.rest_I_mean*r.rest_n).sum()/tot, ' median of drive medians', r.rest_I_med.median(), ' IQR', r.rest_I_med.quantile([.25,.75]).tolist(), ' n drives', len(r))
print('mean I during engine-off decel (dv<-1):', (drv.I_decel*drv.n_decel).sum()/drv.n_decel.sum(), ' accel (dv>1, engine off):', (drv.I_accel*drv.n_accel).sum()/drv.n_accel.sum())
print('share of drives with rest median < 0:', float((r.rest_I_med < 0).mean()))
json.dump(R, open(sys.argv[1] + '.r.json', 'w', encoding='utf-8'))
