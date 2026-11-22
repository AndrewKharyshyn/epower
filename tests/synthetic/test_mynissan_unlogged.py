"""M738 known-answer tests (analyses/M738_spec.md Rev 2): step rule incl. speed at one end, unit joining at 120 s, strict flag, time shares,
unit vector, overlap classes at the 10 % and 90 % edges, TV, terciles, within-day permutation, km partition, absent store skipped."""
import os, sys, tempfile
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_unlogged as u

# optional stage: no store -> skipped with exit 0
tmp = tempfile.mkdtemp()
assert u.main(["--store", os.path.join(tmp, "nostore"), "--out-dir", tmp]) == 0

# step rule: gap <= 35 s, positive increment, implied speed <= 180 km/h, speed above zero at one end
odo = [(0, 100.0), (30, 100.25), (60, 100.5), (200, 100.7)]          # last step spans 140 s: rejected
spd = [(0, 30.0), (30, 30.0), (60, 30.0), (200, 30.0)]
st = u.accepted_steps(odo, spd)
assert [(a, b) for a, b, _ in st] == [(0, 30), (30, 60)] and abs(st[0][2] - 0.25) < 1e-9
assert u.accepted_steps([(0, 1.0), (30, 1.5)], [(0, 0.0), (30, 0.0)]) == []                       # zero speed at both ends: not a step
assert len(u.accepted_steps([(0, 1.0), (30, 1.5)], [(0, 0.0), (30, 20.0)])) == 1                  # speed above zero at one end suffices
assert len(u.accepted_steps([(0, 1.0), (30, 2.0)], [(0, 60.0), (30, 60.0)])) == 1                 # 120 km/h implied: accepted
assert u.accepted_steps([(0, 1.0), (10, 2.0)], [(0, 60.0), (10, 60.0)]) == []                     # 360 km/h implied: rejected
assert u.accepted_steps([(0, 1.0), (30, 1.0)], [(0, 60.0), (30, 60.0)]) == []                     # zero increment: rejected

# unit joining: a pause of 120 s joins, 121 s splits
a_ = [(0, 30, 0.2), (30, 60, 0.2), (180, 210, 0.2)]                # pause 120 s between 60 and 180
assert len(u.join_units(a_)) == 1
b_ = [(0, 30, 0.2), (30, 60, 0.2), (181, 211, 0.2)]                # pause 121 s
assert [len(x) for x in u.join_units(b_)] == [2, 1]
# strict flag: at least two steps and at least 1 km
assert u.is_strict([(0, 30, 0.5), (30, 60, 0.5)]) and not u.is_strict([(0, 30, 2.0)]) and not u.is_strict([(0, 30, 0.4), (30, 60, 0.4)])

# time shares: 60 s at 20 km/h, 60 s at 50 km/h, 60 s at 100 km/h (samples every 30 s)
sp = [(0, 20.0), (30, 20.0), (60, 20.0), (90, 50.0), (120, 50.0), (150, 100.0), (180, 100.0)]
sh, cov = u.time_shares(sp, 0, 180)
# interval classes use the interval mean speed: 0-60 s at 20 (class 0); 60-90 (mean 35), 90-120 (50), 120-150 (mean 75) in class 1; 150-180 at 100 (class 2)
assert cov == 180 and abs(sh[0] - 1 / 3) < 1e-9 and abs(sh[1] - 0.5) < 1e-9 and abs(sh[2] - 1 / 6) < 1e-9
assert abs(sum(sh) - 1.0) < 1e-9
sh2, cov2 = u.time_shares([(0, 20.0), (30, 20.0), (200, 20.0)], 0, 200)         # the 170 s hole is not bridged
assert cov2 == 30 and sh2[0] == 1.0
assert u.time_shares([(0, 20.0)], 0, 10) == (None, 0.0)

