"""PCL-1 known-answer tests (spec analyses/PCL1_spec.md Rev 2): the schedule (design A permuted blocks of two, design B half-days, determinism, independence of the number of trips), the report-only monitor (observed arm, compliance, paired days, slot rule,
no cell values), the holding rule and the pure decision rule of the one-shot analysis incl. the view-total rule (B1)."""
import datetime as dt
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import pcl_schedule as PS
import pcl_monitor as PM
import pcl_gate as PG
import regen_v2_agg as G

# ---- design A: each block of two holds one fast and one slow trip; deterministic; the arm of a block does not depend on the number of trips of the day
d0 = dt.date(2026, 11, 1)
for k in range(40):
    d = d0 + dt.timedelta(days=k)
    for blk in range(1, 6):
        assert {PS.arm_for(42, d, 2 * blk - 1), PS.arm_for(42, d, 2 * blk)} == {"fast", "slow"}
firsts = [PS.arm_for(42, d0 + dt.timedelta(days=k), 1) for k in range(60)]
assert 15 < firsts.count("fast") < 45                                              # the order of the first block is random, not constant
assert any(PS.arm_for(43, d0 + dt.timedelta(days=k), 1) != firsts[k] for k in range(60))                                          # the seed matters
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "sched.csv")
rows = PS.write(path, d0, 5, 6, 42)
start, seed, design, table, sha = PS.read(path)
assert start == d0 and seed == 42 and design == "A" and len(table) == 30 and all(table[(r[0], r[1])] == r[3] for r in rows) and len(sha) == 64
assert [r for r in PS.build(d0, 5, 12, 42) if r[1] <= 6] == rows                                    # a longer trip list extends the schedule without changing it

# ---- design B: days in pairs; the morning arm of the two days of a pair differ; the afternoon arm is the opposite of the morning arm; boundary 13:00
pathb = os.path.join(tmp, "schedB.csv")
PS.write(pathb, d0, 10, 12, 42, "B")
sb, seb, db, tb, shab = PS.read(pathb)
assert db == "B" and len(tb) == 20
for k in range(0, 10, 2):
    a0, a1 = [(d0 + dt.timedelta(days=k + j)).isoformat() for j in (0, 1)]
    assert tb[(a0, "AM")] != tb[(a1, "AM")]
    for dd in (a0, a1):
        assert tb[(dd, "AM")] != tb[(dd, "PM")]
assert PS.period_of("12:59:59.000") == "AM" and PS.period_of("13:00:00.000") == "PM"
assert PS.assigned_arm("B", tb, d0.isoformat(), 7, "08:10:00.000") == tb[(d0.isoformat(), "AM")]

# ---- monitor: day 0 before the start, day 1 two fast + two slow (paired), day 2 three fast one slow (ineligible slow) ; slot rule counts ALL files of the day
def drive(date, hhmm, ev, km=10.0, ens=False):
    return {"file": "%s_%s.csv" % (date, hhmm), "date": date, "time_start": hhmm + ":00.000", "ev_rpm_dt_med_s": ev, "distance_km": km, "ens_outlier_v2": ens}

dm = pd.DataFrame([drive("2026-10-31", "08:00", 0.8), drive("2026-11-01", "08:00", 0.8), drive("2026-11-01", "09:00", 1.4), drive("2026-11-01", "10:00", 0.85), drive("2026-11-01", "11:00", 1.4),
                   drive("2026-11-02", "08:00", 0.8), drive("2026-11-02", "09:00", 0.8), drive("2026-11-02", "10:00", 0.8), drive("2026-11-02", "11:00", 1.4, ens=True)])
