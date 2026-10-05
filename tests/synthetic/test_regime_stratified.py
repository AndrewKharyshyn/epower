"""M380 known-answer tests for the decision rules of tools/regime_stratified.py (analyses/M380_spec.md Rev 2 P7): flip classification (CI side of zero, sign, status, support-driven
status), the quarter-half-width flag measured on the side the estimate moves toward, regime attachment from the digit key, and the scaling of one regime only."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import regime_stratified as R

av = lambda d, lo, hi: {"status": "available", "adjustedDiff": d, "ci95": [lo, hi]}
base = av(-1.3, -3.4, 0.3)
assert R.flips(base, av(-1.7, -3.5, 0.4)) == {"estimateDriven": [], "supportDriven": []}, "same side of zero, same sign: no flip"
f = R.flips(base, av(-1.8, -3.7, -0.07))
assert f["estimateDriven"] == ["CI side of 0 changes (includes 0 -> excludes 0)"], "newly significant is a flip"
f = R.flips(av(-1.3, -3.4, -0.2), av(-1.1, -3.0, 0.2))
assert any("includes 0" in x or "excludes 0" in x for x in f["estimateDriven"]), "significant -> not significant is a flip"
f = R.flips(base, av(0.2, -0.5, 0.9))
assert any("sign" in x for x in f["estimateDriven"]), "sign change is a flip"
f = R.flips(base, {"status": "unavailable", "reasonCode": "empty_cohort"})
assert f["supportDriven"] and not f["estimateDriven"], "a support-driven status change is reported separately"
f = R.flips(base, {"status": "unavailable"})
assert f["estimateDriven"] and not f["supportDriven"], "a status change without a support reason is estimate-driven"

q = R.quarter_flag(10.0, 8.0, 14.0, 9.5)          # moves down: half-width on the lower side = 2.0, shift -0.5 = 0.25 of it
assert abs(q["shiftOverHalfWidth"] + 0.25) < 1e-12 and q["class"].startswith("below"), q
q = R.quarter_flag(10.0, 8.0, 14.0, 9.0)          # shift -1.0 = 0.5 of the lower half-width
assert q["class"].startswith("material"), q
q = R.quarter_flag(10.0, 8.0, 14.0, 11.5)         # moves up: half-width on the upper side = 4.0, shift 1.5 = 0.375
assert q["class"].startswith("material") and abs(q["shiftOverHalfWidth"] - 0.375) < 1e-12, q

dr = [{"file": "2026-09-02_07-53-16.csv", "date": "2026-09-02", "gross_throughput_kwh": 10.0, "gross_throughput_kwh_per100km": 20.0, "cad_regime": "fast"},
      {"file": "20260905_103157.csv", "date": "2026-09-05", "gross_throughput_kwh": 10.0, "gross_throughput_kwh_per100km": 20.0, "cad_regime": "slow"},
      {"file": "x.csv", "date": "2026-09-05", "gross_throughput_kwh": None, "gross_throughput_kwh_per100km": None, "cad_regime": None}]
fa = R.scaled(dr, None, "fast", 0.9)
assert fa[0]["gross_throughput_kwh"] == 9.0 and abs(fa[0]["gross_throughput_kwh_per100km"] - 18.0) < 1e-12 and fa[1]["gross_throughput_kwh"] == 10.0 and fa[2]["gross_throughput_kwh"] is None
sl = R.scaled(dr, None, "slow", 1 / 0.9)
assert fa is not dr and dr[0]["gross_throughput_kwh"] == 10.0, "the input drives are not modified"
assert abs(sl[1]["gross_throughput_kwh"] - 10.0 / 0.9) < 1e-12 and sl[0]["gross_throughput_kwh"] == 10.0
rm = {"20260902075316": "fast"}
assert R.dig("2026-09-02_07-53-16.csv") == "20260902075316" and R.attach([dict(dr[0])], rm)[0]["cad_fast"] == 1.0
print("test_regime_stratified: OK")
