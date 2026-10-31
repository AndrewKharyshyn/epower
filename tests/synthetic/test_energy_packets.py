"""M551 (analyses/M551_spec.md Rev 2): known-answer tests for the energy-packet kernel tools/energy_packets.py."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import energy_packets as E

WH = lambda kw, s: kw * s / 3.6      # kW x s -> Wh
def runs(r):
    return [(s, round(w, 6), round(d, 6), cs, ce) for s, w, d, cs, ce in zip(r["sign"], r["wh"], r["dur_s"], r["cens_start"], r["cens_end"])]

# KA2a: +10, +10, -10, -10, +10 kW at 1 s: the crossing intervals split at the analytic portions (each 0.5 s of a 10 -> 0 ramp = 2.5 kW s)
r = E.stream_runs([0, 1, 2, 3, 4], [10, 10, -10, -10, 10])
x = runs(r)
assert len(x) == 3
assert x[0] == (1, round(WH(10, 1) + WH(2.5, 1), 6), 1.5, True, False)
assert x[1] == (-1, round(WH(2.5, 1) + WH(10, 1) + WH(2.5, 1), 6), 2.0, False, False)
assert x[2] == (1, round(WH(2.5, 1), 6), 0.5, False, True)
assert abs(sum(w for s, w in zip(r["sign"], r["wh"]) if s > 0) / 1000 - r["disc"]) < 1e-12 and abs(sum(w for s, w in zip(r["sign"], r["wh"]) if s < 0) / 1000 - r["chg"]) < 1e-12

# KA2b: a 8 s gap breaks the segment, censors both neighbours, and its capped (5 s) energy is carried by direction
r = E.stream_runs([0, 1, 2, 10, 11, 12], [10] * 6)
x = runs(r)
assert len(x) == 2 and all(c[3] and c[4] for c in x)
assert abs(r["gapDisc"] - 10 * 5 / 3600) < 1e-12 and r["gapChg"] == 0 and r["nGaps"] == 1 and r["nSegments"] == 2
assert abs(sum(r["wh"]) / 1000 + r["gapDisc"] - r["disc"]) < 1e-12

# KA2c: a mid-segment idle interval is an OBSERVED end (not censored) and breaks the run
r = E.stream_runs([0, 1, 2, 3, 4, 5], [10, 10, 0, 0, 10, 10])
x = runs(r)
assert len(x) == 2 and x[0][3] and not x[0][4] and not x[1][3] and x[1][4] and r["nIdle"] == 1

# KA2d: a sign change across a duplicate timestamp breaks the run; a same-sign duplicate does not
r = E.stream_runs([0, 1, 1, 2], [10, 10, -10, -10])
x = runs(r)
assert [c[0] for c in x] == [1, -1] and r["nZeroDt"] == 1
r = E.stream_runs([0, 1, 1, 2], [10, 10, 10, 10])
assert len(runs(r)) == 1

# KA1-like property: random power series with gaps and duplicate stamps reconcile to the released ledger formula (copied from compute_drive_summary_v6)
def ledger(ts, P):
    dt = np.clip(np.diff(ts, prepend=ts[0]), 0, 5.0) / 3600.0
    p0 = np.concatenate([[0.0], P[:-1]])
    cross = (p0 * P) < 0
    absum = np.abs(p0) + np.abs(P); den = np.where(absum > 0, 2.0 * absum, 1.0)
    dc = dt * ((p0 > 0) * p0 ** 2 + (P > 0) * P ** 2) / den; cc = dt * ((p0 < 0) * p0 ** 2 + (P < 0) * P ** 2) / den
    sg = dt * (p0 + P) / 2.0
    return float(np.where(cross, dc, np.where(sg > 0, sg, 0.0)).sum()), float(np.where(cross, cc, np.where(sg < 0, -sg, 0.0)).sum())
rng = np.random.default_rng(7)
for k in range(30):
    n = int(rng.integers(5, 400))
    step = rng.choice([0.0, 0.5, 1.0, 2.0, 7.0], size=n, p=[0.05, 0.3, 0.4, 0.2, 0.05])
    ts = np.cumsum(step); P = rng.normal(0, 20, n) * (rng.random(n) > 0.15)
    r = E.stream_runs(ts, P)
    ld, lc = ledger(ts, P)
    assert abs(r["disc"] - ld) < 1e-10 and abs(r["chg"] - lc) < 1e-10, (k, r["disc"], ld)
    sd = sum(w for s, w in zip(r["sign"], r["wh"]) if s > 0) / 1000 + r["gapDisc"]; sc = sum(w for s, w in zip(r["sign"], r["wh"]) if s < 0) / 1000 + r["gapChg"]
    assert abs(sd - ld) < 1e-10 and abs(sc - lc) < 1e-10, (k, sd, ld, sc, lc)

# aggregation helpers: ratio of sums, the p99 interval needs 20 days, fewer than 5 days gives no interval
b = E._ratio({"d1": 1.0}, {"d1": 4.0, "d2": 4.0})
assert b["pct"] == 12.5 and b["ci95Pct"] is None
h = {f"d{i}": E._hist(np.array([1.0, 2.0, 50.0])) for i in range(6)}
assert E._qint(h, 0.99, 20)["ci95"] is None and E._qint(h, 0.5, 5)["ci95"] is not None

# stored block (after the splice): reconciliation closed, strata only, no pooled headline key
import json
a = json.load(open("summary_arrays.json", encoding="utf-8"))
B = a["energyPackets"]
assert B["reconciliation"]["nMisses"] == 0 and set(B["strata"]) <= {"fast", "slow", "unknown"} and "pooled" not in B
print("test_energy_packets OK")
