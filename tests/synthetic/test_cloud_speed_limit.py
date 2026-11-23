"""M750 known-answer tests (owner decision 2026-11-23): the physical car limit is 180 km/h; cloud speed readings from 130 to 180 km/h are valid in any export
(the current export's display is clipped at exactly 130.0, measured, but no tool assumes 130 as a limit); a reading above 180 km/h or below 0 is dropped;
an odometer step that implies more than 180 km/h is rejected, one that implies 150 km/h is accepted."""
import os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_coverage as mc
import mynissan_unlogged as u

assert mc.PHYSICAL_MAX_KMH == 180.0 and mc.STEP_MAX_KMH == 180.0 and u.STEP_MAX_KMH == 180.0

# displayed-speed readings
for ok in ("0", "60", "130", "130.0", "131", "150", "179.9", "180"):
    assert mc.speed_kmh(ok) == float(ok), ok
for bad in ("180.1", "200", "250", "-1", "", "x", None):
    assert mc.speed_kmh(bad) is None, bad

# an odometer step that implies 150 km/h (1.25 km in 30 s) with displayed speeds at or above the old 130 display ceiling is accepted; 200 km/h implied is rejected
spd = [(0, 130.0), (30, 150.0), (60, 150.0)]
fast = [(0, 100.0), (30, 101.25), (60, 102.5)]
assert [(a, b) for a, b, _ in u.accepted_steps(fast, spd)] == [(0, 30), (30, 60)]
too_fast = [(0, 100.0), (30, 101.7), (60, 103.4)]                     # 1.7 km in 30 s = 204 km/h
assert u.accepted_steps(too_fast, spd) == []
edge = [(0, 100.0), (30, 101.5)]                                      # 1.5 km in 30 s = exactly 180 km/h: accepted
assert len(u.accepted_steps(edge, [(0, 130.0), (30, 130.0)])) == 1
print("test_cloud_speed_limit: OK")
