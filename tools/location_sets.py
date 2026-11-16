"""M694: calibrated location sets for the change points (spec analyses/M693_spec.md Rev 1.1). Offline coverage study plus the constructions.

C0 reference: day-clustered wild Rademacher bootstrap at fixed K (the M676 interval).
C1 unconditional wild bootstrap: K refitted by BIC in every draw, one-to-one order-preserving matching of the draw's breaks to the fitted ones.
C2 profile likelihood-ratio set (Bai 1997 limit, c = 2 ln(1 / (1 - sqrt(0.95))) = 7.35) with a day-cluster variance correction lambda_hat.
"""
import hashlib, itertools, json, math, os, sys, zlib
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import changepoints as C

SPEC = "analyses/M693_spec.md"
SEED = 42
CRIT = 2.0 * math.log(1.0 / (1.0 - math.sqrt(0.95)))       # 7.35
CONSTRUCTIONS = ("C0", "C1", "C2")                           # selection ties: the construction listed first among C1, C2 (C0 is never admissible)
UNMATCHED_MAX = 0.05
CORE = ("S1", "S2", "S3", "S4", "S5", "S5effect")
DESCRIPTIVE = ("N0", "D1", "D2", "D3", "D4", "D6")
PHI = 0.3
ICC = 0.3


# ------------------------------------------------------------------------------------------------ matching and sets
def match(planted, est, n):
    """One-to-one, order-preserving assignment of planted to estimated breaks minimising the total distance; a pair counts only if the planted break lies in the
    estimated break's window (the cell between the midpoints of adjacent estimated breaks, edges 0 and n). Returns {planted index: estimated index}."""
    kp, ke = len(planted), len(est)
    if kp == 0 or ke == 0:
        return {}
    edges = [0.0] + [(est[i] + est[i + 1]) / 2.0 for i in range(ke - 1)] + [float(n)]
    best, bestd = None, None
    if ke >= kp:
        for sub in itertools.combinations(range(ke), kp):
            d = sum(abs(planted[i] - est[sub[i]]) for i in range(kp))
            if bestd is None or d < bestd:
                bestd, best = d, [(i, sub[i]) for i in range(kp)]
    else:
        for sub in itertools.combinations(range(kp), ke):
            d = sum(abs(planted[sub[i]] - est[i]) for i in range(ke))
            if bestd is None or d < bestd:
                bestd, best = d, [(sub[i], i) for i in range(ke)]
    return {p: e for p, e in best if edges[e] <= planted[p] < edges[e + 1]}


def fit(y, feas):
    n = len(y)
    rss, lc = C.partition(y, feas)
    K = C.choose_k(C.bic_table(rss, n))
    return (0, []) if K is None or K == 0 else (K, list(lc[K]))


def lr_set(y, dayidx, feas, locs, j, crit=CRIT):
    """C2 for break j of the fitted segmentation `locs` (neighbours fixed). Returns dict(lo, hi, lambda, sigma2, nonContiguous, nAccepted)."""
    n = len(y)
    edges = [0] + list(locs) + [n]
    a, b = edges[j], edges[j + 2]
    cost = C._cost_matrix(y)
    cand = [t for t in range(a + 1, b) if feas[a, t] and feas[t, b]]
    if not cand:
        return None
    rss = np.array([cost[a, t] + cost[t, b] for t in cand])
    t_hat = locs[j]
    rss_hat = cost[a, t_hat] + cost[t_hat, b]
    seg = np.concatenate([y[a:t_hat] - y[a:t_hat].mean(), y[t_hat:b] - y[t_hat:b].mean()])
    e2 = float(np.sum(seg ** 2))
    if e2 <= 0:
        return None
    days = dayidx[a:b]
    u, inv = np.unique(days, return_inverse=True)
    S = np.bincount(inv, weights=seg, minlength=len(u))
    lam = max(1.0, float((np.sum(S ** 2) + np.sum(S[:-1] * S[1:])) / e2))
    s2 = e2 / (b - a)
    ok = (rss - rss_hat) / (s2 * lam) <= crit
    acc = np.array(cand)[ok]
    if len(acc) == 0:
        acc = np.array([t_hat])
    lo, hi = int(acc.min()), int(acc.max())
    return {"lo": lo, "hi": hi, "lambda": lam, "sigma2": s2, "nonContiguous": bool(len(acc) < int(np.sum([(lo <= t <= hi) for t in cand]))), "nAccepted": int(len(acc))}


