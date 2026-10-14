"""M438 blind audit: start-temperature strata of the M435 time-to-threshold headline cells.
Reuses (own earlier audit code) analyses/M435_audit/build_records.py output (rec.csv) and analyze.prep / km / stats.
Usage: python -X utf8 strata_audit.py <rec.csv> <out.json> [B]"""
import sys, json, math, importlib.util, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('an435', os.path.join(HERE, '..', 'M435_audit', 'analyze.py'))
an = importlib.util.module_from_spec(spec); spec.loader.exec_module(an)

H = 600
rec = pd.read_csv(sys.argv[1], encoding='utf-8', low_memory=False)
B = int(sys.argv[3]) if len(sys.argv) > 3 else 4000

cool = an.prep(rec, 3, 'cool', 80)
starts_all = cool['startc'].values.astype(float)          # coolant start of all coolant cold starts (cohort all)
assert len(cool) == 389


def cuts_of(x):
    q = np.percentile(x, [100 / 3 * 0 + 33.33333, 66.66667])    # numpy linear
    return [math.floor(2 * v + 0.5) / 2 for v in q], q


cuts, rawq = cuts_of(starts_all)


def stratum(x, cuts):
    return (np.asarray(x) >= cuts[0]).astype(int) + (np.asarray(x) >= cuts[1]).astype(int)   # 0,1,2


def km_F(t, ev, h):
    """1 - S_KM(h); events before censorings at ties. also returns risk-set-at-h size"""
    if len(t) == 0:
        return np.nan, 0
    o = np.lexsort((1 - ev, t)); t = t[o]; ev = ev[o]
    n = len(t)
    em = (ev == 1) & (t <= h)
    if em.sum() == 0:
        return 0.0, int((t >= h).sum())
    ut, first, cnt = np.unique(t[em], return_index=True, return_counts=True)
    atrisk = n - np.searchsorted(t, ut, side='left')
    S = np.prod(1 - cnt / atrisk)
    return 1 - S, int((t >= h).sum())


def cell(fluid, thr):
    d = an.prep(rec, 3, fluid, thr)
    # stratum from the COOLANT start (startc)
    d['s'] = stratum(d['startc'].values, cuts)
    return d


def cell_stats(d, h=H):
    out = {'strata': []}
    n = len(d)
    t, ev, s = d['t'].values, d['ev'].values, d['s'].values
    Fp, _ = km_F(t, ev, h)
    w = np.array([(s == k).mean() for k in range(3)])
    Fs = []
    for k in range(3):
        m = s == k
        tk, ek = t[m], ev[m]
        F, _ = km_F(tk, ek, h)
        Fs.append(F)
        reached_h = int(((ek == 1) & (tk <= h)).sum())
        cens_before = int(((ek == 0) & (tk < h)).sum())
        out['strata'].append(dict(
            stratum=k + 1, n=int(m.sum()), days=int(d.loc[m, 'day'].nunique()),
            reachedEver=int(ek.sum()), reachedBy600=reached_h,
            atRiskDrives=int((tk >= h).sum()), atRiskDays=int(d.loc[m & (d['t'] >= h), 'day'].nunique()),
            E1=reached_h / m.sum(), F=F, upper=(reached_h + cens_before) / m.sum(),
            share=m.mean(), tripEnd=int((d.loc[m, 'reason'] == 'tripEnd').sum()),
            channelLoss=int((d.loc[m, 'reason'] == 'channelLoss').sum())))
    Fs = np.array(Fs)
    out['n'] = n; out['days'] = int(d['day'].nunique())
    out['weights'] = w.tolist()
    out['F_pooled'] = Fp
    out['E2_std'] = float((w * Fs).sum())
    out['D'] = float(Fp - (w * Fs).sum())
    out['c31'] = float(Fs[2] - Fs[0]); out['c21'] = float(Fs[1] - Fs[0])
    # identities
    E1s = sum(w[k] * out['strata'][k]['E1'] for k in range(3))
    out['E1_std_minus_E1'] = float(E1s - ((ev == 1) & (t <= h)).mean())
    return out


def boot_cell(d, days_all, idx_days_cell, draws, h=H):
    t, ev, s = d['t'].values, d['ev'].values, d['s'].values
    res = np.full((len(draws), 5), np.nan)   # E2_std, D, c31, c21, unident flag
    unid = 0
    for b, sel in enumerate(draws):
        ii = np.concatenate([idx_days_cell[k] for k in sel if k in idx_days_cell]) if any(k in idx_days_cell for k in sel) else np.array([], int)
        tb, eb, sb = t[ii], ev[ii], s[ii]
        Fs = np.full(3, np.nan); w = np.zeros(3); bad = False
        for k in range(3):
            m = sb == k
            w[k] = m.mean() if len(sb) else 0
            if m.sum() == 0:
                Fs[k] = np.nan
                continue
            F, r = km_F(tb[m], eb[m], h)
            if r == 0 and F < 1 - 1e-12:      # empty risk set at h while S_KM(h) > 0
                bad = True
            Fs[k] = F
        Fp, rp = km_F(tb, eb, h)
        pos = w > 0
        if bad:
            unid += 1; continue
        E2 = np.sum(w[pos] * Fs[pos])
        res[b, 0] = E2; res[b, 1] = Fp - E2
        if not (np.isnan(Fs[2]) or np.isnan(Fs[0])): res[b, 2] = Fs[2] - Fs[0]
        if not (np.isnan(Fs[1]) or np.isnan(Fs[0])): res[b, 3] = Fs[1] - Fs[0]
    return res


