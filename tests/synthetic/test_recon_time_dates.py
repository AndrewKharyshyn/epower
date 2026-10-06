"""M384 (regression from M383): recon_engine.load_drive's time column must equal, in ABSOLUTE terms, what consumers get from their own
pd.to_datetime(df['time'], errors='coerce') (tools/fuel_analytics2.load_trip windows the load_drive series on a counter series parsed that way). The
M383 fast path dated times 1900-01-01 while the inferring parse dates them today, which emptied every window."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
raw = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"); os.environ["XT_RAW_DIR"] = raw
import pandas as pd
import recon_engine as RE

files = sorted(f for f in os.listdir(raw) if f.endswith(".csv") and not f.startswith("e4ORCE"))[::22][:20]
for f in files:
    s = pd.read_csv(os.path.join(raw, f), usecols=["time"], low_memory=False)["time"]
    assert RE._parse_time(s).equals(pd.to_datetime(s, errors="coerce")), f
fuel = [f for f in sorted(os.listdir(raw)) if f.startswith("2026-08-1")][:3]
n = 0
for f in fuel:
    g = RE.load_drive(f, float("nan"))
    if g is None:
        continue
    t_ext = pd.to_datetime(pd.read_csv(os.path.join(raw, f), usecols=["time"], low_memory=False)["time"], errors="coerce")
    assert g["t"].isin(set(t_ext.dropna())).all(), f                 # every load_drive timestamp exists in the consumer's own parse
    assert ((g["t"] >= t_ext.min()) & (g["t"] <= t_ext.max())).all(), f
    n += 1
assert n >= 1, "no fuel-instrumented drive found to check"
print("OK test_recon_time_dates (%d parse files, %d drives)" % (len(files), n))
