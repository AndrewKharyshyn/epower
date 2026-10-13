"""M426 known-answer test for tools/regime_override_sensitivity.py: the override-off values are the published estimator (paired canonical-clean ratio of sums, day-clustered
percentile bootstrap) on the cohort with the physical regime restored; the applied values equal the cohort as published; an override not in force refuses."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import refresh_seasonal_kpis as RK
import regime_override_sensitivity as R

def row(f, d, reg, km, kwh, ex=False):
    return {"file": f, "date": d, "thermal_regime": reg, "distance_km": km, "gross_throughput_kwh": kwh, "excluded": ex}

ROWS = [row("c1", "2026-10-01", "cold", 10.0, 4.0), row("c2", "2026-10-02", "cold", 10.0, 4.0), row("c3", "2026-10-03", "cold", 10.0, 4.0),
        row("b", "2026-10-04", "shoulder", 100.0, 15.0),                       # the boundary drive, assigned to shoulder (physical: cold)
        row("s1", "2026-10-05", "shoulder", 10.0, 3.0), row("s2", "2026-10-06", "shoulder", 10.0, 3.0), row("s3", "2026-10-06", "shoulder", 10.0, 9.9, ex=True)]
OV = {"b": {"physicalRegime": "cold", "regime": "shoulder"}}
out = R.sensitivity(ROWS, OV, RK)["b"]
assert abs(out["cold"]["applied"]["value"] - 40.0) < 1e-9 and out["cold"]["applied"]["n"] == 3 and out["cold"]["applied"]["pairedKm"] == 30.0
assert abs(out["cold"]["removed"]["value"] - 100 * 27.0 / 130.0) < 1e-3 and out["cold"]["removed"]["n"] == 4 and out["cold"]["removed"]["pairedKm"] == 130.0
assert abs(out["shoulder"]["applied"]["value"] - 100 * 21.0 / 120.0) < 1e-3 and out["shoulder"]["applied"]["n"] == 3        # the excluded drive s3 never enters
assert abs(out["shoulder"]["removed"]["value"] - 30.0) < 1e-9 and out["shoulder"]["removed"]["n"] == 2
for c in ("cold", "shoulder"):
    for k in ("applied", "removed"):
        ci = out[c][k]["ci95"]
        assert ci["lo"] <= out[c][k]["value"] <= ci["hi"] and ci["nClusters"] >= 2 and 0 < ci["essDays"] <= ci["nClusters"], (c, k, ci)
assert R.sensitivity(ROWS, OV, RK)["b"] == out                                                       # deterministic (fixed seed)
try:
    R.sensitivity([dict(r, thermal_regime="cold") if r["file"] == "b" else r for r in ROWS], OV, RK)
except ValueError as e:
    assert "not in force" in str(e)
else:
    raise AssertionError("an override that is not in force was accepted")
assert R.sensitivity(ROWS, {}, RK) == {}
print("test_regime_override_sensitivity: OK")