def boot_both(y, dayidx, feas, K, locs, B, seed):
    """One set of day-clustered Rademacher draws serving C0 (fixed K) and C1 (K refitted)."""
    n = len(y)
    f, _ = C.fitted(y, locs)
    res = y - f
    nd, inv = C._day_groups(dayidx)
    rng = np.random.default_rng(seed)
    c0 = np.zeros((B, K), dtype=int)
    c1 = np.full((B, K), -1, dtype=int)
    for b in range(B):
        sg = rng.choice([-1.0, 1.0], size=nd)[inv]
        yb = f + res * sg
        rss, lc = C.partition(yb, feas, C.KMAX)
        kb = C.choose_k(C.bic_table(rss, n))
        c0[b] = lc[K] if lc[K] is not None else locs
        est = list(lc[kb]) if (kb is not None and kb >= 1) else []
        for p, e in match(list(locs), est, n).items():
            c1[b, p] = est[e]
    return c0, c1


def intervals(y, dayidx, feas, K, locs, B, seed):
    """All constructions for the fitted segmentation: {construction: [ {lo, hi, ...} or None per break ]}."""
    out = {"C0": [], "C1": [], "C2": []}
    if K == 0:
        return out
    c0, c1 = boot_both(y, dayidx, feas, K, locs, B, seed)
    for j in range(K):
        out["C0"].append({"lo": float(np.percentile(c0[:, j], 2.5)), "hi": float(np.percentile(c0[:, j], 97.5))})
        m = c1[:, j] >= 0
        un = 1.0 - m.mean()
        out["C1"].append(None if un > UNMATCHED_MAX or m.sum() < 10 else {"lo": float(np.percentile(c1[m, j], 2.5)), "hi": float(np.percentile(c1[m, j], 97.5)), "unmatchedShare": float(un)})
        out["C2"].append(lr_set(y, dayidx, feas, locs, j))
    return out


# ------------------------------------------------------------------------------------------------ real structure and scenarios
_STRUCT = {}


def structure(root=ROOT):
    if "d" in _STRUCT:
        return _STRUCT["d"]
    m, frames = C.load(root)
    df = frames["X2"]
    df = df[np.isfinite(df["y"].values)].reset_index(drop=True)
    dates = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d").values
    dayidx = pd.factorize(dates)[0]
    feas = C._feasible(dayidx)
    _STRUCT["d"] = {"y": df["y"].values.astype(float), "dates": dates, "dayidx": dayidx, "feas": feas, "n": len(df)}
    return _STRUCT["d"]


def fingerprint(st, B):
    cnt = np.bincount(st["dayidx"])
    return {"n": int(st["n"]), "nDays": int(len(cnt)), "drivesPerDayHash": hashlib.sha256(cnt.astype(np.int64).tobytes()).hexdigest()[:16],
            "feasibility": "minimum segment %d drives and %d distinct calendar days (M675 section 2)" % (C.MIN_DRIVES, C.MIN_DAYS), "kMax": C.KMAX, "B": int(B), "critical": round(CRIT, 4)}


