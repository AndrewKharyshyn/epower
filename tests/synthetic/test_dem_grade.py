"""M757 known-answer tests (analyses/M757_spec.md Rev 2): GeoTIFF reader and bilinear height on planted tiles (plane, sine hill, point and area rasters, a tile boundary), path-independent height difference,
step-grade recovery, planted energy-balance coefficients (b 1.0 and 0.5, road-load terms, duration term), null, displaced-DEM placebo, sign split, errors-in-variables attenuation, day-blocked cross-validation,
F1 statistics, decision rules R2/R3/R4, displaced-fix geometry, and the optional-stage exit codes (skip 0, sha256 mismatch 3)."""
import json, os, sys, tempfile
import numpy as np
import pandas as pd
from PIL import Image, TiffImagePlugin

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import dem_step_grade as D

N_PX = 60                                   # pixels per degree of the planted tiles (the reader takes the size from the file)


def write_tile(path, N, E, fn, rtype="point"):
    """One-degree float32 GeoTIFF; fn(lat, lon) gives the height at each node (point raster) or pixel centre (area raster)."""
    i, j = np.meshgrid(np.arange(N_PX), np.arange(N_PX), indexing="ij")
    sh = 0.5 if rtype == "area" else 0.0
    lat = (N + 1) - (i + sh) / N_PX
    lon = E + (j + sh) / N_PX
    arr = fn(lat, lon).astype(np.float32)
    ifd = TiffImagePlugin.ImageFileDirectory_v2()
    s = 1.0 / N_PX
    ifd[33550] = (s, s, 0.0); ifd.tagtype[33550] = 12
    ifd[33922] = (0.0, 0.0, 0.0, float(E), float(N + 1), 0.0); ifd.tagtype[33922] = 12
    ifd[34735] = (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 2 if rtype == "point" else 1, 2048, 0, 1, 4326); ifd.tagtype[34735] = 3
    ifd[42113] = "-9999"; ifd.tagtype[42113] = 2
    Image.fromarray(arr, mode="F").save(path, tiffinfo=ifd)


plane = lambda lat, lon: 1000.0 * (lat - 49.0) + 500.0 * (lon - 30.0) + 100.0
hill = lambda lat, lon: 20.0 * np.sin(2 * np.pi * (lat - 49.0) / 0.5) * np.cos(2 * np.pi * (lon - 30.0) / 0.5)

tmp = tempfile.mkdtemp()
for rt in ("point", "area"):
    d = os.path.join(tmp, rt)
    os.makedirs(d)
    for E in (30, 31):
        write_tile(os.path.join(d, "N49E%03d_FABDEM_V1-2.tif" % E), 49, E, plane, rt)
    dem = D.Dem(d)
    rng = np.random.default_rng(3)
    la, lo = rng.uniform(49.05, 49.95, 200), rng.uniform(30.05, 31.9, 200)             # includes points on both sides of the lon 31.0 tile boundary
    assert np.nanmax(np.abs(dem.height(la, lo) - plane(la, lo))) < 1e-3, rt
    assert dem.rtype == rt
# exactly on a tile boundary (lon 31.0 is node 0 of the east tile; lon 30.99 interpolates across both tiles)
dem = D.Dem(os.path.join(tmp, "point"))
assert abs(dem.height([49.5], [30.9999])[0] - plane(49.5, 30.9999)) < 1e-3
# outside the tiles and nodata give NaN
assert np.isnan(dem.height([52.0], [35.0])[0])
# sine hill: bilinear error stays small at 1/60 degree spacing
d = os.path.join(tmp, "hill"); os.makedirs(d)
write_tile(os.path.join(d, "N49E030_FABDEM_V1-2.tif"), 49, 30, hill)
dh_ = D.Dem(d)
la, lo = rng.uniform(49.05, 49.95, 300), rng.uniform(30.05, 30.95, 300)
assert np.nanmax(np.abs(dh_.height(la, lo) - hill(la, lo))) < 0.25
# height DIFFERENCE is path independent: via a detour point it telescopes to the direct difference
p1, p2, pm = (49.30, 30.20), (49.62, 30.71), (49.9, 30.1)
H = lambda p: dem.height([p[0]], [p[1]])[0]
assert abs((H(p2) - H(p1)) - ((H(pm) - H(p1)) + (H(p2) - H(pm)))) < 1e-9