def pct(x):
    x = x[np.isfinite(x)]
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5)), int(len(x))]


out = {'cuts': cuts, 'rawQuantiles': list(map(float, rawq)),
       'coolStarts': {'n': 389, 'shares': [float((stratum(starts_all, cuts) == k).mean()) for k in range(3)],
                      'counts': [int((stratum(starts_all, cuts) == k).sum()) for k in range(3)]}}
cells = {}
dcool = cell('cool', 80); doil = cell('oil', 70)
cells['cool80'] = dcool; cells['oil70'] = doil
for k, d in cells.items():
    out[k] = cell_stats(d)

# shared day resamples of the coolant cold-start days (cohort all), seed 42
days = np.array(sorted(dcool['day'].unique()))
rng = np.random.default_rng(42)
draws = [rng.choice(days, len(days), replace=True) for _ in range(B)]
for k, d in cells.items():
    idx = {dd: np.where(d['day'].values == dd)[0] for dd in days if (d['day'].values == dd).any()}
    r = boot_cell(d, days, idx, draws)
    out[k]['boot'] = {'E2_std': pct(r[:, 0]), 'D': pct(r[:, 1]), 'c31': pct(r[:, 2]), 'c21': pct(r[:, 3]),
                      'unidentifiedDraws': int(np.isnan(r[:, 0]).sum())}

# ---- reviews
c = dcool.copy()
c['lag'] = rec.set_index('file').loc[c['file'], 'ff3_lag_first_valid'].values
c['month'] = pd.to_datetime(c['day']).dt.month
c['hour'] = pd.to_datetime(c['local'], utc=False, errors='coerce', format='mixed').dt.hour
c['ev80'] = c['ev']
oil = doil.set_index('file')
c['ev_oil70'] = oil['ev'].reindex(c['file']).values
rv = {}
rv['lag_gt10_count'] = int((c['lag'] > 10).sum())
rv['lag_gt10_by_stratum'] = [int(((c['lag'] > 10) & (c['s'] == k)).sum()) for k in range(3)]
rv['lag_quantiles'] = list(map(float, np.percentile(c['lag'], [50, 75, 90, 95, 100])))
# sensitivity: back-extrapolate start by early warming slope observed in lag<=10 drives (temp rise over first 60 s)
# use ff3 grid not available in rec; fall back to a shift grid: reassign with start lowered by delta for lag>10 drives
sens = {}
for delta in (1, 2, 3, 5, 10):
    s2 = c['startc'].values - np.where(c['lag'].values > 10, delta, 0)
    sens[str(delta)] = int((stratum(s2, cuts) != c['s'].values).sum())
rv['reassigned_if_lag_gt10_start_lowered_by_C'] = sens
rv['lag_gt10_starts_within_1C_of_cut'] = int(((c['lag'] > 10) & ((np.abs(c['startc'] - cuts[0]) <= 1) | (np.abs(c['startc'] - cuts[1]) <= 1))).sum())
rv['all_starts_within_1C_of_cut'] = int(((np.abs(c['startc'] - cuts[0]) <= 1) | (np.abs(c['startc'] - cuts[1]) <= 1)).sum())
# profile
prof = []
for k in range(3):
    m = c['s'] == k
    prof.append(dict(stratum=k + 1, n=int(m.sum()),
                     startRange=[float(c.loc[m, 'startc'].min()), float(c.loc[m, 'startc'].max())],
                     medianDistKm=float(c.loc[m, 'dist'].median()), shareUnder5km=float((c.loc[m, 'dist'] < 5).mean()),
                     medianSpanS=float(c.loc[m, 'span'].median()),
                     medianHour=float(c.loc[m, 'hour'].median()), shareStartBefore10=float((c.loc[m, 'hour'] < 10).mean()),
                     medianMonth=float(c.loc[m, 'month'].median()),
                     monthShares={int(mo): round(float((c.loc[m, 'month'] == mo).mean()), 3) for mo in sorted(c['month'].unique())},
                     shareCensored_cool80=float((c.loc[m, 'ev80'] == 0).mean()),
                     shareCensored_oil70=float((c.loc[m, 'ev_oil70'] == 0).sum() / c.loc[m, 'ev_oil70'].notna().sum()),
                     medianAmbientProxy_months=None,
                     ))
rv['profile'] = prof
rv['rank_corr_start_month'] = float(pd.Series(c['startc']).corr(c['month'], method='spearman'))
rv['rank_corr_start_dist'] = float(pd.Series(c['startc']).corr(c['dist'], method='spearman'))
rv['rank_corr_start_hour'] = float(pd.Series(c['startc']).corr(c['hour'], method='spearman'))
out['review'] = rv
json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
