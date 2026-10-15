"""Independent (blind) interval extractor v2 written from analyses/M441_spec.md sections 1,2,9,10 only.
Usage: python extract.py [--order A|B] [--out DIR] [--files f1,f2]
Time is handled in integer microseconds so that slice counts n=ceil(dt/0.05 s) are exact.
"""
import os, sys, pickle, argparse, json
import numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
import drive_raw_cache as drc

C_I = '[BMS] HV Battery Current (A)'
C_V = '[BMS] HV Battery voltage (V)'
C_SOC = '[BMS] HV State of charge (%)'
C_T = ['[BMS] HV Battery Temperature Sensor %d (℃)' % i for i in (1, 2, 3, 4)]
C_RPM = 'Оберти двигуна (rpm)'
C_SPD_VCM = '[VCM] Vehicle Speed (km/h)'
C_SPD_OBD = 'Швидкість автомобіля (km/h)'

NB = 14          # speed bins 0..12 = [10j,10j+10), 13 = overflow >=130
GAP_MAX = 5.0
SLICE_US = 50000  # 0.05 s
CV_MODE = 'consecutive'


def native(df, col, lo=None, hi=None, decimate=None):
    """Return (t_us int64, value float64) native numeric samples, sorted, duplicate timestamps keep last."""
    if col not in df.columns:
        return np.array([], dtype=np.int64), np.array([], dtype=float)
    x = pd.to_numeric(df[col], errors='coerce').to_numpy(float)
    ok = np.isfinite(x)
    if lo is not None:
        ok &= (x >= lo) & (x <= hi)
    t = df['time'].to_numpy('datetime64[us]').astype(np.int64)
    t, x = t[ok], x[ok]
    if len(t) > 1:
        keep = np.ones(len(t), bool)
        keep[:-1] = t[1:] != t[:-1]       # keep last of equal timestamps
        t, x = t[keep], x[keep]
    return t, x


def resolve_speed(df):
    """M167 rule (copied from _apply_speed_priority): VCM if >=20 non-null numeric samples, else OBD generic."""
    if C_SPD_OBD not in df.columns:
        return C_SPD_VCM
    vcm_ok = C_SPD_VCM in df.columns and pd.to_numeric(df[C_SPD_VCM], errors='coerce').notna().sum() >= 20
    return C_SPD_VCM if vcm_ok else C_SPD_OBD


def latest(tc, xc, tq, max_age_us):
    """latest native sample at or before tq with age<=max_age; returns value (nan if none)."""
    if len(tc) == 0:
        return np.full(len(tq), np.nan), np.zeros(len(tq), bool)
    i = np.searchsorted(tc, tq, 'right') - 1
    ok = i >= 0
    ii = np.where(ok, i, 0)
    age = tq - tc[ii]
    ok &= age <= max_age_us
    return np.where(ok, xc[ii], np.nan), ok


def interp_support(tc, xc, ts, te, gap_us):
    """piecewise-linear support: bracketing samples (at/before start, at/after end) exist and every consecutive gap
    among the samples from the first to the last bracket is <= gap_us."""
    n = len(ts)
    if len(tc) < 2:
        return np.zeros(n, bool)
    i0 = np.searchsorted(tc, ts, 'right') - 1
    i1 = np.searchsorted(tc, te, 'left')
    ok = (i0 >= 0) & (i1 < len(tc))
    g = (np.diff(tc) > gap_us).astype(np.int64)
    cum = np.concatenate([[0], np.cumsum(g)])   # cum[j] = bad gaps among gaps 0..j-1
    i0c = np.clip(i0, 0, len(tc) - 1)
    i1c = np.clip(i1, 0, len(tc) - 1)
    if CV_MODE == 'outer':
        return ok & ((tc[i1c] - tc[i0c]) <= gap_us)
    nbad = cum[i1c] - cum[i0c]
    return ok & (nbad == 0)


