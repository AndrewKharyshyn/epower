"""M493 test of the per-process memo of the HV-current sampling density (compute_drive_summary_v6._density_of_bytes / _i_channel_sampling_density): the value equals an independent computation on known bytes, repeated calls
parse a file once, a changed file never returns a stale value (the key is the SHA-256 of the bytes), unreadable and column-less files are (nan, nan), a failing raw loader is (nan, nan), and the result for the corpus equals the
tracked sidecar powerfade_density.csv (which was filled by the same production function)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_drive_summary_v6 as V

ICOL = "[BMS] HV Battery Current (A)"


def csv_bytes(times, cur):
    clock = lambda s: "%02d:%02d:%06.3f" % (int(s // 3600), int(s % 3600 // 60), s % 60)          # the raw logs carry HH:MM:SS.mmm
    rows = ["time,%s,other" % ICOL] + ["%s,%s,1" % (clock(t), "" if c is None else c) for t, c in zip(times, cur)]
    return ("\n".join(rows) + "\n").encode()


# known answer: current logged at t = 0, 1, 2, 4 s on a 5-row file (one row without current): median interval of [1, 1, 2] = 1.0, coverage 4/5
b = csv_bytes([0, 1, 2, 3, 4], [5, 6, 7, None, 8])
V._DENSITY_MEMO.clear()
assert V._density_of_bytes(b) == (1.0, 0.8), V._density_of_bytes(b)
# fewer than 3 current samples: eff is nan, coverage kept
e, c = V._density_of_bytes(csv_bytes([0, 1, 2], [1, None, 2]))
assert np.isnan(e) and abs(c - 2 / 3) < 1e-12
# no current column / unreadable bytes
assert all(np.isnan(x) for x in V._density_of_bytes(b"time,other\n0,1\n1,2\n"))
assert all(np.isnan(x) for x in V._density_of_bytes(b"\x00\x01\x02not a csv at all"))

# one parse per distinct content; a changed file is a different key
calls = {"n": 0}
orig = pd.read_csv
def counting(*a, **k):
    calls["n"] += 1
    return orig(*a, **k)
pd.read_csv = counting
try:
    V._DENSITY_MEMO.clear()
    files = {"a": b, "b": b, "c": csv_bytes([0, 2, 4, 6], [1, 2, 3, 4])}
    d1 = V._i_channel_sampling_density(list(files), lambda f: files[f])
    n1 = calls["n"]
    d2 = V._i_channel_sampling_density(list(files), lambda f: files[f])
    assert calls["n"] == n1 == 2, (calls["n"], n1)            # a and b share content: 2 parses for 3 files, none on the repeat
    assert d1 == d2 and d1["a"] == d1["b"] == (1.0, 0.8) and d1["c"] == (2.0, 1.0)
    files["a"] = csv_bytes([0, 5, 10, 15], [1, 2, 3, 4])          # the same name with new content is parsed again
    d3 = V._i_channel_sampling_density(["a"], lambda f: files[f])
    assert d3["a"] == (5.0, 1.0) and calls["n"] == n1 + 1
finally:
    pd.read_csv = orig

# a raw loader that raises
def bad(f):
    raise OSError("missing")
r = V._i_channel_sampling_density(["x"], bad)
assert all(np.isnan(v) for v in r["x"])

# corpus: the memoised production function equals the tracked sidecar on a sample of drives (the sidecar was written by the same function)
import powerfade_equivalence as PE
side = PE._read(PE.SIDECAR)
side = side[side["reason"].isna() & side["eff_dt_s"].notna()].head(12)
raw = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
import ah_throughput as AH
loader = AH.raw_loader()
V._DENSITY_MEMO.clear()
got = V._i_channel_sampling_density(list(side["file"]), loader)
for _, r in side.iterrows():
    assert abs(got[r["file"]][0] - r["eff_dt_s"]) < 1e-9 and abs(got[r["file"]][1] - r["coverage_frac"]) < 1e-9, (r["file"], got[r["file"]], r["eff_dt_s"], r["coverage_frac"])
print("test_m493_density_memo OK")
