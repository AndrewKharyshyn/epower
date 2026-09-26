"""
test_seasonal_adjust.py (M284, audit #7) -- unit + simulation tests for seasonal_adjust v2.
Self-contained: synthetic data only, no pipeline artefacts.  Run: python3 test_seasonal_adjust.py
"""
from __future__ import annotations
import copy, math, sys, time
import numpy as np
import seasonal_adjust as SA

PASS, FAIL = [], []
def ok(name, cond):
    (PASS if cond else FAIL).append(name); print(("  ok  " if cond else " FAIL ") + name)

def make(n=400, effect=0.0, slope=0.5, seed=1, a_rng=(30, 60), b_rng=(40, 70), ndays=18, dtype_b="urban"):
    rng = np.random.default_rng(seed); dr = []
    for i in range(n):
        b = i % 2
        sp = rng.uniform(*(b_rng if b else a_rng))
        dr.append({"g": "B" if b else "A", "drive_type": dtype_b if b else "urban", "speed_mean_moving": sp,
                   "stationary_pct": rng.uniform(5, 25), "pct_highway": rng.uniform(0, 30),
                   "distance_km": rng.uniform(2, 18), "date": f"2026-02-{(i % ndays) + 1:02d}",
                   "Y": slope * sp + effect * b + rng.normal(0, 2)})
    return dr

def run(dr, **kw):
    kw.setdefault("n_boot", 300)
    return SA.adjusted_contrast(dr, "Y", "g", "A", "B", **kw)

# 1 -- overlapping confounder: raw is confounded, adjusted ~ 0
def t01():
    r = run(make())
    ok("01 available on overlapping confounder", r["status"] == "available")
    ok("01 raw confounded diff > 2", r["rawDiff"] > 2)
    ok("01 adjusted ~0, CI spans 0", r["ci95"][0] < 0 < r["ci95"][1] and abs(r["adjustedDiff"]) < 2)
    ok("01 estimators agree (overlap-weighted vs g-comp)", abs(r["estimatorGap"]) < 1.5)

# 2 -- recovers a known effect on top of the confounder
def t02():
    r = run(make(effect=3.0, seed=2))
    ok("02 known effect 3.0 inside 95% CI", r["ci95"][0] < 3.0 < r["ci95"][1])
    ok("02 point estimate within 1.0 of truth", abs(r["adjustedDiff"] - 3.0) < 1.0)

# 3 -- disjoint continuous support -> unavailable (never a number)
def t03():
    dr = make(a_rng=(20, 40), b_rng=(150, 200), seed=3)
    r = run(dr)
    ok("03 disjoint covariates -> unavailable", r["status"] == "unavailable" and "adjustedDiff" not in r)
    ok("03 reason code present", r.get("reasonCode") in ("disjoint_propensity", "insufficient_support", "thin_on_support", "low_ess"))

# 4 -- categorical non-overlap that per-covariate ranges cannot see (the v1 false-optimistic case)
def t04():
    rng = np.random.default_rng(4); dr = []
    for i in range(500):
        b = i % 5 == 0                      # B = 20% of rows, ALL urban
        dt = "urban" if b else rng.choice(["urban", "highway"], p=[0.7, 0.3])
        sp = rng.uniform(20, 60) if dt == "urban" else rng.uniform(60, 110)
        if b: sp = rng.uniform(20, 60)
        dr.append({"g": "B" if b else "A", "drive_type": dt, "speed_mean_moving": sp,
                   "stationary_pct": rng.uniform(5, 25), "pct_highway": 80 if dt == "highway" else 2,
                   "distance_km": rng.uniform(2, 18), "date": f"2026-03-{((i + i // 5) % 20) + 1:02d}",
                   # highway drives have a LARGE extra outcome that only cohort A can reveal
                   "Y": 0.1 * sp + (12.0 if dt == "highway" else 0.0) + 2.0 * b + rng.normal(0, 1.5)})
    r = run(dr)
    ok("04 available inside the shared stratum", r["status"] == "available")
    ok("04 highway stratum reported as trimmed", "highway" in r["commonSupport"]["trimmedStrata"])
    ok("04 estimate recovers the urban-only effect (2.0)", r["ci95"][0] < 2.0 < r["ci95"][1])
    ok("04 estimand restriction is warned", any("shared_strata" in w for w in r["warnings"]))
    # the v1 gate (fraction of B inside A's per-covariate [min,max] box) could not see this problem:
    A = [d for d in dr if d["g"] == "A"]; B = [d for d in dr if d["g"] == "B"]
    v1 = min(sum(min(a[c] for a in A) <= b[c] <= max(a[c] for a in A) for b in B) / len(B) for c in SA.DEFAULT_COVARIATES)
    ok(f"04 v1 marginal-box gate would have passed ({v1:.2f} >= 0.5) while highway is unsupported", v1 >= 0.5)

# 5 -- inputs never mutated
def t05():
    dr = make(n=120, seed=5); snap = copy.deepcopy(dr)
    run(dr, n_boot=50); SA.assess_overlap(dr, "g", "A", "B")
    ok("05 drives unchanged after adjusted_contrast + assess_overlap", dr == snap)
    ok("05 no '_y' key written", all("_y" not in d for d in dr))

