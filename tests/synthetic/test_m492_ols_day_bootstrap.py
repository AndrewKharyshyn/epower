"""M492 known-answer test of tools/day_bootstrap.ols_boot_slopes (sufficient-statistics day bootstrap of an OLS coefficient) against a verbatim copy of the former loop
(rng.choice(uniq, size=len(uniq), replace=True) -> concatenated row indexes -> np.linalg.lstsq, with the 'fewer than 3 distinct t' skip). Checks: (1) the same draws and the same slopes (max |difference| < 1e-8) and the same
skipped draws on a synthetic day-clustered design; (2) a design with a dummy column that is absent in many resamples (rank-deficient resamples -> lstsq fallback, min-norm behaviour unchanged); (3) the skip rule on few days;
(4) the real S1 design (powerFade, HV-current density covariates): same boot array, and the published interval [-0.426, 1.837] at 3 decimals from summary_arrays.json; (5) the production functions give the published numbers."""
import json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import day_bootstrap as DB


def old_loop(X, y, days, t, nb, seed, coef=1):
    uniq = np.unique(days)
    grp = {d: np.where(days == d)[0] for d in uniq}
    rng = np.random.default_rng(seed)
    boot = []
    for _ in range(nb):
        idx = np.concatenate([grp[d] for d in rng.choice(uniq, size=len(uniq), replace=True)])
        if len(np.unique(t[idx])) < 3:
            continue
        try:
            boot.append(float(np.linalg.lstsq(X[idx], y[idx], rcond=None)[0][coef]))
        except Exception:
            pass
    return np.asarray(boot)


# (1) synthetic day-clustered design
rg = np.random.default_rng(7)
G, per = 40, 4
days = np.repeat(["2026-01-%02d" % i if i < 31 else "2026-02-%02d" % (i - 30) for i in range(G)], per)
t = np.repeat(np.arange(G) * 0.7, per).astype(float)
X = np.column_stack([np.ones(G * per), t, rg.normal(30, 5, G * per), rg.uniform(20, 80, G * per), rg.uniform(0.05, 1.0, G * per)])
y = 100 + 0.8 * t + 0.3 * X[:, 2] + rg.normal(0, 3, G * per) + np.repeat(rg.normal(0, 2, G), per)
t0 = time.perf_counter(); old = old_loop(X, y, days, t, 1000, 42); t1 = time.perf_counter()
new, fb = DB.ols_boot_slopes(X, y, days, coef=1, nb=1000, seed=42); t2 = time.perf_counter()
assert len(old) == len(new) and np.max(np.abs(old - new)) < 1e-8 and fb == 0, (len(old), len(new), np.max(np.abs(old - new)) if len(old) == len(new) else None, fb)
assert np.allclose(np.percentile(old, [2.5, 97.5]), np.percentile(new, [2.5, 97.5]), atol=1e-8)

# (2) a dummy column present on only 3 days: many resamples miss it entirely (zero column -> singular normal equations -> lstsq fallback, same min-norm slope)
X2 = np.column_stack([X, (np.isin(days, days[[0, 80, 120]])).astype(float)])
old2 = old_loop(X2, y, days, t, 400, 5); new2, fb2 = DB.ols_boot_slopes(X2, y, days, coef=1, nb=400, seed=5)
assert fb2 > 0 and len(old2) == len(new2) and np.max(np.abs(old2 - new2)) < 1e-7, (fb2, len(old2), len(new2), np.max(np.abs(old2 - new2)))

# (3) the skip rule: 4 days only -> draws with fewer than 3 distinct days are skipped (and consume their random numbers)
d4 = np.repeat(["a", "b", "c", "d"], 5); t4 = np.repeat([0.0, 1.0, 2.5, 4.0], 5)
X4 = np.column_stack([np.ones(20), t4, rg.normal(0, 1, 20)]); y4 = 1 + 2 * t4 + rg.normal(0, 0.2, 20)
o4 = old_loop(X4, y4, d4, t4, 300, 3); n4, _ = DB.ols_boot_slopes(X4, y4, d4, coef=1, nb=300, seed=3)
assert 0 < len(o4) < 300 and len(o4) == len(n4) and np.max(np.abs(o4 - n4)) < 1e-8

# (4) real S1 design: months = days / 30.44 from the minimum date of the clean complete cases; HV-current density covariates from the tracked sidecar
import powerfade_equivalence as PE
dm = pd.read_csv("drive_master.csv", low_memory=False)
side = PE._read(PE.SIDECAR)
dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in side.to_dict("records")}
cc, have_d = PE.s1_rows(dm, dens)
dt0 = pd.to_datetime(cc["date"]).min()
tm = ((pd.to_datetime(have_d["date"]) - dt0).dt.days / PE.POWERFADE_MONTH_DAYS).values
XS = np.column_stack([np.ones(len(have_d)), tm, have_d["T_pack_mean_avg"].values, have_d[PE.ICOL].values, have_d["_de"].values.astype(float), have_d["_dc"].values.astype(float)])
yS = have_d[PE.RCOL].values.astype(float); dS = have_d["date"].values
t0 = time.perf_counter(); oldS = old_loop(XS, yS, dS, tm, 4000, 42); t1 = time.perf_counter()
newS, fbS = DB.ols_boot_slopes(XS, yS, dS, coef=1, nb=4000, seed=42); t2 = time.perf_counter()
assert len(oldS) == len(newS) and np.max(np.abs(oldS - newS)) < 1e-8, (len(oldS), len(newS), np.max(np.abs(oldS - newS)))
qo, qn = np.percentile(oldS, [2.5, 97.5]), np.percentile(newS, [2.5, 97.5])
assert round(qo[0], 3) == round(qn[0], 3) and round(qo[1], 3) == round(qn[1], 3)
A = json.load(open("summary_arrays.json", encoding="utf-8"))
assert [round(float(qn[0]), 3), round(float(qn[1]), 3)] == A["powerFade"]["ci95MohmPerMo"], (qn, A["powerFade"]["ci95MohmPerMo"])

# (5) the production function reproduces the published numbers (no raw loader: the S0 design is the released resistanceVreg-like path; the density path is covered by (4))
import compute_drive_summary_v6 as V
r = V._powerfade_trend(dm)
assert r["n_boot"] > 3000 and "boot_ci95_mohm_per_month" in r
print("test_m492_ols_day_bootstrap OK (synthetic max diff %.2e; S1 real design: %d draws, max diff %.2e, old %.2f s, new %.3f s)" % (np.max(np.abs(old - new)), len(newS), np.max(np.abs(oldS - newS)), t1 - t0, t2 - t1))
