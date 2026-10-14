import pickle, sys, json, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '.')
import m119v2_model as M
from scipy import stats as sps
P = r'C:\Users\ANDRII~1\AppData\Local\Temp\claude\C--Users-AndriiKharyshyn-Downloads-X-Trail-Investigation-Repo-xtrail-repo\f2ab55fa-e6d5-45d0-976d-c55d9b3eda14\scratchpad\tables578.pkl'
d = pickle.load(open(P, 'rb'))
S, T, cov, srcs, diag = d['tables']; files = d['files']
dm = pd.read_csv('drive_master.csv', usecols=['file'])
assert list(dm.file) == list(files), 'order mismatch'
basis = set(files[:489]); later = set(files[489:])
CORE5 = ['soc', 'speed', 'tpack', 'demand', 'durationS']
PRED = CORE5
SEED, B = 42, 4000


def design():
    return M.DesignSpec(['soc', 'speed', 'tpack', 'demand', 'logdur'], M.INTERACTIONS)


def ll(y, p):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))


def stats_fn(y, p, p0):
    out = {}
    out['ll'] = ll(y, p)
    out['skill'] = 1 - out['ll'] / ll(y, np.full_like(p, p0))
    e = p.sum()
    out['oe'] = y.sum() / e if e > 0 else np.nan
    pa = M.pr_auc(y, p)
    out['pr'] = np.nan if pa is None else pa
    prev = y.mean()
    out['lift'] = out['pr'] / prev if prev > 0 else np.nan
    return out


def boot(day, y, p, p0, fns=('skill', 'oe', 'pr', 'lift')):
    days = pd.unique(day)
    idx = {k: np.where(day == k)[0] for k in days}
    rng = np.random.default_rng(SEED)
    res = {f: [] for f in fns}
    undefined = 0
    for _ in range(B):
        pick = rng.choice(days, size=len(days), replace=True)
        ii = np.concatenate([idx[k] for k in pick])
        s = stats_fn(y[ii], p[ii], p0)
        if np.isnan(s['oe']) or np.isnan(s['pr']):
            undefined += 1
        for f in fns:
            res[f].append(s[f])
    return {f: [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))] for f, v in res.items()}, undefined


def jack(day, y, p, p0):
    days = pd.unique(day)
    G = len(days)
    out = {}
    vals = {'skill': [], 'oe': []}
    for k in days:
        m = day != k
        s = stats_fn(y[m], p[m], p0)
        vals['skill'].append(s['skill'])
        vals['oe'].append(s['oe'])
    full = stats_fn(y, p, p0)
    for f in vals:
        v = np.array(vals[f])
        se = np.sqrt((G - 1) / G * np.sum((v - v.mean()) ** 2))
        t = sps.t.ppf(0.975, G - 1)
        out[f] = {'est': full[f], 'jk_ci': [full[f] - t * se, full[f] + t * se], 'loo_range': [v.min(), v.max()]}
    return out


def states(skill_lo, oe_ci, excess_max):
    d1 = 'PASS' if skill_lo > 0 else 'FAIL'
    lo, hi = oe_ci
    if lo >= 0.80 and hi <= 1.25:
        d2 = 'within'
    elif hi < 0.80 or lo > 1.25:
        d2 = 'MATERIAL'
    else:
        d2 = 'indeterminate'
    d3 = 'MATERIAL' if excess_max > 10 else 'not material'
    return d1, d2, d3


def support(bas, lat, cols):
    r = {}
    for c in cols:
        lo, hi = np.nanpercentile(bas[c], [1, 99])
        ob = ((bas[c] < lo) | (bas[c] > hi)).mean() * 100
        ol = ((lat[c] < lo) | (lat[c] > hi)).mean() * 100
        mn, mx = bas[c].min(), bas[c].max()
        omx = ((lat[c] < mn) | (lat[c] > mx)).mean() * 100
        r[c] = {'basis_out': ob, 'later_out': ol, 'excess_pp': ol - ob, 'later_outside_minmax_pct': omx,
                'p1p99': [lo, hi], 'minmax': [mn, mx]}
    return r


