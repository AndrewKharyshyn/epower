"""M435 audit: method review (classification sensitivity, independence diagnostics, channelLoss concentration).
Usage: python -X utf8 review.py <rec.csv> <diag.csv> <out.json>"""
import sys, json, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
import analyze as A

r = pd.read_csv(sys.argv[1], encoding='utf-8', low_memory=False)
dg = pd.read_csv(sys.argv[2], encoding='utf-8', low_memory=False)
out = {}
cases = (('cool', 80), ('oil', 70))
for fl, thr in cases:
    key = f'{fl}{thr}'
    base = A.prep(r, 3, fl, thr)
    o = {}
    # (1) classification sensitivity
    for lab, ff, tol in (('ff3_tol10', 3, 10), ('ff0_tol10', 0, 10), ('ff3_tol5', 3, 5), ('ff3_tol30', 3, 30), ('ff0_tol5', 0, 5), ('ff0_tol30', 0, 30)):
        d = A.prep(r, ff, fl, thr, tol)
        m = d.merge(base[['file', 'reason']], on='file', suffixes=('', '_b'))
        s = A.stats(d['t'].values, d['ev'].values, 600)
        o[lab] = dict(n=len(d), tripEnd=int((d.reason == 'tripEnd').sum()), channelLoss=int((d.reason == 'channelLoss').sum()),
                      changed_class_vs_base=int((m.reason != m.reason_b).sum()), F_km600=round(s['F_km'], 4), F_low600=round(s['F_low'], 4), F_high600=round(s['F_high'], 4), median=s['median'])
    # distribution of (grid end - last valid) among censored
    c = base[base.ev == 0].copy()
    c['gapend'] = c['span'] - base.loc[c.index, 't']
    o['censored_end_minus_last_quantiles'] = {q: float(np.percentile(c.gapend, q)) for q in (50, 75, 90, 95, 99, 100)}
    o['censored_end_minus_last_bins'] = {'0-3': int((c.gapend <= 3).sum()), '3-5': int(((c.gapend > 3) & (c.gapend <= 5)).sum()), '5-10': int(((c.gapend > 5) & (c.gapend <= 10)).sum()),
                                         '10-30': int(((c.gapend > 10) & (c.gapend <= 30)).sum()), '>30': int((c.gapend > 30).sum())}
    # (3) channelLoss
    cl = base[base.reason == 'channelLoss']
    o['channelLoss_rows'] = [dict(file=f, day=d, last=float(t), span=float(s)) for f, d, t, s in zip(cl.file, cl.day, cl.t, cl.span)]
    o['channelLoss_days'] = int(cl.day.nunique())
    # (2) independence evidence
    b = base.merge(dg, on='file', how='left')
    b['hour'] = pd.to_datetime(b['local'].str[:19]).dt.hour
    grp = {'reached': b[b.ev == 1], 'censored': b[b.ev == 0]}
    ind = {}
    for k, g in grp.items():
        ind[k] = dict(n=len(g), start_med=float(g.startc.median()), start_q=[float(x) for x in np.percentile(g.startc, [25, 75])],
                      obs_time_med=float(g.t.median()), obs_time_q=[float(x) for x in np.percentile(g.t, [25, 75])],
                      dist_med=float(g.dist.median()), dist_q=[float(x) for x in np.nanpercentile(g.dist, [25, 75])],
                      hour_med=float(g.hour.median()), share_hour_lt10=float((g.hour < 10).mean()), share_hour_ge16=float((g.hour >= 16).mean()))
    from scipy import stats as ss
    ind['mannwhitney_p'] = {v: float(ss.mannwhitneyu(grp['reached'][v].dropna(), grp['censored'][v].dropna()).pvalue) for v in ('startc', 'dist', 'hour')}
    ind['spearman_start_vs_obstime_censored'] = [float(x) for x in ss.spearmanr(grp['censored'].startc, grp['censored'].t)]
    ind['spearman_dist_vs_obstime_censored'] = [float(x) for x in ss.spearmanr(grp['censored'].dist, grp['censored'].t, nan_policy='omit')]
    # start-temp of those that reach vs span: does start temp predict early stopping? bins of start
    b['sbin'] = pd.qcut(b.startc, 3, labels=['low', 'mid', 'high'])
    sb = {}
    for lab, g in b.groupby('sbin', observed=True):
        s = A.stats(g.t.values, g.ev.values, 600)
        sb[str(lab)] = dict(n=len(g), start_range=[float(g.startc.min()), float(g.startc.max())], reached=int(g.ev.sum()), censored=int((g.ev == 0).sum()),
                            median_obs_time_censored=float(g.loc[g.ev == 0, 't'].median()), F_km600=round(s['F_km'], 3), F_low600=round(s['F_low'], 3), F_high600=round(s['F_high'], 3), at_risk600=int((g.t >= 600).sum()))
    ind['by_start_tercile'] = sb
    # direct standardisation to overall start tercile mix
    mix = b.groupby('sbin', observed=True).size() / len(b)
    ind['F_km600_start_standardised'] = round(float(sum(mix[l] * sb[str(l)]['F_km600'] for l in mix.index)), 4)
    ind['F_km600_marginal'] = round(A.stats(b.t.values, b.ev.values, 600)['F_km'], 4)
    # observable-process check: temp at 300 s among drives still observed at 300 s; compare those that go on to be censored before 900 (non-event) vs those with obs >= 900 or event
    ref = 'cool' if fl == 'cool' else 'oil'
    v300 = b[f'{ref}_v300']; v120 = b[f'{ref}_v120']
    m = (b.t >= 300) & v300.notna()
    early_stop = m & (b.ev == 0) & (b.t < 600)
    cont = m & ((b.t >= 600))
    ind['temp_at_300s'] = dict(stop_before_600_n=int(early_stop.sum()), stop_median=float(v300[early_stop].median()) if early_stop.any() else None,
                               continue_n=int(cont.sum()), continue_median=float(v300[cont].median()), mannwhitney_p=float(ss.mannwhitneyu(v300[early_stop], v300[cont]).pvalue) if early_stop.sum() > 2 else None,
                               gain_from_start_stop=float((v300 - b.startc)[early_stop].median()) if early_stop.any() else None, gain_from_start_continue=float((v300 - b.startc)[cont].median()))
    m2 = (b.t >= 120) & v120.notna()
    es2 = m2 & (b.ev == 0) & (b.t < 300); c2 = m2 & (b.t >= 300)
    ind['temp_at_120s'] = dict(stop_before_300_n=int(es2.sum()), stop_median=float(v120[es2].median()) if es2.any() else None, continue_n=int(c2.sum()), continue_median=float(v120[c2].median()),
                               mannwhitney_p=float(ss.mannwhitneyu(v120[es2], v120[c2]).pvalue) if es2.sum() > 2 else None)
    # last observed temperature of censored (how close to threshold at key-off)
    lv = b.loc[b.ev == 0, f'{ref}_lastval']
    ind['censored_last_value_quantiles'] = {q: float(np.nanpercentile(lv, q)) for q in (10, 25, 50, 75, 90)}
    ind['censored_last_value_ge_thr_minus5'] = int((lv >= thr - 5).sum())
    # time origin offset
    o['independence'] = ind
    out[key] = o
# lag from origin to first valid coolant
cold = r[r.ff3_status == 'cold']
out['lag_first_valid_coolant_s'] = {q: float(np.percentile(cold.ff3_lag_first_valid, q)) for q in (50, 75, 90, 99, 100)}
out['start_coolant_quartiles'] = [float(x) for x in np.percentile(cold.ff3_cstart, [25, 50, 75])]
out['n_cold_by_regime'] = cold.thermal_regime.value_counts().to_dict()
out['n_cold_per_day_mean'] = float(len(cold) / cold.date.nunique())
json.dump(out, open(sys.argv[3], 'w', encoding='utf-8'), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
