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
assert "not yet quantified" in b["effectOnKeys"] and "confounded by season, ambient and drive mix" in b["effectOnKeys"]
assert list(d["file"]) == list("abcdefgh") and d["regime"].isna().sum() == 1
print("test_cadence_regime: OK")
