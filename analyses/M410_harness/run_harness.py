"""M410 simulation harness (spec analyses/M409_spec.md Rev 1-3, 'Known-answer harness'). Real regressor matrix X, real calendar-day grid and real ISO-week structure of the cell-spread design;
simulated outcomes only (the real outcome is never used). Writes harness_results.json. Failures are flagged, never tuned or re-scoped.
Parallel over (scenario, chunk of replications); each replication has its own seed, so the result does not depend on the chunking.
Usage: python analyses/M410_harness/run_harness.py [R] [B] [workers]"""
import os
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import json, sys, time
import numpy as np
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import dependence_sensitivity as DS
import serial_dependence as SD
from scipy import stats

BETA = np.array([0.0, 0.2, 0.3, -0.2])  # intercept, months, T, I (true months slope 0.2)
SCEN = [("null", "null", 0.0), ("ar1_phi0.0", "ar1", 0.0), ("ar1_phi0.3", "ar1", 0.3), ("ar1_phi0.6", "ar1", 0.6), ("season_plus_noise", "season", 0.0)]
_D = {}


def _setup():
    if _D:
        return _D
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    dd, X, _y, use = DS._design(dm, "cell_spread_loaded_p95_mv", ("T", "I"), "peak_I_discharge")
    X = X.copy()
    for c in range(2, X.shape[1]):
        X[:, c] = (X[:, c] - X[:, c].mean()) / X[:, c].std()
    t = SD.day_axis(dd["date"])
    wk = DS.week_blocks(dd["date"])
    days, inv = SD.unique_days(t)
    others = [c for c in range(X.shape[1]) if c != SD.K]
    _D.update(X=X, t=t, wk=wk, days=days, inv=inv, nd=len(days), W=len(np.unique(wk)), Z=np.column_stack([X[:, others], SD.spline_cols(t)]),
              dist=np.abs(days[:, None] - days[None, :]).astype(float))
    return _D


def sim(rng, kind, phi):
    d = _setup()
    nd, inv, t = d["nd"], d["inv"], d["t"]
    season = 0.0
    if kind == "null":
        u = rng.normal(size=nd)
    elif kind == "ar1":
        L = np.linalg.cholesky(phi ** d["dist"] + 1e-10 * np.eye(nd))
        u = L @ rng.normal(size=nd)
    else:
        u = rng.normal(size=nd)
        uu = (d["days"] - d["days"].min()) / (d["days"].max() - d["days"].min())
        season = (3.0 * np.sin(3 * np.pi * uu))[inv]
    eps = rng.normal(size=len(t)) * (1.0 if kind in ("null", "season") else 0.3)
    return d["X"] @ BETA + u[inv] + eps + season


def run_chunk(args):
    si, rep0, nrep, B = args
    name, kind, phi = SCEN[si]
    d = _setup()
    X, t, wk, days, inv, nd, W, Z = d["X"], d["t"], d["wk"], d["days"], d["inv"], d["nd"], d["W"], d["Z"]
    recs = []
    for rep in range(rep0, rep0 + nrep):
        rng = np.random.default_rng([1000 + si, rep])
        y = sim(rng, kind, phi)
        b, M, e = DS.ols(X, y)
        r = SD.day_means(e, inv, nd)
        pt = SD.autocorr_point(r, days)
        bk, se1, Gc, n, p = DS.cr1(X, y, t, SD.K)
        hs = {L: SD.hac(X, y, t, L, W) for L in SD.HAC_L}
        zq, tq1, tr = stats.norm.ppf(0.975), stats.t.ppf(0.975, Gc - 1), BETA[1]
        cov = {"cr1Normal": abs(bk - tr) <= zq * se1, "cr1T": abs(bk - tr) <= tq1 * se1}
        for L in SD.HAC_L:
            cov["hacL%dNormal" % L] = hs[L]["ci95Normal"][0] <= tr <= hs[L]["ci95Normal"][1]
            cov["hacL%dT" % L] = hs[L]["ci95T"][0] <= tr <= hs[L]["ci95T"][1]
        for L in SD.BLOCK_L:
            mb = SD.moving_block(X, y, t, L, B=B, seed=7 + rep)
            cov["movingBlockL%d" % L] = mb["ci95"][0] <= tr <= mb["ci95"][1]
        pre, post, byg, sk = SD.week_bootstrap_rho(X, y, Z, t, wk, B=B, seed=11 + rep)
        ci, c1 = SD._ci(pre), SD._ci(byg[:, 0])
        sup, sup1 = bool(ci[0] is not None and ci[0] > 0), bool(c1[0] is not None and c1[0] > 0)
        _, e2, _ = SD.wls_resid(Z, y)
        r2 = SD.day_means(e2, inv, nd)
        pi, pj, _d = SD.pair_index(days, SD.DMAX)
        post_pt = float(np.corrcoef(r2[pi], r2[pj])[0, 1])
        cd, cp = SD._ci(pre - post), SD._ci(post)
        pos = cp[0] is not None and cp[0] > 0
        recs.append({"slope": float(bk), "rhoPooled": pt["pooled"]["rho"], "rho1": pt["1"]["rho"], "hacRatio": hs[7]["se"] / se1, "glsRho": SD.gls_ar1(X, y, t, W)["rho"],
                     "supportedPooled": sup, "supportedRho1": sup1, "rhoPostPositive": bool(pos), "cov": {k: bool(v) for k, v in cov.items()}})
    return si, recs