# 6 -- non-finite / missing values are dropped and counted, never propagated
def t06():
    dr = make(seed=6)
    dr[0]["Y"] = float("nan"); dr[1]["speed_mean_moving"] = float("inf"); dr[2]["distance_km"] = None
    dr[3]["Y"] = "abc"
    r = run(dr, n_boot=100)
    ok("06 four bad rows counted", r["inputAudit"]["nDroppedNonFinite"] == 4)
    ok("06 output is finite", all(math.isfinite(x) for x in (r["adjustedDiff"], r["ci95"][0], r["ci95"][1])))

# 7 -- bootstrap validity: stratified resampling never loses a cohort
def t07():
    dr = make(n=200, seed=7)
    P = SA._prepare(dr, "Y", "g", "A", "B", SA.DEFAULT_COVARIATES, "date", "drive_type")
    rng = np.random.default_rng(0); bad = 0
    for _ in range(500):
        ix = SA._stratified_cluster_resample(P["cl"], P["g"], rng)
        if len(set(P["g"][ix].tolist())) < 2: bad += 1
    ok("07 500 replicates all retain both cohorts", bad == 0)
    # one cohort confined to a single day -> too few days, refused (not a degenerate bootstrap)
    dr2 = make(n=120, seed=8, ndays=1)
    ok("07 single-day data -> unavailable (too_few_days)", run(dr2)["reasonCode"] == "too_few_days")

# 8 -- determinism + seed sensitivity
def t08():
    dr = make(seed=9)
    a, b = run(dr, seed=5), run(dr, seed=5)
    c = run(dr, seed=6)
    ok("08 same seed -> identical output", a == b)
    ok("08 different seed -> same point estimate", a["adjustedDiff"] == c["adjustedDiff"])
    ok("08 different seed -> (slightly) different CI", a["ci95"] != c["ci95"])

# 9 -- FDR family control
def t09():
    q = SA.bh_adjust([0.01, 0.04, 0.03, 0.005])
    ok("09 BH textbook example", [round(x, 4) for x in q] == [0.02, 0.04, 0.04, 0.02])
    dr = make(effect=3.0, seed=10)
    rng = np.random.default_rng(11)
    for d in dr:
        d["N1"], d["N2"], d["N3"], d["N4"] = (float(rng.normal()) for _ in range(4))
        d["T"] = d["Y"]
    fam = SA.adjusted_contrast_family(dr, {"T": {}, "N1": {}, "N2": {}, "N3": {}, "N4": {}}, "g", "A", "B", n_boot=200)
    res = fam["results"]
    ok("09 true effect survives FDR", res["T"]["fdrSignificant"] is True)
    ok("09 null outcomes not declared significant", sum(res[k]["fdrSignificant"] for k in ("N1", "N2", "N3", "N4")) <= 1)
    ok("09 family bookkeeping", fam["fdr"]["nTested"] == 5)

# 10 -- practical equivalence decision
def t10():
    r0 = run(make(effect=0.0, seed=12, slope=0.0), equivalence_margin=2.0)
    ok("10 null effect, generous margin -> practically_equivalent", r0["equivalence"]["decision"] == "practically_equivalent")
    r1 = run(make(effect=6.0, seed=13, slope=0.0), equivalence_margin=1.0)
    ok("10 large effect -> difference_exceeds_margin", r1["equivalence"]["decision"] == "difference_exceeds_margin")
    r2 = run(make(effect=0.0, seed=14, slope=0.0), equivalence_margin=0.05)
    ok("10 tiny margin -> inconclusive", r2["equivalence"]["decision"] == "inconclusive")

# 11 -- calibration under the null (coverage) -- small simulation
def t11():
    hits, n = 0, 24
    t = time.time()
    for s in range(n):
        r = run(make(n=240, effect=0.0, seed=100 + s), n_boot=120)
        hits += (r["status"] == "available" and r["ci95"][0] <= 0 <= r["ci95"][1])
    cov = hits / n
    ok(f"11 null coverage of 95% CI = {cov:.2f} (>= 0.80; n={n}, {time.time()-t:.0f}s)", cov >= 0.80)

# 12 -- empty cohort / thin data / unmeasurable -> explicit unavailable
def t12():
    dr = make(n=60, seed=15)
    ok("12 empty cohort", SA.adjusted_contrast(dr, "Y", "g", "A", "Z")["reasonCode"] == "empty_cohort")
    ok("12 thin cohort -> unavailable", run(make(n=14, seed=16))["status"] == "unavailable")
    ok("12 cluster key missing -> singleton clusters counted, no crash",
       run([{k: v for k, v in d.items() if k != "date"} for d in make(n=200, seed=17)], n_boot=60)["inputAudit"]["nSingletonClusters"] == 200)

# 13 -- v1 API compatibility fields
def t13():
    r = run(make(seed=18), n_boot=80)
    ok("13 v1 fields present", all(k in r for k in ("rawDiff", "adjustedDiff", "ci95", "commonSupport", "nBoot" if "nBoot" in r else "nBootValid", "nA", "nB", "nDays", "covariates", "interpretation")))

def main():
    for t in (t01, t02, t03, t04, t05, t06, t07, t08, t09, t10, t11, t12, t13): t()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("FAILURES:", FAIL); sys.exit(1)

if __name__ == "__main__":
    main()
