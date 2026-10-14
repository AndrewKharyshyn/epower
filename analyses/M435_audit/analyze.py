"""M435 blind audit step 2: KM, Manski bounds, hazard tilt, day-clustered bootstrap from the per-drive records.
Usage: python -X utf8 analyze.py <rec.csv> <out.json>"""
import sys, json
import numpy as np, pandas as pd

H = [300, 600, 900, 1200, 1800]
THETA = [0.25, 0.5, 1, 2, 4]

def prep(r, ff, fluid, thr, tol=10):
    p = f'ff{ff}_'
    d = r[r[p + 'status'] == 'cold'].copy()
    col = f'{p}{fluid}{thr}_'
    d = d[d[col + 'ev'].notna()]
    ev = d[col + 'ev'].values.astype(int)
    T = np.where(ev == 1, d[col + 'T'].values, d[col + 'last'].values)
    last = d[col + 'last'].values
    end = d[p + 'end'].values
    trip = (end - last) <= tol
    reason = np.where(ev == 1, 'event', np.where(trip, 'tripEnd', 'channelLoss'))
    return pd.DataFrame(dict(file=d['file'].values, day=d['date'].values.astype(str), t=T.astype(float), ev=ev, reason=reason,
                             gap=d[col + 'gap'].values, start=d[col + 'start'].values, startc=d[p + 'cstart'].values,
                             T0=(d[col + 'T'].values == 0) & (ev == 1), dist=d['distance_km'].values, local=d['local_iso'].values,
                             span=end))

def km(t, ev):
    """product-limit; events before censorings at ties. returns (times, S)"""
    o = np.lexsort((1 - ev, t))      # sort by t, events (ev=1) first
    t, ev = t[o], ev[o]
    n = len(t)
    ut = np.unique(t[ev == 1])
    S = np.empty(len(ut)); s = 1.0
    for i, u in enumerate(ut):
        atrisk = n - np.searchsorted(t, u, side='left')
        d = ((t == u) & (ev == 1)).sum()
        s *= 1 - d / atrisk
        S[i] = s
    return ut, S

def Sat(ut, S, x):
    """S(x) = S at last event time <= x"""
    i = np.searchsorted(ut, x, side='right') - 1
    return 1.0 if i < 0 else S[i]

def Sat_vec(ut, S, xs):
    i = np.searchsorted(ut, xs, side='right') - 1
    return np.where(i < 0, 1.0, S[np.maximum(i, 0)])

def stats(t, ev, h, thetas=THETA):
    n = len(t)
    ut, S = km(t, ev)
    out = {}
    Sh = Sat(ut, S, h)
    out['F_km'] = 1 - Sh
    reached = (ev == 1) & (t <= h)
    out['F_low'] = reached.sum() / n
    out['F_high'] = (reached.sum() + ((ev == 0) & (t < h)).sum()) / n
    cens = ev == 0
    for th in thetas:
        c = t[cens]
        Sc = Sat_vec(ut, S, c)
        contrib_c = np.where(c >= h, 1.0, (Sh / Sc) ** th)
        contrib_e = (t[~cens] > h).astype(float)
        out[f'F_theta{th}'] = 1 - (contrib_c.sum() + contrib_e.sum()) / n
    # median
    below = np.where(S <= 0.5)[0]
    out['median'] = float(ut[below[0]]) if len(below) else np.inf
    return out

def boot(d, hs, B=4000, seed=42, thetas=THETA):
    days = np.array(sorted(d['day'].unique()))
    idx = {k: np.where(d['day'].values == k)[0] for k in days}
    t, ev = d['t'].values, d['ev'].values
    rng = np.random.default_rng(seed)
    res = {h: [] for h in hs}
    for _ in range(B):
        s = rng.choice(days, len(days), replace=True)
        ii = np.concatenate([idx[k] for k in s])
        for h in hs:
            res[h].append(stats(t[ii], ev[ii], h, thetas))
    return {h: pd.DataFrame(v) for h, v in res.items()}

def pct(x):
    x = np.asarray(x, float)
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]

def summarize(d, label, do_boot=True, bh=(600,)):
    t, ev = d['t'].values, d['ev'].values
    n = len(d)
    o = dict(label=label, n=n, days=int(d['day'].nunique()), reached=int(ev.sum()),
             tripEnd=int((d['reason'] == 'tripEnd').sum()), channelLoss=int((d['reason'] == 'channelLoss').sum()),
             eventsAfterGt10sGap=int(((d['ev'] == 1) & (d['gap'] > 10)).sum()),
             eventsAfterGt10sGap_ge10=int(((d['ev'] == 1) & (d['gap'] >= 10)).sum()),
             time0=int(d['T0'].sum()),
             reachersOnlyMedian=float(np.median(t[ev == 1])))
    o['h'] = {}
    for h in H:
        s = stats(t, ev, h)
        s['atRiskDrives'] = int((t >= h).sum())
        s['atRiskDays'] = int(d.loc[d['t'] >= h, 'day'].nunique())
        s['E1'] = s['F_low']
        o['h'][h] = s
    o['KM_median'] = o['h'][600]['median']
    if do_boot:
        b = boot(d, bh)
        o['boot'] = {}
        for h in bh:
            B = b[h]
            o['boot'][h] = {k: pct(B[k]) for k in ['F_km', 'F_low', 'F_high'] + [f'F_theta{x}' for x in THETA]}
            o['boot'][h]['median_unidentified_share'] = float(np.isinf(B['median']).mean())
            o['boot'][h]['median_ci'] = pct(B['median'])
            o['boot'][h]['outer'] = [o['boot'][h]['F_low'][0], o['boot'][h]['F_high'][1]]
    return o

if __name__ == '__main__':
    r = pd.read_csv(sys.argv[1], encoding='utf-8', low_memory=False)
    out = {}
    for fluid, thr in (('cool', 80), ('oil', 70)):
        d = prep(r, 3, fluid, thr)
        out[f'{fluid}{thr}'] = summarize(d, f'{fluid}{thr}')
    json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), indent=1, default=float)
    for k, v in out.items():
        print(k, {a: b for a, b in v.items() if a not in ('h', 'boot')})
        for h, s in v['h'].items():
            print(' h', h, {a: round(b, 4) if isinstance(b, float) else b for a, b in s.items()})
        print(' boot', json.dumps(v['boot']))
