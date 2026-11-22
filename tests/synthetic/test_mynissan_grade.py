"""M736 stage G0 known-answer tests (analyses/M736_spec.md Rev 2): along-track distance, planted grade, altitude runs and 500 m chunks,
repeat-traversal noise floor, planted position offset recovered through interpolation, day-clustered bootstrap, gate rule, optional-stage skip."""
import os, sys, tempfile
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_grade as g

# optional stage: no store -> skipped with exit 0
tmp = tempfile.mkdtemp()
assert g.main(["--store", os.path.join(tmp, "nostore"), "--out-dir", tmp]) == 0

# along-track distance: 0.01 degree of latitude is about 1111.95 m
d = g.cum_dist([50.0, 50.01], [30.0, 30.0])
assert abs(d[-1] - 1111.95) < 1.0

# planted 4 % grade over 1000 m recovered by the least-squares slope; noise-free
dist = np.arange(0, 1001, 10.0)
assert abs(g.ols_grade(dist, 100 + 0.04 * dist) - 4.0) < 1e-9
assert abs(g.ols_grade(dist, 100 - 0.025 * dist) + 2.5) < 1e-9
assert g.ols_grade([5.0], [1.0]) is None

# altitude runs break at gaps above 5 s
t = [0, 1, 2, 3, 10, 11, 12, 13, 14]
runs = g.altitude_runs(t, [True] * 9)
assert [r[0] for r in runs] == [0, 4] and [len(r) for r in runs] == [4, 5]
assert g.altitude_runs([0, 1, 2], [True, False, True]) == [[0, 2]]   # one missing sample (2 s) does not break the run

# chunks: a 1100 m run gives two full 500 m chunks and a 100 m remainder that does not qualify; a 450 m run gives one chunk
ch = g.chunk_run(np.arange(0, 1101, 10.0))
assert len(ch) == 2 and ch[0][0] == 0
assert len(g.chunk_run(np.arange(0, 451, 10.0))) == 1
assert g.chunk_run(np.arange(0, 391, 10.0)) == []                    # below 400 m: nothing
assert len(g.chunk_run(np.arange(0, 1401, 10.0))) == 3               # 500 + 500 + 400 qualifies (>= 400)

# noise floor: two traversals with independent noise sigma give floor sigma through SD(diff)/sqrt(2)
rng = np.random.default_rng(7)
a, b = rng.normal(0, 0.8, 4000), rng.normal(0, 0.8, 4000)
assert abs(g.noise_floor(a - b) - 0.8) < 0.04
assert g.noise_floor([1.0]) is None

# planted position offset: a track shifted by 0.001 degree of longitude at 50 N (about 71.5 m) is recovered through interpolation
tt = np.arange(0, 100, 1.0)
lat, lon = 50.0 + 0.0001 * tt, 30.0 + 0.0001 * tt
tq = np.array([10.5, 40.25, 80.0])
tr = g.interp_track(tq, tt, lat, lon)
assert np.allclose(tr[:, 0], 50.0 + 0.0001 * tq) and np.allclose(tr[:, 1], 30.0 + 0.0001 * tq)
err = g.hav_arr(50.0 + 0.0001 * tq, 30.0 + 0.0001 * tq + 0.001, tr[:, 0], tr[:, 1])
assert np.all(abs(err - 71.5) < 1.0)
# a hole larger than 5 s is not bridged
tr2 = g.interp_track(np.array([5.0]), np.array([0.0, 20.0]), np.array([50.0, 50.1]), np.array([30.0, 30.1]))
assert np.isnan(tr2).all()

# cells and heading
c = g.cell_set([50.0004, 50.0006, 50.0016], [30.0004, 30.0004, 30.0004])
assert len(c) == 2
hv = g.heading_vec(np.array([50.0, 50.01]), np.array([30.0, 30.0]))
assert hv[0] == 0 and hv[1] > 0

# track validity screen: a moving track passes (ratio about 1), a frozen GPS fix at 50 km/h fails (ratio 0), too little motion gives None
tt2 = np.arange(0, 100, 1.0)
v = 36.0                                                            # km/h = 10 m/s -> 1 km over 100 s
lat_m = 50.0 + (10.0 * tt2) / 111195.0
assert abs(g.path_ratio(tt2, lat_m, np.full(100, 30.0), np.full(100, v)) - 1.0) < 0.01
assert g.path_ratio(tt2, np.full(100, 50.0), np.full(100, 30.0), np.full(100, v)) == 0.0
assert g.path_ratio(tt2[:5], lat_m[:5], np.full(5, 30.0), np.full(5, v)) is None

# sparse speed rows (about 1 Hz among many position rows): NaN speed rows are skipped, not read as zero
sp_sparse = np.full(100, np.nan); sp_sparse[::2] = v
assert abs(g.path_ratio(tt2, lat_m, np.full(100, 30.0), sp_sparse) - 1.0) < 0.05

# local screen: the first 120 s moving, the next 120 s frozen at 36 km/h -> only the moving windows pass
t4 = np.arange(0, 240, 1.0)
lat4 = np.where(t4 < 120, 50.0 + 10.0 * t4 / 111195.0, 50.0 + 1200.0 / 111195.0)
ok4 = g.window_ok(t4, lat4, np.full(240, 30.0), np.full(240, 36.0))
assert ok4[:120].all() and not ok4[120:].any()

# speed class edges
assert g.speed_class(0) == "below30" and g.speed_class(30) == "30to80" and g.speed_class(80) == "above80"

# day-clustered bootstrap: seeded, reproducible, contains the median of a symmetric planted sample
vals = np.concatenate([rng.normal(50, 5, 40) for _ in range(12)])
days = np.repeat(np.arange(12), 40)
ci1, ci2 = g.boot_median(vals, days, 500), g.boot_median(vals, days, 500)
assert ci1 == ci2 and ci1[0] < np.median(vals) < ci1[1]
assert g.boot_median([1.0, 2.0], ["d", "d"], 100) == [None, None]       # one day: no interval

# gate: support floor 30 days, 100 unique km, 5 repeat pairs (spec R1/RC3)
assert g.g0_decision(40, 150.0, 8, 0.5)["proceed_to_downloads"] is True
r = g.g0_decision(29, 150.0, 8, 0.5)
assert r["proceed_to_downloads"] is False and "days" in r["reasons"][0]
assert g.g0_decision(40, 99.9, 8, None)["proceed_to_downloads"] is False
assert g.g0_decision(40, 150.0, 4, None)["proceed_to_downloads"] is False
print("test_mynissan_grade: OK")
