"""M383 (audit F21): compute_drive_summary_v6 time-parse fast path and shared read/parse in analyze_bytes.
(1) _parse_time_col == pd.to_datetime(format='mixed') up to the date component (compared as offsets from the first sample, NaT positions equal) on real raw files;
(2) other forms / a malformed row fall back to the whole-column 'mixed' parse; (3) analyze_bytes (one shared read + parse, per-family copies) equals the
three families run independently. Full-corpus old/new parity: tools/parity_analyze_bytes.py."""
import io, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import compute_drive_summary_v6 as V

raw = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
files = sorted((f for f in os.listdir(raw) if f.endswith(".csv") and not f.startswith("e4ORCE")), key=lambda f: os.path.getsize(os.path.join(raw, f)))
small, spread = files[:2], files[::max(1, len(files) // 25)][:25]


def rel(t):
    return ((t - t.iloc[0]).dt.total_seconds()).to_numpy()


for f in spread:
    s = pd.read_csv(os.path.join(raw, f), usecols=["time"], low_memory=False)["time"]
    new, old = V._parse_time_col(s), pd.to_datetime(s, format="mixed", errors="coerce")
    assert new.isna().equals(old.isna()), f
    assert new.equals(old), f                       # ABSOLUTE equality (M384: the first M383 version differed by the date and broke fuel_analytics2)

# fallbacks: with a date component, and a malformed row (whole column goes through the 'mixed' parse)
for ser in (pd.Series(["2026-05-11 12:00:00.500", "2026-05-11 12:00:01.250"]), pd.Series(["12:00:00.500", "garbage", "12:00:02.250"]),
            pd.Series(["12:00:00", "12:00:01"])):
    new, old = V._parse_time_col(ser), pd.to_datetime(ser, format="mixed", errors="coerce")
    assert new.isna().equals(old.isna()) and new.dropna().equals(old.dropna()), list(ser)


def same(a, b):
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return bool(a == b) or (pd.isna(a) and pd.isna(b)) if not isinstance(a, np.ndarray) else bool(np.array_equal(a, b, equal_nan=True))


for f in small:
    b = open(os.path.join(raw, f), "rb").read()
    shared = V.analyze_bytes(b, f)
    r = V._v5_analyze_bytes(b, f); r["pipeline_version"] = 6
    for fn in (V._vsag_metrics, V._ev_metrics):
        try:
            r.update(fn(b))
        except Exception:
            pass
    d, tm = V._date_from_name(f)
    if r.get("date") is None or (isinstance(r.get("date"), float) and pd.isna(r.get("date"))):
        r["date"] = d
    if not r.get("time_start"):
        r["time_start"] = tm
    assert same(shared, r), f
print("OK test_v6_prep_parity")
