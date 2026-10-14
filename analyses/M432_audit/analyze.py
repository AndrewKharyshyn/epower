import os, pickle, json, itertools
import numpy as np, pandas as pd
REPO = r'C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo'
AD = os.path.join(REPO, 'analyses', 'M432_audit')
R = {r['file']: r for r in pickle.load(open(os.path.join(AD, 'extract.pkl'), 'rb'))}
dm = pd.read_csv(os.path.join(REPO, 'drive_master.csv'), low_memory=False).copy()


def as_bool(s):
    return s.map(lambda x: x is True or str(x).strip().lower() == 'true').astype(bool)


dm['ens'] = as_bool(dm['ens_outlier_v2'])
dm['mvalid'] = as_bool(dm['ev_valid'])
dm = dm.reset_index(drop=True)
files = dm['file'].tolist()
dist_km = dm['distance_km'].values
day = dm['date'].astype(str).values
OUT = {}


def valid_vec(align, G=0.95):
    out = np.zeros(len(files), bool)
    for i, f in enumerate(files):
        r = R[f]
        if not r['ok']:
            continue
        out[i] = bool(r['cov'][align] >= G and r['cov_speed'] >= G and r['base_ok'])
    return out


def ev_vec(align, T, B):
    return np.array([R[f]['dist'][align + (T, B)] if R[f]['ok'] else np.nan for f in files])


S0A = ('nearest', 3.0)
# --- G1 parity
v0 = valid_vec(S0A)
par = {'valid_mismatch': int((v0 != dm['mvalid'].values).sum())}
e0 = ev_vec(S0A, 400, 3)
m = dm['ev_dist_km'].notna().values
par['ev_dist_maxabsdiff'] = float(np.nanmax(np.abs(e0[m] - dm['ev_dist_km'].values[m])))
par['cov_rpm_maxabsdiff'] = float(max(abs(R[f]['cov'][S0A] - c) for f, c in zip(files, dm['ev_cov_rpm']) if R[f]['ok'] and not np.isnan(c)))
par['cov_speed_maxabsdiff'] = float(max(abs(R[f]['cov_speed'] - c) for f, c in zip(files, dm['ev_cov_speed']) if R[f]['ok'] and not np.isnan(c)))
par['k_maxabsdiff'] = float(max(abs(R[f]['k'] - c) for f, c in zip(files, dm['ev_dist_scale_k']) if R[f]['ok'] and not np.isnan(c)))
bad_ok = [f for f in files if not R[f]['ok']]
par['not_ok_files'] = bad_ok
OUT['parity'] = par
print(par)

P0 = v0 & ~dm['ens'].values
n0 = int(P0.sum())
km0 = dist_km[P0].sum(); ev0 = e0[P0].sum()
S0 = 100 * ev0 / km0
OUT['S0'] = dict(n=n0, km=round(km0, 1), ev=round(ev0, 1), share=round(S0, 3))
print(OUT['S0'], 'masterP0', int((dm['mvalid'] & ~dm['ens']).sum()))


# bootstrap
def boot(num, den, days, B=4000, seed=42):
    ud, inv = np.unique(days, return_inverse=True)
    nd = len(ud)
    sn = np.bincount(inv, weights=num, minlength=nd)
    sd = np.bincount(inv, weights=den, minlength=nd)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, nd, size=(B, nd))
    est = 100 * sn[idx].sum(1) / sd[idx].sum(1)
    pt = 100 * sn.sum() / sd.sum()
    return pt, np.percentile(est, [2.5, 97.5]), nd, sd


def boot_delta(num, den, days, B=4000, seed=42):
    ud, inv = np.unique(days, return_inverse=True)
    nd = len(ud)
    sn = np.bincount(inv, weights=num, minlength=nd)
    sd = np.bincount(inv, weights=den, minlength=nd)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, nd, size=(B, nd))
    est = 100 * sn[idx].sum(1) / sd[idx].sum(1)
    return 100 * sn.sum() / sd.sum(), np.percentile(est, [2.5, 97.5])