def scenario(name, st, rng):
    """Returns (y, planted locations). Noise unit variance; steps in units of the noise sd."""
    n, dayidx = st["n"], st["dayidx"]
    steps1 = ([n // 2], [1.5])
    steps3 = ([n // 4, n // 2, 3 * n // 4], [1.0, -1.0, 1.5])
    cfg = {"S1": ("iid", steps1), "S2": ("ar1", steps1), "S3": ("iid", steps3), "S4": ("ar1", steps3), "S5": ("semi", steps3), "S5effect": ("dayeffect", steps1),
           "N0": ("iid", ([], [])), "D1": ("iid", ([n // 2], [0.75])), "D2": ("iid", ([n // 2], [3.0])), "D3": ("iid", ([n // 4], [1.5])), "D4": ("iid", ([3 * n // 4], [1.5])), "D6": ("t3", steps1)}
    kind, (locs, deltas) = cfg[name]
    if kind == "iid":
        e = rng.normal(0, 1, n)
    elif kind == "ar1":
        z = rng.normal(0, 1, n)
        e = np.empty(n)
        e[0] = z[0]
        for i in range(1, n):
            e[i] = PHI * e[i - 1] + math.sqrt(1 - PHI ** 2) * z[i]
    elif kind == "dayeffect":
        nd = int(dayidx.max()) + 1
        e = rng.normal(0, math.sqrt(ICC), nd)[dayidx] + rng.normal(0, math.sqrt(1 - ICC), n)
    elif kind == "t3":
        e = rng.standard_t(3, n) / math.sqrt(3.0)
    else:   # semi-synthetic: the real residuals of the fitted segmentation, rotated by whole days
        if "res" not in st:
            K, locs0 = fit(st["y"], st["feas"])
            f, _ = C.fitted(st["y"], locs0)
            r = st["y"] - f
            st["res"] = r / np.std(r)
        starts = np.flatnonzero(np.diff(np.concatenate([[-1], dayidx])) != 0)
        e = np.roll(st["res"], -int(starts[rng.integers(0, len(starts))]))
    y = e.copy()
    for l, dlt in zip(locs, deltas):
        y[l:] += dlt
    return y, list(locs)


# ------------------------------------------------------------------------------------------------ one replicate
def replicate(args):
    name, r, B, root = args
    st = structure(root)
    n = st["n"]
    rng = np.random.default_rng([SEED, zlib.crc32(name.encode()), r])
    y, planted = scenario(name, st, rng)
    K, locs = fit(y, st["feas"])
    iv = intervals(y, st["dayidx"], st["feas"], K, locs, B, SEED + r) if K else {c: [] for c in CONSTRUCTIONS}
    mt = match(planted, locs, n)
    rec = {"scenario": name, "rep": r, "kTrue": len(planted), "kHat": K, "falseBreaks": int(K > len(planted)), "constructions": {}}
    dates = st["dates"]
    for c in CONSTRUCTIONS:
        sets = iv[c]
        cov = []
        for p, loc in enumerate(planted):
            e = mt.get(p)
            s = sets[e] if (e is not None and e < len(sets)) else None
            cov.append(int(s is not None and s["lo"] <= loc <= s["hi"]))
        w = [(s["hi"] - s["lo"], (pd.Timestamp(dates[min(int(s["hi"]), n - 1)]) - pd.Timestamp(dates[min(int(s["lo"]), n - 1)])).days) for s in sets if s]
        ov = int(any(sets[j] and sets[j + 1] and sets[j]["hi"] >= sets[j + 1]["lo"] for j in range(len(sets) - 1)))
        d = {"cov": cov, "widths": w, "overlap": ov, "nUndefined": int(sum(1 for s in sets if s is None))}
        if c == "C2":
            d["lambda"] = [s["lambda"] for s in sets if s]
            d["nonContiguous"] = [int(s["nonContiguous"]) for s in sets if s]
        if c == "C1":
            d["unmatched"] = [s["unmatchedShare"] for s in sets if s]
        rec["constructions"][c] = d
    return rec


# ------------------------------------------------------------------------------------------------ aggregation and gate
def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(c - h, 4), round(c + h, 4)]


def summarise(records, n):
    out = {}
    for name in sorted({r["scenario"] for r in records}):
        rs = [r for r in records if r["scenario"] == name]
        kt = rs[0]["kTrue"]
        s = {"nReps": len(rs), "kTrue": kt, "kHatEqualsKTrueRate": round(float(np.mean([r["kHat"] == kt for r in rs])), 4), "falseBreakRate": round(float(np.mean([r["falseBreaks"] for r in rs])), 4), "constructions": {}}
        for c in CONSTRUCTIONS:
            allc = [x for r in rs for x in r["constructions"][c]["cov"]]
            cond = [x for r in rs if r["kHat"] == kt for x in r["constructions"][c]["cov"]]
            per_rep = [float(np.mean(r["constructions"][c]["cov"])) for r in rs if kt >= 1]
            wd = [w for r in rs for w in r["constructions"][c]["widths"]]
            ovs = [r["constructions"][c]["overlap"] for r in rs if r["kHat"] >= 2]
            d = {"coverageUnconditional": round(float(np.mean(per_rep)), 4) if per_rep else None, "wilsonUnconditional": wilson(sum(allc), len(allc)),
                 "nCorrectK": int(sum(1 for r in rs if r["kHat"] == kt)), "coverageConditional": round(float(np.mean(cond)), 4) if cond else None, "wilsonConditional": wilson(sum(cond), len(cond)),
                 "medianWidthDrives": round(float(np.median([w[0] for w in wd])), 2) if wd else None, "medianWidthDays": round(float(np.median([w[1] for w in wd])), 2) if wd else None,
                 "adjacentOverlapShare": round(float(np.mean(ovs)), 4) if ovs else None, "undefinedSets": int(sum(r["constructions"][c]["nUndefined"] for r in rs))}
            if c == "C2":
                lam = [v for r in rs for v in r["constructions"][c].get("lambda", [])]
                nc = [v for r in rs for v in r["constructions"][c].get("nonContiguous", [])]
                d["lambdaQuantiles"] = {q: round(float(np.percentile(lam, q)), 3) for q in (5, 50, 95)} if lam else None
                d["nonContiguousShare"] = round(float(np.mean(nc)), 4) if nc else None
            s["constructions"][c] = d
        out[name] = s
    return out


def admissibility(summ, n):
    """Spec section 4 (Rev 1.1): per construction, every core scenario must satisfy all conditions; C0 is never admissible."""
    res = {}
    for c in CONSTRUCTIONS:
        why = []
        if c == "C0":
            why.append("reference only (the M676 construction)")
        for name in CORE:
            if name not in summ:
                why.append("%s not run" % name)
                continue
            d = summ[name]["constructions"][c]
            cu, cc = d["coverageUnconditional"], d["coverageConditional"]
            if cu is None or not (0.90 <= cu <= 0.99):
                why.append("%s unconditional coverage %s outside [0.90, 0.99]" % (name, cu))
            if d["wilsonUnconditional"][0] is None or d["wilsonUnconditional"][0] < 0.85:
                why.append("%s unconditional Wilson lower bound %s < 0.85" % (name, d["wilsonUnconditional"][0]))
            if d["nCorrectK"] < 50:
                why.append("%s conditional coverage not estimable (%d replicates with the correct K)" % (name, d["nCorrectK"]))
            elif cc is None or cc < 0.90:
                why.append("%s conditional coverage %s < 0.90" % (name, cc))
            elif d["wilsonConditional"][0] is None or d["wilsonConditional"][0] < 0.85:
                why.append("%s conditional Wilson lower bound %s < 0.85" % (name, d["wilsonConditional"][0]))
            if name in ("S3", "S4"):
                if d["medianWidthDrives"] is None or d["medianWidthDrives"] > n / 8.0:
                    why.append("%s median width %s drives > n/8" % (name, d["medianWidthDrives"]))
                if d["adjacentOverlapShare"] is not None and d["adjacentOverlapShare"] > 0.10:
                    why.append("%s adjacent sets overlap in %s of replicates > 0.10" % (name, d["adjacentOverlapShare"]))
        widths = [summ[x]["constructions"][c]["medianWidthDays"] for x in CORE if x in summ and summ[x]["constructions"][c]["medianWidthDays"] is not None]
        res[c] = {"admissible": not why, "reasons": why, "meanOverCoreOfMedianWidthDays": round(float(np.mean(widths)), 2) if widths else None}
    adm = [c for c in ("C1", "C2") if res[c]["admissible"]]
    sel = min(adm, key=lambda c: (res[c]["meanOverCoreOfMedianWidthDays"], ("C1", "C2").index(c))) if adm else None
    return res, sel


def run_study(reps=200, dreps=100, B=200, workers=10, root=ROOT, out=None):
    st = structure(root)
    jobs = [(nm, r, B, root) for nm in CORE for r in range(reps)] + [(nm, r, B, root) for nm in DESCRIPTIVE for r in range(dreps)]
    if workers <= 1:
        recs = [replicate(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            recs = list(ex.map(replicate, jobs, chunksize=4))
    summ = summarise(recs, st["n"])
    adm, sel = admissibility(summ, st["n"])
    res = {"spec": SPEC, "seed": SEED, "reps": reps, "descriptiveReps": dreps, "B": B, "fingerprint": fingerprint(st, B), "scenarios": summ, "admissibility": adm, "selected": sel,
           "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
           "note": "simulated coverage in the stated scenarios at the real X2 structure; planted steps, not fitted ones; wilson bounds are on pooled planted-break counts (an approximation: breaks in one replicate are not independent)"}
    if out:
        json.dump(res, open(out, "w", encoding="utf-8"), indent=1)
    return res


def main(argv):
    reps = int(argv[argv.index("--reps") + 1]) if "--reps" in argv else 200
    dreps = int(argv[argv.index("--dreps") + 1]) if "--dreps" in argv else 100
    B = int(argv[argv.index("--B") + 1]) if "--B" in argv else 200
    workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 10
    out = argv[argv.index("--coverage") + 1] if "--coverage" in argv else None
    res = run_study(reps, dreps, B, workers, out=out)
    print(json.dumps({"selected": res["selected"], "admissibility": {c: {"admissible": v["admissible"], "n_reasons": len(v["reasons"])} for c, v in res["admissibility"].items()}}))


if __name__ == "__main__":
    main(sys.argv[1:])
