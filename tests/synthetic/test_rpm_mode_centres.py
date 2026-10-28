"""M527 known-answer tests for tools/rpm_mode_centres.py (analyses/M527_spec.md Rev 2): hand-computed centres, window edges (1975.0 included, 2025.0 excluded), NaN / zero rpm, a drive with no samples in
range, duplicate timestamps, window sums equal bin sums, the day bootstrap with a one-drive day, cache invalidation (window list, grid source hash)."""
import copy, io, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import compute_summary_arrays as cs
import rpm_mode_centres as M
import rpm_opt_band as OB

RPM = "Оберти двигуна (rpm)"

def csv_bytes(vals, dup_at=None):
    t = pd.date_range("2026-01-01 00:00:00", periods=len(vals), freq="1s").strftime("%Y-%m-%d %H:%M:%S.%f").tolist()
    df = pd.DataFrame({"time": t, RPM: vals})
    if dup_at is not None:                      # duplicate timestamp with a different value: resample('1s').mean() averages them
        extra = df.iloc[[dup_at]].copy(); extra[RPM] = extra[RPM] + 2.0
        df = pd.concat([df, extra]).sort_values("time", kind="stable").reset_index(drop=True)
    b = io.BytesIO(); df.to_csv(b, index=False); return b.getvalue()

# 1) hand-computed centre: 10 s each at 1999, 2000, 2001 in the 1975-2025 window -> centre exactly 2000.0; edges: 1975.0 in, 2025.0 out, 1974.0 out
vals = [1999.0] * 10 + [2000.0] * 10 + [2001.0] * 10 + [1975.0] * 5 + [2025.0] * 5 + [1974.0] * 5
n, h, ws, nw = M.drive_row(csv_bytes(vals), cs)
wi = {k: i for i, k in enumerate(M.WNAMES)}
s, c = ws[wi["c2000"]]
assert n == len(vals) and c == 35 and abs(s - (1999 * 10 + 2000 * 10 + 2001 * 10 + 1975 * 5)) < 1e-9, (s, c)
assert abs(s / c - (1999 * 10 + 2000 * 10 + 2001 * 10 + 1975 * 5) / 35) < 1e-12
assert h[2000 - M.LO] == 10 and h[1975 - M.LO] == 5 and h[2025 - M.LO] == 5 and h[1974 - M.LO] == 5     # 1 rpm bins; 2025.0 is in the bin [2025, 2026), outside the window
# narrow window [1985, 2015): 30 samples at 1999-2001
assert ws[wi["c2000n"]][1] == 30 and abs(ws[wi["c2000n"]][0] / 30 - 2000.0) < 1e-12
# window sums equal the 1 rpm bin sums for integer-valued rpm
for k, (a, b) in M.WINDOWS.items():
    assert ws[wi[k]][1] == int(h[a - M.LO:b - M.LO].sum()), k
# native rows weighting gives the same sample set here (1 row per second)
assert nw[wi["c2000"]][1] == 35
# 1b) a sample exactly at the upper bin edge (2100.0) is NOT counted in the last bin [2099, 2100) (np.histogram closes its last bin; the stored rpmDistribution bin [2100, 2400) owns it)
n1, h1, ws1, _ = M.drive_row(csv_bytes([2099.0] * 5 + [2100.0] * 5), cs)
assert h1.sum() == 5 and h1[2099 - M.LO] == 5
# 2) NaN and zero rpm: NaN seconds are forward-filled up to 15 s then dropped; zeros are outside the range; a drive with no samples in range still returns a row
n2, h2, ws2, _ = M.drive_row(csv_bytes([0.0] * 20 + [np.nan] * 5 + [0.0] * 5), cs)
assert n2 >= 20 and h2.sum() == 0 and all(c == 0 for _, c in ws2)
assert M.drive_row(csv_bytes([np.nan] * 10), cs) is None            # nothing at all: no row
# 3) duplicate timestamps are averaged by the 1 s resample (1500 and 1502 at the same second -> 1501)
n3, h3, ws3, _ = M.drive_row(csv_bytes([1500.0] * 10, dup_at=4), cs)
assert h3.sum() == 10 and h3[1501 - M.LO] == 1 and h3[1500 - M.LO] == 9
# 4) the day bootstrap with a one-drive day: point estimate known, interval brackets it, deterministic
num = np.array([2000.0 * 10, 2002.0 * 10, 2001.0 * 10]); den = np.array([10.0, 10.0, 10.0]); days = np.array(["d1", "d2", "d2"])
pt, ci, nd, bad = OB.ratio_ci(num, den, days, nb=1000)
assert abs(pt - 2001.0) < 1e-9 and nd == 2 and ci[0] <= pt <= ci[1]
assert OB.ratio_ci(num, den, days, nb=1000) == (pt, ci, nd, bad)
# 5) cache invalidation: the meta key changes with the window list and with the grid source hash
m0 = M.meta_now()
saved = copy.deepcopy(M.WINDOWS)
try:
    M.WINDOWS["c2000"] = (1976, 2025)
    assert M.meta_now() != m0
finally:
    M.WINDOWS.clear(); M.WINDOWS.update(saved)
assert M.meta_now() == m0
import hashlib, inspect
assert m0["gridRpmSourceSha256"] == hashlib.sha256(inspect.getsource(OB.grid_rpm).encode("utf-8")).hexdigest()
# columns: 700 bins + 4 id columns + 2 x 6 x 2 window columns
assert len(M.cols()) == 4 + 700 + 24
print("OK test_rpm_mode_centres: hand-computed centre, edges, NaN/zero, duplicates, bootstrap, cache key")