pt, ci, nd, sd = boot(e0[P0], dist_km[P0], day[P0])
w = sd[sd > 0]
kish = float(w.sum() ** 2 / (w ** 2).sum())
cnt = pd.Series(day[P0]).value_counts().values.astype(float)
OUT['boot0'] = dict(point=round(pt, 3), ci=[round(ci[0], 2), round(ci[1], 2)], n_days=nd,
                    kish_days_km=round(kish, 1), kish_days_drives=round(cnt.sum() ** 2 / (cnt ** 2).sum(), 1))
print(OUT['boot0'])

# ------------- variants
era_fast = np.array([R[f]['ok'] and R[f]['dt_med'] < 1.0 for f in files])


def evaluate(align, T, B, G=0.95, name=None, with_boot=False):
    vv = valid_vec(align, G) & ~dm['ens'].values  # P_v
    Cv = P0 & vv
    ev_v = ev_vec(align, T, B)
    sh0C = 100 * e0[Cv].sum() / dist_km[Cv].sum()
    shvC = 100 * ev_v[Cv].sum() / dist_km[Cv].sum()
    shvP = 100 * np.nansum(ev_v[vv]) / dist_km[vv].sum()
    d = dict(name=name, nC=int(Cv.sum()), nP=int(vv.sum()),
             pct_drives=100 * Cv.sum() / n0, pct_km=100 * dist_km[Cv].sum() / km0,
             days=int(len(np.unique(day[Cv]))),
             delta=shvC - sh0C, lost=sh0C - S0, gained=shvP - shvC, total=shvP - S0)
    d['sum_check'] = d['delta'] + d['lost'] + d['gained'] - d['total']
    d['comparable'] = bool(d['pct_drives'] >= 90 and d['pct_km'] >= 90)
    if with_boot:
        pt, ci = boot_delta(ev_v[Cv] - e0[Cv], dist_km[Cv], day[Cv])
        # paired Delta bootstrap: ratio of per-day sums of (ev_v-ev_0) over distance
        d['delta_boot_ci'] = [100 * 0 + ci[0], ci[1]]
    # unknown-RPM share grid seconds (all P_v)
    sec_unk = sum(R[files[i]]['ngrid'] * (1 - R[files[i]]['cov'][align]) for i in np.where(vv)[0])
    sec_tot = sum(R[files[i]]['ngrid'] for i in np.where(vv)[0])
    d['unk_share_pct'] = 100 * sec_unk / sec_tot
    d['_Cv'] = Cv
    return d


rows = []
spec = []
for T in [100, 200, 800]:
    spec.append((f'T={T}', ('nearest', 3.0), T, 3, 0.95))
for A in [0.5, 1.0, 1.5]:
    spec.append((f'nearest A={A}', ('nearest', A), 400, 3, 0.95))
for A in [1.0, 1.5, 3.0]:
    spec.append((f'backward matched A={A} (one-sided {2*A})', ('backward', 2 * A), 400, 3, 0.95))
    spec.append((f'forward matched A={A} (one-sided {2*A})', ('forward', 2 * A), 400, 3, 0.95))
spec.append(('backward same-tol 3.0 (stress)', ('backward', 3.0), 400, 3, 0.95))
for B in [0, 2, 5, 10]:
    spec.append((f'B={B}', ('nearest', 3.0), 400, B, 0.95))
for G in [0.90, 0.98]:
    spec.append((f'G={G}', ('nearest', 3.0), 400, 3, G))
res = {}
for nm, al, T, B, G in spec:
    d = evaluate(al, T, B, G, nm, with_boot=True)
    res[nm] = d
    print(f"{nm:45s} Delta={d['delta']:+.3f} lost={d['lost']:+.3f} gained={d['gained']:+.3f} sum_chk={d['sum_check']:.1e} "
          f"nC={d['nC']} {d['pct_drives']:.1f}%/{d['pct_km']:.1f}% days={d['days']} comp={d['comparable']} unk={d['unk_share_pct']:.2f} ci={np.round(d['delta_boot_ci'],3)}")
