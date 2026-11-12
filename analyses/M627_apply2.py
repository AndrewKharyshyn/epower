"""M627 edit #2 (audit finding): unit, ceiling and era counts are header-based (every drive carrying the channel), independent of a usable I-V pairing."""
p = 'compute_summary_arrays.py'
s = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s[:5000] else '\n'


def N(t):
    return t.replace('\n', nl)


def rep(old, new):
    global s
    o, n = N(old), N(new)
    assert s.count(o) == 1, (old[:70], s.count(o))
    s = s.replace(o, n)


# 1. events: unit statistics first (header-based, no I-V pairing needed); pairing failures return a 'noPairing' record instead of None
rep('''    df = df_raw.rename(columns={k: v for k, v in _v6.COL_MAP.items() if k in df_raw.columns})
    t = _ft(df['time'], mixed=True)
    I = _v6._series(df, t, 'I')
    if I is not None:
        I = I[I['v'].abs() < 900]
    V = _v6._series(df, t, 'V', lo=200, hi=450)
    if I is None or V is None or not len(I) or not len(V):
        return None
    e = _v6._asof(I.copy(), V, 'V', _v6.V_ALIGN_TOL).dropna(subset=['V'])
    if not len(e):
        return None
    e['P_kw'] = e['v'] * e['V'] / 1000.0     # charge-positive raw (M11)
    e = e[['t', 'P_kw']].sort_values('t')

    out = {'file': filename, 'charge': [], 'discharge': [], 'unit': {}}
    for label, direction in (('charge', 0), ('discharge', 1)):
        s, era = _hdrm_pp_series(df_raw, direction)
        if s is None:
            continue
        pp = pd.DataFrame({'t': t, 'pp_kw': s}).dropna().sort_values('t')
        if not len(pp):
            continue
        gaps = pp['t'].diff().dt.total_seconds().dropna()
''', '''    df = df_raw.rename(columns={k: v for k, v in _v6.COL_MAP.items() if k in df_raw.columns})
    t = _ft(df['time'], mixed=True)
    I = _v6._series(df, t, 'I')
    if I is not None:
        I = I[I['v'].abs() < 900]
    V = _v6._series(df, t, 'V', lo=200, hi=450)
    e = None
    if I is not None and V is not None and len(I) and len(V):
        e = _v6._asof(I.copy(), V, 'V', _v6.V_ALIGN_TOL).dropna(subset=['V'])
        if len(e):
            e['P_kw'] = e['v'] * e['V'] / 1000.0     # charge-positive raw (M11)
            e = e[['t', 'P_kw']].sort_values('t')
        else:
            e = None

    out = {'file': filename, 'charge': [], 'discharge': [], 'unit': {}, 'noPairing': e is None}
    for label, direction in (('charge', 0), ('discharge', 1)):
        s, era = _hdrm_pp_series(df_raw, direction)
        if s is None:
            continue
        pp = pd.DataFrame({'t': t, 'pp_kw': s}).dropna().sort_values('t')
        if not len(pp):
            continue
        gaps = pp['t'].diff().dt.total_seconds().dropna()
''')
rep('''        m = pd.merge_asof(pp, e, on='t', direction='nearest', tolerance=pd.Timedelta(_HDRM_ALIGN_TOL)).dropna(subset=['P_kw'])
        u['matchRate'] = float(len(m) / len(pp)) if len(pp) else None
        out['unit'][label] = u
        if not len(m):
            continue
''', '''        if e is None:
            u['matchRate'] = None
            out['unit'][label] = u
            continue
        m = pd.merge_asof(pp, e, on='t', direction='nearest', tolerance=pd.Timedelta(_HDRM_ALIGN_TOL)).dropna(subset=['P_kw'])
        u['matchRate'] = float(len(m) / len(pp)) if len(pp) else None
        out['unit'][label] = u
        if not len(m):
            continue
''')
# 2. summary: header-based counting; analysed = drives with at least one event
rep('''        ev = _headroom_utilization_events(b, fn)
        if ev is None:
            continue
        n_channel += 1
        eras_here = {u['era'] for u in ev['unit'].values()}''', '''        ev = _headroom_utilization_events(b, fn)
        if ev is None:
            continue
        n_channel += 1                         # header-based: the drive carries a possible-power column of either name
        eras_here = {u['era'] for u in ev['unit'].values()}''')
print('ok')
open(p, 'w', encoding='utf-8', newline='').write(s)