# step grade recovery on the planted plane: driving north at 20 m/s, fixes 30 s apart, 600 m steps; analytic grade 100 * 1000 m/deg * (600 m / 111195 m/deg) / 600 m
t = np.arange(0.0, 900.0, 1.0)
obd = {"t": t, "v": np.full(len(t), 20.0), "dt": np.ones(len(t)), "P": np.full(len(t), 10.0)}
ft = np.arange(60.0, 800.0, 30.0)
flat = 49.1 + (ft - 60.0) * 20.0 / 111194.9
flon = np.full(len(ft), 30.4)
rows, drop = D.build_steps(obd, ft, flat, flon, D.Dem(os.path.join(tmp, "point")), shift=0.0)          # 600 m steps are inside 300 to 900 m
assert len(rows) == len(ft) - 1 and abs(rows[0]["d_m"] - 600.0) < 1e-6
short, dshort = D.build_steps(obd, np.arange(60.0, 400.0, 10.0), 49.1 + np.arange(60.0, 400.0, 10.0) * 20.0 / 111194.9, np.full(34, 30.4), D.Dem(os.path.join(tmp, "point")), shift=0.0)
assert short == [] and dshort["short"] == 33                                                       # 200 m steps are below 300 m: dropped and counted
ftl = np.arange(60.0, 800.0, 40.0)                                                  # 800 m steps
flat_l = 49.1 + (ftl - 60.0) * 20.0 / 111194.9
rows, drop = D.build_steps(obd, ftl, flat_l, np.full(len(ftl), 30.4), D.Dem(os.path.join(tmp, "point")), shift=0.0)
assert len(rows) == len(ftl) - 1 and abs(rows[0]["d_m"] - 800.0) < 1e-6
g = [100.0 * r["dh"] / r["d_m"] for r in rows]
assert abs(np.mean(g) - 100.0 * 1000.0 / 111194.9) < 0.1 and max(g) - min(g) < 0.1, (np.mean(g), 100.0 * 1000.0 / 111194.9)
assert rows[0]["first"] and rows[-1]["last"] and not rows[1]["first"]
assert abs(rows[0]["E_kJ"] - 10.0 * 40.0) < 1e-6                                    # 10 kW over 40 s
# a gap above 120 s and a short step are dropped and counted
rows, drop = D.build_steps(obd, np.array([60.0, 300.0]), np.array([49.1, 49.2]), np.array([30.4, 30.4]), D.Dem(os.path.join(tmp, "point")), shift=0.0)
assert rows == [] and drop["gap"] == 1
# the window follows the shift: a shift of +16 s moves the OBD window, the fixes (hence dh) stay
r0, _ = D.build_steps(obd, ftl, flat_l, np.full(len(ftl), 30.4), D.Dem(os.path.join(tmp, "point")), shift=0.0)
r16, _ = D.build_steps(obd, ftl, flat_l, np.full(len(ftl), 30.4), D.Dem(os.path.join(tmp, "point")), shift=16.0)
assert abs(r0[3]["dh"] - r16[3]["dh"]) < 1e-9

# displaced fixes: perpendicular to the heading, 2000 m away
la1, lo1, la2, lo2 = D.displace(49.10, 30.40, 49.11, 30.40, 2000.0, 1.0)
assert abs(la1 - 49.10) < 1e-9 and abs((lo1 - 30.40) * 111320.0 * np.cos(np.radians(49.105)) + 2000.0) < 1.0     # northbound heading: left is west
assert np.isnan(D.displace(49.1, 30.4, 49.1, 30.4, 2000.0)[0])

# altitude smoothing
ta = np.arange(0.0, 100.0)
assert abs(D.alt_at(ta, 100.0 + 0.5 * ta, [50.0])[0] - 125.0) < 1e-9 and np.isnan(D.alt_at(ta[:1], np.array([1.0]), [0.0])[0])


