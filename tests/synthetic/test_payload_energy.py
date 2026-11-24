"""M769 known-answer tests (analyses/M769_spec.md Rev 2): tools/payload_energy.py recovers a planted payload slope inside its day-clustered interval with covariates and a planted confounder, computes the outcome-blind design MDE,
applies the pre-registered reading rule on the LOWER end of the elasticity bracket, builds the displaced-day placebo only from other days of the same class, thermal class and month with distances within 25 %, evaluates the kinematic
reference B1 on a planted speed trace with an analytic kinetic energy, stops on a foreign master and keeps per-drive rows, dates and coordinates out of a result. No real data is needed."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import payload_energy as PE
import odometer_jump_audit as J


def planted(n_days=120, per_day=4, slope=0.30, seed=5):
    """Fuel = 5 + slope * payload100 + 0.5 * confounder + noise; the confounder (ambient) also drives the payload (occupants travel in warm weather), so an unadjusted slope is biased."""
    r = np.random.default_rng(seed)
    rows = []
    for d in range(n_days):
        day = "2026-%02d-%02d" % (5 + d // 28, 1 + d % 28)
        amb = r.normal(15, 8)
        pay_day = np.clip(0.7 + 0.02 * amb + r.normal(0, 0.35), 0, 3)
        for k in range(per_day):
            cls = ["urban", "mixed", "mixed_highway", "highway"][(d + k) % 4]
            pay = max(0.0, pay_day + r.normal(0, 0.15))
            dist = r.uniform(6, 60)
            rows.append({"file": "f%d_%d.csv" % (d, k), "day": day, "month": day[:7], "cls": cls, "thermal": "warm" if amb > 12 else "cold", "payload100": pay, "payload_central": pay * 100, "payload_low": pay * 90, "payload_high": pay * 110,
                         "ambient": amb, "logdist": np.log(dist), "distance_km": dist, "speed_mean_moving": r.uniform(25, 80), "dsoc100": r.normal(0, 1), "first_of_day": float(k == 0),
                         "fuel_L_per_100km": 5 + slope * pay + 0.08 * amb + r.normal(0, 0.4), "has_pattern": "True", "ens_outlier_v2": "False"})
    d = pd.DataFrame(rows)
    d["v2"] = d["speed_mean_moving"] ** 2
    return d


d = planted()
est, ci, sd = PE.day_boot(d, "fuel_L_per_100km", PE.COVS, 400)
assert ci[0] < 0.30 < ci[1] and abs(est - 0.30) < 0.12, (est, ci)                 # the planted slope is recovered with the adjustment
# without the ambient covariate the confounded slope is biased upward (the adjustment is needed)
est_naive = PE.ols_slope(d, "fuel_L_per_100km", [c for c in PE.COVS if c != "ambient"])
assert est_naive > est + 0.05, (est_naive, est)
assert abs(PE.ols_slope(d, "fuel_L_per_100km", PE.COVS) - est) < 1e-12

# design MDE: payload SD, ICC by day and the expected MDE are positive and consistent; a larger sample lowers the MDE
dm = PE.design_mde(d)
assert dm["drives"] == len(d) and dm["days"] == d["day"].nunique() and dm["payload_sd_per100kg"] > 0 and 0 <= dm["payload_icc_by_day"] <= 1 and dm["expected_mde_per100kg"] > 0 and dm["n_eff"] <= dm["drives"]
dm2 = PE.design_mde(planted(n_days=240))
assert dm2["expected_mde_per100kg"] < dm["expected_mde_per100kg"]

# reading rule on the LOWER end of the pre-registered bracket 0.2 to 0.6
ex = PE.expectation_per100kg(5.0)
assert abs(ex["low"] - 0.2 * (100 / 1900.0) * 5.0) < 1e-12 and abs(ex["high"] - 0.6 * (100 / 1900.0) * 5.0) < 1e-12 and ex["low"] < ex["high"]
assert PE.reading(0.5 * ex["low"], ex["low"]) == "informative" and PE.reading(0.51 * ex["low"], ex["low"]) == "not informative at this support"

# displaced-day placebo: donors come from another day in the same class, thermal class and month and a distance within 25 %
pl = PE.displaced_payload(d, np.random.default_rng(1))
assert len(pl) > 0.8 * len(d)
src = d.set_index("file")
assert (pl["payload100"].values != d.set_index("file").loc[pl["file"], "payload100"].values).mean() > 0.9           # the payload is replaced
pr = PE.placebo(d, "fuel_L_per_100km", PE.COVS, 400, est)
assert pr["ratio_to_primary"] is not None and pr["ratio_to_primary"] < 0.5 and not pr["interval_excludes_zero"], pr         # the placebo carries no planted signal
assert PE.within_day_variation(d) > 0.9

# kinematic reference B1 on an analytic trace: 0 -> 10 m/s in 10 s then constant (100 m + 10 m/s x 10 s): KE per kg = 0.5 v^2 = 50 J/kg; the distance is the trapezoid
t = np.arange(0, 21, 1.0)
v = np.where(t <= 10, t, 10.0)
dt = np.ones(len(t))
ke, dist = PE.kinematic_reference(v, dt)
assert abs(ke - 50.0) < 1e-9 and abs(dist - (50.0 + 100.0 + 0.0)) < 1e-9 + 5.0, (ke, dist)
w = PE.b1_payload_energy(ke, dist, 100.0, 0.010)
assert abs(w - 100.0 * (ke + 0.010 * PE.G_ACC * dist) / 3.6e6 * (100000.0 / dist)) < 1e-12
assert PE.b1_payload_energy(ke, dist, 200.0, 0.010) == 2 * w                                                         # exactly proportional to the payload
assert np.isnan(PE.b1_payload_energy(0.0, 0.0, 100.0, 0.01))

# a result without per-drive rows, dates or coordinates passes the privacy scan; a planted date or drive name does not
assert J.scan_privacy({"A1": {"drives": 400, "days": 120, "slope_per100kg_payload": 0.2}, "C": {"class_counts": {"urban": 10}}}) == []
assert J.scan_privacy({"f": "2026-10-17_23-13-01.csv"}) and J.scan_privacy({"2026-10-17": 3})

# master pin: a foreign master stops (exit 1) and nothing is written
import tempfile, shutil
td = tempfile.mkdtemp()
try:
    with open(os.path.join(td, "m.csv"), "w", encoding="utf-8") as f:
        f.write("file\nx.csv\n")
    out = os.path.join(td, "out")
    rc = PE.main(["--run", "--master", os.path.join(td, "m.csv"), "--out-dir", out])
    assert rc == 1 and not os.path.exists(out)
finally:
    shutil.rmtree(td, ignore_errors=True)
assert PE.ELASTICITY == (0.2, 0.6) and PE.C_RR == (0.008, 0.010, 0.012) and PE.DIST_MIN == 5.0 and PE.SEED == 42
print("test_payload_energy: OK")
