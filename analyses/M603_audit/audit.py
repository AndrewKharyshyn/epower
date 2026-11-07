import re, sys, json, os, numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
import compute_drive_summary_v6 as C
from scipy import stats
dm = pd.read_csv('drive_master.csv')
rows = []
for f in dm['file']:
    fn = f if os.path.exists(os.path.join('raw', f)) else (f[:4]+'-'+f[4:6]+'-'+f[6:8]+' '+f[9:11]+'-'+f[11:13]+'-'+f[13:15]+f[15:]) if f[4].isdigit() else f.replace('_',' ',1)
    if not os.path.exists(os.path.join('raw', fn)): fn = f.replace('_',' ')
    b = open(os.path.join('raw', fn), 'rb').read()
    df, t = C._prep_bytes(b)
    I = C._series(df, t, 'I')
    if I is not None: I = I[I['v'].abs() < 900].reset_index(drop=True)
    vmax = C._series(df, t, 'Vcell_max', lo=2.0, hi=5.0); vmin = C._series(df, t, 'Vcell_min', lo=2.0, hi=5.0)
    rec = dict(file=f, nL=0, pL=np.nan, nS=0, pS=np.nan)
    if vmax is not None and vmin is not None and I is not None:
        vmin2 = vmin.rename(columns={'v': 'vmin'}); vmin2['tmin'] = vmin2['t']
        p = pd.merge_asof(vmax.rename(columns={'v': 'vmax'}), vmin2, on='t', direction='nearest',
                          tolerance=pd.Timedelta(C.SPREAD_TOL)).dropna().reset_index(drop=True)
        if len(p):
            p['spread_mv'] = (p['vmax'] - p['vmin']) * 1000.0
            p2 = C._asof(p, I, 'I', C.V_ALIGN_TOL)
            L = p2.loc[p2['I'].abs() > 50, 'spread_mv']
            if len(L): rec.update(nL=len(L), pL=round(L.quantile(.95), 1))
            # bracket at midpoint
            tm = p2['t'] + (p2['tmin'] - p2['t']) / 2
            Id = I.drop_duplicates('t').sort_values('t').reset_index(drop=True)
            tn = Id['t'].values.astype('datetime64[ns]').astype('int64'); iv = Id['v'].values
            q = tm.values.astype('datetime64[ns]').astype('int64')
            lo = np.searchsorted(tn, q, side='right') - 1   # last at or before
            hi = lo + 1                                     # first strictly after
            ok = (lo >= 0) & (hi < len(tn))
            lo_c = np.clip(lo, 0, len(tn)-1); hi_c = np.clip(hi, 0, len(tn)-1)
            dt = (tn[hi_c] - tn[lo_c]) / 1e9
            ok &= (dt > 0) & (dt <= 2)
            slew = np.where(ok, np.abs(iv[hi_c] - iv[lo_c]) / np.where(dt > 0, dt, 1), np.inf)
            Ia = p2['I'].abs().values
            m = ok & (slew <= 3) & (Ia >= 30) & (Ia <= 100)
            S = p2.loc[m, 'spread_mv']
            rec['nS'] = int(m.sum())
            if len(S) >= 20: rec['pS'] = float(S.quantile(.95))
    rows.append(rec)
r = pd.DataFrame(rows); r.to_csv('analyses/M603_audit/audit_sidecar.csv', index=False)
d = dm.merge(r, on='file')
has = d['cell_spread_loaded_p95_mv'].notna()
mism = (~np.isclose(d.loc[has, 'cell_spread_loaded_p95_mv'], d.loc[has, 'pL'], equal_nan=False, atol=1e-9)).sum()
print('loaded recon mismatches', mism, 'of', has.sum(), 'nL mismatch', (d.loc[has,'n_loaded_spread_samples']!=d.loc[has,'nL']).sum())
d['date'] = pd.to_datetime(d['date']).dt.normalize()
cc = d[(~d['ens_outlier_v2'].astype(bool))].copy()
print('canon clean', len(cc), 'with >=20 steady', int((cc.nS >= 20).sum()))
s = cc[cc.pS.notna() & cc.pL.notna()].copy()   # loaded also needs to be defined
s['months'] = (s['date'] - cc['date'].min()).dt.days / 30.4375
print('n drives', len(s), 'days', s.date.nunique())
def fit(y, df):
    import statsmodels.api as sm
    X = sm.add_constant(df[['months', 'T_pack_mean_avg', 'peak_I_discharge']].astype(float))
    ok = X.notna().all(axis=1) & df[y].notna()
    return X[ok], df.loc[ok, y], df.loc[ok, 'date']
