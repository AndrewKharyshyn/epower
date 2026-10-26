#!/usr/bin/env python3
"""M507 (spec analyses/M507_spec.md Rev 2): coverage of the day-clustered percentile bootstrap (P) and of a linearised t(G-1) interval (T, comparator, not adopted) for a ratio of sums with few
clusters (audit ST-06). A stylised, corpus-independent simulation: no data interval, estimator or decision changes. Seeds: SeedSequence(42).spawn in the fixed cell order (phi ascending, G ascending).
Default: write analyses/M507_result.json. --splice: also write the additive static payload block fewClusterCoverage + stamp.
Usage: python tools/few_cluster_coverage.py [--out analyses/M507_result.json] [--splice] [--reps 2000] [--draws 4000]"""
import copy, datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
import numpy as np
from scipy import stats

GRID, PHIS = [3, 5, 7, 10, 15, 20, 40], [0.0, 0.3]
SEED, REPS, DRAWS, CHECK_SEED = 42, 2000, 4000, 1042
SD_DAY, SD_DRIVE, K_MEAN, LOG_D, SD_D, INTENS = 0.15, 0.25, 2.0, np.log(4.0), 0.8, 0.25
R0_CLOSED = INTENS * np.exp((SD_DAY ** 2 + SD_DRIVE ** 2) / 2)          # primary population value (spec Rev 2 R2)


def day_effects(G, phi, rng):
    """Zero-mean Gaussian AR(1) series along consecutive calendar days with marginal sd SD_DAY, started from its stationary marginal."""
    z = rng.standard_normal(G)
    e = np.empty(G)
    e[0] = SD_DAY * z[0]
    for t in range(1, G):
        e[t] = phi * e[t - 1] + np.sqrt(1 - phi ** 2) * SD_DAY * z[t]
    return e


def day_totals(G, phi, rng):
    e = day_effects(G, phi, rng)
    N, Dsum = np.zeros(G), np.zeros(G)
    for i in range(G):
        k = 1 + rng.poisson(K_MEAN)
        d = rng.lognormal(LOG_D, SD_D, k)
        num = d * INTENS * np.exp(e[i] + SD_DRIVE * rng.standard_normal(k))
        N[i], Dsum[i] = num.sum(), d.sum()
    return N, Dsum


def r0_check(rng, n_days=1_000_000):
    """Check of the closed form R0 by a large separate simulation of independent days (same marginal)."""
    k = 1 + rng.poisson(K_MEAN, n_days)
    tot = int(k.sum())
    d = rng.lognormal(LOG_D, SD_D, tot)
    day = np.repeat(np.arange(n_days), k)
    e = SD_DAY * rng.standard_normal(n_days)
    num = d * INTENS * np.exp(e[day] + SD_DRIVE * rng.standard_normal(tot))
    return float(num.sum() / d.sum())


def interval_percentile(N, Dsum, rng, draws):
    G = len(N)
    idx = rng.integers(0, G, size=(draws, G))
    r = N[idx].sum(1) / Dsum[idx].sum(1)
    q = np.percentile(r, [2.5, 97.5])
    return float(q[0]), float(q[1])


def interval_t(N, Dsum):
    """R_hat +/- t(0.975, G-1) x SE, SE = sqrt(G/(G-1) x sum (n_i - R_hat d_i)^2) / sum d_i (delta-method cluster-robust)."""
    G = len(N)
    R = N.sum() / Dsum.sum()
    se = np.sqrt(G / (G - 1) * np.sum((N - R * Dsum) ** 2)) / Dsum.sum()
    h = stats.t.ppf(0.975, G - 1) * se
    return float(R - h), float(R + h), float(se)


def cell(G, phi, R0, reps, draws, seed_seq):
    rng = np.random.default_rng(seed_seq)
    hit_p = hit_t = 0
    wp, wt = [], []
    for _ in range(reps):
        N, Dsum = day_totals(G, phi, rng)
        lo, hi = interval_percentile(N, Dsum, rng, draws)
        hit_p += (lo <= R0 <= hi); wp.append(hi - lo)
        lo, hi, _ = interval_t(N, Dsum)
        hit_t += (lo <= R0 <= hi); wt.append(hi - lo)
    cp, ct = hit_p / reps, hit_t / reps
    mc = lambda p: float(np.sqrt(p * (1 - p) / reps))
    return {"G": G, "phi": phi, "reps": reps, "percentile": {"coverage": round(cp, 4), "mcse": round(mc(cp), 4), "meanWidth": round(float(np.mean(wp)), 5)},
            "linearisedT": {"coverage": round(ct, 4), "mcse": round(mc(ct), 4), "meanWidth": round(float(np.mean(wt)), 5), "status": "comparator, not adopted"}}


