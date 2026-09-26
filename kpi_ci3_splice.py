#!/usr/bin/env python3
"""kpi_ci3_splice.py (M285d): additive day-cluster intervals for the last Compare KPIs without one.
Usage: kpi_ci3_splice.py ARRAYS.json EXTRACT.pkl SEASONAL_DRIVE_MASTER.csv REPORT.json
Every recomputed POINT value is asserted equal to the shipped one (per cohort) before an interval is written; on any mismatch nothing is written.
Estimators: pooled/per-window MEDIANS -> day-clustered percentile bootstrap of the median (seed 42, 4000 draws; identical algorithm to the blocks' own dayboot);
SHARES -> ratio-of-sums with calendar-day clusters (kpi_ci.day_cluster_ci, seed 20260919, 4000 draws, Kish ESS)."""
import sys, json, pickle
sys.path.insert(0, '/home/claude/work/code')
import numpy as np, pandas as pd
from kpi_ci import day_cluster_ci
arr_p, ext_p, sdm_p, rep_p = sys.argv[1:5]
A = json.load(open(arr_p)); X = pickle.load(open(ext_p, 'rb')); HO = pickle.load(open('/home/claude/work/s3/ho_boostobs.pkl', 'rb')); sdm = pd.read_csv(sdm_p)
CH = A['seasonalCharts']['charts']
B = 4000
def dayboot_median(vals, days, nd, seed=42):
    v = np.asarray(vals, float); d = np.asarray(days); m = np.isfinite(v); v, d = v[m], d[m]
    if v.size < 3: return None
    uniq = np.unique(d); by = {k: v[d == k] for k in uniq}
    rng = np.random.default_rng(seed); meds = []
    for _ in range(B):
        s = rng.choice(uniq, len(uniq), replace=True); meds.append(np.median(np.concatenate([by[k] for k in s])))
    return {'bootMedian': round(float(np.median(v)), nd), 'ci95': [round(float(np.percentile(meds, 2.5)), nd), round(float(np.percentile(meds, 97.5)), nd)],
            'nSamples': int(v.size), 'nDays': int(uniq.size), 'method': 'day-clustered percentile bootstrap of the median (seed 42, 4000 draws); M285d'}
def share(num, den, days, nd):
    val, lo, hi, K, ess = day_cluster_ci(num, den, days, scale=100.0, B=B)
    return {'point': round(val, nd), 'ci95': [round(lo, nd), round(hi, nd)], 'nDays': K, 'essDays': round(ess, 2),
            'method': 'ratio-of-sums, calendar-day clusters, percentile bootstrap (seed 20260919, 4000 draws), Kish ESS; M285d'}