OUT['oneatatime'] = {k: {kk: (round(float(vv), 3) if isinstance(vv, (float, np.floating)) else vv) for kk, vv in d.items() if kk != '_Cv'} for k, d in res.items()}

# factorial
cells = []
for T in [100, 200, 400, 800]:
    for D in ['nearest', 'backward', 'forward']:
        for A in [1.0, 1.5, 3.0]:
            for B in [0, 2, 3, 5]:
                al = (D, A if D == 'nearest' else 2 * A)
                d = evaluate(al, T, B, 0.95)
                cells.append((T, D, A, B, d['delta'], d['comparable'], d['pct_drives'], d['pct_km']))
cf = pd.DataFrame(cells, columns=['T', 'D', 'A', 'B', 'delta', 'comp', 'pdr', 'pkm'])
cf.to_csv(os.path.join(AD, 'factorial.csv'), index=False)
cc = cf[cf.comp]
imin = cc.delta.idxmin(); imax = cc.delta.idxmax()
OUT['factorial'] = dict(n_cells=len(cf), n_comparable=int(cf.comp.sum()), min=round(cc.delta.min(), 3), max=round(cc.delta.max(), 3),
                        min_cell=cf.loc[imin, ['T', 'D', 'A', 'B']].tolist(), max_cell=cf.loc[imax, ['T', 'D', 'A', 'B']].tolist())
print(OUT['factorial'])
print(cf.groupby('D').delta.agg(['min', 'max']))
print('S0 range', S0 + cc.delta.min(), S0 + cc.delta.max())

# unknown RPM share in released
sec_unk = sum(R[files[i]]['ngrid'] * (1 - R[files[i]]['cov'][S0A]) for i in np.where(P0)[0])
sec_tot = sum(R[files[i]]['ngrid'] for i in np.where(P0)[0])
OUT['unk_released_P0_pct'] = round(100 * sec_unk / sec_tot, 3)
print('unk', OUT['unk_released_P0_pct'])

# Q3: era split for backward/forward matched and others
Q3 = {}
for nm in ['backward matched A=3.0 (one-sided 6.0)', 'forward matched A=3.0 (one-sided 6.0)', 'backward matched A=1.0 (one-sided 2.0)',
           'forward matched A=1.0 (one-sided 2.0)', 'backward matched A=1.5 (one-sided 3.0)', 'forward matched A=1.5 (one-sided 3.0)',
           'backward same-tol 3.0 (stress)', 'nearest A=1.0', 'nearest A=1.5']:
    d = res[nm]
    spec_i = [s for s in spec if s[0] == nm][0]
    Cv = d['_Cv']
    ev_v = ev_vec(spec_i[1], spec_i[2], spec_i[3])
    q = {}
    for ename, em in [('fast', era_fast), ('slow', ~era_fast)]:
        c = Cv & em
        base = 100 * e0[c].sum() / dist_km[c].sum()
        q[ename] = dict(n=int(c.sum()), delta=round(100 * ev_v[c].sum() / dist_km[c].sum() - base, 3), base_share=round(base, 2),
                        P0_n=int((P0 & em).sum()), common_pct=round(100 * c.sum() / max(1, (P0 & em).sum()), 1))
    Q3[nm] = q
    print(nm, q)
OUT['Q3_era'] = Q3
OUT['era_counts_P0'] = dict(fast=int((P0 & era_fast).sum()), slow=int((P0 & ~era_fast).sum()),
                            share_fast=round(100 * e0[P0 & era_fast].sum() / dist_km[P0 & era_fast].sum(), 2),
                            share_slow=round(100 * e0[P0 & ~era_fast].sum() / dist_km[P0 & ~era_fast].sum(), 2))
