"""M390 (analyses/M390_spec.md): single-sample SoC logger-glitch rejection, shared by the per-drive code, the arrays code and the raw frame loader.
Pure numpy/pandas on purpose (drive_raw_cache must not import the heavy per-drive module).

Rule (fixed, M388c + the M390 short-side guard): on the time-ordered SoC samples, sample b with neighbours a (previous) and c (next) is a spike iff
|b - a| >= 20 pp and |b - c| >= 20 pp and |a - c| <= 1.0 pp and, when times are given, min(t_b - t_a, t_c - t_b) <= 5 s (at least one side of the
spike is a short interval: a move of >= 20 pp within 5 s implies about 300 kW on the 2.1 kWh pack, above the motor rating, so it is not a battery state;
SoC is polled about every 1.2 s, median). A spike whose both sides are long gaps is NOT flagged (a genuine excursion hidden by a logging gap stays).
First and last samples are never spikes. A non-monotonic time pair (midnight roll-over of HH:MM:SS strings) fails the guard, i.e. is NOT a spike.
Corpus evidence: 22 SoC intervals exceed 60 s (max 1791 s); the one glitch follows a 45.8 s dropout and returns after 1.6 s."""
import numpy as np

SOC_SPIKE_JUMP_PP = 20.0
SOC_SPIKE_NEIGHBOUR_TOL_PP = 1.0
SOC_SPIKE_MAX_GAP_S = 5.0
SOC_RAW_COL = '[BMS] HV State of charge (%)'


def soc_spike_mask(v, t=None, max_gap_s=SOC_SPIKE_MAX_GAP_S):
    """True where a time-ordered SoC sample is a single-sample spike. v: values; t: optional matching times (datetime64 / Timestamps / seconds)."""
    v = np.asarray(v, dtype=float)
    m = np.zeros(len(v), dtype=bool)
    if len(v) < 3:
        return m
    a, b, c = v[:-2], v[1:-1], v[2:]
    ok = (np.abs(b - a) >= SOC_SPIKE_JUMP_PP) & (np.abs(b - c) >= SOC_SPIKE_JUMP_PP) & (np.abs(a - c) <= SOC_SPIKE_NEIGHBOUR_TOL_PP)
    if t is not None:
        tt = np.asarray(t)
        nat = np.zeros(len(tt), dtype=bool)
        if np.issubdtype(tt.dtype, np.datetime64):
            nat = np.isnat(tt)
            tt = tt.astype('datetime64[ns]').astype('int64') / 1e9          # explicit ns -> s (pandas 3 frames are datetime64[us])
        else:
            tt = tt.astype(float)
            nat = np.isnan(tt)
        dab, dbc = tt[1:-1] - tt[:-2], tt[2:] - tt[1:-1]
        ok &= (dab >= 0) & (dbc >= 0) & (np.minimum(dab, dbc) <= max_gap_s) & ~(nat[:-2] | nat[1:-1] | nat[2:])      # a missing time on any of the three fails the guard
    m[1:-1] = ok
    return m


def despike_frame(df, col=SOC_RAW_COL, tcol='time'):
    """Frame-level form for the raw frame loader: the flagged SoC cells are set to NaN (row alignment with the other channels is kept).
    Works on the non-null subseries of col. Returns df itself when nothing is flagged, otherwise a shallow copy with only that column replaced."""
    if df is None or col not in df.columns:
        return df
    s = df[col]
    nn = s.notna().to_numpy()
    if nn.sum() < 3:
        return df
    vals = pd_to_numeric(s[nn])
    t = None
    if tcol in df.columns:
        import pandas as pd
        t = pd.to_datetime(df.loc[nn, tcol], errors='coerce').to_numpy()          # string times coerced; unparseable -> NaT -> guard fails (not a spike)
    m = soc_spike_mask(vals, t)
    if not m.any():
        return df
    out = df.copy(deep=False)
    col_new = s.astype(float).copy()
    col_new.iloc[np.where(nn)[0][m]] = np.nan
    out[col] = col_new
    return out


def pd_to_numeric(s):
    import pandas as pd
    return pd.to_numeric(s, errors='coerce').to_numpy(dtype=float)
