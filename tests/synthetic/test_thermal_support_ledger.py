"""M418 known-answer tests for tools/thermal_support_ledger.py (spec analyses/M418_spec.md): synthetic frames classified by the estimators' own helpers give hand-computed candidates / excluded / accepted /
reached / censored counts and risk-set tables; the reconciliation with the published estimator n holds on the live payload and FAILS when a gate is mutated; the block carries the required reading and no survival estimate."""
import copy, json, os, sys
import numpy as np
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import compute_summary_arrays as C
import thermal_support_ledger as T


def frame(n, cool, oil=None, speed=30.0):
    t = ["12:%02d:%02d.000" % (i // 60, i % 60) for i in range(n)]
    d = {"time": t, C._TWL_COOL: cool}
    if oil is not None:
        d[C._TWL_OIL] = oil
    d["[VCM] Vehicle Speed (km/h)"] = np.full(n, speed)
    return pd.DataFrame(d)


# --- warm-up lag: five drives
n = 600
rec = [
    T.lag_record(frame(n, np.linspace(30, 85, n), np.linspace(25, 75, n)), C),        # cold, coolant reaches 60/70/80, oil reaches 60/70
    T.lag_record(frame(n, np.linspace(30, 55, n), np.linspace(25, 40, n)), C),        # cold, ends at 55 C: censored for every threshold
    T.lag_record(frame(n, np.full(n, 75.0), np.full(n, 70.0)), C),                    # warm start (>= 60): excluded
    T.lag_record(frame(20, np.linspace(30, 40, 20)), C),                              # fewer than 30 valid coolant seconds
    T.lag_record(None, C),                                                            # no frame
    T.lag_record(frame(n, np.linspace(30, 85, n), np.linspace(65, 90, n)), C),        # cold; oil starts at 65 C (>= 60: time 0 for the 60 threshold)
]
assert [r["status"] for r in rec] == ["cold", "cold", "warmStart", "fewerThan30ValidCoolantSeconds", "noFrameOrCoolantChannel", "cold"]
L = T.aggregate_lag(rec, C)
assert L["candidates"] == 6 and L["warmStartExcluded"] == 1 and L["coldStarts"] == 3 and L["nValidCoolant"] == 4 and L["nWithOil"] == 3
assert {e["reason"]: e["n"] for e in L["excluded"]} == {"fewerThan30ValidCoolantSeconds": 1, "noFrameOrCoolantChannel": 1}
for thr in ("60", "70", "80"):
    assert L["coolant"][thr]["reached"] == 2 and L["coolant"][thr]["censored"] == 1, thr          # drive 2 never gets there
assert L["coolant"]["80"]["censoredObservedSeconds"]["n"] == 1 and abs(L["coolant"]["80"]["censoredObservedSeconds"]["max"] - 599.0) < 1.0
# oil 60: drive 1 reaches (25 -> 75), drive 2 ends at 40 (censored), drive 6 starts at 65 (time 0): reached = 2, atStart = 1, afterStart = 1, censored = 1
assert (L["oil"]["60"]["reached"], L["oil"]["60"]["atOrAboveAtStart"], L["oil"]["60"]["reachedAfterStart"], L["oil"]["60"]["censored"]) == (2, 1, 1, 1)
assert (L["oil"]["80"]["reached"], L["oil"]["80"]["censored"]) == (1, 2)                          # only drive 6 (65 -> 90) reaches 80
# risk set at 300 s for coolant 80: drive 1 reaches 80 at ~ 5/55*... check against a direct computation
tt = [r["cool"][80] for r in rec if r["status"] == "cold"]
sp = [r["spanS"] for r in rec if r["status"] == "cold"]
rs = {x["t"]: x for x in L["coolant"]["80"]["riskSet"]}
direct = lambda t: (int(sum(1 for a, s in zip(tt, sp) if (a if np.isfinite(a) else s) >= t)), int(sum(1 for a in tt if np.isfinite(a) and a <= t)), int(sum(1 for a, s in zip(tt, sp) if not np.isfinite(a) and s < t)))
for t in T.RISK_TIMES_S:
    assert (rs[t]["atRisk"], rs[t]["reachedByT"], rs[t]["censoredBeforeT"]) == direct(t), t
assert rs[60]["atRisk"] == 3 and rs[1800]["atRisk"] == 0 and rs[1800]["reachedByT"] == 2 and rs[1800]["censoredBeforeT"] == 1
assert L["coolant"]["80"]["pooledMedianOver"] == "reachers only"

# --- hvcEngine80C and warmupCurve
def rr(fr, dist, cls):
    return T.raw_record(fr, dist, cls, C)
raw = [
    rr(frame(n, np.linspace(30, 90, n)), 5.0, "urban"),            # cold start, reaches 80: hvc accepted+reached, curve accepted
    rr(frame(n, np.linspace(30, 60, n)), 5.0, "urban"),            # cold start, never reaches 80
    rr(frame(n, np.full(n, 85.0)), 5.0, "urban"),                  # warm restart: counted as reached (starts >= 80); curve: warm start
    rr(frame(n, np.linspace(30, 90, n)), 0.0, "urban"),            # distance not positive
    rr(frame(n, np.linspace(30, 90, n)), 5.0, "unknown"),          # class outside the taxonomy
    rr(frame(n, np.full(n, np.nan)), 5.0, "mixed"),                # no valid coolant
    rr(None, 5.0, "urban"),                                        # no frame
]
hv, cu = T.aggregate_raw(raw, C)
u = hv["accepted"]["urban"]
assert (u["n"], u["reached"], u["notReached"], u["startedAtOrAbove80"], u["coldStartAndReached"], u["coldStartNotReached"]) == (3, 2, 1, 1, 1, 1), u
assert {e["reason"]: e["n"] for e in hv["excluded"]} == {"distanceNotPositive": 1, "classOutsideTaxonomy": 1, "noValidCoolant": 1, "noFrame": 1}
# drives 1, 2 and 4 are cold starts: the curve does not require reaching 80 C or a positive distance
assert cu["accepted"]["urban"] == 3
assert {e["reason"]: e["n"] for e in cu["excluded"]} == {"warmStart": 1, "classOutsideTaxonomy": 1, "noValidCoolant": 1, "noFrame": 1}
assert [g["nDrivesReachingThisDistance"] for g in cu["gridAttrition"]["urban"]][0] == 3                       # all three accepted drives reach 0 km
assert all(g["emitted"] is False for g in cu["gridAttrition"]["urban"])                                       # 3 drives < WARMUP_MIN_N = 5: no point emitted

# --- the comparison with the published n: live payload, then a mutated gate
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["thermalSupportLedger"]
assert B["reconciliation"]["allEqual"] and len(B["reconciliation"]["checks"]) >= 20
rec2 = T.reconcile(copy.deepcopy(B), A)
assert rec2["allEqual"], {k: v for k, v in rec2["checks"].items() if not v["equal"]}
mut = copy.deepcopy(B); mut["estimators"]["warmupLag"]["coolant"]["80"]["reached"] += 1
assert not T.reconcile(mut, A)["allEqual"], "a changed accepted count must fail the reconciliation"
mut = copy.deepcopy(B); mut["estimators"]["hvcEngine80C"]["accepted"]["urban"]["n"] -= 1
assert not T.reconcile(mut, A)["allEqual"]
mut = copy.deepcopy(B); mut["estimators"]["fuelPenalty"]["accepted"] += 1
assert not T.reconcile(mut, A)["allEqual"]

# days and partitions (Director M418: n drives AND days; every candidate in exactly one bucket)
E = B["estimators"]
assert E["warmupLag"]["coldStartDays"] > 0 and E["fuelPenalty"]["acceptedDays"] > 0 and E["hvcEngine80C"]["accepted"]["urban"]["nDays"] > 0 and E["warmupCurve"]["acceptedDays"]["urban"] > 0
assert all(v["equal"] for k, v in B["reconciliation"]["checks"].items() if "partition." in k) and any("partition." in k for k in B["reconciliation"]["checks"])
mut = copy.deepcopy(B); mut["estimators"]["fuelPenalty"]["excluded"][0]["n"] += 1
assert not T.reconcile(mut, A)["allEqual"], "a broken partition must fail the reconciliation"
syn = T.aggregate_lag([{**r, "_d": d} for r, d in zip(rec, ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-02", "2026-06-03", "2026-06-04"])], C)
assert syn["coldStartDays"] == 2 and syn["candidateDays"] == 4, (syn["coldStartDays"], syn["candidateDays"])

# cohort variants: the block carries warm and shoulder ledgers that reconcile with the cohort chart payloads; the cold cohort is not computed
COLD_OPEN = A["cohortMeta"]["cold"]["inferenceAvailable"] is True       # M426: the cold cohort has its own ledger once it meets the minimum support
assert set(B["byCohort"]) == ({"warm", "shoulder", "cold"} if COLD_OPEN else {"warm", "shoulder"}) and any(k.startswith("warm.") for k in B["reconciliation"]["checks"]) and any(k.startswith("shoulder.") for k in B["reconciliation"]["checks"])
ch = A["seasonalCharts"]["charts"]
for c in B["byCohort"]:
    if ch["ThermalWarmupLag"]["data"].get(c):
        assert B["byCohort"][c]["warmupLag"]["coldStarts"] == ch["ThermalWarmupLag"]["data"][c]["nColdStart"], c
    if ch["ThermalFuelPenalty"]["data"].get(c):          # a small cohort may get no published fuel-penalty block (reported by the reconciliation as informational)
        assert B["byCohort"][c]["fuelPenalty"]["accepted"] == ch["ThermalFuelPenalty"]["data"][c]["nColdStartDrives"], c
    else:
        assert B["reconciliation"]["checks"][c + ".thermalFuelPenalty.nColdStartDrives"]["equal"] is None, c
mut = copy.deepcopy(B); mut["byCohort"]["shoulder"]["warmupLag"]["coolant"]["70"]["reached"] += 1
assert not T.reconcile(mut, A)["allEqual"], "a changed cohort count must fail the reconciliation"
assert sum(B["byCohort"][c]["warmupLag"]["coldStarts"] for c in B["byCohort"]) <= B["estimators"]["warmupLag"]["coldStarts"]

# --- content rules: censoring reading, no survival estimate, winter suppressed, no forbidden wording
txt = json.dumps(B).lower()
assert "right-censored" in txt and "reachers only" in txt and "not a time-to-event estimate" in txt and ("winter stays unobserved" if COLD_OPEN else "winter stays suppressed") in txt and "not identifiable" in txt
import re as _re
txt = _re.sub(r"kaplan-meier \(product-limit\) estimate", "", txt)      # M435: Kaplan-Meier only as the named estimate (language rule M435-thermal-tte)
assert not any(w in txt for w in ("kaplan", "survival", "failed to warm up", "failure to warm up", "did not warm up", "significant", "confirmed", "robust"))
assert (B["coldCohort"]["inferenceAvailable"] is True) if COLD_OPEN else (B["coldCohort"]["suppressed"] == "below_min_support" and B["coldCohort"]["inferenceAvailable"] is False)
print("OK test_thermal_support_ledger")
