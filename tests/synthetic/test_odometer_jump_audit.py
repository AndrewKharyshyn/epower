"""M765 known-answer tests (analyses/M765_spec.md Rev 2): planted odometer streams for the jump rules B (tool), B1 (strictly inside), B2, B3 (audit-like) and P (physical), the location and size classes of a flagged step,
the availability test, the excursion diagnostic, the cross-tabulation and the frozen H1 predictions, and the privacy scan. No store is needed."""
import os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import odometer_jump_audit as J


def stream(rows):
    rows = sorted(rows)
    return np.array([r[0] for r in rows], float), np.array([r[1] for r in rows], float)


# drive window [500, 600]; the tool window is [465, 635] plus one row beyond each end
base = [(300, 100.0), (400, 100.0), (470, 100.0), (500, 100.0), (550, 101.0), (600, 102.0), (640, 102.0), (700, 102.0)]
ts, vs = stream(base)
f = J.rule_flags(500.0, 600.0, ts, vs)
assert not any(f.values()), f                                             # a clean stream is flagged by no rule

# 1. a negative step inside the drive span: every rule flags it
ts, vs = stream([(300, 100.0), (400, 100.0), (470, 100.0), (520, 100.0), (550, 40.0), (600, 41.0), (640, 41.0), (700, 41.0)])
f = J.rule_flags(500.0, 600.0, ts, vs)
assert all(f[k] for k in J.RULES), f
assert J.flagged_location(500.0, 600.0, ts, vs, f) == "inside_drive_span"
assert J.size_class(ts, vs, 500.0, 600.0) == "10_to_100km" or J.size_class(ts, vs, 500.0, 600.0) == "above_10km"

# 2. a step at the extra edge rows only (row 400 -> 470 lies before the window): the tool flags it, strict-inside and P do not
ts, vs = stream([(300, 100.0), (400, 100.0), (470, 10.0), (500, 10.0), (550, 11.0), (600, 12.0), (640, 12.0), (700, 12.0)])
f = J.rule_flags(500.0, 600.0, ts, vs)
assert f["B"] and not f["B1"] and not f["P"] and f["B2"] and not f["B3"], f
assert J.flagged_location(500.0, 600.0, ts, vs, f) == "extra_edge_rows_only"

# 3. a positive step at dt = 0 (duplicate timestamps): B and B1 keep it, B2, B3 and P flag it
ts, vs = stream([(300, 10.0), (400, 10.0), (470, 10.0), (500, 10.0), (550, 10.0), (550.0, 12.0), (600, 12.0), (640, 12.0), (700, 12.0)])
f = J.rule_flags(500.0, 600.0, ts, vs)
assert not f["B"] and not f["B1"] and f["B2"] and f["B3"] and f["P"], f
assert J.flagged_location(500.0, 600.0, ts, vs, f) in ("inside_drive_span", "endpoint_stretch")

# 4. a long gap with a step at less than 180 km/h is never a jump (90 km in 3100 s = 104 km/h)
ts, vs = stream([(300, 10.0), (400, 10.0), (470, 10.0), (500, 10.0), (3600, 100.0), (3640, 100.0)])
f = J.rule_flags(500.0, 600.0, ts, vs)
assert not any(f.values()), f
# the same step in a shorter gap exceeds 180 km/h: 90 km in 1000 s = 324 km/h, a jump under P (the stretch between the rows used) and under B
ts, vs = stream([(300, 10.0), (400, 10.0), (470, 10.0), (500, 10.0), (1500, 100.0), (1540, 100.0)])
f = J.rule_flags(500.0, 1400.0, ts, vs)
assert f["P"] and f["B"], f

# 5. a stretch wider than the window: the step lies between the last row before t0 (t0 - 100) and the first row after (t0 + 10)
ts, vs = stream([(300, 10.0), (400, 0.0), (510, 50.0), (600, 51.0), (640, 51.0)])
f = J.rule_flags(500.0, 600.0, ts, vs)
assert f["P"] and f["B"] and not f["B1"], f

# availability by the bracket test alone, and the order of reasons: an unavailable drive with a jump counts once per rule order
ts, vs = stream([(100, 10.0), (200, 10.0), (900, 10.0), (1000, 10.2), (1100, 10.3)])
ok, reason, dist = J.availability(500.0, 600.0, ts, vs)                       # flat bracket: exact whatever the gap
assert ok and abs(dist) < 1e-9, (ok, reason, dist)
ts2, vs2 = stream([(100, 10.0), (200, 11.0), (900, 12.0)])
ok, reason, dist = J.availability(500.0, 600.0, ts2, vs2)                     # not flat, gap 700 s > the 35 s cap
assert not ok and reason == "no_row_within_cap", (ok, reason)

# excursion diagnostic: a stretch below the running maximum is an excursion; an endpoint inside it is counted
ts, vs = stream([(0, 100.0), (10, 100.0), (20, 50.0), (30, 50.0), (40, 100.0), (50, 101.0)])
spans = J.excursion_spans(ts, vs)
assert spans == [(20.0, 30.0)], spans
assert J.in_excursion(25.0, spans) and not J.in_excursion(45.0, spans)

# cross-tabulation and the frozen H1 predictions
recs = []
def add(n, unavail, **flags):
    for _ in range(n):
        base_f = {k: False for k in J.RULES}
        base_f.update(flags)
        recs.append({"unavailable_A": unavail, "flags": dict(base_f)})
add(124, True)                                          # unavailable by A
for _ in range(8):
    recs[_]["flags"]["B"] = True                        # 8 flagged by B among the unavailable
add(9, False, B=True)                                   # B and available by A: 9
add(7, False, B=True, B3=True)                          # B3 and available by A: 7 (those 7 are also B)
add(600, False)
ct = J.crosstab(recs)
assert ct["unavailable_by_A"] == 124 and ct["rules"]["B"]["flagged_and_unavailable_by_A"] == 8
assert ct["rules"]["B"]["flagged_and_available_by_A"] == 16 and ct["rules"]["B3"]["flagged_and_available_by_A"] == 7
h = J.h1_check(ct, 4)
assert h["observed"]["B_and_available_by_A"] == 16 and h["h1_confirmed"] is False and h["falsified_by_cross_tab"] is False
# exactly the predicted configuration confirms H1
recs2 = []
recs = recs2
add(124, True)
for _ in range(8):
    recs2[_]["flags"]["B"] = True
add(9, False, B=True)
add(7, False, B3=True)
add(500, False)
h2 = J.h1_check(J.crosstab(recs2), 4)
assert h2["observed"] == J.PREDICTIONS and h2["h1_confirmed"] is True and h2["outside_span_drives"] == 4
# falsified when fewer than 8 jump-labelled drives are unavailable by A
recs3 = []
recs = recs3
add(124, True)
for _ in range(7):
    recs3[_]["flags"]["B"] = True
assert J.h1_check(J.crosstab(recs3), 4)["falsified_by_cross_tab"] is True

# privacy scan: dates, file names and values in the absolute odometer range are refused; counts, rates and months are allowed
assert J.scan_privacy({"a": {"n": 584, "rel": 1.2, "byMonth": {"2026-05": {"drives": 38}}}}) == []
assert J.scan_privacy({"f": "2026-10-17_23-13-01.csv"}) and J.scan_privacy({"v": 48104.8}) and J.scan_privacy({"2026-10-17": 3})
assert J.PREDICTIONS == {"unavailable_by_A": 124, "B_and_unavailable_by_A": 8, "B_and_available_by_A": 9, "B3_and_available_by_A": 7}
print("test_odometer_jump_audit: OK")
