"""M379a known-answer tests for tools/cadence_regime.py (analyses/M379_spec.md Rev 2 P1): regime rule, STOP inside the empty gap, null handling, run building (nulls do not split a run),
days with both regimes, and that the payload block carries the statements the dashboard binds to."""
import os, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cadence_regime as C

assert C.classify(0.85) == "fast" and C.classify(0.999) == "fast" and C.classify(1.1) == "slow" and C.classify(1.45) == "slow"
assert C.classify(None) is None and C.classify(float("nan")) is None
for bad in (1.0, 1.05, 1.0999):
    try:
        C.classify(bad)
    except SystemExit as e:
        assert "empty gap" in str(e)
    else:
        raise AssertionError("a drive inside the gap must STOP: %r" % bad)

dm = pd.DataFrame({
    "file": list("abcdefgh"),
    "date": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02", "2026-01-03", "2026-01-03", "2026-01-04", "2026-01-05"],
    "time_start": ["08:00:00", "09:00:00", "08:00:00", "09:00:00", "08:00:00", "09:00:00", "08:00:00", "08:00:00"],
    "I_sample_period_s": [1.4, 1.4, 0.8, float("nan"), 0.8, 1.4, 1.4, 0.9]})
d, b = C.build(dm)
assert b["counts"] == {"fast": 3, "slow": 4, "null": 1}, b["counts"]
assert [(r["regime"], r["nDrives"], r["nDays"]) for r in b["runs"]] == [("slow", 2, 1), ("fast", 2, 2), ("slow", 2, 2), ("fast", 1, 1)], b["runs"]      # the null drive does not split the fast run
assert b["daysWithBothRegimes"] == ["2026-01-03"] and b["nDaysByRegime"] == {"fast": 3, "slow": 3}
assert "not yet quantified" in b["effectOnKeys"] and "confounded by season, ambient and drive mix" in b["effectOnKeys"] and "sensitivity" not in b
assert list(d["file"]) == list("abcdefgh") and d["regime"].isna().sum() == 1

# ---- M379b: summary of a (synthetic) sensitivity study: classes, corpus arithmetic, flips ----
def _k(est, ci, cls, stat="ratio of sums (emulated / original)"):
    return {"estimate": est, "ci95": ci, "class": cls, "statistic": stat}
study = {"meta": {"nStudyDrives": 3, "nStudyDays": 2, "seeds": [1, 2], "nControlDrives": 3, "nRobustnessDrives": 2, "limits": ["x"]},
         "validation": {"identityKeepAll": {"maxAbsDiffAllKeys": 0.0}, "intervalMatch": {"relDiffMean": 0.003, "withinFivePercent": True}, "ivGap": {"flagOutsidePlusMinus25pct": True, "relDiff": -0.4},
                        "masterReproduction": {"nDrives": 3, "nDistanceDiffering": 0, "maxAbsDiffDistance": 0.0}},
         "emulation": {"fast_to_slow": {"keys": {"gross_throughput_kwh": _k(0.97, [0.96, 0.98], "cadence-sensitive (outside the pre-registered margin)"), "gross_discharge_kwh": _k(0.97, [0.96, 0.98], "cadence-sensitive (x)"),
                                                 "gross_charge_kwh": _k(0.97, [0.96, 0.98], "cadence-sensitive (x)"), "fce": _k(0.97, [0.96, 0.98], "cadence-sensitive (x)"), "rf_efc": _k(0.98, [0.97, 0.99], "cadence-sensitive (x)"),
                                                 "distance_km": _k(1.0, [0.999, 1.001], "cadence-insensitive within the pre-registered margin"),
                                                 "net_draw_per100km_corr": _k(0.03, [-0.02, 0.08], "cadence-sensitive (x)", "mean per-drive difference (emulated - original)"),
                                                 "peak_discharge_kw": _k(-2.0, [-2.5, -1.5], "reported (one-sided bias; negative control)", "mean per-drive difference (emulated - original)") | {"movementDetected": True},
                                                 "peak_I_charge": _k(3.0, [2.0, 4.0], "reported (one-sided bias; negative control)", "mean per-drive difference (emulated - original)") | {"movementDetected": True}}},
                       "fast_to_slower": {"keys": {"gross_throughput_kwh": _k(0.91, [0.9, 0.92], "x")}}, "slow_to_slower": {"keys": {"gross_throughput_kwh": _k(0.92, [0.91, 0.93], "x")}}},
         "headlineQuarterRule": {"shiftBelowQuarter": True}, "robustnessClassFlips": {"regen_share_of_charge": {}}}
dmx = pd.DataFrame({"gross_throughput_kwh": [10.0, 30.0, 60.0], "distance_km": [1.0, 1.0, 1.0], "ens_outlier_v2": [False, False, False]})
sm = C.summarize_sensitivity(study, dmx, pd.Series(["fast", "slow", "slow"]).values)
assert sm["classificationFastToSlow"]["sensitive"] == ["gross_throughput_kwh", "gross_discharge_kwh", "gross_charge_kwh", "fce", "rf_efc"], sm["classificationFastToSlow"]
assert sm["classificationFastToSlow"]["notEstablishedInsensitive"] == ["net_draw_per100km_corr"] and sm["classificationFastToSlow"]["insensitive"] == ["distance_km"]
assert sm["classificationFastToSlow"]["reportedOnly"] == ["peak_discharge_kw", "peak_I_charge"]
assert abs(sm["corpusImplication"]["fastRegimeShareOfGrossThroughput"] - 0.1) < 1e-12 and abs(sm["corpusImplication"]["impliedCorpusGrossThroughputShiftIfAllSlow"] - 0.1 * (0.97 - 1.0)) < 1e-12
assert sm["robustnessClassFlips"] == ["regen_share_of_charge"] and sm["study"]["nFastRegimeDrives"] == 1
assert "not a causal cadence effect" in sm["basis"] and "not a correction" in sm["corpusImplication"]["note"]
print("test_cadence_regime: OK")
