"""M475 (spec analyses/M475_spec.md, check E1) exactness of the piecewise integration in tools/regen_v2.py: closed-form cases (constant I and V; I crossing zero; V linear; offset charge), the telescoping KE loss
v0^2 - v1^2 over the pieces, the speed-bin assignment at edge crossings and on a plateau at an edge, the touch rule (half a former slice), and agreement with a very fine reference quadrature on random channels."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import regen_v2 as R

K = 1.0 / 1000.0 / 3600.0            # A V s -> kWh
trapz = getattr(np, "trapezoid", None) or np.trapz


def run(t0, dt, v0, v1, it, iv, vt, vv, off=None):
    return R._exact_energy(np.array(t0, float), np.array(dt, float), np.array(v0, float), np.array(v1, float), np.array(it, float), np.array(iv, float), np.array(vt, float), np.array(vv, float), off)


# constant I = 10 A, V = 300 V over 2 s, speed constant 25 km/h (bin 2): 6000 A V s
S = run([0.0], [2.0], [25.0], [25.0], [-1.0, 3.0], [10.0, 10.0], [-1.0, 3.0], [300.0, 300.0])
assert abs(S["ch"].sum() - 6000 * K) < 1e-15 and S["bin"].tolist() == [2] and abs(S["dv2"].sum()) < 1e-12 and S["owner"].tolist() == [0]
# I falls 10 -> -10 linearly over [0, 2]: positive on [0, 1): integral 300 * (10 - 5) = 1500
S = run([0.0], [2.0], [25.0], [25.0], [0.0, 2.0], [10.0, -10.0], [0.0, 2.0], [300.0, 300.0])
assert abs(S["ch"].sum() - 1500 * K) < 1e-14
# negative everywhere -> 0; I rising -10 -> 10: the mirror image
assert run([0.0], [2.0], [25.0], [25.0], [0.0, 2.0], [-5.0, -1.0], [0.0, 2.0], [300.0, 300.0])["ch"].sum() == 0.0
assert abs(run([0.0], [2.0], [25.0], [25.0], [0.0, 2.0], [-10.0, 10.0], [0.0, 2.0], [300.0, 300.0])["ch"].sum() - 1500 * K) < 1e-14
# V linear 300 -> 340, I constant 10 over 2 s: 10 * (300 + 340) / 2 * 2 = 6400
assert abs(run([0.0], [2.0], [25.0], [25.0], [0.0, 2.0], [10.0, 10.0], [0.0, 2.0], [300.0, 340.0])["ch"].sum() - 6400 * K) < 1e-14
# offset charge: I = 2 -> -6 (zero at 0.5 of the piece) with off = +2 -> I+off = 4 -> -4 (zero at the middle): exact positive parts
S = run([0.0], [2.0], [25.0], [25.0], [0.0, 2.0], [2.0, -6.0], [0.0, 2.0], [300.0, 300.0], off=2.0)
pos = lambda a, b, h: 0.0 if a <= 0 and b <= 0 else (a + b) / 2 * h if a >= 0 and b >= 0 else (a * a / (a - b) * h / 2 if a > 0 else b * b / (b - a) * h / 2)
assert abs(S["ch"].sum() - 300 * pos(2.0, -6.0, 2.0) * K) < 1e-14 and abs(S["cho"].sum() - 300 * pos(4.0, -4.0, 2.0) * K) < 1e-14

# speed 38 -> 12 km/h over 2 s crosses 30, 20: three pieces in bins 3, 2, 1; KE telescopes
S = run([0.0], [2.0], [38.0], [12.0], [-1.0, 3.0], [5.0, 5.0], [-1.0, 3.0], [300.0, 300.0])
assert sorted(S["bin"].tolist()) == [1, 2, 3] and abs(S["dv2"].sum() - (38.0 ** 2 - 12.0 ** 2)) < 1e-9 and abs(S["ch"].sum() - 5 * 300 * 2 * K) < 1e-14
# durations follow the linear speed: 8/26, 10/26, 8/26 of 2 s
assert abs(S["dv2"][S["bin"] == 2].sum() - (30.0 ** 2 - 20.0 ** 2)) < 1e-9
# plateau exactly on an edge: bin 2 (floor(20/10)); decel ending exactly at an edge adds no zero-length piece
S = run([0.0], [1.0], [20.0], [20.0], [-1.0, 3.0], [1.0, 1.0], [-1.0, 3.0], [300.0, 300.0])
assert S["bin"].tolist() == [2] and S["owner"].shape == (1,)
S = run([0.0], [1.0], [30.0], [20.0], [-1.0, 3.0], [1.0, 1.0], [-1.0, 3.0], [300.0, 300.0])
assert S["bin"].tolist() == [2] and abs(S["dv2"].sum() - (900 - 400)) < 1e-9
# overflow bin (>= 130 km/h) and edges above it
S = run([0.0], [2.0], [150.0], [120.0], [-1.0, 3.0], [1.0, 1.0], [-1.0, 3.0], [300.0, 300.0])
assert sorted(S["bin"].tolist()) == [12, 13] and abs(S["dv2"].sum() - (150.0 ** 2 - 120.0 ** 2)) < 1e-6
# touch rule: a crossing 0.01 s before the end leaves a 0.01 s piece: not touched (< 0.025 s); a 0.03 s piece is touched
S = run([0.0], [1.0], [30.0], [19.7], [-1.0, 3.0], [1.0, 1.0], [-1.0, 3.0], [300.0, 300.0])      # crossing 20 at t = 10/10.3 = 0.9709: the bin 1 piece is 0.0291 s
assert sorted(S["bin"].tolist()) == [1, 2] and R.touch_flags(S["owner"] * R.NB + S["bin"], S["piece_h"], R.NB)[1] == 1      # M490: total-overlap rule
S = run([0.0], [1.0], [30.0], [19.8], [-1.0, 3.0], [1.0, 1.0], [-1.0, 3.0], [300.0, 300.0])      # the bin 1 piece is 0.0196 s
assert R.touch_flags(S["owner"] * R.NB + S["bin"], S["piece_h"], R.NB)[1] == 0

# random channels: exact vs a very fine trapezoid reference (second order), per interval and total
rng = np.random.default_rng(11)
t = np.cumsum(rng.uniform(0.1, 1.5, 40)); I = rng.normal(0, 40, 40); V = rng.uniform(280, 380, 40) * 1.0
vt = np.cumsum(rng.uniform(0.2, 1.7, 30)); VV = rng.uniform(280, 380, 30)
t0 = np.array([t[3] + 0.05, t[10] + 0.2, t[20] + 0.01]); dt = np.array([2.2, 3.9, 1.3]); v0 = np.array([55.0, 33.0, 12.0]); v1 = np.array([5.0, 31.0, 0.0])
t0 = np.maximum(t0, max(t[0], vt[0]) + 0.01); ok = (t0 + dt < min(t[-1], vt[-1]))
t0, dt, v0, v1 = t0[ok], dt[ok], v0[ok], v1[ok]
S = run(t0, dt, v0, v1, t, I, vt, VV, off=-0.4)
ref_ch, ref_cho = np.zeros(t0.size), np.zeros(t0.size)
for k in range(t0.size):
    g = np.linspace(t0[k], t0[k] + dt[k], 2_000_001)
    P = np.interp(g, t, I) * np.interp(g, vt, VV); Po = (np.interp(g, t, I) - 0.4) * np.interp(g, vt, VV)
    ref_ch[k] = trapz(np.maximum(P, 0), g) * K; ref_cho[k] = trapz(np.maximum(Po, 0), g) * K
ex = np.bincount(S["owner"], weights=S["ch"], minlength=t0.size); exo = np.bincount(S["owner"], weights=S["cho"], minlength=t0.size)
assert np.max(np.abs(ex - ref_ch) / np.maximum(ref_ch, 1e-12)) < 1e-6 and np.max(np.abs(exo - ref_cho) / np.maximum(ref_cho, 1e-12)) < 1e-6, (ex, ref_ch)
assert np.allclose(np.bincount(S["owner"], weights=S["dv2"], minlength=t0.size), v0 ** 2 - v1 ** 2, atol=1e-9)
print("OK test_regen_exact_integral (%d random intervals, %d pieces)" % (t0.size, S["owner"].size))