print(OUT['era_counts_P0'])
# era split for T and B too
for nm in ['T=100', 'T=800', 'B=0', 'B=5']:
    Cv = res[nm]['_Cv']; spec_i = [s for s in spec if s[0] == nm][0]
    ev_v = ev_vec(spec_i[1], spec_i[2], spec_i[3])
    for ename, em in [('fast', era_fast), ('slow', ~era_fast)]:
        c = Cv & em
        print(nm, ename, round(100 * ev_v[c].sum() / dist_km[c].sum() - 100 * e0[c].sum() / dist_km[c].sum(), 3))

# Q4: sign shares per drive
Q4 = {}
for nm in ['B=0', 'B=2', 'B=5', 'B=10', 'T=100', 'T=800', 'backward matched A=3.0 (one-sided 6.0)', 'forward matched A=3.0 (one-sided 6.0)', 'nearest A=1.0']:
    spec_i = [s for s in spec if s[0] == nm][0]
    Cv = res[nm]['_Cv']
    ev_v = ev_vec(spec_i[1], spec_i[2], spec_i[3])
    dd = ev_v[Cv] - e0[Cv]
    km = dist_km[Cv]
    pos = dd > 5e-4; neg = dd < -5e-4
    Q4[nm] = dict(n=int(Cv.sum()), pos=int(pos.sum()), neg=int(neg.sum()), zero=int((~pos & ~neg).sum()),
                  pos_pct=round(100 * pos.mean(), 1), neg_pct=round(100 * neg.mean(), 1),
                  sum_pos_km=round(float(dd[pos].sum()), 2), sum_neg_km=round(float(dd[neg].sum()), 2),
                  pp_pos=round(100 * dd[pos].sum() / km.sum(), 3), pp_neg=round(100 * dd[neg].sum() / km.sum(), 3),
                  max_abs_drive_pp=round(float(np.max(np.abs(100 * dd / km))), 2))
    print(nm, Q4[nm])
OUT['Q4_signs'] = Q4

# Q1 band
ex = [R[files[i]]['ex'] for i in np.where(P0)[0]]
tot_known = sum(e['ngrid'] - e['unk'] for e in ex)
Q1 = {}
for nm in ['le100', 'b100_200', 'b200_400', 'b400_800', 'gt800']:
    s = sum(e['s_' + nm] for e in ex)
    k = sum(e['km_' + nm] for e in ex)
    mv = sum(e['mov_' + nm] for e in ex)
    Q1[nm] = dict(sec=s, pct_known_sec=round(100 * s / tot_known, 3), km=round(k, 1), pct_km=round(100 * k / km0, 3), moving_sec=mv)
bs = sum(e['s_b100_200'] + e['s_b200_400'] + e['s_b400_800'] for e in ex)
Q1['band100_800_total'] = dict(sec=bs, pct_known_sec=round(100 * bs / tot_known, 3))
rl = {}
for e in ex:
    for k_, v_ in e['band_runlen_s'].items():
        rl[k_] = rl.get(k_, 0) + v_
Q1['band_grid_runlen_seconds'] = rl
ctx = {}
for e in ex:
    for k_, v_ in e['nat_ctx'].items():
        ctx[str(k_)] = ctx.get(str(k_), 0) + int(v_)
Q1['native_band_context_samples'] = ctx
Q1['native'] = dict(n=sum(e['nat_n'] for e in ex), band=sum(e['nat_band'] for e in ex), le100=sum(e['nat_le100'] for e in ex), gt800=sum(e['nat_gt800'] for e in ex))
Q1['native_hist_100_150_200_250_300_350_400_500_600_700_800'] = np.sum([e['nat_hist'] for e in ex], axis=0).tolist()
Q1['band_secs_far_from_native'] = dict(gt0p5=sum(e['band_sec_dist_gt05'] for e in ex), gt1=sum(e['band_sec_dist_gt1'] for e in ex))
OUT['Q1_band'] = Q1
print(json.dumps(Q1, indent=1, default=lambda o: o.item() if hasattr(o,'item') else str(o)))

json.dump(OUT, open(os.path.join(AD, 'audit_results.json'), 'w', encoding='utf-8'), indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