def agg(recs, R):
    m = lambda f: float(np.mean([f(r) for r in recs]))
    rate = lambda f: {"rate": m(f), "mcse": float(np.sqrt(max(m(f) * (1 - m(f)), 0) / R))}
    return {"rhoPooledMean": m(lambda r: r["rhoPooled"]), "rhoPooledMeanMCSE": float(np.std([r["rhoPooled"] for r in recs], ddof=1) / np.sqrt(R)), "rho1Mean": m(lambda r: r["rho1"]),
            "hacL7OverCR1SeMean": m(lambda r: r["hacRatio"]), "glsRhoMean": m(lambda r: r["glsRho"]),
            "supportedPooled": rate(lambda r: r["supportedPooled"]), "supportedRho1": rate(lambda r: r["supportedRho1"]), "rhoPostPositive": rate(lambda r: r["rhoPostPositive"]),
            "coverage": {k: rate(lambda r, k=k: r["cov"][k]) for k in recs[0]["cov"]}, "slopeVarianceEmpirical": float(np.var([r["slope"] for r in recs], ddof=1))}


if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor
    R = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    B = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    NW = int(sys.argv[3]) if len(sys.argv) > 3 else 11
    d = _setup()
    CH = 50
    tasks = [(si, r0, min(CH, R - r0), B) for si in range(len(SCEN)) for r0 in range(0, R, CH)]
    t0 = time.time()
    by = {i: [] for i in range(len(SCEN))}
    with ProcessPoolExecutor(NW) as ex:
        for k, (si, recs) in enumerate(ex.map(run_chunk, tasks)):
            by[si] += recs
            if k % 10 == 0:
                print("chunk %d/%d %.0fs" % (k, len(tasks), time.time() - t0), flush=True)
    sc = {SCEN[i][0]: agg(by[i], R) for i in by}
    out = {"R": R, "B": B, "trueMonthsSlope": float(BETA[1]), "gridDays": int(d["nd"]), "gridWeeks": int(d["W"]), "nObs": int(len(d["t"])), "scenarios": sc, "verdicts": {}}
    V = {}
    V["nullBias"] = {"value": sc["null"]["rhoPooledMean"], "mcse": sc["null"]["rhoPooledMeanMCSE"], "criterion": "|mean rho_pooled| <= 0.05", "pass": abs(sc["null"]["rhoPooledMean"]) <= 0.05}
    for nm in ("null", "ar1_phi0.0"):
        V["falseSupport_" + nm] = {"pooled": sc[nm]["supportedPooled"], "rho1": sc[nm]["supportedRho1"], "criterion": "false 'supported' rate <= 0.10",
                                   "pass": sc[nm]["supportedPooled"]["rate"] <= 0.10 and sc[nm]["supportedRho1"]["rate"] <= 0.10}
    for nm in ("ar1_phi0.3", "ar1_phi0.6"):
        ph = float(nm.split("phi")[1])
        V["misclassification_" + nm] = {"pooledNotSupported": 1 - sc[nm]["supportedPooled"]["rate"], "rho1NotSupported": 1 - sc[nm]["supportedRho1"]["rate"], "mcse": sc[nm]["supportedRho1"]["mcse"],
                                        "criterion": "share not 'supported' <= 0.10 (pre-registered, Rev 1 item 8; not re-scoped)",
                                        "pass": (1 - sc[nm]["supportedPooled"]["rate"]) <= 0.10 and (1 - sc[nm]["supportedRho1"]["rate"]) <= 0.10,
                                        "passPooledOnly": (1 - sc[nm]["supportedPooled"]["rate"]) <= 0.10, "passRho1Only": (1 - sc[nm]["supportedRho1"]["rate"]) <= 0.10}
        V["rho1Recovery_" + nm] = {"value": sc[nm]["rho1Mean"], "target": ph, "criterion": "rho_1 mean within 0.07 of phi (day-mean residuals; hat-matrix attenuation expected)", "pass": abs(sc[nm]["rho1Mean"] - ph) <= 0.07}
        vif = SD.vif_ar1(d["X"], d["t"], ph)
        emp = sc[nm]["slopeVarianceEmpirical"] / sc["ar1_phi0.0"]["slopeVarianceEmpirical"]
        V["vifVsSimulatedVariance_" + nm] = {"vifAtTruePhi": vif, "empiricalVarianceRatio": emp, "criterion": "relative difference <= 15 %", "pass": abs(emp / vif - 1) <= 0.15}
        V["glsRho_" + nm] = {"value": sc[nm]["glsRhoMean"], "criterion": "reported only"}
    ss = sc["season_plus_noise"]
    V["seasonControl"] = {"supportedPooled": ss["supportedPooled"], "rhoPostPositive": ss["rhoPostPositive"], "criterion": "descriptive: rho_post interval above 0 in at most 10 % of replications under season-plus-noise",
                          "pass": ss["rhoPostPositive"]["rate"] <= 0.10}
    V["rhoPostPositiveUnderAR1"] = {k: sc[k]["rhoPostPositive"] for k in ("ar1_phi0.3", "ar1_phi0.6")}
    V["coverage"] = {sn: {k: v["rate"] for k, v in s["coverage"].items()} for sn, s in sc.items()}
    V["coverageNote"] = "nominal coverage is reported per row and scenario with MCSE in 'scenarios'; not required row by row; differences within about 2 MCSE are not 'better'; failures are flagged, never tuned"
    out["verdicts"] = V
    json.dump(out, open(os.path.join(os.path.dirname(__file__), "harness_results.json"), "w", encoding="utf-8"), indent=1)
    print("DONE %.0fs" % (time.time() - t0))
    print(json.dumps({k: (v.get("pass") if isinstance(v, dict) and "pass" in v else None) for k, v in V.items()}, indent=1))
