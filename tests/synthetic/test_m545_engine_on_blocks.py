"""M545 (analyses/M545_spec.md Rev 2): wave 3 of the engine-on migration: the sidecar aggregator against an independent recomputation on synthetic per-drive entries (run lengths concatenate, counts sum, day clustering, stored-wording identity),
the sidecar stores no class / cohort / cadence / date / label, the payload Rule blocks (structure, counts, intervals, n days, floor, stamps, E1 / known answers recorded in the provenance), the display rebind (guarded accessor, cohort selection, labels),
the crosscheck_events identity, and the language rules."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import engine_on_blocks_stage as ST
import compute_summary_arrays as C

# ---- synthetic aggregation: three drives, two days, hand-computable ----
def ent(runs, eod, spd_tot, spd_on, tr, ts, hvc):
    return {"runs": runs, "eod": eod, "spdTot": spd_tot, "spdOn": spd_on, "spdAny": True, "tr": tr, "ts": ts, "hvc": hvc, "sha256": "x"}
z = [0.0] * 7
E = {"a": ent([10, 20, 30, 40, 50], [150.0, 300.0, 5.0], [10.0] + z[1:], [4.0] + z[1:], {"<1500": [10, 2, 1.0, 0.5]}, {"0-40": [10, 2, 0.5]}, [10, 2, 0.5]),
     "b": ent([5, 5, 5, 5, 5], [25.0, 100.0, 5.0], [10.0] + z[1:], [6.0] + z[1:], {"<1500": [5, 1, 0.4, 0.4]}, {"0-40": [5, 1, 0.4]}, [5, 1, 0.4]),
     "c": ent([], None, [0.0] * 7, [0.0] * 7, {}, {}, None)}
E["c"]["spdAny"] = False
rows = [{"file": "a", "cls": "urban", "day": "2026-01-01", "label": "L1"}, {"file": "b", "cls": "urban", "day": "2026-01-02", "label": "L2"}, {"file": "c", "cls": "urban", "day": "2026-01-02", "label": "L3"}]
out, det = ST.aggregate(E, rows, with_ci=False)
r = out["engineOnDuration"][0]
allruns = np.array([10, 20, 30, 40, 50, 5, 5, 5, 5, 5], float)
assert r["label"] == "Urban" and r["nSegments"] == 10 and r["median"] == float(np.median(allruns)) and r["min"] == 5.0 and r["max"] == 50.0
assert r["p90"] == round(float(np.percentile(allruns, 90)), 1) and r["onFraction"] == round(175.0 / 400.0 * 100, 1) and r["segsPer10min"] == round(10 / (400.0 / 600.0), 1)
assert out["engineOnBySpeed"][0]["pct"] == round(10 / 20 * 100) and det["engineOnBySpeed"]["nDrives"] == 2 and det["engineOnBySpeed"]["zones"][0]["onRows"] == 10
assert out["turboByRpm"][0] == {"rpm": "<1500", "n": 15, "activePct": round(3 / 15 * 100), "meanActive": round(1.4 / 3, 3), "maxBoost": 0.5}
assert out["turboBySpeedCtx"][0] == {"zone": "0-40", "activePct": round(3 / 15 * 100), "maxBoost": 0.5}
assert det["hvcTurboActivity"]["urban"]["n"] == 15 and det["hvcTurboActivity"]["urban"]["maxLabel"] == "L1" and det["hvcTurboActivity"]["urban"]["nDays"] == 2
assert out["hvcTurboActivity"]["urban"].startswith("20.0% of engine-on native rows (rpm > 400, logged samples; n=15, >0.1 bar)")
sw, _ = ST.aggregate(E, rows, with_ci=False, stored_wording=True)
assert sw["hvcTurboActivity"]["urban"].startswith("20.0% of engine-on time (n=15, >0.1 bar)")        # the identity-gate wording
assert out["hvcTurboActivity"]["mixed"] is None
# unknown / unclassified drive types are not in the displayed classes
rows2 = [dict(rows[0], cls="unknown"), rows[1]]
o2, d2 = ST.aggregate(E, rows2, with_ci=False)
assert [(x["label"], x["nSegments"]) for x in o2["engineOnDuration"]] == [("Urban", 5)] and d2["hvcTurboActivity"]["urban"]["n"] == 5      # drive a (unknown class) is outside the displayed classes
# day-clustered intervals: reproducible (seed 42), within [min, max] of the runs, absent below two days
o3, d3 = ST.aggregate(E, rows, with_ci=True)
ci = d3["engineOnDuration"]["urban"]["medianCi95"]
assert ci and 5.0 <= ci[0] <= ci[1] <= 50.0 and d3["engineOnDuration"]["urban"]["nDays"] == 2 and d3["engineOnDuration"]["urban"]["exploratory"] is True       # 2 < 5 days: exploratory
assert ST.aggregate(E, rows, with_ci=True)[1]["engineOnDuration"]["urban"]["medianCi95"] == ci
o4, d4 = ST.aggregate(E, rows[:1], with_ci=True)
assert d4["engineOnDuration"]["urban"]["medianCi95"] is None

# ---- the sidecar stores no class / cohort / cadence / date / label ----
sc_path = os.path.join(ROOT, "engine_on_blocks_sidecar.json")
J = json.load(open(sc_path, encoding="utf-8"))
assert J["meta"]["thresholdRpm"] == 400 and J["meta"]["boundary"] == "gt" and len(J["drives"]) == 606
one = next(iter(J["drives"].values()))
assert set(one) == {"runs", "eod", "spdTot", "spdOn", "spdAny", "tr", "ts", "hvc", "sha256"}, set(one)
txt = open(sc_path, encoding="utf-8").read()
assert "\r" not in txt and txt.endswith("\n") and not re.search(r"urban|highway|thermal|cold|warm|shoulder|cadence", json.dumps(J["drives"]).replace("hvc", ""))

# ---- payload ----
A = json.load(open("summary_arrays.json", encoding="utf-8"))
for k, st in ST.STORED.items():
    b = A[k]
    assert b["rule"] == {"thresholdRpm": 400, "boundary": "gt", "name": "engine-on (rpm > 400)", "storedKey": st}
    assert b["displayed"] is False or b["displayed"] is True
    assert set(b["byCohort"]) == {"warm", "shoulder", "cold"} and b["provenance"]["gates"]["passed"] is True
    assert b["provenance"]["gates"]["E1RuleSecondsExact"]["nDifferent"] == 0 and b["provenance"]["gates"]["M544KnownAnswers"]["passed"] is True
    assert A["_artifactStamps"][k]["corpusHash"] and "no 300-versus-400 contrast or difference interval is drawn" in b["limits"]
    # the stored block is untouched in shape (key kept)
    assert st in A
d = A["engineOnDurationRule"]["detail"]["pooled"]
assert all(v["nDays"] >= 1 and v["nDrives"] >= 1 for v in d.values()) and all((v["medianCi95"] is None) == (v["nDays"] < 2) for v in d.values())
assert A["engineOnBySpeedRule"]["detail"]["pooled"]["nDrives"] == A["engineOnDrives"]
assert sum(z["onRows"] for z in A["engineOnBySpeedRule"]["detail"]["pooled"]["zones"]) > 0 and all(z["ci95"] for z in A["engineOnBySpeedRule"]["detail"]["pooled"]["zones"])
assert all("stored basis (rpm > 300, native rows)" == v["label"] for v in A["hvcTurboActivityRule"]["storedBasis"].values())
# cohort lists have the stored shape
assert set(A["turboByRpmRule"]["pooled"][0]) == set(A["turboByRpm"][0]) and set(A["engineOnBySpeedRule"]["pooled"][0]) == set(A["engineOnBySpeed"][0]) and set(A["engineOnDurationRule"]["pooled"][0]) == set(A["engineOnDuration"][0])

# ---- display rebind ----
src = open("xtrail_summary.jsx", encoding="utf-8").read()
assert "function engineOnBlockRule(key)" in src and "b.rule.thresholdRpm===400" in src and "b.rule.boundary==='gt'" in src
assert sum(len(re.findall(r"S\[key\]|S\.(?:engineOnDurationRule|engineOnBySpeedRule|turboByRpmRule|turboBySpeedCtxRule|hvcTurboActivityRule)", l)) for l in src.split("\n") if not l.strip().startswith("//")) == 1       # one direct reader: the accessor
assert 'cohortOrRule("EngineOnDuration"' in src and 'cohortOrRule("EngineOnBySpeed"' in src and 'cohortOrRule("TurboByRpm"' in src
assert 'engineOnBlockRule("turboBySpeedCtxRule")' in src and 'engineOnBlockRule("hvcTurboActivityRule")' in src
assert "stored basis (rpm > 300" in src or "sb.label" in src
assert "run-boundary re-definition, deterministic, same data" in src and "not the rpm &gt; 400 rule" in src
assert 'stored basis, rpm > 300' in src
# ---- crosscheck_events: the aux side uses the same kernels and gate as the primary side ----
cc = open("crosscheck_events.py", encoding="utf-8").read()
assert "csa._RawAccum(eng_on_rpm=csa.ENGINE_ON_STORED_RPM)" in cc and "Engine-on basis (M545)" in cc
assert C._RawAccum().eng_on_rpm == C.ENGINE_ON_STORED_RPM == 300
import inspect
assert "_RawAccum()" in inspect.getsource(C.build_summary_arrays) or "_RawAccum()" in open("compute_summary_arrays.py", encoding="utf-8").read()
# ---- language ----
import language_gate as G
ids = [x.rid for x in G.RULES]
assert "M545-engine-on-native-rows" in ids and "M545-engine-on-run-wording" in ids
assert G.scan_text("of ENGINE-ON time (rpm > 300) at >0.1 bar") and not G.scan_text("7.4% of engine-on native rows (rpm > 400, logged samples; n=1,200,763, >0.1 bar)")
assert G.scan_text("a false engine-on run")
print("OK test_m545_engine_on_blocks: aggregator vs hand computation, sidecar content, payload gates / stamps / intervals, display rebind, crosscheck identity, language rules")
