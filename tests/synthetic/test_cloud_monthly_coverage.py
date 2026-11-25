"""M776 known-answer test: monthly cloud movement outside the OBD logs (spec analyses/M776_spec.md Rev 2, section 6 gate 2).
Constructed odometer/speed series and windows; planted totals recovered exactly; no store needed."""
import os, sys
from datetime import datetime
from zoneinfo import ZoneInfo

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import cloud_monthly_coverage as cm

K = ZoneInfo("Europe/Kyiv")
P = dict(cm.PRIMARY)


def ep(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=K).timestamp()


def spd_every(t0, t1, v, dt=10):
    out, t = [], t0
    while t <= t1:
        out.append((t, v))
        t += dt
    return out


# 1. step fully outside a window is counted; step overlapping a padded window is not; month-spanning step -> unknown
t = ep(2026, 6, 10, 12, 0)
odo = [(t, 100.0), (t + 30, 100.5)]                           # outside, 0.5 km in 30 s = 60 km/h
t_in = ep(2026, 6, 10, 15, 0)
odo += [(t_in, 101.0), (t_in + 30, 101.4)]                    # overlaps the window below
tm = ep(2026, 6, 30, 23, 59, 50)
odo += [(tm, 102.0), (tm + 30, 102.3)]                        # crosses 30 Jun -> 1 Jul (Kyiv)
spd = spd_every(t - 100, tm + 100, 60.0)
wins = [(t_in - 10, t_in + 60)]
recs = cm.classify(odo, spd, wins, P)
cls = [r["cls"] for r in recs]
# pairs: outside step, gap to the window (g2: the gap touches the padded window), inside step, gap (g2), month-spanning outside step
assert cls == ["step_outside", "g2", "step_inside", "g2", "step_outside"], cls
agg = cm.aggregate(recs, t - 1000, tm + 1000)
assert abs(agg["2026-06"]["step_outside"]["km"] - 0.5) < 1e-9 and agg["2026-06"]["step_outside"]["n"] == 1
assert abs(agg["2026-06"]["step_inside"]["km"] - 0.4) < 1e-9
assert abs(agg["month unknown"]["step_outside"]["km"] - 0.3) < 1e-9

# 2. rejected: negative step, implied speed above 180, no speed support, all counted not dropped
base = ep(2026, 7, 1, 10, 0)
odo2 = [(base, 200.0), (base + 20, 199.0),                    # negative
        (base + 40, 199.0 + 2.0),                             # +2.0 km in 20 s = 360 km/h -> rej_speed
        (base + 60, 201.2)]                                   # 0.2 km in 20 s = 36 km/h but no speed sample near
r2 = cm.classify(odo2, [(base - 500, 50.0)], [], P)
assert [r["cls"] for r in r2] == ["rej_negative", "rej_speed", "rej_nosupport"], [r["cls"] for r in r2]

# 3. gap increment classes: g1 no overlap, g2 overlap with a padded window
b3 = ep(2026, 8, 5, 8, 0)
odo3 = [(b3, 300.0), (b3 + 600, 310.0), (b3 + 1200, 320.0)]
r3 = cm.classify(odo3, [], [(b3 + 1000, b3 + 1100)], P)
assert [r["cls"] for r in r3] == ["g1", "g2"], [r["cls"] for r in r3]

# 4. DST: 2026-10-25 03:30 Kyiv is ambiguous (fold); both folds map to the same local date; midnight crossing local date
t_amb, amb = cm.parse_local("2026-10-25", "03:30:00")
assert amb is True
assert cm.local_date(t_amb) == "2026-10-25" and cm.local_date(t_amb + 3600) == "2026-10-25"
t_mid = ep(2026, 10, 25, 23, 59, 59)
assert cm.local_date(t_mid) == "2026-10-25" and cm.local_date(t_mid + 2) == "2026-10-26"   # 25 h day does not shift the date
assert cm.parse_local("2026-07-01", "12:00:00")[1] is False

# 5. windows merged with padding; overlap at the exact padded edge counts
s, e = cm.merge_windows([(1000.0, 1100.0), (1130.0, 1200.0)], 45.0)
assert s == [955.0] and e == [1245.0]
assert cm.overlaps(s, e, 1245.0, 1300.0) and not cm.overlaps(s, e, 1246.0, 1300.0)

# 6. OBD km by Kyiv month inside the span
rows = [{"file": "a", "t0": ep(2026, 5, 31, 23, 30), "km": 10.0}, {"file": "b", "t0": ep(2026, 6, 1, 0, 30), "km": 5.0},
        {"file": "c", "t0": ep(2026, 6, 1, 8, 0), "km": 2.5}, {"file": "d", "t0": ep(2026, 9, 1, 8, 0), "km": 99.0}]
o = cm.obd_by_month(rows, ep(2026, 5, 1, 0, 0), ep(2026, 6, 30, 0, 0))
assert set(o) == {"2026-05", "2026-06"} and o["2026-06"]["km"] == 7.5 and o["2026-06"]["drives"] == 2

# 7. skips cleanly without a store
assert cm.main(["--store", os.path.join(REPO, "no_such_store_dir")]) == 0
print("PASS test_cloud_monthly_coverage")
