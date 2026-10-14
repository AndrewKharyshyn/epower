"""M435 known-answer tests, part 2 (spec analyses/M435_spec.md Rev 2, section 8): tools/m435_tte.py per-drive time rules (vii), the distance-grid support (ix), the block arithmetic and the
percentile helper. Synthetic 1 Hz frames classified by the same code path as the M418 ledger (C._twl_grid / C._twl_time_to)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import m435_tte as M
import time_to_threshold as T

T0 = pd.Timestamp("2026-01-01 08:00:00")


def frame(cool, oil=None):
    n = len(cool)
    d = {"time": T0 + pd.to_timedelta(np.arange(n), unit="s"), C._TWL_COOL: np.asarray(cool, float)}
    if oil is not None:
        d[C._TWL_OIL] = np.asarray(oil, float)
    return pd.DataFrame(d)


# ---- percentile helper equals numpy on finite samples
x = np.random.default_rng(3).normal(size=4000)
assert np.allclose(T.pct(x), np.percentile(x, [2.5, 97.5]))

# ---- (vii) per-drive time rules
ramp = np.linspace(20, 90, 200)                                          # reaches 80 C at second 171 (20 + 70*k/199 >= 80)
r = M.tte_record(frame(ramp), C)
assert r["status"] == "cold" and r["coolant"]["thr"]["80"]["e"] and r["coolant"]["thr"]["80"]["reason"] == "event"
k80 = int(np.argmax(ramp >= 80)); assert r["coolant"]["thr"]["80"]["t"] == float(k80) and r["lagFirstValidS"] == 0.0 and r["startC"] == 20.0
assert r["oil"] is None                                                  # no oil channel
# ends at 55 C with a valid channel to the last second: trip-end censoring at the last valid second (the last grid second)
short = np.linspace(20, 55, 120)
r = M.tte_record(frame(short), C)
f = r["coolant"]["thr"]["80"]
assert (not f["e"]) and f["reason"] == "tripEnd" and f["t"] == 119.0 and r["coolant"]["tripEndS"] == 119.0
# channel loss: valid for 100 s, then NaN to the end of a 300 s drive; the forward fill (<= 3 s) makes the last valid grid second 103 -> censored there, reason channelLoss
loss = np.r_[np.linspace(20, 55, 100), np.full(200, np.nan)]
r = M.tte_record(frame(loss), C)
f = r["coolant"]["thr"]["80"]
assert (not f["e"]) and f["reason"] == "channelLoss" and f["t"] == 102.0 and r["coolant"]["tripEndS"] == 299.0, f
# a loss within 10 s of the end is still trip end (tolerance)
tail = np.r_[np.linspace(20, 55, 100), np.full(8, np.nan)]
assert M.tte_record(frame(tail), C)["coolant"]["thr"]["80"]["reason"] == "tripEnd"
# crossing inside a gap: 20 invalid seconds, then a value above the threshold -> the event is the first valid second after the gap, flagged afterGap (17 invalid grid seconds after the 3 s fill)
gap = np.r_[np.linspace(20, 60, 60), np.full(20, np.nan), np.full(60, 85.0)]
r = M.tte_record(frame(gap), C)
f = r["coolant"]["thr"]["80"]
assert f["e"] and f["t"] == 80.0 and f["afterGap"] is True, f
# small gap (5 invalid seconds, 2 invalid after the fill): not flagged
gap2 = np.r_[np.linspace(20, 60, 60), np.full(5, np.nan), np.full(60, 85.0)]
f2 = M.tte_record(frame(gap2), C)["coolant"]["thr"]["80"]
assert f2["e"] and f2["afterGap"] is False
# oil start at or above the threshold: time 0 event; coolant warm start is excluded
r = M.tte_record(frame(ramp, oil=np.full(200, 75.0)), C)
assert r["oil"]["thr"]["70"]["e"] and r["oil"]["thr"]["70"]["t"] == 0.0 and r["oil"]["startC"] == 75.0
assert M.tte_record(frame(np.full(100, 75.0)), C)["status"] == "warmStart"
assert M.tte_record(frame(np.full(20, 20.0)), C)["status"] == "fewerThan30ValidCoolantSeconds"

# ---- ties: an event and a censoring in the same second -> the event first (the censored drive is still at risk)
c = T.Cell([100, 100], [False, True], [1, 2])
assert c.t.tolist() == [100.0, 100.0] and c.e.tolist() == [True, False]
assert abs(c.surv_steps(c.ones())[0, 0] - 0.5) < 1e-12                    # at risk 2 at t = 100, one event

# ---- (ix) distance grid: hand-computed drives / days / support end
spans = [0.2, 0.6, 1.2, 2.5, 2.6, 3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6]
days = ["a", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"]
rows, end = M.grid_support(spans, days, [0.0, 0.5, 1.0, 2.0, 3.0, 3.5])
assert [r["nDrives"] for r in rows] == [12, 11, 10, 9, 7, 2]
assert [r["nDays"] for r in rows] == [11, 11, 10, 9, 7, 2]
assert end == 2.0                                                         # first grid point with fewer than 10 drives (9 at 2.0 km); days would allow it
rows, end = M.grid_support([5.0] * 12, ["a", "a", "a", "b", "b", "b", "c", "c", "c", "d", "d", "d"], [0.0, 1.0])
assert end == 0.0 and rows[0]["nDays"] == 4                              # 12 drives on 4 days: the days condition (>= 5) fails at the first point

# ---- block arithmetic on synthetic records: counts by reason, E1 equals the lower bound, bounds bracket E2, the common RMST horizon
rng = np.random.default_rng(5)
recs, raw, dys, regs = [], [], [], []
for i in range(200):
    reached = rng.random() < 0.5
    t_ev = float(rng.integers(60, 900))
    cens = float(rng.integers(100, 1500))
    ev = reached and t_ev <= cens
    one = {"t": t_ev if ev else cens, "e": bool(ev), "reason": "event" if ev else ("tripEnd" if rng.random() < 0.9 else "channelLoss"), "afterGap": False}
    thr = {str(k): one for k in (60, 70, 80)}
    fl = {"thr": thr, "lastValidS": one["t"], "tripEndS": cens}
    recs.append({"status": "cold", "spanS": cens, "startC": 25.0, "lagFirstValidS": 0.0, "coolant": fl, "oil": dict(fl, startC=24.0, lagFirstValidS=0.0)})
    raw.append({"hvc": None, "curve": {"status": "accepted", "class": "urban", "spanKm": float(rng.integers(1, 8))}})
    dys.append("2026-05-%02d" % (1 + i // 4)); regs.append("warm" if i % 2 else "shoulder")
blk = M.build_block(recs, raw, dys, regs, C)
a = blk["cohorts"]["all"]["coolant"]["80"]
assert a["n"] == 200 and a["reached"] + a["censoredTripEnd"] + a["censoredChannelLoss"] == 200
for h in a["horizons"]:
    if h["supported"]:
        assert h["E1"]["point"] == h["bounds"]["low"]["point"]            # E1 is the lower worst-case bound
        assert h["bounds"]["low"]["point"] - 1e-9 <= h["E2"]["point"] <= h["bounds"]["high"]["point"] + 1e-9
        assert h["bounds"]["outerInterval"] == [h["bounds"]["low"]["ci95"][0], h["bounds"]["high"]["ci95"][1]]
taus = {blk["cohorts"][c]["coolant"]["80"]["rmst"]["tauS"] for c in ("all", "warm", "shoulder")}
assert len(taus) == 1                                                     # one tau per fluid / threshold across the cohorts
assert blk["curveSupport"]["all"]["urban"]["nDrives"] == 200
print("OK test_m435_tte")
