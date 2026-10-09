"""M386 (audit F21): drive_raw_cache.fast_time is an ABSOLUTE drop-in for pd.to_datetime(s, errors='coerce'[, format='mixed']) on raw time columns (same values, same
NaT positions, same dtype), falls back to the original call for other forms / malformed rows, and passes datetime64 input through unchanged."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
from drive_raw_cache import fast_time

raw = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
files = sorted(f for f in os.listdir(raw) if f.endswith(".csv"))[::20][:26]
for f in files:
    s = pd.read_csv(os.path.join(raw, f), usecols=["time"], low_memory=False)["time"]
    for mixed in (False, True):
        old = pd.to_datetime(s, errors="coerce", format="mixed") if mixed else pd.to_datetime(s, errors="coerce")
        new = fast_time(s, mixed=mixed)
        assert new.dtype == old.dtype and new.isna().equals(old.isna()) and new.equals(old), (f, mixed)
cases = [pd.Series(["2026-05-11 12:00:00.500", "2026-05-11 12:00:01.250"]), pd.Series(["12:00:00.500", "garbage", "12:00:02.250"]), pd.Series(["12:00:00", "12:00:01"]),
         pd.Series(["12:00:00.5", None, "12:00:01.25"]), pd.Series([], dtype=object)]
for ser in cases:
    for mixed in (False, True):
        old = pd.to_datetime(ser, errors="coerce", format="mixed") if mixed else pd.to_datetime(ser, errors="coerce")
        assert fast_time(ser, mixed=mixed).equals(old), (list(ser), mixed)
dt = pd.to_datetime(pd.Series(["12:00:00.500", "12:00:01.250"]), errors="coerce")
assert fast_time(dt).equals(dt) and fast_time(dt, mixed=True).equals(dt)                     # frames carry datetime64: untouched
print("OK test_fast_time (%d files x 2 modes)" % len(files))
