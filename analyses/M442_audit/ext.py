"""Blind re-implementation of the M442 harmonized reduction + M441 interval extractor (auditor's own code)."""
import os, sys, pickle, math
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault('XT_RAW_DIR', os.path.join(ROOT, 'raw'))
import drive_raw_cache as drc
import compute_summary_arrays as csa

TEMP_BINS = csa.REGEN_TEMP_BINS
SOC_EDGES = [40, 50, 55, 60, 63, 66, 69, 72, 100]
CH = {'speed': '[VCM] Vehicle Speed (km/h)', 'I': '[BMS] HV Battery Current (A)', 'V': '[BMS] HV Battery voltage (V)',
      'rpm': 'Оберти двигуна (rpm)', 'soc': '[BMS] HV State of charge (%)',
      'T1': '[BMS] HV Battery Temperature Sensor 1 (℃)', 'T2': '[BMS] HV Battery Temperature Sensor 2 (℃)',
      'T3': '[BMS] HV Battery Temperature Sensor 3 (℃)', 'T4': '[BMS] HV Battery Temperature Sensor 4 (℃)'}
SIGN = +1   # charge = max(SIGN*I*V/1000, 0)  (BMS current charge-positive per spec)
GAPMAX = 5.0
SLICE = 0.05


def load_native(df):
    """-> dict ch -> (t, v) native arrays (dedup keep last), t0 (s from first native sample of any channel), tlast"""
    df, _ = csa._apply_speed_priority(df)
    tt = df['time']
    sec = (tt - tt.iloc[0]).dt.total_seconds().to_numpy()
    out = {}
    for k, c in CH.items():
        if c not in df.columns:
            out[k] = (np.array([]), np.array([])); continue
        v = pd.to_numeric(df[c], errors='coerce').to_numpy(dtype=float)
        m = np.isfinite(v)
        if k == 'speed':
            m &= (v >= 0) & (v <= 260)
        if k == 'soc':
            m &= (v >= 0) & (v <= 100)
        t, v = sec[m], v[m]
        if len(t):
            # duplicate timestamps keep last
            keep = np.ones(len(t), bool)
            keep[:-1] = t[1:] != t[:-1]
            t, v = t[keep], v[keep]
        out[k] = (t, v)
    allt = np.concatenate([out[k][0] for k in out if len(out[k][0])]) if any(len(out[k][0]) for k in out) else np.array([0.])
    t0 = allt.min()
    tl = allt.max()
    return out, t0, tl


def q90_interval(t):
    d = np.diff(t)
    d = d[(d > 0) & (d <= 5)]
    return float(np.quantile(d, 0.9)) if len(d) else np.nan


def decimate(nat, f, q):
    return {k: (t[q::f], v[q::f]) for k, (t, v) in nat.items()}


def harmonize(nat, t0, tl, delta, phase, interp=True):
    start = t0 + phase
    jmax = int(math.ceil((tl - start) / delta - 1e-9))
    nodes = start + delta * np.arange(0, jmax + 1)
    out = {}
    for k, (t, v) in nat.items():
        if len(t) == 0:
            out[k] = (t, v); continue
        if interp and k in ('speed', 'I', 'V'):
            a = np.searchsorted(t, nodes, 'right') - 1
            b = np.searchsorted(t, nodes, 'left')
            ok = (a >= 0) & (b < len(t))
            a2 = np.clip(a, 0, len(t) - 1); b2 = np.clip(b, 0, len(t) - 1)
            ok &= (t[b2] - t[a2]) <= GAPMAX
            vals = np.interp(nodes, t, v)
            out[k] = (nodes[ok], vals[ok])
        else:
            a = np.searchsorted(t, nodes, 'right') - 1
            ok = (a >= 0)
            a2 = np.clip(a, 0, len(t) - 1)
            ok &= t[a2] > nodes - delta
            out[k] = (t[a2][ok], v[a2][ok])
    return out


def latest_at(t, v, x, maxage):
    """latest sample at or before x with age<=maxage -> (value, ok)"""
    if len(t) == 0:
        return np.full(len(x), np.nan), np.zeros(len(x), bool)
    a = np.searchsorted(t, x, 'right') - 1
    a2 = np.clip(a, 0, len(t) - 1)
    ok = (a >= 0) & ((x - t[a2]) <= maxage + 1e-9)
    return np.where(ok, v[a2], np.nan), ok


def iv_supported(t, x0, x1):
    if len(t) < 2:
        return np.zeros(len(x0), bool)
    bad = np.concatenate([[0], np.cumsum((np.diff(t) > GAPMAX + 1e-9).astype(int))])
    a = np.searchsorted(t, x0, 'right') - 1
    b = np.searchsorted(t, x1, 'left')
    ok = (a >= 0) & (b < len(t))
    a2 = np.clip(a, 0, len(t) - 1); b2 = np.clip(b, 0, len(t) - 1)
    return ok & (bad[b2] - bad[a2] == 0)


