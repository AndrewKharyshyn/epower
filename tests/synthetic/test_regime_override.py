"""M426 known-answer tests for seasonal_core.apply_regime_override (owner decision 2026-10-13: the 6->4->6 C boundary drive is assigned to Shoulder)."""
import os, sys, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)
import seasonal_core as sc

OV = {"d.csv": {"physicalRegime": "cold", "regime": "shoulder", "reason": "boundary", "decision": "owner"}}
assert sc.apply_regime_override("cold", "d.csv", OV) == ("shoulder", "cold->shoulder")
assert sc.apply_regime_override("cold", "other.csv", OV) == ("cold", "")                 # only the named file
assert sc.apply_regime_override("warm", "other.csv", None) == ("warm", "")
for bad_regime in ("shoulder", "warm"):                                                  # stale: the physical class changed
    try:
        sc.apply_regime_override(bad_regime, "d.csv", OV)
    except ValueError as e:
        assert "stale" in str(e)
    else:
        raise AssertionError("stale override accepted")
for mut in ({"regime": "warm"}, {"regime": "cold"}, {"reason": ""}, {"decision": None}, {"physicalRegime": "hot"}):       # non-adjacent / same / missing fields
    try:
        sc.apply_regime_override("cold", "d.csv", {"d.csv": dict(OV["d.csv"], **mut)})
    except ValueError:
        continue
    raise AssertionError("bad override accepted: %r" % mut)
# the committed config carries exactly the owner's override, with a reason and a decision, and it applies to the committed physical class
cfg = json.load(open(os.path.join(ROOT, "seasonal_config.json"), encoding="utf-8"))
ov = cfg["cohorts"]["regimeOverrides"]
assert list(ov) == ["2026-10-10_06-57-23.csv"] and ov["2026-10-10_06-57-23.csv"]["regime"] == "shoulder" and ov["2026-10-10_06-57-23.csv"]["physicalRegime"] == "cold"
assert sc.classify_thermal_regime(5.0) == "cold" and sc.apply_regime_override("cold", "2026-10-10_06-57-23.csv", ov)[0] == "shoulder"
print("test_regime_override: OK")