import statsmodels.api as sm
def slope(y, df, ci=True):
    X, Y, g = fit(y, df)
    m = sm.OLS(Y, X).fit(cov_type='cluster', cov_kwds={'groups': pd.factorize(g)[0]})
    G = g.nunique()
    # CR2 via manual bias-reduced
    b = slope_cr2(X.values, Y.values, pd.factorize(g)[0])
    tcrit = stats.t.ppf(.975, G - 1)
    return b[0], b[0] - tcrit*b[1], b[0] + tcrit*b[1], m.params['months'], len(Y), G
def slope_cr2(X, y, g):
    n, k = X.shape
    XtXi = np.linalg.inv(X.T @ X); beta = XtXi @ X.T @ y; e = y - X @ beta
    meat = np.zeros((k, k))
    for c in np.unique(g):
        i = g == c; Xc = X[i]
        H = Xc @ XtXi @ Xc.T
        A = np.linalg.pinv(sqrtm_inv(np.eye(i.sum()) - H))
        ec = A @ e[i]
        u = Xc.T @ ec; meat += np.outer(u, u)
    V = XtXi @ meat @ XtXi
    return beta[1], np.sqrt(V[1, 1])
def sqrtm_inv(M):
    w, v = np.linalg.eigh((M+M.T)/2); w = np.clip(w, 1e-12, None)
    return v @ np.diag(w**-0.5) @ v.T
def pinv(M): return M
out = {}
a = slope('pS', s); b = slope('pL', s)
out['steady'] = a; out['loaded'] = b
print('steady (cr2 est, lo, hi, cr0 est, n, G)', a); print('loaded', b)
# paired bootstrap
rng = np.random.default_rng(42)
days = s['date'].unique(); grp = {k: v for k, v in s.groupby('date')}
def ols_slope(df, y):
    X = np.column_stack([np.ones(len(df)), df[['months', 'T_pack_mean_avg', 'peak_I_discharge']].astype(float).values])
    return np.linalg.lstsq(X, df[y].values, rcond=None)[0][1]
D0 = ols_slope(s, 'pS') - ols_slope(s, 'pL'); Ds = []
for _ in range(4000):
    pick = rng.choice(len(days), len(days))
    bs = pd.concat([grp[days[i]] for i in pick])
    try: Ds.append(ols_slope(bs, 'pS') - ols_slope(bs, 'pL'))
    except Exception: pass
Ds = np.array(Ds)
print('D point (OLS)', D0, 'pctl CI', np.percentile(Ds, [2.5, 97.5]), 'diff CR2 pts', a[0]-b[0])
# Theil-Sen of day medians
dmed = s.groupby('date').agg(m=('pS', 'median'), months=('months', 'first')).reset_index()
ts = stats.theilslopes(dmed['m'], dmed['months'])
print('TS days', len(dmed), ts[0], ts[2], ts[3])
dd = {k: (g['pS'].median(), g['months'].iloc[0]) for k, g in grp.items()}
rng = np.random.default_rng(42); bts = []
for _ in range(4000):
    pick = rng.choice(len(days), len(days))
    # day medians of resampled days (a repeated day keeps same median)
    x = np.array([dd[days[i]][1] for i in pick]); y = np.array([dd[days[i]][0] for i in pick])
    if np.ptp(x) == 0: continue
    bts.append(stats.theilslopes(y, x)[0])
print('TS boot pctl', np.percentile(bts, [2.5, 97.5]))
