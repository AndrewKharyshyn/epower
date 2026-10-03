"""Blind re-check (auditor): GTR node excess and f_gen, day-clustered bootstrap. Reads data only."""
import json, numpy as np, pandas as pd
R = 'C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo/'
fr = pd.read_csv(R + 'fuel_recon_master.csv')
dm = pd.read_csv(R + 'drive_master.csv', usecols=['file', 'ens_outlier_v2', 'distance_km', 'I_offset_A_applied',
                                                   'charge_eng_only_kwh', 'charge_dual_kwh'])
m = fr.merge(dm, on='file', how='inner', suffixes=('', '_dm'))
out = {'n_join': len(m), 'dist_diff_max': float((m.distance_km - m.distance_km_dm).abs().max())}
ok = m.ens_outlier_v2.astype(str).eq('False') & (m.distance_km > 0)
ok &= m[['I_offset_A_applied', 'charge_eng_only_kwh', 'charge_dual_kwh']].notna().all(axis=1)
x = m[ok].copy()
out['alt_mask_dm_distance_n'] = int((m.ens_outlier_v2.astype(str).eq('False') & (m.distance_km_dm > 0) &
                                    m[['I_offset_A_applied', 'charge_eng_only_kwh', 'charge_dual_kwh']].notna().all(axis=1)).sum())
d = x.distance_km.values
cols = {'gen': 'generator_kWh_100', 'g2t': 'gen_to_traction_kWh_100', 'g2b': 'gen_to_batt_kWh_100',
        'tr': 'traction_gross_kWh_100'}
out['nan_in_cols'] = {k: int(x[c].isna().sum()) for k, c in cols.items()}
days = x.date.astype(str).values
ud = np.unique(days)
idx = {u: np.where(days == u)[0] for u in ud}
# per-day weighted sums
S = {k: np.array([np.nansum(x[c].values[idx[u]] * d[idx[u]]) for u in ud]) for k, c in cols.items()}
D = np.array([d[idx[u]].sum() for u in ud])

def stats(w):
    s = {k: (v * w).sum() for k, v in S.items()}
    dd = (D * w).sum()
    return ((s['g2t'] + s['g2b'] - s['gen']) / s['gen'], s['g2t'] / s['tr'],
            s['gen'] / dd, s['g2t'] / dd, s['g2b'] / dd, (s['g2t'] + s['g2b'] - s['gen']) / dd)

pt = stats(np.ones(len(ud)))
out.update(n_drives=len(x), n_days=len(ud), km=round(float(d.sum()), 1), excess_pct=round(pt[0] * 100, 4),
           f_gen=round(pt[1], 4), per100={'GEN': round(pt[2], 3), 'G2T': round(pt[3], 3), 'G2B': round(pt[4], 3),
                                          'RES': round(pt[5], 3)})
n = len(ud)

def boot(draw):
    ex, fg = [], []
    for _ in range(4000):
        w = np.bincount(draw(), minlength=n).astype(float)
        r = stats(w); ex.append(r[0]); fg.append(r[1])
    q = lambda a: [round(float(v), 4) for v in np.percentile(a, [2.5, 97.5])]
    return {'excess_pct': [round(v * 100, 2) for v in q(ex)], 'f_gen': q(fg)}

g = np.random.default_rng(42)
out['boot_default_rng_integers'] = boot(lambda: g.integers(0, n, n))
g2 = np.random.default_rng(42)
out['boot_default_rng_choice'] = boot(lambda: g2.choice(n, n, replace=True))
rs = np.random.RandomState(42)
out['boot_RandomState_choice'] = boot(lambda: rs.choice(n, n, replace=True))
rs2 = np.random.RandomState(42)
out['boot_RandomState_randint'] = boot(lambda: rs2.randint(0, n, n))
print(json.dumps(out, indent=1))
json.dump(out, open(R + 'audit/audit_m361_gtr_recheck.json', 'w'), indent=1)
