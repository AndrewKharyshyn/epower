"""M437 known-answer tests (spec analyses/M437_spec.md Rev 2 + 2.1, section 6; criteria declared there before any result): tools/m437_fill.py.
(i) the grid with F = 3 equals compute_summary_arrays._twl_grid, a 4 s gap gets 3 filled + 1 NaN; (ii) F = 0 never fills, F = 6 fills a 6 s gap and a 7 s gap gets 6 filled + 1 NaN;
(iii) the >= 30 valid-second rule: 20 samples every 2 s are a cold start at F = 3 (39 valid seconds) and not at F = 0 (20); (iv) event times are EQUAL across F (seed 42);
(v) the trip-end tolerance (<=) on drives whose last valid second is exactly X, below and above X before the end; (vi) paired counts on a 6-drive synthetic set."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import m435_tte as M
import m437_fill as F7

T0 = pd.Timestamp("2026-01-01 08:00:00")


def frame_at(times_s, cool):
    return pd.DataFrame({"time": T0 + pd.to_timedelta(np.asarray(times_s, float), unit="s"), C._TWL_COOL: np.asarray(cool, float)})


def gappy(gap_len):
    t = np.r_[np.arange(0, 20), np.arange(20 + gap_len, 60)]
    return frame_at(t, np.linspace(20, 50, len(t)))


# ---- (i) F = 3 equals the released grid; a 4 s gap gets 3 filled + 1 NaN
for gl in (1, 3, 4, 8):
    fr = gappy(gl)
    a = C._twl_grid(fr); b = F7.grids(fr, C)[3]
    assert a.equals(b), gl
fr = gappy(4)                                   # seconds 20..23 are missing (samples at 0..19 and 24..59)
g3 = F7.grids(fr, C)[3]["cool"]
assert g3.iloc[20:23].notna().all() and g3.iloc[23:24].isna().all(), g3.iloc[18:26].tolist()
# ---- (ii) F = 0 never fills; F = 6 fills a 6 s gap and a 7 s gap gets 6 filled + 1 NaN
g0 = F7.grids(gappy(6), C)[0]["cool"]
assert g0.iloc[20:26].isna().all()
g6 = F7.grids(gappy(6), C)[6]["cool"]
assert g6.iloc[20:26].notna().all()
g6b = F7.grids(gappy(7), C)[6]["cool"]
assert g6b.iloc[20:26].notna().all() and g6b.iloc[26:27].isna().all()

# ---- (iii) the 30 valid-second rule
fr = frame_at(np.arange(0, 40, 2), np.linspace(20, 40, 20))
recs, _ = F7.records_for_drive(fr, C)
assert recs[3]["status"] == "cold" and recs[6]["status"] == "cold" and recs[0]["status"] == "fewerThan30ValidCoolantSeconds"
assert int(F7.grids(fr, C)[3]["cool"].notna().sum()) == 39 and int(F7.grids(fr, C)[0]["cool"].notna().sum()) == 20

# ---- (iv) event times are equal across F (seed 42), whenever the drive is a cold start in both
rng = np.random.default_rng(42)
checked = 0
for k in range(60):
    n = int(rng.integers(60, 400))
    t = np.cumsum(rng.choice([1, 1, 2, 3, 5, 8], n)).astype(float)
    v = 20 + np.cumsum(np.abs(rng.normal(0.2, 0.3, n)))
    fr = frame_at(t, v)
    recs, _ = F7.records_for_drive(fr, C)
    for fl, thr in (("coolant", 60), ("coolant", 70), ("coolant", 80)):
        es = [F7._entry(recs[F], fl, thr) for F in F7.FILLS]
        es = [e for e in es if e is not None]
        for a in es[1:]:
            assert a["e"] == es[0]["e"] and (not a["e"] or a["t"] == es[0]["t"]), (k, fl, thr)
        checked += len(es) > 1
assert checked > 30

# ---- (v) the trip-end tolerance, comparison <=
ent = lambda gap: {"e": False, "tripEndS": 100.0, "lastValidS": 100.0 - gap}
for gap, X, want in ((3, 5, "tripEnd"), (5, 5, "tripEnd"), (8, 5, "channelLoss"), (8, 10, "tripEnd"), (10, 10, "tripEnd"), (20, 10, "channelLoss"), (20, 30, "tripEnd"), (40, 30, "channelLoss")):
    assert F7._reason_at(ent(gap), X) == want, (gap, X)
assert F7._reason_at({"e": True, "tripEndS": 100.0, "lastValidS": 50.0}, 5) == "event"


# ---- (vi) paired counts on a 6-drive set
def rec(t, e, last=None, end=300.0, reason=None):
    last = t if last is None else last
    return {"status": "cold", "startC": 25.0, "lagFirstValidS": 0.0, "coolant": {"thr": {"80": {"t": t, "e": e, "reason": reason or ("event" if e else "tripEnd"), "afterGap": False}}, "lastValidS": last, "tripEndS": end}, "oil": None}


S0 = [rec(300.0, True), rec(500.0, False, last=500.0, end=505.0), rec(700.0, False, last=700.0, end=702.0), rec(200.0, False, last=200.0, end=204.0), {"status": "fewerThan30ValidCoolantSeconds"}, rec(900.0, True)]
V0 = [rec(300.0, True), rec(497.0, False, last=497.0, end=505.0), {"status": "fewerThan30ValidCoolantSeconds"}, {"status": "fewerThan30ValidCoolantSeconds"}, rec(100.0, False, last=100.0, end=101.0), rec(900.0, True)]
p = F7._paired(S0, V0, "coolant", 80, -3)
# drive 3 (S0 censored at 700, at risk at 600) dropped; drive 4 (S0 censored at 200 < 600) dropped; drive 5 added (censored at 100 < 600); drive 2 shifts by 3 s and stays tripEnd (505 - 497 = 8 <= 10)
assert p["dropped"] == {"reachedBy600": 0, "censoredBefore600": 1, "atRiskAt600": 1} and p["added"] == {"reachedBy600": 0, "censoredBefore600": 1, "atRiskAt600": 0}
assert p["nDropped"] == 2 and p["nAdded"] == 1 and p["eventTimeChanged"] == 0 and p["censoringTimeChanged"] == 1 and p["maxCensoringShiftS"] == 3.0 and p["maxAllowedShiftS"] == 3
assert p["reasonChanged"] == 0
V1 = [rec(300.0, True), rec(480.0, False, last=480.0, end=505.0), S0[2], S0[3], S0[4], S0[5]]            # drive 2: last valid second 25 s before the end -> channelLoss under X = 10
p1 = F7._paired(S0, V1, "coolant", 80, -3)
assert p1["reasonChanged"] == 1 and p1["reasonChangedDirection"] == {"tripEndToChannelLoss": 1, "channelLossToTripEnd": 0} and p1["censoringTimeChanged"] == 1
V2 = [rec(299.0, True)] + S0[1:]                                                                          # an event time that moved is counted (and stops the run in build_block)
assert F7._paired(S0, V2, "coolant", 80, -3)["eventTimeChanged"] == 1
print("OK test_m437_fill")
