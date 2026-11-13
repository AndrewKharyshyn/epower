"""M638 known-answer tests (analyses/M638_spec.md Rev 1): grid, 45 s hold, 3-of-4 support, >= convention, ratio of sums, day bootstrap."""
import os, sys
import numpy as np
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools")); sys.path.insert(0, REPO)
import m638_sample_occupancy as O

# 100 s drive, four probes sampled every 1 s: constant 36 C on three probes, 34 C on the fourth -> mean 35.5 C everywhere -> every supported second is >= 35, none >= 40
t = np.arange(0, 101.0)
pr = [(t, np.full(len(t), v)) for v in (36.0, 36.0, 36.0, 34.0)]
r = O.drive_occupancy(t, pr)
assert r["supS"] == 100.0 - (r["supS"] % 2) and r["ge35"] == r["supS"] and r["ge40"] == 0.0 and r["ge30"] == r["supS"], r
# the >= convention: a mean exactly at the threshold counts
pe = [(t, np.full(len(t), 35.0)) for _ in range(4)]
assert O.drive_occupancy(t, pe)["ge35"] == O.drive_occupancy(t, pe)["supS"] > 0
# exactly 2 of 4 probes present: unsupported (None below the minimum number of channels)
assert O.drive_occupancy(t, pe[:2]) is None
# 3 of 4 present: supported, uses the mean of the three
p3 = [(t, np.full(len(t), v)) for v in (30.0, 40.0, 50.0)]
r3 = O.drive_occupancy(t, p3)
assert r3["ge40"] == r3["supS"] and r3["ge30"] == r3["supS"]          # mean 40.0 counts as >= 40
# the hold expires mid-gap: probes silent for 60 s (> 45 s) -> those seconds are unsupported
tg = np.r_[np.arange(0, 21.0), np.arange(81.0, 101.0)]
pg = [(tg, np.full(len(tg), 36.0)) for _ in range(4)]
rg = O.drive_occupancy(tg, pg)
full = O.drive_occupancy(t, [(t, np.full(len(t), 36.0)) for _ in range(4)])
expect = 2.0 * sum(1 for x in np.arange(1, 100, 2.0) if x <= 20 + 45 or x >= 81)          # last reading at 20 s holds to 65 s; the next reading is at 81 s
assert rg["supS"] < full["supS"] and rg["supS"] == expect, (rg, expect)
# hold: a grid second at most 45 s after the last reading is supported, 46 s after is not
th = np.array([0.0, 50.0]); ph = [(th, np.full(2, 36.0)) for _ in range(4)]
rh = O.drive_occupancy(th, ph)                                         # grid 1,3,...,49: readings at 0 (age 1..49) and 50 (after the grid)
assert rh["supS"] == 2.0 * 23.0, rh                                      # ages 1..45 -> grid times 1,3,...,45 = 23 points
# hottest-probe variant is at least as hot as the mean
mx = O.drive_occupancy(t, pr, use_max=True)
assert mx["ge35"] >= r["ge35"] and mx["ge40"] == 0.0

# ratio of sums (not mean of ratios) and the day bootstrap
rows = []
for d in range(12):
    for k in range(2):
        rows.append({"day": "d%02d" % d, "supS": 100.0 * (1 + k), "ge35": 50.0 * (1 + k) if d % 2 else 10.0 * (1 + k)})
p, ci = O.ratio_and_ci(rows, "ge35")
want = sum(x["ge35"] for x in rows) / sum(x["supS"] for x in rows)
assert abs(p - want) < 1e-12 and ci[0] < p < ci[1]
assert O.ratio_and_ci(rows, "ge35") == O.ratio_and_ci(rows, "ge35")    # deterministic (seed 42)
assert O.ratio_and_ci(rows[:4], "ge35")[1] is None                       # fewer than 3 days: no interval
s = O.summarise([dict(r, driveS=r["supS"] * 1.25, step=0.5, ge30=r["ge35"], ge40=0.0) for r in rows], ["fewer than 3 pack probe channels in the header (2)"])
assert s["nDays"] == 12 and s["nExcludedDrives"] == 1 and abs(s["coverageShare"] - 0.8) < 1e-3 and s["probeResolutionC"] == 0.5
import language_gate as LG
assert "M638-hot-tail-share-wording" in LG.scan_text("This is the hot-tail share of the pack.") and not LG.scan_text("Share of logged drive time with a mean pack-probe reading at or above 35 C (sample-resolved).")
import json
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
b = A["seasonalLife"]["hotTail"]["packThermalMeasured"]
o = b["sampleOccupancy"]
assert o["nExcludedDrives"] == 0 and o["coverageShare"] > 0.9 and o["probeResolutionC"] > 0 and o["knownAnswer"]["auditEmulationAllRows"]["share35"] == 0.3897
assert o["ci95"]["35"][0] < o["share"]["35"] < o["ci95"]["35"][1] and "driveTimeShareGeC" in b and "interval" in o["meaning"] or "no interval" in o["meaning"] or "carries no interval" in o["meaning"]
J = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read()
assert "S.hotTail?.packThermalMeasured?.sampleOccupancy" in J and "sample-resolved; 95% CI" in J
print("PASS test_m638_sample_occupancy")
