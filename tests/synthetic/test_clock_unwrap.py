"""M467 (external audit F06) known-answer test: midnight rollover of the time-only raw clock, in every parser that reads it. Synthetic 23:59:58, 23:59:59, 00:00:00, 00:00:01 must span
3 s (the audit reproduced 86,399 s) and integrate 3.6 kW to 0.003 kWh (0.007 before); a multi-midnight record unwraps twice; a series without rollover, a small backward step (ambiguous
clock jump, <= 12 h) and a series that already carries real dates are returned unchanged; NaT positions are kept."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
from clock_unwrap import unwrap_clock
import compute_drive_summary_v6 as V6, recon_engine as RE, drive_raw_cache as DRC

wrap = pd.Series(["23:59:58.000", "23:59:59.000", "00:00:00.000", "00:00:01.000"])
for name, fn in (("v6", V6._parse_time_col), ("recon_engine", RE._parse_time), ("fast_time", DRC.fast_time),
                 ("fast_time_mixed", lambda s: DRC.fast_time(s, mixed=True))):
    t = fn(wrap)
    assert (t.iloc[-1] - t.iloc[0]).total_seconds() == 3.0, (name, t.tolist())
    assert t.is_monotonic_increasing, name
    dt = np.diff(t.values.astype("datetime64[ns]").astype("int64")) / 1e9
    assert abs(float((3.6 * dt).sum() / 3600.0) - 0.003) < 1e-9, name                            # 3.6 kW over 3 s
# unsorted-by-wrap fallback path (non-HH:MM:SS.f form) is unwrapped too
alt = pd.Series(["23:59:58", "23:59:59", "00:00:00", "00:00:01"])
assert (V6._parse_time_col(alt).iloc[-1] - V6._parse_time_col(alt).iloc[0]).total_seconds() == 3.0
# multi-midnight record
two = pd.Series(["12:00:00.0", "23:00:00.0", "01:00:00.0", "13:00:00.0", "23:30:00.0", "02:00:00.0"])
t2 = unwrap_clock(pd.to_datetime(two, format="%H:%M:%S.%f"))
assert (t2.iloc[-1] - t2.iloc[0]).total_seconds() == 38 * 3600 and t2.is_monotonic_increasing
# no rollover: same object back; small backward step (10 h) untouched; real dates untouched
plain = pd.to_datetime(pd.Series(["10:00:00.0", "10:00:01.0"]), format="%H:%M:%S.%f")
assert unwrap_clock(plain) is plain
amb = pd.to_datetime(pd.Series(["20:00:00.0", "10:00:00.0"]), format="%H:%M:%S.%f")
assert unwrap_clock(amb) is amb
dated = pd.to_datetime(pd.Series(["2026-05-11 23:59:59", "2026-05-12 00:00:01"]))
assert unwrap_clock(dated) is dated
# NaT kept
nat = pd.to_datetime(pd.Series(["23:59:59.0", None, "00:00:01.0"]), format="%H:%M:%S.%f")
tn = unwrap_clock(nat)
assert tn.isna().tolist() == [False, True, False] and (tn.iloc[2] - tn.iloc[0]).total_seconds() == 2.0
# corpus: no current file wraps, so unwrap is the identity on the real data (sample of files)
raw = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
files = sorted(f for f in os.listdir(raw) if f.endswith(".csv"))[::25]
for f in files:
    s = pd.read_csv(os.path.join(raw, f), usecols=["time"], low_memory=False)["time"]
    raw_t = pd.to_datetime(s, errors="coerce")
    assert DRC.fast_time(s).equals(raw_t), f
print("OK test_clock_unwrap (%d corpus files identity)" % len(files))
