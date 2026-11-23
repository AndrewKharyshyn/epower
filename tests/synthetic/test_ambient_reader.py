"""M755 known-answer tests (analyses/M755_spec.md Rev 2): the shared ambientByDrive reader (plain number, one-reading list, two- and three-reading lists, unreadable and out-of-domain entries), the sites that read it
(heat-soak pairing, auxiliary load, the m435 scope and coverage text), a static check that no ad hoc list-only parse is left at the named sites, and the guard on the real configuration (every entry readable;
non-canonical entries exactly the frozen legacy keys)."""
import inspect, json, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import ambient_protocol as AP
import compute_summary_arrays as C
import m435_tte
import thermal_support_ledger  # noqa: F401  (import check: the module loads with the shared reader)

# reader
assert AP.readings(13) == [13.0] and AP.readings(13.5) == [13.5] and AP.readings([27.0]) == [27.0]
assert AP.readings([10, 14]) == [10.0, 14.0] and AP.readings([8, 9, 13]) == [8.0, 9.0, 13.0] and AP.readings((5, 6)) == [5.0, 6.0]
assert AP.mean_reading(13) == 13.0 and AP.mean_reading([8, 9, 13]) == 10.0 and AP.first_reading(13) == 13.0 and AP.first_reading([8, 9, 13]) == 8.0
for bad in (None, True, False, [], "13", "+10", {"a": 1}, [None, 5], [True, 5], [float("nan")], [99], [-60], 70, ["x"]):
    assert AP.readings(bad) is None and AP.mean_reading(bad) is None and AP.first_reading(bad) is None, bad
assert AP.is_canonical([10.0, 12.0]) and not AP.is_canonical(13) and not AP.is_canonical([27.0])

# heat-soak pairing: a drive whose ambient is stored as a plain number counts as a pair with ambient (it was skipped before M755)
dm = pd.DataFrame({"file": ["a", "b", "c"], "date": ["2026-09-12"] * 3, "time_start": ["08:00:00", "10:00:00", "12:00:00"], "time_end": ["09:00:00", "11:00:00", "13:00:00"]})
traj = {"a": {"pm_end": 30, "pm_start": 25}, "b": {"pm_end": 32, "pm_start": 24}, "c": {"pm_end": 31, "pm_start": 22}}
hs = C._heat_soak_carryover(dm, traj, {"b": 10, "c": [10.0, 10.0]})
assert hs["nPairs"] == 2 and hs["nPairsAmbient"] == 2, hs["nPairsAmbient"]
hs0 = C._heat_soak_carryover(dm, traj, {"b": "n/a", "c": [10.0, 10.0]})
assert hs0["nPairsAmbient"] == 1                                                  # an unreadable entry is still not an ambient (and the guard catches it in the real config)

# auxiliary load vs ambient: plain-number entries are read (the block needs at least 20 drives with an ambient)
n = 30
dm2 = pd.DataFrame({"file": ["f%02d" % i for i in range(n)], "date": ["2026-09-%02d" % (1 + i % 28) for i in range(n)], "standstill_draw_kw": np.linspace(0.5, 2.0, n)})
amb_all_plain = {f: 5.0 + i for i, f in enumerate(dm2["file"])}
assert C._aux_load_ambient(dm2, amb_all_plain) is not None
assert C._aux_load_ambient(dm2, {f: "x" for f in dm2["file"]}) is None

# m435 scope and coverage text read a plain number as the start reading
tte = [{"status": "cold"}, {"status": "cold"}, {"status": "warm"}]
files = ["a", "b", "c"]
assert m435_tte.coverage_text(tte, files, {"a": 8, "b": [9.0, 12.0], "c": 20}) == "start ambient recorded for 2 of 2 cold starts"
assert m435_tte.coverage_text(tte, files, {"a": "x", "b": [9.0, 12.0]}) == "start ambient recorded for 1 of 2 cold starts"

# static: no ad hoc list-only parse left at the named sites
src = open(os.path.join(ROOT, "compute_summary_arrays.py"), encoding="utf-8").read()
assert "sum(float(x) for x in pair)" not in src
for fn in ("_heat_soak_carryover", "_daily_fingerprints", "_linked_adjacent_drive_table", "_battery_temp_ranges", "_aux_load_ambient"):
    code = inspect.getsource(getattr(C, fn))
    assert "_ambient_reader()" in code, fn
for rel in ("tools/m435_tte.py", "tools/thermal_support_ledger.py", "tools/heatsoak_gap_sensitivity.py", "tools/build_ambient_table.py"):
    txt = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    assert "ambient_protocol as AP" in txt and "sum(float(x) for x in pair)" not in txt, rel

# guard on the real configuration
cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))["ambientByDrive"]
legacy = set(json.load(open(os.path.join(ROOT, "tools", "ambient_legacy_keys.json"), encoding="utf-8"))["keys"])
assert len(cfg) >= 717 and all(AP.readings(v) is not None for v in cfg.values())
assert {k for k, v in cfg.items() if not AP.is_canonical(v)} <= legacy and len(legacy) == 69
plain = [k for k, v in cfg.items() if isinstance(v, (int, float))]
assert len(plain) == 66 and all(k in legacy for k in plain)
print("test_ambient_reader: OK")