# ---- energy balance on a synthetic drive set
def synth(nd=40, per=30, b=1.0, seed=1, b_neg=None, noise_dh=0.0, c_aux=0.5, noise_e=20.0):
    rng = np.random.default_rng(seed)
    n = nd * per
    d = rng.uniform(300.0, 900.0, n)
    v = rng.uniform(8.0, 30.0, n)
    T = d / v
    V2, V3 = v ** 2 * T, v ** 3 * T
    dh = rng.normal(0.0, 8.0, n)
    vs, ve = v + rng.normal(0, 1.0, n), v + rng.normal(0, 1.0, n)
    pe = D.MASS_KG * D.G * dh / 1000.0
    bb = np.where(pe < 0, b if b_neg is None else b_neg, b)
    kin = D.MASS_KG * (ve ** 2 - vs ** 2) / 2000.0
    E = 120.0 * d / 1000.0 + 0.0015 * V2 + 0.0004 * V3 + c_aux * T + kin + bb * pe + rng.normal(0, noise_e, n)
    day = np.repeat(["2026-09-%02d" % (1 + i % 28) if i < 28 else "2026-10-%02d" % (1 + i - 28) for i in range(nd)], per)
    dh_obs = dh + rng.normal(0, noise_dh, n) if noise_dh else dh
    pl = rng.normal(0.0, 8.0, n)
    return pd.DataFrame({"day": day, "drive": day, "d_m": d, "T_s": T, "V2": V2, "V3": V3, "vs": vs, "ve": ve, "E_kJ": E, "dh": dh_obs, "dh_pl": pl, "dh_pr": rng.normal(0, 8.0, n)})


NB = 400
for bt in (1.0, 0.5):
    df = synth(b=bt)
    r = D.fit_b(df, nb=NB)
    assert abs(r["b"] - bt) < 0.03 * bt + 0.01 and r["b_ci95"][0] <= bt <= r["b_ci95"][1], (bt, r["b"], r["b_ci95"])
    pl = D.fit_b(df, "dh_pl", nb=NB)
    assert pl["b_ci95"][0] <= 0.0 <= pl["b_ci95"][1], pl["b_ci95"]                                    # displaced-DEM placebo: interval contains zero although b = bt
    cv = D.cv_incremental(df, nb=NB)
    assert cv["partial_r2"] > 0.2 and cv["partial_r2_ci95"][0] > 0 and all(x > 0 for x in cv["b_fold"].values())
    assert 0.0 < cv["delta_r2"] <= cv["partial_r2"] + 1e-9 and cv["delta_r2_ci95"][0] > 0 and cv["posthoc_flat_road_load_null"]["delta_r2"] > 0     # delta R2 shares the held-out total variance, so it cannot exceed the partial ratio
# road-load and duration coefficients are recovered when the noise is small (with 20 kJ noise the four speed-shaped terms are collinear and only b is checked)
cf = D.fit_b(synth(b=1.0, seed=8, noise_e=0.01), nb=50)["coefficients"]
assert abs(cf["F0_kJ_per_km"] - 120.0) < 0.5 and abs(cf["c_kJ_per_s"] - 0.5) < 0.005 and abs(cf["F1_kJ_per_m2s"] - 0.0015) < 1e-5 and abs(cf["F2_kJ_per_m3s2"] - 0.0004) < 1e-6 and abs(cf["b"] - 1.0) < 1e-3, cf
null = synth(b=0.0, seed=2)
rn = D.fit_b(null, nb=NB)
assert abs(rn["b"]) < 0.02 and -0.02 < rn["b_ci95"][0] and rn["b_ci95"][1] < 0.02, rn                    # planted null: b is zero to within 0.02 (a 95 % interval excludes an exact zero in 1 of 20 seeds)
cvn = D.cv_incremental(null, nb=NB)
assert cvn["partial_r2"] < 0.01 and cvn["delta_r2"] < 0.01
# sign split recovers an asymmetric b
sp = D.fit_b(synth(b=1.0, b_neg=0.5, seed=4), nb=NB, split=True)
assert abs(sp["b_pos"] - 1.0) < 0.05 and abs(sp["b_neg"] - 0.5) < 0.05, sp
# flat-first road-load fit also recovers b
ff = D.fit_b(synth(b=1.0, seed=5), nb=NB, flat_first=True)
assert abs(ff["b"] - 1.0) < 0.1, ff
# errors in variables: dh noise with the same variance as dh halves b (attenuation 0.5)
at = D.fit_b(synth(b=1.0, seed=6, noise_dh=8.0), nb=NB)
assert 0.42 < at["b"] < 0.58, at["b"]
# day-clustered interval is wider than a step-level one would be: the bootstrap resamples whole days (weights sum to the number of days)
W = D.boot_weights(10, 50)
assert np.all(W.sum(axis=1) == 10)

