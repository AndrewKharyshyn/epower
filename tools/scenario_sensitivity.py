#!/usr/bin/env python3
"""M713d (spec analyses/M712_spec.md Rev 1.1, section 6; gate G-S4 is REPORTED, not gated): global sensitivity of the S2 primary scenario to its ASSUMPTIONS.

Pre-registered ranges: analyses/M712_ranges.json (hashed by the spec; tau_p and the parking offset re-centred on the M709 fit, offset bracket [0, 2.7] C). One-at-a-time tornado (low / default / high) and
Saltelli-2010 first-order + Jansen total-order Sobol indices (N = 384 base samples, uniform ranges, own implementation). One fixed synthetic day sequence (common random numbers), so the outputs are deterministic
functions of the assumptions; the day-block sampling variability is reported separately (E-real / E-exp). The Sobol ranking follows the chosen ranges: it describes this table, it is not a finding about the car.
Usage: python tools/scenario_sensitivity.py [--dir analyses/M713] [--n 384]   writes <dir>/scenario_sensitivity.json"""
import argparse, hashlib, json, os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import scenario_engine as SE

SEED = SE.SEED
OUTS = ["gtc_5Ah_rated", "calendarDose_hEq", "calendarDose_SoCweighted_hEq", "cycleDose_AhEq", "coldChargeIndex_AhxC_lt10", "coldCharge_ah_lt0", "ahShare_T_lt10", "ahShare_T_ge35", "warmups_Tstart_lt15"]


def load_ranges():
    p = os.path.join(ROOT, "analyses", "M712_ranges.json")
    R = json.load(open(p, encoding="utf-8"))["ranges"]
    names = list(R)
    return names, R, hashlib.sha256(open(p, "rb").read()).hexdigest()


def run(M, names, X, seed=SEED):
    """X [n, k] parameter samples (columns = names) -> dict of outputs [n] for the S2 day sequence drawn once (common random numbers)."""
    n = X.shape[0]
    g = {nm: X[:, i] for i, nm in enumerate(names)}
    rng = np.random.default_rng(seed)
    sc = SE.scenarios(M.ODO_KM)["S2_balanced_owner_expected"]
    mo = SE.month_of_doy()
    tilt = SE.solve_tilt(M, M.ODO_KM, SE.W_SUM_BAL, M.params["f_s"], M.params["f_a"])
    u1, u2 = rng.random(365), rng.random(365)
    src = np.zeros((n, 365), int)
    iss = np.zeros((n, 365), bool)
    cdf = {}
    for nm in ("summer", "autumn"):
        pl = M.POOL[nm]
        w = np.exp(tilt * M.DAYKM[pl] / 100.0)
        cdf[nm] = (np.cumsum(w) / w.sum(), pl)
    for d in range(365):
        ws = np.where(SE.W_SUM_BAL[mo[d]] > 0, SE.W_SUM_BAL[mo[d]], g["w_off"])
        ps = u1[d] < ws
        for nm, flag in (("summer", True), ("autumn", False)):
            c_, pl = cdf[nm]
            k_ = min(int((u2[d] > c_).sum()), len(pl) - 1)
            src[ps == flag, d] = pl[k_]
            iss[ps == flag, d] = flag
    sh = np.zeros((n, 365))
    for m, f in ((11, 1.0), (0, 1.0), (1, 1.0), (10, 0.5), (2, 0.5)):
        sh[:, mo == m] = (g["winter_shift"] * f)[:, None]
    par = dict(M.params)
    for nm in ("tau_p", "EaR", "der", "kappa", "c1", "f_a", "amp_w_scale", "gamma"):
        par[nm] = g[nm]
    par["off_s"] = par["off_a"] = par["off_w"] = g["off_w"]               # one parking offset all seasons (M709); the ranges file keeps the key off_w
    acc = SE.simulate(M, src, sh, par, iss)
    o = SE.summarise(acc)

    def at_ea(k40, k50, k60):                                             # log-quadratic interpolation of a dose in Ea
        l = np.log(np.c_[k40, k50, k60])
        x = (g["Ea_age"] - 50.0) / 10.0
        a = l[:, 1]
        b = (l[:, 2] - l[:, 0]) / 2
        c = (l[:, 2] + l[:, 0]) / 2 - l[:, 1]
        return np.exp(a + b * x + c * x * x)
    cal = lambda e: o["arrCalendar_driveHoursEq_Ea%d" % e] + o["arrCalendar_parkedHoursEq_Ea%d" % e]
    Y = {"gtc_5Ah_rated": o["gtc_5Ah_rated"], "calendarDose_hEq": at_ea(cal(40), cal(50), cal(60)),
         "cycleDose_AhEq": at_ea(o["arrCycleDose_AhEq_Ea40"], o["arrCycleDose_AhEq_Ea50"], o["arrCycleDose_AhEq_Ea60"]),
         "calendarDose_SoCweighted_hEq": o["arrCalendar_parked_SoCweighted_hoursEq_Ea50"] * at_ea(cal(40), cal(50), cal(60)) / cal(50)}
    for k in OUTS:
        if k not in Y:
            Y[k] = o[k]
    return Y