def extract(ch, mass_kg):
    """ch: dict of (t,v) (already reduced). returns dict of per-kept-interval arrays."""
    st, sv = ch['speed']
    if len(st) < 2:
        return None
    x0 = st[:-1]; x1 = st[1:]; v0 = sv[:-1]; v1 = sv[1:]
    dt = x1 - x0
    gap = (dt > GAPMAX + 1e-9) | (dt <= 0)
    rt, rv = ch['rpm']
    r0, ok0 = latest_at(rt, rv, x0, 5.0)
    r1, ok1 = latest_at(rt, rv, x1, 5.0)
    rpm_known = ok0 & ok1
    # native rpm samples inside the interval above 300
    if len(rt):
        hi = np.concatenate([[0], np.cumsum((rv > 300).astype(int))])
        lo_i = np.searchsorted(rt, x0, 'left'); hi_i = np.searchsorted(rt, x1, 'right')
        inside_hi = (hi[hi_i] - hi[lo_i]) > 0
    else:
        inside_hi = np.zeros(len(x0), bool)
    engoff = rpm_known & (r0 <= 300) & (r1 <= 300) & ~inside_hi
    ivok = iv_supported(ch['I'][0], x0, x1) & iv_supported(ch['V'][0], x0, x1)
    valid = ~gap & engoff & ivok
    cand = valid & (v1 <= v0)
    strict = valid & (v0 > v1)
    n = len(x0)
    runid = np.cumsum(~cand)
    keep = np.zeros(n, bool)
    sidx = np.flatnonzero(strict)
    if len(sidx):
        rid = runid[sidx]
        uniq, first_i = np.unique(rid, return_index=True)
        last_i = np.concatenate([first_i[1:] - 1, [len(sidx) - 1]])
        for fi, li in zip(first_i, last_i):
            keep[sidx[fi]:sidx[li] + 1] = True
    keep &= cand
    k = np.flatnonzero(keep)
    if len(k) == 0:
        return None
    ke_ms = 0.5 * mass_kg * ((v0[k] / 3.6) ** 2 - (v1[k] / 3.6) ** 2) / 3.6e6
    # charge
    It, Iv = ch['I']; Vt, Vv = ch['V']
    chg = np.zeros(len(k))
    nsl = np.ceil(dt[k] / SLICE - 1e-6).astype(int)
    for N in np.unique(nsl):
        sel = np.flatnonzero(nsl == N)
        a = x0[k[sel]]; d = dt[k[sel]]
        nodes = a[:, None] + d[:, None] * (np.arange(N + 1)[None, :] / N)
        Ii = np.interp(nodes.ravel(), It, Iv).reshape(nodes.shape)
        Vi = np.interp(nodes.ravel(), Vt, Vv).reshape(nodes.shape)
        pc = np.maximum(SIGN * Ii * Vi / 1000.0, 0.0)
        h = d / N
        chg[sel] = (0.5 * (pc[:, :-1] + pc[:, 1:]) * h[:, None]).sum(1) / 3600.0
    # temperature and soc at interval start
    T = []
    tok = np.ones(len(k), bool)
    for kk in ('T1', 'T2', 'T3', 'T4'):
        val, ok = latest_at(*ch[kk], x0[k], 10.0)
        T.append(val); tok &= ok
    temp = np.where(tok, np.mean(T, axis=0), np.nan)
    soc, sok = latest_at(*ch['soc'], x0[k], 10.0)
    return dict(ke=ke_ms, chg=chg, strict=strict[k], temp=temp, soc=np.where(sok, soc, np.nan))


def tbin(temp):
    out = np.full(len(temp), -1)
    for i, (lo, hi, lbl) in enumerate(TEMP_BINS):
        out[(temp >= lo) & (temp < hi)] = i
    return out


def sbin(soc):
    """0..7 for the eight bands; 8 for below 40; -1 unknown"""
    out = np.full(len(soc), -1)
    fin = np.isfinite(soc)
    out[fin & (soc < 40)] = 8
    for i in range(8):
        lo, hi = SOC_EDGES[i], SOC_EDGES[i + 1]
        m = fin & (soc >= lo) & ((soc < hi) if i < 7 else (soc <= hi))
        out[m] = i
    return out


NT = len(TEMP_BINS)
CELLS = ['total'] + ['T%d' % i for i in range(NT)] + ['S%d' % i for i in range(9)]


def cellsums(r, um):
    """r from extract (with mass applied). returns array (ncell, 5): chg, ke, nstrict, nplateau, ke_um"""
    out = np.zeros((len(CELLS), 5))
    if r is None:
        return out
    tb = tbin(r['temp']); sb = sbin(r['soc'])
    vals = np.stack([r['chg'], r['ke'], r['strict'].astype(float), (~r['strict']).astype(float), r['ke'] * um], 1)
    out[0] = vals.sum(0)
    for i in range(NT):
        m = tb == i
        if m.any(): out[1 + i] = vals[m].sum(0)
    for i in range(9):
        m = sb == i
        if m.any(): out[1 + NT + i] = vals[m].sum(0)
    return out


def drive_variants(fname, dtype, fast, loader, deltas=(3.0,), do_dec=True):
    nat, t0, tl = load_native(loader(fname))
    mass = csa._mass_for_drive(dtype, fname)
    um = 1.0 if dtype in ('urban', 'mixed') else 0.0
    q = {k: q90_interval(nat[k][0]) for k in ('speed', 'I', 'V')}
    res = {'q90': q, 'mass': mass, 'um': um}
    phases = [0.0, 0.75, 1.5, 2.25]
    def run(natv):
        acc = np.zeros((len(CELLS), 5))
        for ph in phases:
            red = harmonize(natv, t0, tl, 3.0, ph, True)
            acc += cellsums(extract(red, mass), um)
        return acc / len(phases)
    res['nat'] = run(nat)
    if fast and do_dec:
        for f in (2, 3):
            acc = np.zeros((len(CELLS), 5))
            for qq in range(f):
                acc += run(decimate(nat, f, qq))
            res['d%d' % f] = acc / f
    return res