def smallest_g(cells, method, phi, target=0.93):
    """Smallest G with coverage + 2 MCSE >= target that also holds at every larger G of the grid (a description, never a flag or a suppression rule)."""
    cs = sorted([c for c in cells if c["phi"] == phi], key=lambda c: c["G"])
    ok = [c["coverage"] + 2 * c["mcse"] >= target for c in (x[method] for x in cs)]
    for i in range(len(cs)):
        if all(ok[i:]):
            return cs[i]["G"]
    return None


def run(reps=REPS, draws=DRAWS, grid=GRID, phis=PHIS):
    ss = np.random.SeedSequence(SEED).spawn(len(phis) * len(grid))
    cells, i = [], 0
    for phi in phis:
        for G in grid:
            cells.append(cell(G, phi, float(R0_CLOSED), reps, draws, ss[i]))
            i += 1
    chk = r0_check(np.random.default_rng(CHECK_SEED))
    smallest = {"%s|phi=%s" % (m, phi): smallest_g(cells, m, phi) for m in ("percentile", "linearisedT") for phi in phis}
    pc = {"phi=%s" % phi: {str(c["G"]): c["percentile"]["coverage"] for c in cells if c["phi"] == phi} for phi in phis}
    c20 = next(c for c in cells if c["phi"] == 0.0 and c["G"] == 20)["percentile"]
    branch = "A" if c20["coverage"] + 2 * c20["mcse"] < 0.93 else "B"
    return {"R0": round(float(R0_CLOSED), 6), "R0Check": round(chk, 6), "R0CheckRelDiff": round(abs(chk - float(R0_CLOSED)) / float(R0_CLOSED), 5), "cells": cells,
            "smallestGWithCoverageAtLeast0p93": smallest, "percentileCoverage": pc, "dashboardBranch": branch}


def main():
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M507_result.json"
    reps = int(sys.argv[sys.argv.index("--reps") + 1]) if "--reps" in sys.argv else REPS
    draws = int(sys.argv[sys.argv.index("--draws") + 1]) if "--draws" in sys.argv else DRAWS
    res = run(reps, draws)
    prov = {"scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "specSha256": hashlib.sha256(open("analyses/M507_spec.md", "rb").read()).hexdigest(), "seed": SEED, "reps": reps, "draws": draws}
    out = {"spec": "analyses/M507_spec.md", "provenance": {**prov, "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}, "design": {
        "drivesPerDay": "1 + Poisson(2)", "distance": "lognormal(log 4, 0.8) km", "numerator": "distance x 0.25 x exp(day effect + N(0, 0.25^2))", "dayEffect": "zero-mean Gaussian AR(1), marginal sd 0.15, lag-1 correlation phi, started from the stationary marginal",
        "estimand": "ratio of sums over G days; population value R0 = 0.25 x exp((0.15^2 + 0.25^2)/2) (closed form), checked by a 10^6-day simulation"}, **res}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({"R0": res["R0"], "check": res["R0Check"], "pct": res["percentileCoverage"], "t": {"phi=%s" % phi: {str(c["G"]): c["linearisedT"]["coverage"] for c in res["cells"] if c["phi"] == phi} for phi in PHIS}, "smallest": res["smallestGWithCoverageAtLeast0p93"], "branch": res["dashboardBranch"]}, indent=1))
    if "--splice" in sys.argv:
        splice(out, prov)


def splice(out, prov):
    P = "summary_arrays.json"
    raw = open(P, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    blk = {"label": "stylised, corpus-independent simulation of the coverage of the day-clustered percentile bootstrap (and, as a comparator that is not adopted, a linearised t(G-1) interval) for a ratio of sums with few day clusters; it describes the method, not the coverage of any displayed interval; no interval is changed",
           "spec": "analyses/M507_spec.md", "specSha256": prov["specSha256"], "scriptSha256": prov["scriptSha256"], "seed": prov["seed"], "reps": prov["reps"], "draws": prov["draws"],
           "design": out["design"], "cells": out["cells"], "R0": out["R0"], "R0Check": out["R0Check"], "percentileCoverage": out["percentileCoverage"],
           "smallestGWithCoverageAtLeast0p93": out["smallestGWithCoverageAtLeast0p93"], "dashboardBranch": out["dashboardBranch"]}
    blk = json.loads(json.dumps(blk))
    A["fewClusterCoverage"] = blk
    st = copy.deepcopy(A["_artifactStamps"]["powerFadeEquivalence"])
    st.update(computationStatus="computed", generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              computationStatusNote="M507: static, corpus-independent stylised simulation by tools/few_cluster_coverage.py (spec analyses/M507_spec.md; script and spec sha256 in the block); identical at every ingestion")
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    import stamp_common as _sc
    A["_artifactStamps"]["fewClusterCoverage"] = _sc.carry_declared(None, st)      # M518: an undeclared block never inherits a cloned declared lineage
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"spliced": True}))


if __name__ == "__main__":
    main()