def r_(x, n=4):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "analyses", "M713"))
    ap.add_argument("--n", type=int, default=384)
    a = ap.parse_args(argv)
    M = SE.load_model(a.dir, "production")
    names, R, rsha = load_ranges()
    k = len(names)
    lo = np.array([R[n]["lo"] for n in names]); df = np.array([R[n]["default"] for n in names]); hi = np.array([R[n]["hi"] for n in names])
    res = {"milestone": "M713d", "spec": "analyses/M712_spec.md", "rangesSha256": rsha, "label": "sensitivity of the S2 primary scenario to assumptions; ranges are ASSUMPTIONS (uniform), outputs deterministic given one fixed day sequence; the ranking follows the chosen ranges (reported, not gated)",
           "ranges": {n: R[n] for n in names}}
    X = np.tile(df, (2 * k + 1, 1))
    for i in range(k):
        X[1 + 2 * i, i] = lo[i]
        X[2 + 2 * i, i] = hi[i]
    Y = run(M, names, X)
    tor = {}
    for y in OUTS:
        base = Y[y][0]
        bars = [{"param": names[i], "atLo": r_(Y[y][1 + 2 * i]), "atHi": r_(Y[y][2 + 2 * i]), "relLo": r_(Y[y][1 + 2 * i] / base - 1) if base else None, "relHi": r_(Y[y][2 + 2 * i] / base - 1) if base else None,
                 "span": r_(abs(Y[y][2 + 2 * i] - Y[y][1 + 2 * i]))} for i in range(k)]
        tor[y] = {"base": r_(base), "bars": sorted(bars, key=lambda b: -b["span"])}
    res["tornado"] = tor
    N = a.n
    rng = np.random.default_rng(SEED)
    A = lo + (hi - lo) * rng.random((N, k))
    B = lo + (hi - lo) * rng.random((N, k))
    Xs = [A, B]
    for i in range(k):
        AB = A.copy()
        AB[:, i] = B[:, i]
        Xs.append(AB)
    Ys = run(M, names, np.vstack(Xs))
    sob = {}
    for y in OUTS:
        v = Ys[y]
        fA, fB = v[:N], v[N:2 * N]
        var = np.var(np.r_[fA, fB])
        rows = []
        for i in range(k):
            fAB = v[(2 + i) * N:(3 + i) * N]
            S1 = np.mean(fB * (fAB - fA)) / var if var > 0 else np.nan
            ST = 0.5 * np.mean((fA - fAB) ** 2) / var if var > 0 else np.nan
            rows.append({"param": names[i], "S1": r_(S1, 3), "ST": r_(ST, 3)})
        allv = np.r_[fA, fB]
        sob[y] = {"mean": r_(np.mean(allv)), "p2.5": r_(np.percentile(allv, 2.5)), "p97.5": r_(np.percentile(allv, 97.5)), "cv": r_(np.sqrt(var) / np.mean(allv)) if np.mean(allv) else None,
                  "indices": sorted(rows, key=lambda b: -(b["ST"] if b["ST"] is not None else 0))}
    res["sobol"] = {"N": N, "evaluations": N * (k + 2), "estimators": "first order Saltelli 2010, total order Jansen", "outputs": sob}
    json.dump(res, open(os.path.join(a.dir, "scenario_sensitivity.json"), "w", encoding="utf-8"), indent=1)
    for y in OUTS:
        print(y, sob[y]["mean"], [sob[y]["p2.5"], sob[y]["p97.5"]], [(b["param"], b["ST"]) for b in sob[y]["indices"][:4]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
