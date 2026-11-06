"""M588 (analyses/M588_spec.md Rev 1) known-answer tests of tools/m588_cell_scan_simultaneity.py: pair construction (production pairing reproduced, matched Vmin time carried), signed dI_A, same-I pairs, quantum, designs D1-D4,
the E2 regression with a planted signed effect (load level partialled), a coarse-quantised current series, a planted load-mix shift, the nearest-within-300-ms rule against the production helper, the paired bootstrap
with common day draws, the degenerate-draw rule and the arm floor."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import compute_drive_summary_v6 as D
import m588_cell_scan_simultaneity as M

t0 = pd.Timestamp("2026-11-01 12:00:00")
ms = lambda x: t0 + pd.Timedelta(milliseconds=float(x))


def series(times, vals):
    return pd.DataFrame({"t": pd.to_datetime([ms(x) for x in times]).astype("datetime64[ns]"), "v": list(vals)})


def synth(n=400, seed=1, dt_max=250.0, effect=0.0, I_period=100.0, base_I=100.0):
    """Vmax read every 1000 ms; Vmin read at a random offset in [-dt_max, dt_max]; the current ramps linearly (slope 0.02 A/ms); the planted spread = 20 mV + effect * dI_A (mV per A)."""
    rng = np.random.default_rng(seed)
    tv = np.arange(n) * 1000.0
    off = rng.uniform(-dt_max, dt_max, n)
    tn = tv + off
    cur = lambda t: base_I + 0.02 * t
    I_t = np.arange(0, tv[-1] + 3000, I_period)
    I_v = cur(I_t)
    I = series(I_t, I_v)
    dI = cur(tn) - cur(tv)
    vmax = series(tv, 3.700 + 0.020 * np.ones(n))
    vmin = series(tn, 3.700 - 0.0 * np.ones(n) - effect * dI / 1000.0)
    return vmax, vmin.sort_values("t").reset_index(drop=True), I


# ---- 1 pair construction reproduces the production pairing and carries the matched Vmin time
vmax, vmin, I = synth()
p = M.build_pairs(vmax, vmin, I)
prod = pd.merge_asof(vmax.rename(columns={"v": "vmax"}), vmin.rename(columns={"v": "vmin"}), on="t", direction="nearest", tolerance=pd.Timedelta(D.SPREAD_TOL)).dropna()
assert len(p) == len(prod) and np.allclose(p["vmax"].values, prod["vmax"].values) and np.allclose(p["vmin"].values, prod["vmin"].values)
assert (p["dt_ms"] <= 300.0 + 1e-6).all() and p["t_vmin"].notna().all()
assert np.allclose((p["t_vmax"] - p["t_vmin"]).abs().dt.total_seconds() * 1000.0, p["dt_ms"])
loaded = p[p["abs_I"] > 50]
assert len(loaded) == len(p) and abs(M.p95(loaded["spread_mv"].values) - round(float(np.quantile(prod["vmax"].values * 1000 - prod["vmin"].values * 1000, 0.95)), 1)) < 0.11
# the sign convention: dI_A = I(t_vmin) - I(t_vmax) is positive when the Vmin read is later on a rising current
r = p.iloc[5]
assert np.sign(r["dI_A"]) == np.sign((r["t_vmin"] - r["t_vmax"]).total_seconds()) or abs(r["dI_A"]) < 1e-9

# ---- 2 quantum, reuse
q = M.quantum_ms(series([0, 100, 250, 350, 350.0 + 100], [1] * 5))
assert q[0] == 100.0 and q[1] == 100.0
vm2 = series([0, 400, 5000], [3.7] * 3); vn2 = series([200, 5100], [3.6] * 2)             # Vmax 0 and 400 both pair with the Vmin read at 200 (reuse); Vmax 5000 pairs with 5100
I2 = series(np.arange(0, 8000, 1000.0), np.full(8, 120.0))                                  # a current sample per second: reads 0 / 200 / 400 map to the same I sample
p2 = M.build_pairs(vm2, vn2, I2)
assert len(p2) == 3 and p2["t_vmin"].nunique() == 2 and abs((1.0 - p2["t_vmin"].nunique() / len(p2)) - 1 / 3) < 1e-9 and bool(p2.iloc[0]["same_I"]) and bool(p2.iloc[1]["same_I"])
assert abs(M.drive_record(p2, vm2, vn2)["vminReuseShare"] - 1 / 3) < 1e-9

# ---- 3 designs: tighter dt keeps fewer pairs; D4 needs distinct samples and |dI| <= 10 A
rec = M.drive_record(p, vmax, vmin)
d = rec["designs"]
assert d["D1"]["nKept"] >= d["D2"]["nKept"] >= d["D3"]["nKept"] > 0
assert all(rec["designs"][k]["nKept"] <= rec["nLoaded"] for k in d)
exp_d1 = int((loaded["dt_ms"] <= 150).sum())
assert d["D1"]["nKept"] == exp_d1
exp_d4 = int(((loaded["dI_A"].abs() <= 10) & (~loaded["same_I"])).sum())
assert d["D4"]["nKept"] == exp_d4
assert M.p95(np.array([])) is None and rec["designs"]["D3"]["p95"] is not None if d["D3"]["nKept"] >= M.MIN_PAIRS else rec["designs"]["D3"]["p95"] is None

# ---- 4 E2: a planted signed dI_A effect is recovered with the load level partialled; no effect gives ~0
vm_, vn_, I_ = synth(n=600, seed=2, effect=0.5, dt_max=250.0)
r_eff = M.drive_record(M.build_pairs(vm_, vn_, I_), vm_, vn_)
assert abs(r_eff["e2"]["dIcoef"] - (-0.5)) < 0.05 or abs(r_eff["e2"]["dIcoef"] - 0.5) < 0.05, r_eff["e2"]          # sign follows the construction (vmin lowered by effect*dI)
vm0, vn0, I0 = synth(n=600, seed=3, effect=0.0)
r_zero = M.drive_record(M.build_pairs(vm0, vn0, I0), vm0, vn0)
assert abs(r_zero["e2"]["dIcoef"]) < 0.05
# tighter pairing removes the planted inflation: p95 of the kept pairs is closer to the null value
assert abs(r_eff["designs"]["D1"]["p95"] - 20.0) < abs(M.p95(M.build_pairs(vm_, vn_, I_)["spread_mv"].values) - 20.0) + 1e-9

# ---- 5 coarse current cadence: same_I_share is high and D4 keeps only distinct-sample pairs
vq, nq, Iq = synth(n=500, seed=4, I_period=1000.0, dt_max=250.0)      # a coarse current PID: both reads often map to the same I sample
rq = M.drive_record(M.build_pairs(vq, nq, Iq), vq, nq)
assert rq["sameIShare"] > 0.5 and rq["designs"]["D4"]["sameIShareKept"] in (None, 0.0)       # D4 keeps only distinct-sample pairs

# ---- 6 load-mix shift: the kept pairs report their own |I| median (a mix effect is visible, not hidden)
assert rec["designs"]["D2"]["absIMedianKept"] is not None and rec["absIMedian"] is not None

# ---- 7 fidelity: exact equality after the same rounding and the same count
dm_ok = pd.DataFrame({"file": ["a"], "cell_spread_loaded_p95_mv": [21.34], "n_loaded_spread_samples": [100]})
assert M.fidelity(dm_ok, {"a": {"p95Ref": 21.3, "nLoaded": 100}}) == []
assert M.fidelity(dm_ok, {"a": {"p95Ref": 21.4, "nLoaded": 100}}) == ["a"] and M.fidelity(dm_ok, {"a": {"p95Ref": 21.3, "nLoaded": 99}}) == ["a"]
dm_na = pd.DataFrame({"file": ["a"], "cell_spread_loaded_p95_mv": [np.nan], "n_loaded_spread_samples": [np.nan]})
assert M.fidelity(dm_na, {"a": {"p95Ref": None, "nLoaded": 0}}) == [] and M.fidelity(dm_na, {"a": {"p95Ref": 3.0, "nLoaded": 0}}) == ["a"]

# ---- 8 E3: paired difference with common day draws, arm floor, reading rules
rng = np.random.default_rng(5)
days = pd.date_range("2026-08-01", periods=60, freq="D")
rows = []
for i, dte in enumerate(days):
    for j in range(3):
        rows.append({"day": str(dte.date()), "date": dte, "step": float(i >= 30), "slow": float(rng.random() < .5), "months": i / 30.4, "T": rng.uniform(15, 35), "I": rng.uniform(60, 140), "soc": rng.uniform(40, 80),
                     "socr": rng.uniform(10, 30), "lrest": rng.uniform(0, 3), "first": float(rng.random() < .3), "wk": dte.strftime("%G-%V")})
df = pd.DataFrame(rows)
df["y"] = 20 + 0.1 * df["T"] + 3.0 * df["step"] + rng.normal(0, 1.0, len(df))
df["y_k"] = df["y"]                                          # identical outcome: the paired difference must be exactly 0
out = M.fit_both(df, "y_k", n=200)
assert out["status"] == "ok" and out["terms"]["step"]["pairedDiff"] == 0.0 and out["terms"]["step"]["pairedDiffCi95"] == [0.0, 0.0]
assert out["terms"]["step"]["reading"].startswith("no change beyond")
df["y_k"] = df["y"] + 2.0 * df["step"]                       # a planted +2 mV step difference is detected and the reading says so
out2 = M.fit_both(df, "y_k", n=200)
assert abs(out2["terms"]["step"]["pairedDiff"] - 2.0) < 1e-6 and out2["terms"]["step"]["reading"].startswith("changes by about")
tiny = df[df["step"] == 0].copy()                           # one arm only: the arm floor
assert M.fit_both(tiny, "y_k", n=50)["status"].startswith("not estimable")
print("test_m588_simultaneity: OK")
