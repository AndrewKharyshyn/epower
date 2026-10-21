"""M467 (external audit F06): midnight rollover of the raw 'time' column. The loggers write HH:MM:SS.fraction only; every parser dates it TODAY, so a drive that
crosses midnight (23:59:59 -> 00:00:00) steps back by about a day and every duration, trapezoid and sort order is wrong. `unwrap_clock` adds one day at each backward
step larger than WRAP_BACK_S (12 h); a backward step of up to 12 h is NOT a rollover (ambiguous clock jump, left untouched, never guessed). It acts only on a series whose
timestamps all carry ONE calendar date (a time-only parse); a series that already has real dates is returned unchanged, and a series without a rollover is returned as the
same object, so every existing result is byte-identical. All raw-time parsers call this one function."""
import numpy as np
import pandas as pd

WRAP_BACK_S = 12 * 3600


def unwrap_clock(t):
    """Return t (datetime64 Series/Index) with midnight rollovers unwrapped; NaT positions are kept."""
    if len(t) < 2:
        return t
    s = pd.Series(t) if not isinstance(t, pd.Series) else t
    ok = s.notna().to_numpy()
    if ok.sum() < 2:
        return t
    v = s.to_numpy(dtype="datetime64[ns]")
    if len(pd.unique(s[ok].dt.normalize())) != 1:
        return t
    iv = v[ok].astype("int64")
    back = np.diff(iv) < -int(WRAP_BACK_S * 1e9)
    if not back.any():
        return t
    day = np.int64(86400 * 10**9)
    add = np.concatenate([[0], np.cumsum(back)]).astype("int64") * day
    out = v.astype("int64").copy()
    out[ok] = iv + add
    res = pd.Series(out.astype("datetime64[ns]"), index=s.index, name=s.name)
    res[~ok] = pd.NaT
    return res if isinstance(t, pd.Series) else pd.DatetimeIndex(res)
