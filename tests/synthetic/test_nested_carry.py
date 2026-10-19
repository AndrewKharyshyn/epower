"""M460: ingest_core.carry_forward keeps the additive leaves that on-demand studies splice into recomputed blocks (evTraction.detectorSensitivity, evTraction.zeroFuelVariant): a fresh evTraction without them gets them back, a fresh one that
already carries them is untouched, a missing previous parent is a no-op, and the report lists the carried names."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ingest_core as IC

prev = {"evTraction": {"nValid": 1, "detectorSensitivity": {"a": 1}, "zeroFuelVariant": {"b": 2}}, "_artifactStamps": {}}
fresh = {"evTraction": {"nValid": 2}}
carried = IC.carry_forward(fresh, prev)
assert fresh["evTraction"] == {"nValid": 2, "detectorSensitivity": {"a": 1}, "zeroFuelVariant": {"b": 2}}, fresh
assert "evTraction.detectorSensitivity" in carried and "evTraction.zeroFuelVariant" in carried
fresh2 = {"evTraction": {"nValid": 3, "zeroFuelVariant": {"b": 9}}}
IC.carry_forward(fresh2, prev)
assert fresh2["evTraction"]["zeroFuelVariant"] == {"b": 9} and fresh2["evTraction"]["detectorSensitivity"] == {"a": 1}      # an existing fresh leaf is never overwritten
fresh3 = {"evTraction": {"nValid": 4}}
assert not [c for c in IC.carry_forward(fresh3, {"evTraction": {"nValid": 1}, "_artifactStamps": {}}) if c.startswith("evTraction.")] and fresh3["evTraction"] == {"nValid": 4}
fresh4 = {"x": 1}
IC.carry_forward(fresh4, prev)                                                                                      # parent absent in the fresh arrays: top-level rule carries the whole block
assert fresh4["evTraction"] == prev["evTraction"]
print("test_nested_carry: OK")
