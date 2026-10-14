"""M437 blind audit step 2. Usage: python -X utf8 analyze_m437.py <rec437.csv> <iv.npz.pkl> <out.json>"""
import sys, os, json, pickle
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'M435_audit'))
import numpy as np, pandas as pd
import analyze as A   # own M435 audit helper (km)

r = pd.read_csv(sys.argv[1], encoding='utf-8', low_memory=False)
H = 600

def prep(F, fl, thr, X=10):
    p = f'f{F}_'
    c = f'{p}{fl}{thr}_'
    d = r[r[p + 'status'] == 'cold']
    d = d[d[c + 'ev'].notna()]
    ev = d[c + 'ev'].values.astype(int)
    last = d[c + 'last'].values
    end = d[p + 'end'].values
    T = np.where(ev == 1, d[c + 'T'].values, last)
    return pd.DataFrame(dict(file=d.file.values, day=d.date.astype(str).values, ev=ev, t=T, last=last, end=end,
                             evfilled=d[c + 'evfilled'].values, gap=end - last))

def reason(d, X):
    return np.where(d.ev == 1, 'event', np.where(d.gap <= X, 'tripEnd', 'channelLoss'))

def est(d):
    n = len(d); t = d.t.values; ev = d.ev.values
    ut, S = A.km(t, ev)
    reached = int(((ev == 1) & (t <= H)).sum())
    cens_before = int(((ev == 0) & (t < H)).sum())
    return dict(n=n, days=int(d.day.nunique()), reached=int(ev.sum()), reached600=reached,
                E1=round(reached / n, 4), KM=round(1 - A.Sat(ut, S, H), 4), upper=round((reached + cens_before) / n, 4),
                atrisk600=int((t >= H).sum()),
                reasons={X: {k: int((reason(d, X) == k).sum()) for k in ('tripEnd', 'channelLoss')} for X in (5, 10, 30)})

cells = (('cool', 80), ('oil', 70))
out = {'est': {}, 'paired': {}, 'eventFilled': {}}
for F in (0, 3, 6):
    for fl, thr in cells:
        d = prep(F, fl, thr)
        out['est'][f'F{F}_{fl}{thr}'] = est(d)
        out['eventFilled'][f'F{F}_{fl}{thr}'] = int(d.evfilled.sum())
for fl, thr in cells:
    base = prep(3, fl, thr)
    for F in (0, 6):
        v = prep(F, fl, thr)
        key = f'F{F}_{fl}{thr}'
        bs, vs = set(base.file), set(v.file)
        def split(files):
            b = base.set_index('file'); vv = v.set_index('file')
            res = dict(n=0, reached600=0, cens_before600=0, atrisk600=0)
            for f in files:
                x = b.loc[f] if f in b.index else vv.loc[f]
                res['n'] += 1
                if x.ev == 1 and x.t <= H: res['reached600'] += 1
                elif x.ev == 0 and x.t < H: res['cens_before600'] += 1
                else: res['atrisk600'] += 1
            return res
        both = sorted(bs & vs)
        b = base.set_index('file').loc[both]; vv = v.set_index('file').loc[both]
        cens_both = (b.ev == 0) & (vv.ev == 0)
        rc = {}
        for X in (5, 10, 30):
            lb = reason(b.reset_index(), 10); lv = reason(vv.reset_index(), X)
            m = cens_both.values
            rc[X] = dict(tripEnd_to_channelLoss=int(((lb == 'tripEnd') & (lv == 'channelLoss') & m).sum()),
                         channelLoss_to_tripEnd=int(((lb == 'channelLoss') & (lv == 'tripEnd') & m).sum()))
        sh = (vv['last'] - b['last'])
        out['paired'][key] = dict(dropped=split(sorted(bs - vs)), added=split(sorted(vs - bs)), nboth=len(both),
            eventTimeChanged=int(((b.ev != vv.ev) | ((b.ev == 1) & (vv.ev == 1) & (b.t != vv.t))).sum()),
            censTimeChanged_censBoth=int((cens_both & (sh != 0)).sum()), maxShift_censBoth=float(sh[cens_both].abs().max()),
            lastValidChanged_allBoth=int((sh != 0).sum()), maxShift_allBoth=float(sh.abs().max()),
            reasonChanged=rc,
            dropped_files=sorted(bs - vs)[:60])
        # T-time nuance: event drives; last valid second shift for event drives
json.dump(out, open(sys.argv[3], 'w', encoding='utf-8'), indent=1, default=float)
print(json.dumps(out['est'], default=float))
for k, v in out['paired'].items(): print(k, {a: b for a, b in v.items() if a != 'dropped_files'})
print('event second filled:', out['eventFilled'])