rep = PM.report(dm, path)
assert rep["started"] and rep["nDrivesSinceStart"] == 8 and rep["nEligibleClean"] == 7 and rep["design"] == "A"
assert rep["observedArm"] == {"fast": 5, "slow": 2, "unknown": 0}
assert rep["pairedDays"] == 1 and rep["readyForAnalysis"] is False                    # only 2026-11-01 has >= 2 drives of each observed arm; 60 paired days are needed
assigned = [PS.arm_for(42, dt.date(2026, 11, 1), t) for t in (1, 2, 3, 4)] + [PS.arm_for(42, dt.date(2026, 11, 2), t) for t in (1, 2, 3, 4)]
obs = ["fast", "slow", "fast", "slow", "fast", "fast", "fast", "slow"]
assert rep["compliance"]["nCompared"] == 8 and rep["compliance"]["nCompliant"] == sum(a == o for a, o in zip(assigned, obs))      # the ineligible fourth file of 2026-11-02 still holds slot 4 and counts toward compliance
assert not any(k in json.dumps(rep) for k in ("eff", "ci95", "diffPp"))                 # counts only: no cell value, no difference, no interval
assert PM.report(dm, os.path.join(tmp, "missing.csv"))["started"] is False
assert rep["compliance"]["directorBeforePassIfBelow"] == 0.9

# ---- holding rule (B4): the hold date is the START DATE while the schedule exists and the one-shot analysis has not run
assert G.protocol_hold(path, os.path.join(tmp, "no.lock")) == "2026-11-01"
open(os.path.join(tmp, "g.lock"), "w", encoding="utf-8").write("x")
assert G.protocol_hold(path, os.path.join(tmp, "g.lock")) is None and G.protocol_hold(os.path.join(tmp, "missing.csv"), os.path.join(tmp, "no.lock")) is None

# ---- decision rule
ok = lambda **kw: dict({"overallSupported": True, "supportedBoth": True, "judgement": "ok"}, **kw)
temp = {"a": ok(), "b": ok(), "c": ok(), "d": ok(supportedBoth=False)}
spd = {l: ok() for l in "12345678"}
tot_ok = {"temperature": "ok", "speed": "ok"}
assert PG.decide({"temperature": temp, "speed": spd}, tot_ok)["verdict"] == "PASS"
assert PG.decide({"temperature": dict(temp, a=ok(judgement="fail")), "speed": spd}, tot_ok)["verdict"] == "FAIL"
assert PG.decide({"temperature": dict(temp, a=ok(judgement="indeterminate")), "speed": spd}, tot_ok)["verdict"] == "INCONCLUSIVE"
assert PG.decide({"temperature": {"a": ok(), "b": ok()}, "speed": spd}, tot_ok)["verdict"] == "INCONCLUSIVE"                       # fewer than 3 temperature cells tested
assert PG.decide({"temperature": dict({l: ok() for l in "abcd"}, **{l: ok(supportedBoth=False) for l in "efghi"}), "speed": spd}, tot_ok)["verdict"] == "INCONCLUSIVE"   # less than half supported in both arms
assert PG.decide({"temperature": temp, "speed": dict(spd, **{"1": ok(judgement="fail")})}, tot_ok)["verdict"] == "FAIL"
assert PG.decide({"temperature": temp, "speed": spd}, {"temperature": "ok", "speed": "indeterminate"})["verdict"] == "INCONCLUSIVE"   # B1: a wide interval at a view total is not a pass
assert PG.decide({"temperature": temp, "speed": spd}, {"temperature": "fail", "speed": "ok"})["verdict"] == "FAIL"
assert PG.decide({"temperature": temp, "speed": spd}, {"temperature": "notTested", "speed": "ok"})["verdict"] == "INCONCLUSIVE"
# total judgement (B1): inside the tolerance with the whole interval = ok; a wide interval around a small difference = indeterminate; excluded zero beyond the tolerance = fail
assert PG.total_judgement(0.5, [-1.0, 1.5], 2.0, True) == "ok"
assert PG.total_judgement(0.5, [-3.0, 4.0], 2.0, True) == "indeterminate"
assert PG.total_judgement(3.0, [2.2, 3.9], 2.0, True) == "fail"
assert PG.total_judgement(0.1, [-0.5, 0.7], 2.0, False) == "notTested"
print("test_pcl1: ALL PASSED")
