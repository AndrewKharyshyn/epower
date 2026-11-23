"""M747 known-answer tests (analyses/M747_spec.md Rev 2): the knot-override spec, the Monte-Carlo borderline rule, the verdict rule and a planted
pack-temperature main effect recovered under K0 / K2 / K5. No repository payload is read."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import m119v2_model as m
import m320_ladder as L
import m747_knot_sensitivity as K

rng = np.random.default_rng(11)


def frame(n, beta=0.0, a0=-4.0):
    d = pd.DataFrame({"soc": rng.uniform(40, 85, n), "speed": rng.uniform(0, 130, n), "tpack": rng.uniform(5, 45, n), "demand": rng.normal(0, 1, n),
                      "durationS": rng.uniform(1, 60, n)})
    eta = a0 + beta * (d["tpack"] - 25.0)
    d["y"] = (rng.uniform(size=n) < 1 - np.exp(-np.exp(eta))).astype(float)
    d["daynum"] = rng.integers(0, 120, n).astype(float)
    return d


# 1 K0 reproduces m.DesignSpec exactly (design matrix and knots)
d = frame(5000)
base = m.DesignSpec(["soc", "speed", "tpack", "demand", "logdur"], m.INTERACTIONS).fit(d)
mine = K.KnotSpec(K.SETS["K0"]).fit(d)
Xb, nb = base.transform(d); Xm, nm = mine.transform(d)
assert nb == nm and np.array_equal(Xb, Xm) and np.array_equal(base.knots["tpack"], mine.knots["tpack"]), "K0 must equal the published design"

# 2 fixed knots are given in C and mapped to z with the draw's own mean and sd; quantile sets re-learn
k2 = K.KnotSpec(K.SETS["K2"]).fit(d); mu, sd = k2.scale["tpack"]
assert np.allclose(mu + sd * k2.knots["tpack"], [12.5, 22.5, 32.5, 42.5]) and k2.knots_c() == [12.5, 22.5, 32.5, 42.5]
k1 = K.KnotSpec(K.SETS["K1"]).fit(d); assert len(k1.knots["tpack"]) == 5
k3 = K.KnotSpec(K.SETS["K3"]).fit(d); z = (d["tpack"] - k3.scale["tpack"][0]) / k3.scale["tpack"][1]
assert np.allclose(k3.knots["tpack"], np.quantile(z, [0.025, 0.34, 0.66, 0.975]))

# 3 linear set, hinge and calendar-day extras
k5 = K.KnotSpec(K.SETS["K5"]).fit(d); X5, n5 = k5.transform(d)
assert [x for x in n5 if x.startswith("tpack_") and "_x_" not in x] == ["tpack_0"] and k5.knots_c() is None
k4 = K.KnotSpec(K.SETS["K4"]).fit(d); X4, n4 = k4.transform(d)
h = np.maximum(0.0, 15.0 - d["tpack"].values)
assert n4[-1] == "hinge15" and np.allclose(X4[:, -1], h - h.mean()) and X4.shape[1] == Xm.shape[1] + 1
k6 = K.KnotSpec(K.SETS["K6"]).fit(d); X6, n6 = k6.transform(d)
assert n6[-1] == "daynum" and abs(X6[:, -1].mean()) < 1e-9
pred = d.drop(columns=["daynum"]).iloc[:3]
Xp, _ = k6.transform(pred)
assert np.all(Xp[:, -1] == 0.0), "a prediction frame without a date gets the centre (zero contribution)"

# 4 Monte-Carlo borderline rule (spec C2, M320 rule b) and status
x_hi = np.random.default_rng(1).normal(0.6, 0.02, 4000)          # lower bound far above delta
s = K.status_mc(0.6, x_hi, 0, 4000); assert s["status"] == "distinct" and not s["nearDeltaWithin3Se"]
x_lo = np.random.default_rng(2).normal(0.02, 0.01, 4000)         # far below delta
s = K.status_mc(0.02, x_lo, 0, 4000); assert s["status"] == "indistinct"
x_near = np.random.default_rng(3).normal(0.30, 0.04, 4000)      # the 2.5 % quantile sits near log(1.25) = 0.2231
s = K.status_mc(0.30, x_near, 0, 4000); assert s["nearDeltaWithin3Se"] and s["status"] == "borderline", s
s = K.status_mc(0.6, x_hi, 100, 4000); assert s["status"] == "inconclusive", "failed-draw rate above 1 %"
assert K.batch_se(np.random.default_rng(4).normal(0, 1, 4000), 2.5) > 0 and np.isnan(K.batch_se(np.zeros(200), 2.5))

# 5 verdict rule (all of K0-K4)
ok = {k: "distinct" for k in K.VERDICT_SETS}
assert K.verdict(ok) == "robustly distinct" and K.verdict({**ok, "K2": "borderline"}) == "knot-dependent"
assert K.verdict({k: "indistinct" for k in K.VERDICT_SETS}) == "robustly indistinct" and K.verdict({**ok, "K4": "indistinct"}) == "knot-dependent"
assert K.verdict({**ok, "K5": "indistinct"}) == "robustly distinct", "K5 and K6 never enter the verdict"

# 6 planted pack-temperature main effect: D between two levels is |beta| x (distance) under K0, K2 and K5; identical levels give 0
beta = 0.05
d = frame(60000, beta=beta)
cs, cv = L.cell_frame(m)
dem = [float(x) for x in np.round(np.nanpercentile(d["demand"], [25, 50, 90]), 2)]
levels = [12.5, 32.5]
for nm in ("K0", "K2", "K5"):
    spec = K.KnotSpec(K.SETS[nm]).fit(d); X, _ = spec.transform(d)
    res = m.fit_glm(X, d["y"].values)
    eta, nc = L.eta_block(m, spec, res.params, levels, dem, cs, cv)
    etas = eta[: nc * 2 * L.NC].reshape(nc, 2, L.NC)
    n = np.full(L.NC, 100.0)
    D = L.rms_contrast(etas[0, 0], etas[0, 1], n, n)
    assert abs(D - beta * 20.0) < 0.2, (nm, D)
    assert L.rms_contrast(etas[0, 0], etas[0, 0], n, n) == 0.0
print("test_m747_knot_sensitivity: OK")