# unit vector on planted data: 1.0 km in 120 s of steps, 60 s pause not counted in moving time
unit = [(0, 30, 0.25), (30, 60, 0.25), (60, 90, 0.25), (90, 120, 0.25)]
spd_in = [(0, 30.0), (30, 30.0), (60, 30.0), (90, 30.0), (120, 30.0)]
amb = [(t, 12.0) for t in range(0, 900, 30)]
v = u.unit_vector(unit, spd_in, amb)
assert abs(v["km"] - 1.0) < 1e-9 and v["duration_s"] == 120 and v["moving_s"] == 120
assert abs(v["mean_moving_kmh"] - 30.0) < 1e-9 and v["shares"][1] == 1.0 and v["ambient"] is None      # unit too short for the 180 s cutoff

# overlap classes at the 10 % and 90 % edges
w = [(0.0, 100.0)]
f, hit = u.overlap_fraction(90.0, 190.0, w)                         # 10 % overlap
assert abs(f - 0.10) < 1e-9 and hit == [0] and u.classify_unit(f) == "boundary"
f2, _ = u.overlap_fraction(91.0, 191.0, w)
assert u.classify_unit(f2) == "unlogged"
f3, _ = u.overlap_fraction(10.0, 110.0, w)                          # 90 % overlap
assert abs(f3 - 0.90) < 1e-9 and u.classify_unit(f3) == "matched"
assert u.classify_unit(u.overlap_fraction(11.0, 111.0, w)[0]) == "boundary"
assert u.overlap_fraction(200.0, 300.0, w) == (0.0, [])
f4, _ = u.overlap_fraction(0.0, 100.0, [(0.0, 60.0), (40.0, 100.0)])   # overlapping windows are not double counted
assert abs(f4 - 1.0) < 1e-9

# TV distance, terciles, calendar classes
assert abs(u.tv_distance([0.5, 0.5, 0.0], [0.0, 0.5, 0.5]) - 0.5) < 1e-9 and u.tv_distance([1, 0, 0], [1, 0, 0]) == 0
cuts = u.tercile_cuts(np.arange(1, 91))
assert u.length_tercile(5, cuts) == 0 and u.length_tercile(45, cuts) == 1 and u.length_tercile(80, cuts) == 2
import calendar, datetime
sat = datetime.datetime(2026, 11, 21, 12, 0, tzinfo=u.mc.KYIV).timestamp()
mon = datetime.datetime(2026, 11, 23, 23, 0, tzinfo=u.mc.KYIV).timestamp()
assert u.day_type(sat) == "weekend" and u.day_type(mon) == "weekday" and u.hour_class(mon) == "night" and u.hour_class(sat) == "day"

# within-day permutation: labels shuffled inside each day keep each day's counts; a planted group difference gives a small p, none a large p
rng = np.random.default_rng(1)
days = np.repeat(np.arange(30), 6)
lab = np.tile([0, 0, 0, 1, 1, 1], 30)
vals_diff = rng.normal(0, 1, 180) + 3.0 * lab
vals_null = rng.normal(0, 1, 180)
stat = lambda vs, lb: abs(vs[lb == 1].mean() - vs[lb == 0].mean())
obs, p_diff = u.within_day_permutation_p(vals_diff, lab, days, stat, 300)
_, p_null = u.within_day_permutation_p(vals_null, lab, days, stat, 300)
assert p_diff < 0.01 and p_null > 0.05

# day-clustered bootstrap: seeded and reproducible; contains the planted mean
x = rng.normal(10, 1, 120)
g = [np.arange(i * 10, (i + 1) * 10) for i in range(12)]
c1, c2 = u.boot_days(g, lambda ix: float(x[ix].mean()), 400), u.boot_days(g, lambda ix: float(x[ix].mean()), 400)
assert c1 == c2 and c1[0] < x.mean() < c1[1] and u.boot_days(g[:1], lambda ix: 0.0, 10) == [None, None]

# km decomposition is disjoint and exhaustive; an overshoot is flagged
d = u.decompose_km(100.0, {"matched_units": 70.0, "unlogged_units": 20.0, "boundary_units": 5.0})
assert abs(d["remainder"] - 5.0) < 1e-9 and d["partition_exhaustive"] and d["remainder_nonnegative"]
assert u.decompose_km(100.0, {"a": 90.0, "b": 20.0})["remainder_nonnegative"] is False
print("test_mynissan_unlogged: OK")
