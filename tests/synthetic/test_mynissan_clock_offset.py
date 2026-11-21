"""M730 known-answer tests (analyses/M730_spec.md Rev 1): interpolation validity and recovery of a planted clock lag."""
import os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_clock_offset as co

# interpolation: exact on a line, invalid across a gap larger than 3 s, invalid outside the observed range
ot = np.array([0.0, 1.0, 2.0, 10.0, 11.0]); ov = np.array([0.0, 10.0, 20.0, 100.0, 110.0])
q = np.array([0.5, 1.5, 5.0, 10.5, -1.0, 12.0])
r = co.interp_valid(ot, ov, q)
assert abs(r[0] - 5.0) < 1e-9 and abs(r[1] - 15.0) < 1e-9 and abs(r[3] - 105.0) < 1e-9
assert np.isnan(r[2]) and np.isnan(r[4]) and np.isnan(r[5])

# planted lag: OBD speed is a smooth waveform at 1 Hz; the cloud reports the same signal 17 s late, sampled every 30 s
t = np.arange(0.0, 1800.0, 1.0)
spd = 60 + 30 * np.sin(t / 90.0) + 10 * np.sin(t / 23.0)
cloud_t = np.arange(120.0, 1700.0, 30.0)
cloud_v = np.interp(cloud_t - 17.0, t, spd)         # cloud at time T shows the OBD value of T-17, i.e. OBD at (T + offset) matches with offset = -17
best = None
for o in co.OFFS:
    qv = co.interp_valid(t, spd, cloud_t + o)
    e = np.median(np.abs(cloud_v - qv))
    if best is None or e < best[0]:
        best = (e, int(o))
assert best[1] == -17 and best[0] < 1e-6, best      # sign convention: the planted lag is found with the sign the convention implies
print("test_mynissan_clock_offset: OK")
