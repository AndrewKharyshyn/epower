#!/usr/bin/env python3
"""Drift/consistency tests for the M284 Track-4 artefacts. Run from the work-dir root (needs summary_arrays.json,
drive_master.csv, seasonal/seasonal_drive_master.csv)."""
import json, os, sys, importlib.util
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get("XT_WORK") or (HERE if os.path.exists(os.path.join(HERE, "drive_master.csv")) else os.path.dirname(HERE))
SD = os.path.join(W, "seasonal") if os.path.isdir(os.path.join(W, "seasonal")) else W
os.environ.setdefault("XT_WORK", W); sys.path.insert(0, HERE); sys.path.insert(0, SD)
import records_resistance as RR, records_rainflow as RF, refresh_seasonal_kpis as RK, cohort_distributions as CDm, seasonal_core as sc
A = json.load(open(os.path.join(W, "summary_arrays.json"), encoding="utf-8"))
DM = pd.read_csv(os.path.join(W, "drive_master.csv"), low_memory=False)
P, F = [], []
def ok(n, c): (P if c else F).append(n); print(("  ok  " if c else " FAIL ") + n)

# 1 paired-eligible ratio-of-sums (independent recompute in pandas)
ei = A["seasonalCharts"]["charts"]["EnergyIntensity"]["data"]
sm = pd.read_csv(os.path.join(SD, "seasonal_drive_master.csv"), low_memory=False)[["file", "thermal_regime"]]
d = DM.merge(sm, on="file")
_bad = lambda c: d[c].astype(str).str.strip().str.lower().eq("true")
d["_clean"] = ~(_bad("ens_invalid") | _bad("ens_outlier_v2"))
for k, mask in (("all", d.file.notna()), ("warm", d.thermal_regime.eq("warm")), ("shoulder", d.thermal_regime.eq("shoulder"))):
    g = d[mask & d.gross_throughput_kwh.notna() & d.distance_km.gt(0)]
    gc = g[g._clean]
    exp = 100 * gc.gross_throughput_kwh.sum() / gc.distance_km.sum()
    ok(f"1 EnergyIntensity[{k}] = independent CLEAN paired ratio-of-sums (M295)", abs(ei[k]["value"] - exp) < 1e-9 and ei[k]["n"] == len(gc))
    pub = 100 * g.gross_throughput_kwh.sum() / g.distance_km.sum(); ps = ei[k]["publishedBasisSensitivity"]
    ok(f"1 EnergyIntensity[{k}] published-basis sensitivity = unfiltered ratio-of-sums", abs(ps["value"] - pub) < 1e-9 and ps["n"] == len(g))
    c = ei[k]["ci95"]
    ok(f"1 EnergyIntensity[{k}] CI brackets estimate", c["lo"] < ei[k]["value"] < c["hi"] and 0 < c["essDays"] <= c["nClusters"])
ok("1 Cold cohort has no fabricated KPI", ei["cold"] is None)
# 2 core: distance of numerator-missing drives must not enter the denominator
ok("2 cohort_per_100km paired", abs(sc.cohort_per_100km([{"q": 10., "distance_km": 100.}, {"q": None, "distance_km": 100.}], "q") - 10.0) < 1e-12)
# 3 refresh is reproducible (fixed seed)
r1 = RK.ratio_ci([r for r in RK.load()]); r2 = RK.ratio_ci([r for r in RK.load()])
ok("3 bootstrap reproducible", r1 == r2)
# builder-owned fields only: records_disclosure.py adds a separate `disclosure` layer (audit B8),
# which the value/drive/note builders do not emit; the drift guards compare the builder's own fields.
def _builder_fields(r): return {k: v for k, v in r.items() if k != "disclosure"}
# 4 resistance record equals fresh rebuild; note quotes the gate literally
rec = next(x for x in A["records"] if x["metric"] == RR.METRIC)
ok("4 resistance record == rebuild", RR.build_record(DM) == _builder_fields(rec))
ok("4 record states NOT SOH", "NOT an SOH" in rec["note"])
ok("4 record discloses gate sensitivity", "Gate sensitivity" in rec["note"])
# 5 rainflow records equal rebuild
new = RF.build(DM); got = [_builder_fields(x) for x in A["records"] if x["metric"] in (RF.M1, RF.M2)]
ok("5 rainflow records == rebuild", sorted(new, key=lambda x: x["metric"]) == sorted(got, key=lambda x: x["metric"]))
# 8 (M291, audit B8): every record carries the disclosure contract; capped exclusions expose the raw extremum
ok("8 records disclosure contract present", all(isinstance(x.get("disclosure"), dict)
    and "excludedByCap" in x["disclosure"]
    and (x["disclosure"]["excludedByCap"] == 0 or "rawExtremum" in x["disclosure"]) for x in A["records"]))
ms = [x["metric"] for x in A["records"]]
ok("9 (M295) no record is won by a canonically invalid drive", all(x["disclosure"].get("winnerValidity") != "canonically_invalid" for x in A["records"]))
ok("6 new records present exactly once; metric names unique", all(ms.count(m) == 1 for m in (RR.METRIC, RF.M1, RF.M2)) and len(ms) == len(set(ms)))
# 7 ECDF payload equals rebuild; counts consistent with cohort membership; sorted; cold absent
CD = A["cohortDistributions"]; fresh = CDm.build()
ok("7 cohortDistributions == rebuild", CD == fresh)
ok("7 per-cohort arrays sorted", all(v == sorted(v) for m in CD["metrics"].values() for v in m["cohorts"].values() if v))
import pandas as _pd
_sdm = _pd.read_csv("seasonal_drive_master.csv", low_memory=False)       # M310 minimum-support rule: drives of a cohort below the minimum sit in 'all' only
_nsup = int((_sdm["thermal_regime"].astype(str).str.endswith("_insufficient") & _sdm["engine_on_pct"].notna()).sum())
ok("7 warm+shoulder+suppressed(below min support) n == all n (engine_on_pct)", len(CD["metrics"]["engine_on_pct"]["cohorts"]["warm"]) + len(CD["metrics"]["engine_on_pct"]["cohorts"]["shoulder"]) + _nsup == len(CD["metrics"]["engine_on_pct"]["cohorts"]["all"]))
ok("7 no fabricated Cold distribution", all(m["cohorts"]["cold"] is None for m in CD["metrics"].values()))
print(f"\n{len(P)} passed, {len(F)} failed"); sys.exit(1 if F else 0)