# ---- F1 statistics
rng = np.random.default_rng(7)
a = rng.normal(0, 3, 400)
days = np.array(["d%02d" % (i % 12) for i in range(400)])
s1 = D.f1_stats(a + 0.3, a, days, nb=300)
assert abs(s1["bias_median_pp"] - 0.3) < 1e-9 and s1["lin_ccc"] > 0.95 and s1["pearson"] > 0.999 and s1["n_days"] == 12
assert abs(D.lin_ccc(a, a) - 1.0) < 1e-12 and abs(D.spearman(a, a) - 1.0) < 1e-12
assert D.r4_decision(s1, 8, 242.0).startswith("not testable")
assert D.r4_decision({"bias_median_pp": 0.1, "bias_median_pp_ci95": [-0.2, 0.4], "median_abs_diff_pp": 0.9}, 40, 150.0) == "accepted"
assert D.r4_decision({"bias_median_pp": 0.1, "bias_median_pp_ci95": [-1.5, 0.4], "median_abs_diff_pp": 0.9}, 40, 150.0) == "not accepted"

one = D.f1_stats(a[:20] + 0.3, a[:20], np.array(["d1"] * 20), nb=50)
assert one["interval"] == "no interval (1 day)" and abs(one["bias_median_pp"] - 0.3) < 1e-9
# ---- decision rules
sup_ok = {"days": 40, "unique_km": 300.0, "n_above2pp": 2000, "days_pos": 30, "days_neg": 30}
base = {"b": 0.6, "b_ci95": [0.4, 0.8], "mde_b": 0.1}
cvok = {"b_fold": {"a": 0.5, "b": 0.7}, "incremental_r2": 0.1, "incremental_r2_ci95": [0.05, 0.15]}
assert D.r2_decision(base, {"b_ci95": [-0.1, 0.1]}, cvok, sup_ok, 0.8, False)[0] == "informative at step scale"
assert D.r2_decision(base, {"b_ci95": [0.1, 0.3]}, cvok, sup_ok, 0.8, False)[0] == "inconclusive"                    # negative control failed: downgrade
assert D.r2_decision(base, {"b_ci95": [-0.1, 0.1]}, cvok, dict(sup_ok, days=8), 0.8, False)[0] == "not testable"
r_, why_ = D.r2_decision(base, {"b_ci95": [0.05, 0.12]}, cvok, dict(sup_ok, n_above2pp=278), 0.8, False)
assert r_ == "not testable" and any("negative control failed" in w for w in why_) and any("support" in w for w in why_)
assert D.r2_decision(base, {"b_ci95": [-0.1, 0.1]}, cvok, dict(sup_ok, days_neg=3), 0.8, False)[0] == "not testable"
nul = {"b": 0.02, "b_ci95": [-0.1, 0.15], "mde_b": 0.3}
assert D.r2_decision(nul, {"b_ci95": [-0.1, 0.1]}, cvok, sup_ok, None, False)[0].startswith("not informative")       # upper bound 0.15 < 0.2 (b_obd not testable)
assert D.r2_decision(nul, {"b_ci95": [-0.1, 0.1]}, cvok, sup_ok, 0.5, True)[0] == "inconclusive"                      # 0.15 is not below 0.25 * 0.5 = 0.125
assert D.r2_decision(nul, {"b_ci95": [-0.1, 0.1]}, cvok, sup_ok, 0.5, False)[0].startswith("not informative")          # b_obd untestable: threshold 0.2
assert D.r3_decision([0.9, 1.1], 8).startswith("not testable") and D.r3_decision([0.9, 1.1], 40) == "met" and D.r3_decision([0.6, 1.1], 40) == "not met"
assert list(D.grade_class(np.array([-5.0, -2.0, 0.0, 2.0, 5.0]))) == [0, 1, 2, 3, 4]

# ---- optional stage: skip without tiles, stop on a sha256 mismatch
empty = tempfile.mkdtemp()
assert D.main(["--dem-dir", empty, "--store", empty, "--raw-dir", empty, "--out-dir", empty]) == 0
store, raw, dd = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
open(os.path.join(store, "manifest.json"), "w", encoding="utf-8").write("{}")
open(os.path.join(dd, "N49E030_FABDEM_V1-2.tif"), "wb").write(b"not a tile")
json.dump({"source": "x", "tiles": {"N49E030": {"file": "N49E030_FABDEM_V1-2.tif", "sha256": "0" * 64}}}, open(os.path.join(dd, "fabdem_tiles_manifest.json"), "w", encoding="utf-8"))
assert D.main(["--dem-dir", dd, "--store", store, "--raw-dir", raw, "--out-dir", empty]) == 3
print("test_dem_grade: OK")
