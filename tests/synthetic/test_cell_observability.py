"""M555 (analyses/M555_spec.md Rev 2): known-answer tests for the observability kernels in tools/cell_observability.py."""
import os, sys, io
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import cell_observability as CO

near = lambda a, b, tol=1e-9: abs(a - b) <= tol

# KA1: a channel exactly co-timed with the pack channel: offset 0, age 0 at every pack sample, coverage 1
tp = np.arange(0.0, 100.0, 1.0)
assert CO.coverage(tp, tp.copy(), 1.5) == 1.0 and np.all(CO.nearest_offset(tp, tp) == 0) and np.all(CO.ages(tp, tp.copy()) == 0)

# KA2: pack every 1 s, channel every 2 s at a 0.5 s phase offset: age alternates 0.5 / 1.5 (median 1.0), nearest offset 0.5, coverage 1 within 1.5 s and 0.5 within 0.25 s
tc = np.arange(0.5, 100.0, 2.0)
a = CO.ages(tp, tc)
assert np.isnan(a[0]) and set(np.round(a[1:], 6)) == {0.5, 1.5} and near(np.median(a[1:99]), 1.0)
assert np.all(CO.nearest_offset(tc, tp) == 0.5)
assert CO.coverage(tp, tc, 1.5) == 1.0 and CO.coverage(tp, tc, 0.25) == 0.0
# KA6: censoring: a channel that starts at 10.5 s leaves the pack samples at 0..10 s censored
tc = np.arange(10.5, 100.0, 1.0)
a = CO.ages(tp, tc)
assert near(np.isnan(a).mean(), 11 / 100)

# oversampled channel: the rate ratio exceeds 1 while the coverage never exceeds 1
tc = np.arange(0.0, 100.0, 0.25)
assert len(tc) / len(tp) == 4.0 and CO.coverage(tp, tc, 1.5) == 1.0

# polling-cycle pairing: Max at integer seconds, Min 0.06 s later: every Max pairs with the Min that follows it, one-to-one, and the offset is 0.06 s
tmax = np.arange(0.0, 50.0, 1.0); tmin = tmax + 0.06
ia, ib = CO.poll_pairs(tmax, tmin)
assert len(ia) == 50 and np.all(ia == ib) and len(np.unique(ib)) == len(ib)
# a Min that comes after the NEXT Max does not pair with the earlier Max
ia, ib = CO.poll_pairs(np.array([0.0, 1.0]), np.array([1.2]))
assert list(ia) == [1] and list(ib) == [0]
# tau cap: a Min more than 1.5 s later is not paired
ia, ib = CO.poll_pairs(np.array([0.0]), np.array([1.6]))
assert len(ia) == 0

# KA3: injected inversions (Max < Min by 2 resolution steps on 10 % of pairs) give exactly 10 % at the pairing, and none when the inversion is within one resolution step
res = 0.001
vmin = np.full(50, 3.600); vmax = np.full(50, 3.650); vmax[::10] = vmin[::10] - 2 * res
ia, ib = CO.poll_pairs(tmax, tmin)
viol = int((vmax[ia] < vmin[ib] - res - 1e-12).sum())
assert viol == 5 and near(viol / len(ia), 0.10)
vmax2 = np.full(50, 3.650); vmax2[::10] = vmin[::10] - res
assert int((vmax2[ia] < vmin[ib] - res - 1e-12).sum()) == 0

# KA5: the nearest-pairing sets are nested in tau and non-decreasing in size
n1 = CO.nearest_pairs(tmax, tmin, 0.05)[0]; n2 = CO.nearest_pairs(tmax, tmin, 0.25)[0]; n3 = CO.nearest_pairs(tmax, tmin, 1.5)[0]
assert len(n1) <= len(n2) <= len(n3) and set(n1) <= set(n2) <= set(n3) and len(n1) == 0 and len(n3) == 50

# resolution on decimal-rounded data: values logged with up to 3 decimals give 0.001; with 2 decimals 0.01; whole numbers 1
assert near(CO.resolution_from_decimals(np.array([3.612, 3.6, 3.65])), 0.001)
assert near(CO.resolution_from_decimals(np.array([3.61, 3.6, 3.65])), 0.01)
assert near(CO.resolution_from_decimals(np.array([3.0, 4.0])), 1.0)

# carry-forward: samples every 2 s leave every other 1 s grid point to be carried forward (limit 3): 50 % carried, none beyond the limit; a 10 s hole goes beyond the limit
cf, beyond = CO.carry_forward(np.arange(0.0, 100.0, 2.0))
assert near(cf, 0.5 * 99 / 99, 0.02) and beyond == 0.0
cf, beyond = CO.carry_forward(np.array([0.0, 1.0, 12.0, 13.0]))
assert beyond > 0.4

# duplicate timestamps and the two independent count routes on a small synthetic file
txt = "time,[BMS] HV Battery voltage (V),[BMS] Max Cell Voltage (V),[BMS] Min Cell Voltage (V)\n" \
      "2026-01-01 00:00:00.000,300,3.65,\n2026-01-01 00:00:00.000,300,3.66,\n2026-01-01 00:00:00.060,,,3.60\n2026-01-01 00:00:01.000,301,3.65,\n2026-01-01 00:00:01.060,,,3.61\n"
rec = CO.drive_record(txt.encode())
assert rec["ok"] and rec["channels"][CO.MAXC]["n"] == 2 and rec["channels"][CO.MAXC]["nNonMissingRaw"] == 3 and rec["channels"][CO.MAXC]["nNonMissingRaw"] == rec["channels"][CO.MAXC]["nNonMissingText"]
assert rec["consistency"]["poll"]["pairs"] == 2 and rec["consistency"]["poll"]["viol"] == 0

# stored block (after the splice): strata only, no pooled headline key; G01 reported with its scale ratio and no band verdict while the ratio is outside [0.9, 1.1]
import json
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["cellObservability"]
assert all(k.split("|")[0] in ("maxMin", "maxMinG01") for k in B["strata"]) and "pooled" not in B and not any(B["knownAnswer"]["misses"].values())
for k, st in B["strata"].items():
    for c, v in st["otherChannels"].items():
        assert v["bandTestRun"] == (0.9 <= v["scaleRatioToMaxMinMidMedianOfDrives"] <= 1.1) and ("bandViolations" in v) == v["bandTestRun"]
assert B["reconciliation"]["rawNotInMasterByRole"]["unexplained"] == 0
print("test_cell_observability OK")