files = {'all': set(X.keys()), 'warm': set(sdm.loc[sdm.thermal_regime == 'warm', 'file']), 'shoulder': set(sdm.loc[sdm.thermal_regime == 'shoulder', 'file'])}
out = {}; problems = []; report = {}
for c, fs in files.items():
    R = [X[f] for f in X if f in fs]
    # EnergyShifting net kW (pooled samples, 5-15 km/h)
    vals, days = [], []
    for r in R:
        if r.get('esh_covered') and len(r.get('esh_net', [])):
            vals.append(r['esh_net'].astype(float)); days += [r['day']] * len(r['esh_net'])
    v = np.concatenate(vals); es = dayboot_median(v, days, 3)
    shipped = CH['EnergyShifting']['data'][c]['netKwLowSpeed']
    if abs(es['bootMedian'] - shipped) > 1e-9: problems.append(('ES netKw', c, es['bootMedian'], shipped))
    out[('EnergyShifting', c, 'netKwLowSpeedBoot')] = es
    # CellSpread
    L, H, ld, hd = [], [], [], []
    for r in R:
        for s_on, hf in r.get('csr', []):
            L.append(s_on); ld.append(r['day'])
            if hf == hf: H.append(hf); hd.append(r['day'])
    cs = CH['CellSpreadRelaxation']['data'][c]
    lb = dayboot_median(L, ld, 2); hb = dayboot_median(H, hd, 2)
    if abs(lb['bootMedian'] - cs['loadedSpreadMv']['median']) > 1e-9: problems.append(('CSR loaded', c, lb['bootMedian'], cs['loadedSpreadMv']['median']))
    if abs(hb['bootMedian'] - cs['relaxationHalfTimeS']['median']) > 1e-9: problems.append(('CSR half', c, hb['bootMedian'], cs['relaxationHalfTimeS']['median']))
    if len(L) != cs['nRestWindows']: problems.append(('CSR n', c, len(L), cs['nRestWindows']))
    out[('CellSpreadRelaxation', c, 'loadedSpreadBoot')] = lb; out[('CellSpreadRelaxation', c, 'relaxationHalfTimeBoot')] = hb
    # Handoff boost involvement -- corrected estimand: boost onsets / boost-OBSERVABLE handoffs (generator field boostInvolvementObservablePct)
    hb_rows = [(X[f]['day'],) + HO[f] for f in X if f in fs and HO[f][0] > 0]     # (day, n_events, n_boost_observable, n_boost_onset)
    hn = [r[1] for r in hb_rows]; ho_ = [r[2] for r in hb_rows]; hb_ = [r[3] for r in hb_rows]; hdays = [r[0] for r in hb_rows]
    sh = share(hb_, ho_, hdays, 1); sh['nEvents'] = int(sum(hn)); sh['nBoostObservable'] = int(sum(ho_))
    sh['estimand'] = 'boost onsets / handoffs whose event window carries a boost channel (boostInvolvementObservablePct)'
    HN = json.load(open('/home/claude/work/s3/handoff_new.json'))[c]
    if abs(sh['point'] - HN['boostInvolvementObservablePct']) > 1e-9: problems.append(('Handoff boost obs', c, sh['point'], HN['boostInvolvementObservablePct']))
    if abs(100.0 * sum(hb_) / sum(hn) - CH['HandoffSequence']['data'][c]['boostInvolvementPct']) > 0.05: problems.append(('Handoff boost shipped', c))
    out[('HandoffSequence', c, 'boostInvolvementBoot')] = sh
    out[('HandoffSequence', c, 'nBoostObservable')] = HN['nBoostObservable']
    out[('HandoffSequence', c, 'boostInvolvementObservablePct')] = HN['boostInvolvementObservablePct']
    # HighSocRegen shares
    hr = [r for r in R if 'hr_n' in r]
    n_ = [r['hr_n'] for r in hr]; d_ = [r['day'] for r in hr]
    for key, fld, ship in (('engineOnShareBoot', 'hr_eng_on', 'engineOnSharePct'), ('nonDeceleratingShareBoot', 'hr_nondec', 'nonDeceleratingSharePct')):
        s = share([r[fld] for r in hr], n_, d_, 2); s['nSamples'] = int(sum(n_))
        shipped = CH['HighSocRegen']['data'][c][ship]
        if abs(s['point'] - shipped) > 1e-9: problems.append(('HighSoc', c, ship, s['point'], shipped))
        out[('HighSocRegen', c, key)] = s
if problems:
    print('MISMATCH — nothing written'); [print(' ', p) for p in problems]; sys.exit(1)
for (blk, c, key), v in out.items():
    CH[blk]['data'][c][key] = v
    if isinstance(v, dict):
        report.setdefault(blk, {}).setdefault(c, {})[key] = {k: v[k] for k in ('ci95', 'nDays') if k in v} | ({'point': v.get('point', v.get('bootMedian'))})
    else:
        report.setdefault(blk, {}).setdefault(c, {})[key] = {'value': v}
# top-level handoffSequence (== cohort 'all' by construction) receives the same corrected-estimand fields
A['handoffSequence']['nBoostObservable'] = out[('HandoffSequence', 'all', 'nBoostObservable')]
A['handoffSequence']['boostInvolvementObservablePct'] = out[('HandoffSequence', 'all', 'boostInvolvementObservablePct')]
st = A['_artifactStamps']['seasonalCharts']
if 'M285d' not in st.get('computationStatusNote', ''):
    st['computationStatusNote'] = st.get('computationStatusNote', '') + ' | M285d: day-cluster CIs added to EnergyShifting (net kW 5-15 km/h), CellSpreadRelaxation (loaded spread, half-time), HandoffSequence (boost involvement, boost-observable denominator; generator estimand corrected, boostInvolvementPct retained as legacy low-bias field), HighSocRegen (engine-on / non-decelerating shares).'
json.dump(A, open(arr_p, 'w'), ensure_ascii=False, indent=1); json.dump(report, open(rep_p, 'w'), indent=1)
print('written', len(out), 'intervals; all point values reproduce shipped'); print(json.dumps(report, indent=1))
