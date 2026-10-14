import sys, json, numpy as np, pandas as pd
sys.path.insert(0, r"C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo\analyses\M440_audit")
from a2_bins import TB, sbin, REPO
d = pd.read_pickle(sys.argv[1]); OUT = sys.argv[2]
a = json.load(open(REPO + r'\summary_arrays.json', encoding='utf-8'))
ioff = a['offsetUncertainty']['pointEstimateA']
dm = pd.read_csv(REPO + r'\drive_master.csv', encoding='utf-8')
d['cadence'] = np.where(dm['ev_rpm_dt_med_s'].reindex(d.k).values < 1.0, 'fast', np.where(dm['ev_rpm_dt_med_s'].reindex(d.k).isna().values, 'unknown', 'slow'))
d['cap_off'] = np.maximum((d.I + ioff) * d.V / 1000.0, 0) / 3600.0
d['smid'] = sbin(d.speed.values); d['smid4'] = sbin(d.vprev.values)
d['amax'] = d[['age_spd', 'age_spd_prev', 'age_I', 'age_V', 'age_rpm']].max(axis=1)
V = {'V1': ~d.rpm_nan, 'V2_2': d.amax <= 2, 'V2_5': d.amax <= 5, 'V2_10': d.amax <= 10, 'V3': d.gap == 1.0, 'V5': d.nprobe == 4}
days = np.array(sorted(d.day.unique())); dix = pd.Series(np.arange(len(days)), index=days)[d.day].values
temp_labels = [l for _, _, l in TB]
tb = {l: (d.Tpack.notna() & (d.Tpack >= lo) & (d.Tpack < hi)).values for lo, hi, l in TB}
sb = {int(b): (d.smid == b).values for b in sorted(d.smid.unique())}
sb4 = {int(b): (d.smid4 == b).values for b in sorted(d.smid4.unique())}
rng = np.random.default_rng(42); B = 4000
draws = rng.integers(0, len(days), size=(B, len(days)))
def ci_ratio(bin_mask, keep, capcol='cap', legacy_mask=None):
    """day-clustered percentile bootstrap of eff_v - eff_0; legacy_mask = bin of legacy (for V4, different bin def)."""
    lm = bin_mask if legacy_mask is None else legacy_mask
    cv = np.bincount(dix, weights=(d[capcol].values * (bin_mask & keep)), minlength=len(days))
    kv = np.bincount(dix, weights=(d.ke.values * (bin_mask & keep)), minlength=len(days))
    c0 = np.bincount(dix, weights=(d.cap.values * lm), minlength=len(days))
    k0 = np.bincount(dix, weights=(d.ke.values * lm), minlength=len(days))
    ndays = int(((bin_mask & keep) | lm).astype(int).__array__().sum() > 0)
    KV = kv[draws].sum(1); K0 = k0[draws].sum(1)
    ok = (KV > 0) & (K0 > 0)
    de = 100 * cv[draws].sum(1)[ok] / KV[ok] - 100 * c0[draws].sum(1)[ok] / K0[ok]
    ncontrib = int((np.bincount(dix, weights=(bin_mask & keep) | lm, minlength=len(days)) > 0).sum())
    if ncontrib < 5: return None, ncontrib, 1 - ok.mean()
    return [float(np.percentile(de, 2.5)), float(np.percentile(de, 97.5))], ncontrib, float(1 - ok.mean())
def cell(bm, keep, capcol='cap', legacy_mask=None, boot=True):
    lm = bm if legacy_mask is None else legacy_mask
    m = bm & keep
    n0 = int(lm.sum()); n1 = int(m.sum())
    e0 = 100 * d.cap.values[lm].sum() / d.ke.values[lm].sum() if n0 else None
    e1 = 100 * d[capcol].values[m].sum() / d.ke.values[m].sum() if n1 else None
    r = {'n0': n0, 'n': n1, 'eff0': e0, 'eff': e1, 'delta': None if (e0 is None or e1 is None) else e1 - e0}
    rem = lm & ~keep if legacy_mask is None else None
    if rem is not None and rem.sum() and keep is not None:
        r['n_removed'] = int(rem.sum()); r['eff_removed'] = 100 * d.cap.values[rem].sum() / d.ke.values[rem].sum()
        r['ke_share_ret'] = float(d.ke.values[m].sum() / d.ke.values[lm].sum())
        w = 1 - r['ke_share_ret']
        if e1 is not None: r['identity_err'] = float(r['delta'] - w * (e1 - r['eff_removed']))
    if boot and n0 and n1:
        r['ci'], r['ndays'], r['unid'] = ci_ratio(bm, keep, capcol, legacy_mask)
    return r
res = {}
allk = np.ones(len(d), bool)
for name, keep in V.items():
    keep = keep.values
    res[name] = {'steps_removed': int((~keep).sum()), 'steps_retained_share': float(keep.mean()), 'ke_retained_share': float(d.ke.values[keep].sum() / d.ke.sum()),
                 'drives_with_removed': int(d.k[~keep].nunique()), 'temp': {}, 'speed': {}}
    for l in temp_labels:
        if tb[l].sum(): res[name]['temp'][l] = cell(tb[l], keep)
    if name != 'V5':
        for b, m in sb.items(): res[name]['speed'][b] = cell(m, keep)
    for c in ['fast', 'slow', 'unknown']:
        mc = (d.cadence == c).values
        if mc.sum(): res[name].setdefault('cadence_retained_share', {})[c] = float(keep[mc].mean()); res[name].setdefault('cadence_n', {})[c] = int(mc.sum())
# V4 speed view
res['V4'] = {'speed': {}}
chg = d.smid != d.smid4
res['V4']['share_steps_change_bin'] = float(chg.mean())
res['V4']['ke_moved_up'] = float(d.ke[(d.smid4 > d.smid)].sum() / d.ke.sum()); res['V4']['ke_moved_down'] = float(d.ke[(d.smid4 < d.smid)].sum() / d.ke.sum())
bins = sorted(set(sb) | set(sb4))
for b in bins:
    if b in sb:
        r = cell(sb4.get(b, np.zeros(len(d), bool)), allk, legacy_mask=sb[b]); res['V4']['speed'][b] = r
# V6
res['V6'] = {'ioff': ioff, 'temp': {}, 'speed': {}}
for l in temp_labels:
    m = tb[l]
    if m.sum():
        r = cell(m, allk, 'cap_off'); r['shift_pp'] = float(100 * (d.cap_off.values[m].sum() - d.cap.values[m].sum()) / d.ke.values[m].sum()); res['V6']['temp'][l] = r
for b, m in sb.items():
    r = cell(m, allk, 'cap_off'); r['shift_pp'] = float(100 * (d.cap_off.values[m].sum() - d.cap.values[m].sum()) / d.ke.values[m].sum()); res['V6']['speed'][b] = r
# VCa (V1+V2(5)+V3 [+V5 temp | V4 speed excl part]) 
vca = (V['V1'] & V['V2_5'] & V['V3']).values
res['VCa_exclusions'] = {'retained_share': float(vca.mean()), 'temp': {l: cell(tb[l], vca & V['V5'].values) for l in temp_labels if tb[l].sum()}}
json.dump(res, open(OUT, 'w', encoding='utf-8'), indent=1, default=float)
d.to_pickle(OUT.replace('.json', '_d.pkl'))