def run_side(name, tbl):
    cc = tbl.dropna(subset=CORE5).reset_index(drop=True)
    b = cc[cc.file.isin(basis)].reset_index(drop=True)
    l = cc[cc.file.isin(later)].reset_index(drop=True)
    spec = design().fit(b)
    Xb, _ = spec.transform(b)
    res = M.fit_glm(Xb, b.y.values.astype(float), groups=b.day.values)
    Xl, _ = spec.transform(l)
    p = M._predict(res, Xl)
    y = l.y.values.astype(float)
    p0 = b.y.mean()
    out = {'basis_n_cc': len(b), 'basis_events_cc': int(b.y.sum()),
           'raw_basis_atrisk': int(tbl.file.isin(basis).sum()), 'raw_basis_events': int(tbl[tbl.file.isin(basis)].y.sum()),
           'raw_later_atrisk': int(tbl.file.isin(later).sum()),
           'later_n': len(l), 'later_events': int(y.sum()), 'later_drives': int(l.file.nunique()), 'later_days': int(l.day.nunique()),
           'later_files_in_table_raw': int(tbl[tbl.file.isin(later)].file.nunique()),
           'basis_files_in_table': int(tbl[tbl.file.isin(basis)].file.nunique())}
    pt = stats_fn(y, p, p0)
    out['point'] = pt
    out['prevalence'] = y.mean()
    out['basis_rate'] = p0
    out['pred_sum'] = p.sum()
    ci, und = boot(l.day.values, y, p, p0)
    out['boot_ci'] = ci
    out['undefined_draws'] = und
    out['jack'] = jack(l.day.values, y, p, p0)
    s1 = M.DesignSpec(['soc'], []).fit(b)
    X1, _ = s1.transform(b)
    r1 = M.fit_glm(X1, b.y.values.astype(float), groups=b.day.values)
    p1 = M._predict(r1, s1.transform(l)[0])
    out['skill_vs_B1'] = 1 - ll(y, p) / ll(y, p1)
    out['ll_model'] = ll(y, p)
    out['ll_B0'] = ll(y, np.full_like(p, p0))
    out['ll_B1'] = ll(y, p1)
    out['later_const_skill'] = 1 - ll(y, p) / ll(y, np.full_like(p, y.mean()))
    sl, ic = M.calibration(y, p)
    out['cal_slope'], out['cal_int'] = sl, ic
    out['support'] = support(b, l, PRED)
    ins = np.ones(len(l), bool)
    for c in PRED:
        lo, hi = np.nanpercentile(b[c], [1, 99])
        ins &= ((l[c] >= lo) & (l[c] <= hi)).values
    out['insupport_share'] = float(ins.mean())
    for nm, m in (('insup', ins), ('outsup', ~ins)):
        if m.sum() and y[m].sum():
            out[nm] = {'n': int(m.sum()), 'ev': int(y[m].sum()), 'oe': y[m].sum() / p[m].sum(),
                       'skill': stats_fn(y[m], p[m], p0)['skill']}
    bands = [(-99, 10), (10, 20), (20, 30), (30, 40), (40, 999)]
    out['bands'] = []
    for a, c in bands:
        m = ((l.tpack >= a) & (l.tpack < c)).values
        e = float(p[m].sum())
        out['bands'].append({'band': '%s-%s' % (a, c), 'n': int(m.sum()), 'ev': int(y[m].sum()), 'exp': e,
                             'oe': (y[m].sum() / e if e > 0 else None)})
    exmax = max(v['excess_pp'] for v in out['support'].values())
    out['excess_max'] = exmax
    out['states_primary'] = states(ci['skill'][0], ci['oe'], exmax)
    out['states_jackknife'] = states(out['jack']['skill']['jk_ci'][0], out['jack']['oe']['jk_ci'], exmax)
    m3 = l.day.values != '2026-09-30'
    l3 = l[m3]
    y3 = y[m3]
    p3 = p[m3]
    ci3, _ = boot(l3.day.values, y3, p3, p0)
    sup3 = support(b, l3, PRED)
    out['S3'] = {'days': int(l3.day.nunique()), 'drives': int(l3.file.nunique()), 'events': int(y3.sum()), 'n': int(len(y3)),
                 'point': stats_fn(y3, p3, p0), 'ci': ci3,
                 'states': states(ci3['skill'][0], ci3['oe'], max(v['excess_pp'] for v in sup3.values())),
                 'excess': {k: v['excess_pp'] for k, v in sup3.items()}}
    w = l.groupby('day').size().values.astype(float)
    out['essDays'] = float(w.sum() ** 2 / (w ** 2).sum())
    out['per_day'] = {k: [int(g.y.sum()), int(len(g)), int(g.file.nunique())] for k, g in l.groupby('day')}
    out['day0930'] = {'basis_events': int(b[b.day == '2026-09-30'].y.sum()), 'later_events': int(l[l.day == '2026-09-30'].y.sum()),
                      'later_n': int((l.day == '2026-09-30').sum()), 'basis_n': int((b.day == '2026-09-30').sum())}
    # S2 halves
    ds = sorted(l.day.unique())
    h1, h2 = ds[:7], ds[7:]
    out['S2'] = {}
    for nm, hh in (('first7', h1), ('last7', h2)):
        m = l.day.isin(hh).values
        s = stats_fn(y[m], p[m], p0)
        out['S2'][nm] = {'events': int(y[m].sum()), 'skill': s['skill'], 'oe': s['oe'], 'pr': s['pr']}
    return out


result = {}
for nm, tbl in (('START', S), ('STOP', T)):
    result[nm] = run_side(nm, tbl)


def conv(o):
    if isinstance(o, dict):
        return {str(k): conv(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [conv(v) for v in o]
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


json.dump(conv(result), open('audit/m428_blind_out.json', 'w', encoding='utf-8'), indent=1)
print('done')
