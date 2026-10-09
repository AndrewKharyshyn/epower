"""M390 known-answer test: the SoC single-sample glitch rule (20 pp / 1.0 pp / short-side 5 s), its frame form and its edge cases."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import numpy as np, pandas as pd
import soc_spike as S

m = S.soc_spike_mask
assert m([60, 60, 0, 60, 60]).tolist() == [False, False, True, False, False]                        # spike, no times
assert m([0, 60, 60]).tolist() == [False] * 3 and m([60, 60, 0]).tolist() == [False] * 3            # edge samples never
assert not m([60, 0, 0, 60]).any()                                                                   # two-sample plateau
assert m([60, 40, 60]).any() and not m([60, 40.5, 60]).any()                                         # jump 20 / 19.5
assert m([60, 0, 61]).any() and not m([60, 0, 61.5]).any()                                           # neighbour tolerance 1.0 / 1.5
assert m([]).shape == (0,) and not m([1.0, 2.0]).any()
# real shape: 45.8 s after the previous sample, back after 1.6 s -> short side present -> flagged
assert m([69.5, 0, 69.5], [0, 45.8, 47.4]).tolist() == [False, True, False]
assert not m([60, 0, 60], [0, 30, 60]).any()                                                         # both sides long: genuine excursion hidden by a gap stays
assert m([60, 0, 60], [0, 5, 60]).any() and not m([60, 0, 60], [0, 5.1, 60.2]).any()                # 5 s boundary
assert not m([60, 0, 60], [10, 11, 5]).any()                                                         # non-monotonic times
t = pd.to_datetime(["1900-01-01 10:21:35.395", "1900-01-01 10:22:21.170", "1900-01-01 10:22:22.739"]).to_numpy()
assert t.dtype.kind == "M" and m([69.5, 0, 69.5], t).tolist() == [False, True, False]                # datetime64 (any unit) handled in seconds

tn = pd.to_datetime(["1900-01-01 00:00:00", None, "1900-01-01 00:00:02"]).to_numpy()
assert not m([60, 0, 60], tn).any()                                                                  # NaT on a neighbour: guard fails (audit M390)
assert m([60, 0, 60], np.array([0.0, 1.0, 2.0])).any() and not m([60, 0, 60], np.array([0.0, np.nan, 2.0])).any()

c = S.SOC_RAW_COL
df = pd.DataFrame({"time": pd.to_datetime(["1900-01-01 00:00:0%d" % i for i in range(6)]), c: [60, np.nan, 0, 60, np.nan, 60.0], "x": range(6)})
out = S.despike_frame(df)
assert out[c].isna().tolist() == [False, True, True, False, True, False] and df[c].iloc[2] == 0.0      # flagged cell NaN, NaN rows kept, input untouched
assert out["x"].equals(df["x"])
clean = pd.DataFrame({"time": df["time"], c: [60, 60, 60, 59.5, np.nan, 59.5]})
assert S.despike_frame(clean) is clean and S.despike_frame(None) is None and S.despike_frame(df[["time", "x"]]) is not None
sdf = pd.DataFrame({"time": ["00:00:00.0", "00:00:01.0", "00:00:02.0"], c: [60.0, 0.0, 60.0]})
assert S.despike_frame(sdf)[c].isna().tolist() == [False, True, False]                               # string times coerced (audit M390)
print("OK soc_spike: rule, short-side guard, edges, frame form")