def extract(df, order='A', gap_max=GAP_MAX, lag_s=0.0, rpm_thr=300.0, i_off=0.0, cv_gap=GAP_MAX, decimate=None,
            float_slices=False):
    sp = resolve_speed(df)
    ts_, vs_ = native(df, sp, 0, 260)
    ti, xi = native(df, C_I)
    tv, xv = native(df, C_V)
    tr, xr = native(df, C_RPM)
    if lag_s:
        ti = ti + int(lag_s * 1e6); tv = tv + int(lag_s * 1e6)
    res = {'n_speed_samples': len(ts_)}
    if len(ts_) < 2:
        res.update(empty=True)
        return res
    ts = ts_[:-1]; te = ts_[1:]; v0 = vs_[:-1]; v1 = vs_[1:]
    dt_us = te - ts
    n = len(ts)
    gap = (dt_us > int(gap_max * 1e6)) | (dt_us <= 0)
    # I/V support
    cv_ok = interp_support(ti, xi, ts, te, int(cv_gap * 1e6)) & interp_support(tv, xv, ts, te, int(cv_gap * 1e6))
    # RPM
    r0, k0 = latest(tr, xr, ts, 5_000_000)
    r1, k1 = latest(tr, xr, te, 5_000_000)
    rpm_known = k0 & k1
    # any native rpm sample strictly inside (ts,te) above thr
    if len(tr):
        hi_idx = np.flatnonzero(xr > rpm_thr)
        th = tr[hi_idx]
        a = np.searchsorted(th, ts, 'right'); b = np.searchsorted(th, te, 'left')
        inside_hi = b > a
    else:
        inside_hi = np.zeros(n, bool)
    eng_off = rpm_known & (r0 <= rpm_thr) & (r1 <= rpm_thr) & ~inside_hi
    inc = v1 > v0   # speed increase
    # reason assignment by precedence
    reason = np.full(n, '', dtype=object)   # '' = valid
    def setr(mask, name):
        sel = mask & (reason == '')
        reason[sel] = name
    if order == 'A':
        setr(gap, 'speedGap'); setr(~cv_ok, 'currentOrVoltageUnsupported'); setr(~rpm_known, 'rpmUnknown')
        setr(~eng_off, 'engineOn'); setr(inc, 'notDecelOrFlat')
    elif order == 'B':
        setr(gap, 'speedGap'); setr(inc, 'notDecelOrFlat'); setr(~cv_ok, 'currentOrVoltageUnsupported'); setr(~rpm_known, 'rpmUnknown')
        setr(~eng_off, 'engineOn')
    elif order == 'C':   # gap, rpm, engine, cv, notDecel
        setr(gap, 'speedGap'); setr(~rpm_known, 'rpmUnknown'); setr(~eng_off, 'engineOn'); setr(~cv_ok, 'currentOrVoltageUnsupported'); setr(inc, 'notDecelOrFlat')
    elif order == 'D':   # gap, cv, notDecel, rpm, engine
        setr(gap, 'speedGap'); setr(~cv_ok, 'currentOrVoltageUnsupported'); setr(inc, 'notDecelOrFlat'); setr(~rpm_known, 'rpmUnknown'); setr(~eng_off, 'engineOn')
    else:
        raise ValueError(order)
    valid = reason == ''
    excl = {k: int((reason == k).sum()) for k in
            ['speedGap', 'currentOrVoltageUnsupported', 'rpmUnknown', 'engineOn', 'notDecelOrFlat']}
    # episodes among valid (v1<=v0, engine-off, supported): maximal runs of consecutive indices
    strict = valid & (v1 < v0)
    kind = np.full(n, -1, np.int8)   # -1 invalid, 0 strict, 1 plateau kept, 2 plateau trimmed
    idx = np.flatnonzero(valid)
    if len(idx):
        brk = np.flatnonzero(np.diff(idx) != 1) + 1
        runs = np.split(idx, brk)
        for r in runs:
            s = strict[r]
            if not s.any():
                kind[r] = 2
                continue
            f = np.argmax(s); l = len(s) - 1 - np.argmax(s[::-1])
            kind[r[:f]] = 2; kind[r[l + 1:]] = 2
            kind[r[f:l + 1]] = np.where(s[f:l + 1], 0, 1)
    sel = np.flatnonzero(kind >= 0)
    # ---- charge & slices for all valid (kind>=0) intervals
    if len(sel) == 0:
        res.update(empty=False, excl=excl, iv=None, n_intervals=int(n), ends0=0)
        return res
    dts = dt_us[sel]
    if float_slices:
        ns = np.ceil((dts / 1e6) / 0.05).astype(np.int64)
    else:
        ns = -(-dts // SLICE_US)           # exact integer ceil
    ns = np.maximum(ns, 1)
    tot = int(ns.sum())
    rep = np.repeat(np.arange(len(sel)), ns)
    start_pos = np.cumsum(ns) - ns
    j = np.arange(tot) - np.repeat(start_pos, ns)
    nn = np.repeat(ns, 1)[rep]
    # node times (us, float for interp), nodes j and j+1
    tsel = ts[sel][rep].astype(np.float64); dtsel = dts[rep].astype(np.float64)
    tA = tsel + dtsel * j / nn
    tB = tsel + dtsel * (j + 1) / nn
    def interp(tc, xc, tq):
        return np.interp(tq, tc.astype(np.float64), xc)
    pA = np.maximum(interp(ti, xi, tA) * interp(tv, xv, tA) / 1000.0, 0.0)
    pB = np.maximum(interp(ti, xi, tB) * interp(tv, xv, tB) / 1000.0, 0.0)
    h = dtsel / nn / 1e6   # s
    ch = 0.5 * (pA + pB) * h / 3600.0      # kWh
    # offset-charge (I + i_off), kept for dual report
    if i_off:
        pAo = np.maximum((interp(ti, xi, tA) + i_off) * interp(tv, xv, tA) / 1000.0, 0.0)
        pBo = np.maximum((interp(ti, xi, tB) + i_off) * interp(tv, xv, tB) / 1000.0, 0.0)
        cho = 0.5 * (pAo + pBo) * h / 3600.0
    v0r = v0[sel][rep]; v1r = v1[sel][rep]
    # speeds at nodes and exact midpoint-bin
    vA = v0r + (v1r - v0r) * j / nn
    vB = v0r + (v1r - v0r) * (j + 1) / nn
    dv2 = vA * vA - vB * vB
    num = 2.0 * nn * v0r + (v1r - v0r) * (2.0 * j + 1.0)     # = 2n * mid
    b = np.floor(num / (20.0 * nn)).astype(np.int64)
    b = np.clip(b, 0, 13)
    interval_charge = np.bincount(rep, weights=ch, minlength=len(sel))
    key = rep * NB + b
    bin_dv2 = np.bincount(key, weights=dv2, minlength=len(sel) * NB).reshape(len(sel), NB)
    bin_ch = np.bincount(key, weights=ch, minlength=len(sel) * NB).reshape(len(sel), NB)
    touched = np.bincount(key, minlength=len(sel) * NB).reshape(len(sel), NB) > 0
    # temperature & SOC at interval start
    tsel_i = ts[sel]
    tmp = []
    okT = np.ones(len(sel), bool)
    for c in C_T:
        tc_, xc_ = native(df, c)
        vv, ok = latest(tc_, xc_, tsel_i, 10_000_000)
        tmp.append(vv); okT &= ok
    temp = np.where(okT, np.mean(tmp, axis=0), np.nan)
    tcs, xcs = native(df, C_SOC, 0, 100)
    soc, oks = latest(tcs, xcs, tsel_i, 10_000_000)
    iv = pd.DataFrame({'k': sel, 'kind': kind[sel], 't0_us': tsel_i, 'dt_s': dts / 1e6, 'v0': v0[sel], 'v1': v1[sel],
                       'charge': interval_charge, 'dv2': v0[sel] ** 2 - v1[sel] ** 2, 'temp': temp, 'soc': soc,
                       'rpm0': r0[sel]})
    if i_off:
        iv['charge_off'] = np.bincount(rep, weights=cho, minlength=len(sel))
    res.update(empty=False, excl=excl, iv=iv, bin_dv2=bin_dv2.astype(np.float64), bin_ch=bin_ch, touched=touched,
               n_intervals=int(n), ends0=((v1[sel] == 0) & (kind[sel] == 0)).sum(),
               med_dt_speed=float(np.median(dt_us / 1e6)))
    return res


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--order', default='A')
    ap.add_argument('--out', default='analyses/M441_audit/cache_A')
    ap.add_argument('--files', default='')
    ap.add_argument('--float_slices', action='store_true')
    ap.add_argument('--cv_mode', default='consecutive')
    ap.add_argument('--slice_us', type=int, default=50000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    CV_MODE = a.cv_mode; SLICE_US = a.slice_us
    L = drc.make_frame_loader(raw_dir='raw_only')
    m = pd.read_csv('drive_master.csv', usecols=['file'])
    files = a.files.split(',') if a.files else list(m.file)
    for f in files:
        df = L(f)
        r = extract(df, order=a.order, float_slices=a.float_slices)
        r['file'] = f
        with open(os.path.join(a.out, f + '.pkl'), 'wb') as fh:
            pickle.dump(r, fh)
    print('done', len(files))
