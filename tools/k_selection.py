"""M700 (spec analyses/M700_spec.md Rev 1): selection of the number of mean-shift breaks under day-level dependence (follow-up F1 of M693).

Offline planted-structure study of four rules at the real X2 drives-per-day layout. Rules: K0 fixed BIC (the M676 rule, reference), K1 design-effect BIC, K2 day-level weighted BIC,
K3 sequential day-clustered bootstrap test, K4 day-blocked cross-validation (one-SE rule). Nothing here edits a payload; a payload key is written only after a blind audit
reproduces the admissibility table (spec Rev 1 item 10). Usage: python tools/k_selection.py [--pilot] [--study OUT.json [--reps N] [--dreps N] [--workers N]]"""
import hashlib, json, math, os, sys, time, zlib
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import changepoints as C
import location_sets as LS

SPEC = "analyses/M700_spec.md"
SEED = 42
RULES = ("K0", "K1", "K2", "K3", "K4")
CORE = ("S1", "S2", "S3", "S4", "S5", "D5a", "D5b", "AI")
NULLS = ("N0", "N5", "S5null")
DESCRIPTIVE = ("D1", "D2", "D6")
B_K3 = 199                    # bootstrap draws per sequential step (study and payload alike, spec Rev 1 item 3)
STOP_EXCEED = 10              # sequential Monte Carlo stop: ceil(0.05 * (B + 1)) exceedances end the step (p cannot fall to 0.05 or below)
K3_CAP_S = 120.0              # runtime cap per replicate for K3 (pre-registered)
FOLDS = 5
PHI, ICC = LS.PHI, LS.ICC
KMAX = C.KMAX                 # 5, equal to the M676 code (spec text said 6; errata in spec Rev 1 item 13)
REC_MIN, REC_WILSON_LO, NULL_POINT, NULL_UPPER, OVERSEG_MAX = 0.80, 0.70, 0.10, 0.15, 0.10


# ------------------------------------------------------------------------------------------------ helpers
def _bic(rss, n, lam=1.0):
    out = []
    for k, r in enumerate(rss):
        out.append(None if (not np.isfinite(r) or r <= 0) else float(n * np.log(r / n) + lam * (2 * k + 1) * np.log(n)))
    return out


def lambda_hat(res, dayidx):
    """Day-cluster variance inflation (M693 Rev 1.1 formula) from residuals: [sum S_d^2 + sum S_d S_{d+1}] / sum e^2, uncentred day sums, floored at 1."""
    S = np.bincount(dayidx, weights=res, minlength=int(dayidx.max()) + 1)
    num = float((S ** 2).sum() + (S[:-1] * S[1:]).sum())
    den = float((res ** 2).sum())
    return max(1.0, num / den) if den > 0 else 1.0


def _fit_rss_locs(y, feas, kmax=KMAX):
    return C.partition(y, feas, kmax)


def rule_k0(y, dayidx, feas):
    rss, lc = _fit_rss_locs(y, feas)
    K = C.choose_k(_bic(rss, len(y)))
    return (0, []) if K is None or K == 0 else (K, list(lc[K])), rss, lc


def rule_k1(y, dayidx, feas, base):
    (K0, l0), rss, lc = base
    f, _ = C.fitted(y, l0)
    lam = lambda_hat(y - f, dayidx)
    K = C.choose_k(_bic(rss, len(y), lam))
    return ((0, []) if K is None or K == 0 else (K, list(lc[K]))), lam


def _weighted_cost(ybar, w):
    n = len(ybar)
    S = np.concatenate([[0.0], np.cumsum(w * ybar)])
    W = np.concatenate([[0.0], np.cumsum(w)])
    Q = np.concatenate([[0.0], np.cumsum(w * ybar * ybar)])
    i, j = np.arange(n + 1)[:, None], np.arange(n + 1)[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        c = (Q[j] - Q[i]) - (S[j] - S[i]) ** 2 / (W[j] - W[i])
    return np.where(j > i, np.maximum(c, 0.0), np.inf)


def rule_k2(y, dayidx, feas, base):
    """Day-level weighted DP: weights 1 / (sb2 + sw2 / m_d) from the BIC-fit residual components (method of moments); minimum segment 8 drives and 3 days at the day level."""
    (K0, l0), _, _ = base
    f, _ = C.fitted(y, l0)
    res = y - f
    nd = int(dayidx.max()) + 1
    m = np.bincount(dayidx, minlength=nd).astype(float)
    dm = np.bincount(dayidx, weights=res, minlength=nd) / m
    dmy = np.bincount(dayidx, weights=y, minlength=nd) / m
    sw2 = float(((res - dm[dayidx]) ** 2).sum() / max(1, len(y) - nd))
    sb2 = max(0.0, float(((dm ** 2) - sw2 / m).mean()))
    w = 1.0 / (sb2 + sw2 / m)
    w = w / w.mean()
    cs = np.concatenate([[0], np.cumsum(m)])
    i, j = np.arange(nd + 1)[:, None], np.arange(nd + 1)[None, :]
    dfeas = ((cs[j] - cs[i]) >= C.MIN_DRIVES) & ((j - i) >= C.MIN_DAYS)
    c = np.where(dfeas, _weighted_cost(dmy, w), np.inf)
    f1 = c[0, :].copy()
    best, arg = [f1], []
    for k in range(1, KMAX + 1):
        tot = best[-1][:, None] + c
        a = np.argmin(tot, axis=0)
        best.append(tot[a, np.arange(nd + 1)])
        arg.append(a)
    bics, locs = [], []
    for k in range(KMAX + 1):
        v = best[k][nd]
        if not np.isfinite(v) or v <= 0:
            bics.append(None); locs.append(None); continue
        pos, jj = [], nd
        for kk in range(k, 0, -1):
            ii = int(arg[kk - 1][jj]); pos.append(ii); jj = ii
        locs.append(sorted(pos))
        bics.append(float(nd * np.log(v / nd) + (2 * k + 1) * np.log(nd)))
    K = C.choose_k(bics)
    if K is None or K == 0:
        return (0, []), (sb2, sw2)
    first = np.searchsorted(dayidx, np.array(locs[K]))      # first drive of each break day (dayidx is non-decreasing)
    return (K, [int(x) for x in first]), (sb2, sw2)


def rule_k3(y, dayidx, feas, rng, t0, cap=K3_CAP_S):
    """Sequential test: K -> K+1 accepted while the RSS ratio exceeds the 95th percentile (p <= 0.05) of a day-clustered wild Rademacher bootstrap that refits both segmentations (exact DP)."""
    n = len(y)
    nd = int(dayidx.max()) + 1
    rss, lc = C.partition(y, feas, min(KMAX, 1))
    K = 0
    capped = False
    steps = []
    while K < KMAX:
        r2, l2 = C.partition(y, feas, K + 1)
        if not np.isfinite(r2[K + 1]) or r2[K + 1] <= 0:
            break
        stat = r2[K] / r2[K + 1]
        locsK = [] if K == 0 else list(l2[K])
        f, _ = C.fitted(y, locsK)
        res = y - f
        exc, draws = 0, 0
        for b in range(B_K3):
            if time.time() - t0 > cap:
                capped = True
                break
            eps = rng.choice([-1.0, 1.0], nd)[dayidx]
            ys = f + res * eps
            rb, _ = C.partition(ys, feas, K + 1)
            sb = rb[K] / rb[K + 1] if (np.isfinite(rb[K + 1]) and rb[K + 1] > 0) else 1.0
            draws += 1
            exc += int(sb >= stat)
            if exc >= STOP_EXCEED:
                break
        if capped:
            break
        p = (1 + exc) / (draws + 1)
        steps.append(round(p, 4))
        if p <= 0.05:
            K += 1
        else:
            break
    if capped:
        return None, steps, True
    _, lcK = C.partition(y, feas, K) if K > 0 else (None, None)
    return ((0, []) if K == 0 else (K, list(lcK[K]))), steps, False


def rule_k4(y, dayidx, feas, months, seed=SEED):
    """Day-blocked CV with whole days per fold (stratified by month), refit on training drives only, one-SE rule."""
    n = len(y)
    nd = int(dayidx.max()) + 1
    day_month = np.zeros(nd, int)
    for d in range(nd):
        day_month[d] = months[np.searchsorted(dayidx, d)]
    rng = np.random.default_rng(seed)
    fold_of_day = np.zeros(nd, int)
    for mo in np.unique(day_month):
        ds = np.flatnonzero(day_month == mo)
        rng.shuffle(ds)
        fold_of_day[ds] = np.arange(len(ds)) % FOLDS
    fold = fold_of_day[dayidx]
    err = np.full((FOLDS, KMAX + 1), np.nan)
    cnt = np.zeros(FOLDS)
    for fo in range(FOLDS):
        tr = np.flatnonzero(fold != fo)
        te = np.flatnonzero(fold == fo)
        ytr = y[tr]
        ftr = C._feasible(dayidx[tr])
        rss, lc = C.partition(ytr, ftr, KMAX)
        cnt[fo] = len(te)
        for k in range(KMAX + 1):
            if not np.isfinite(rss[k]):
                continue
            edges_tr = [] if k == 0 else [int(tr[x]) for x in lc[k]]
            seg_tr = np.searchsorted(np.array(edges_tr), tr, side="right") if k else np.zeros(len(tr), int)
            means = np.array([ytr[seg_tr == s].mean() if (seg_tr == s).any() else np.nan for s in range(k + 1)])
            seg_te = np.searchsorted(np.array(edges_tr), te, side="right") if k else np.zeros(len(te), int)
            err[fo, k] = float(np.mean((y[te] - means[seg_te]) ** 2))
    if np.isnan(err).any(axis=0).all():
        return (0, []), None
    ok = ~np.isnan(err).any(axis=0)
    mean = np.where(ok, np.nansum(err * cnt[:, None], axis=0) / cnt.sum(), np.inf)
    kmin = int(np.argmin(mean))
    se = float(np.std(err[:, kmin], ddof=1) / math.sqrt(FOLDS)) if ok[kmin] else 0.0
    K = min(k for k in range(KMAX + 1) if mean[k] <= mean[kmin] + se)
    rss, lc = C.partition(y, feas, KMAX)
    return ((0, []) if K == 0 or lc[K] is None else (K, list(lc[K]))), [round(float(v), 5) if np.isfinite(v) else None for v in mean]


# ------------------------------------------------------------------------------------------------ scenarios
def scenario(name, st, rng):
    """(y, planted); noise unit variance; the M693 generator for the shared scenarios, new ones defined here."""
    n, dayidx = st["n"], st["dayidx"]
    steps1, steps3 = ([n // 2], [1.5]), ([n // 4, n // 2, 3 * n // 4], [1.0, -1.0, 1.5])
    cfg = {"D5a": ("dayeffect", steps1), "D5b": ("dayeffect", steps3), "N5": ("dayeffect", ([], [])), "AI": ("ar1icc", steps1), "S5null": ("semi", ([], []))}
    if name in ("S1", "S2", "S3", "S4", "S5", "N0", "D1", "D2", "D6"):
        return LS.scenario(name, st, rng)
    kind, (locs, deltas) = cfg[name]
    nd = int(dayidx.max()) + 1
    if kind == "dayeffect":
        e = rng.normal(0, math.sqrt(ICC), nd)[dayidx] + rng.normal(0, math.sqrt(1 - ICC), n)
    elif kind == "ar1icc":
        z = rng.normal(0, 1, n)
        a = np.empty(n)
        a[0] = z[0]
        for i in range(1, n):
            a[i] = PHI * a[i - 1] + math.sqrt(1 - PHI ** 2) * z[i]
        e = math.sqrt(1 - ICC) * a + rng.normal(0, math.sqrt(ICC), nd)[dayidx]
    else:       # semi-synthetic null: real residuals of the fitted segmentation rotated by whole days
        if "res" not in st:
            K, l0 = LS.fit(st["y"], st["feas"])
            f, _ = C.fitted(st["y"], l0)
            r = st["y"] - f
            st["res"] = r / np.std(r)
        starts = np.flatnonzero(np.diff(np.concatenate([[-1], dayidx])) != 0)
        e = np.roll(st["res"], -int(starts[rng.integers(0, len(starts))]))
    y = e.copy()
    for l, dlt in zip(locs, deltas):
        y[l:] += dlt
    return y, list(locs)


def wrap_step(st, w=30):
    """Size (sd) of the seam step the circular day shift adds: |mean of the last w residuals - mean of the first w| (a property of the residuals, constant across rotations)."""
    LS.scenario("S5", st, np.random.default_rng(0))
    r = st["res"]
    return float(abs(r[-w:].mean() - r[:w].mean()))


# ------------------------------------------------------------------------------------------------ one replicate
def replicate(args):
    name, r, root = args
    st = LS.structure(root)
    n = st["n"]
    rng = np.random.default_rng([SEED, zlib.crc32(name.encode()), r])
    y, planted = scenario(name, st, rng)
    dayidx, feas = st["dayidx"], st["feas"]
    months = pd.to_datetime(st["dates"]).month.values
    rec = {"scenario": name, "rep": r, "kTrue": len(planted), "rules": {}}
    t = time.time()
    base = rule_k0(y, dayidx, feas)
    out = {"K0": (base[0], time.time() - t, {})}
    t = time.time()
    k1, lam = rule_k1(y, dayidx, feas, base)
    out["K1"] = (k1, time.time() - t, {"lambda": round(lam, 4)})
    t = time.time()
    k2, comp = rule_k2(y, dayidx, feas, base)
    out["K2"] = (k2, time.time() - t, {"sb2": round(comp[0], 4), "sw2": round(comp[1], 4)})
    t = time.time()
    k3, steps, capped = rule_k3(y, dayidx, feas, np.random.default_rng([SEED, zlib.crc32(name.encode()), r, 3]), t)
    out["K3"] = (k3 if k3 is not None else (0, []), time.time() - t, {"steps": steps, "capped": bool(capped)})
    t = time.time()
    k4, cv = rule_k4(y, dayidx, feas, months)
    out["K4"] = (k4, time.time() - t, {})
    for rule, ((K, locs), dt, extra) in out.items():
        mt = LS.match(planted, locs, n) if planted and K else {}
        right_k = K == len(planted)
        located = right_k and len(mt) == len(planted)
        if extra.get("capped"):
            located = False
        rec["rules"][rule] = {"kHat": int(K), "recovered": bool(located and not extra.get("capped")), "kRightMisplaced": bool(right_k and not located and not extra.get("capped")),
                              "overSeg": bool(K > len(planted)), "underDet": bool(K < len(planted)), "falseBreak": bool(len(planted) == 0 and K >= 1), "atKmax": bool(K >= KMAX),
                              "seconds": round(dt, 3), **extra}
    return rec


# ------------------------------------------------------------------------------------------------ aggregation and gate
def summarise(recs):
    out = {}
    for name in sorted({r["scenario"] for r in recs}):
        rr = [r for r in recs if r["scenario"] == name]
        n = len(rr)
        d = {"n": n, "kTrue": rr[0]["kTrue"], "rules": {}}
        for rule in RULES:
            xs = [r["rules"][rule] for r in rr]
            cnt = lambda k: sum(1 for x in xs if x[k])
            kd = {}
            for x in xs:
                kd[str(x["kHat"])] = kd.get(str(x["kHat"]), 0) + 1
            rate = lambda k: round(cnt(k) / n, 4)
            d["rules"][rule] = {"recovery": rate("recovered"), "recoveryWilson95": LS.wilson(cnt("recovered"), n), "kRightMisplaced": rate("kRightMisplaced"), "overSegmentation": rate("overSeg"),
                                "overSegWilson95": LS.wilson(cnt("overSeg"), n), "underDetection": rate("underDet"), "falseBreakRate": rate("falseBreak"), "falseBreakWilson95": LS.wilson(cnt("falseBreak"), n),
                                "shareAtKmax": rate("atKmax"), "kHatDistribution": dict(sorted(kd.items())), "medianSeconds": round(float(np.median([x["seconds"] for x in xs])), 3)}
            if rule == "K3":
                d["rules"][rule]["nCapped"] = int(sum(1 for x in xs if x.get("capped")))
            if rule == "K1":
                d["rules"][rule]["medianLambda"] = round(float(np.median([x["lambda"] for x in xs])), 4)
        out[name] = d
    return out


def admissibility(summ):
    adm = {}
    for rule in RULES:
        why = []
        mins = []
        for sc in CORE:
            if sc not in summ:
                why.append("%s: not run" % sc)
                continue
            s = summ[sc]["rules"][rule]
            mins.append(s["recovery"])
            if s["recovery"] < REC_MIN or (s["recoveryWilson95"][0] or 0) < REC_WILSON_LO:
                why.append("(a) %s recovery %.3f (Wilson lower %s)" % (sc, s["recovery"], s["recoveryWilson95"][0]))
            if s["overSegmentation"] > OVERSEG_MAX:
                why.append("(c) %s over-segmentation %.3f" % (sc, s["overSegmentation"]))
        for sc in NULLS:
            if sc not in summ:
                why.append("%s: not run" % sc)
                continue
            s = summ[sc]["rules"][rule]
            if s["falseBreakRate"] > NULL_POINT or (s["falseBreakWilson95"][1] or 1) > NULL_UPPER:
                why.append("(b) %s false-break rate %.3f (Wilson upper %s)" % (sc, s["falseBreakRate"], s["falseBreakWilson95"][1]))
        adm[rule] = {"admissible": not why, "reasons": why, "minCoreRecovery": round(min(mins), 4) if mins else None}
    cand = [r for r in RULES[1:] if adm[r]["admissible"]]       # K0 is the reference and is never selected
    sel = max(cand, key=lambda r: (adm[r]["minCoreRecovery"], -RULES.index(r))) if cand else None
    return adm, sel


def fingerprint(st):
    cnt = np.bincount(st["dayidx"])
    return {"n": int(st["n"]), "nDays": int(len(cnt)), "drivesPerDayHash": hashlib.sha256(cnt.astype(np.int64).tobytes()).hexdigest()[:16], "kMax": KMAX, "minDrives": C.MIN_DRIVES, "minDays": C.MIN_DAYS}


def run_study(reps=200, dreps=100, workers=10, root=ROOT, out=None):
    st = LS.structure(root)
    jobs = [(nm, r, root) for nm in CORE + NULLS for r in range(reps)] + [(nm, r, root) for nm in DESCRIPTIVE for r in range(dreps)]
    t0 = time.time()
    if workers <= 1:
        recs = [replicate(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            recs = list(ex.map(replicate, jobs, chunksize=2))
    summ = summarise(recs)
    adm, sel = admissibility(summ)
    ws = wrap_step(st)
    res = {"spec": SPEC + " Rev 1", "seed": SEED, "reps": reps, "descriptiveReps": dreps, "fingerprint": fingerprint(st), "scenarios": summ, "admissibility": adm, "selected": sel,
           "K3": {"bootstrapDrawsPerStep": B_K3, "sequentialStopExceedances": STOP_EXCEED, "runtimeCapSecondsPerReplicate": K3_CAP_S},
           "semiSyntheticWrapStepSd": round(ws, 4), "semiSyntheticWrapStepAbove0.5sd": bool(ws > 0.5),
           "runtimeSeconds": round(time.time() - t0, 1), "scriptSha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest(),
           "note": "simulated performance in the stated scenarios at the real X2 structure; planted steps, not fitted ones; K0 is the reference rule and is never selected"}
    if out:
        json.dump(res, open(out, "w", encoding="utf-8"), indent=1)
    return res


def main(argv):
    if "--pilot" in argv:
        t = time.time()
        recs = [replicate((nm, r, ROOT)) for nm in ("S1", "N0") for r in range(5)]
        print(json.dumps({"seconds": round(time.time() - t, 1), "perReplicate": round((time.time() - t) / len(recs), 2),
                          "summary": {k: {r: v["rules"][r]["recovery"] for r in RULES} for k, v in summarise(recs).items()}}))
        return
    arg = lambda k, dflt: int(argv[argv.index(k) + 1]) if k in argv else dflt
    out = argv[argv.index("--study") + 1] if "--study" in argv else None
    res = run_study(arg("--reps", 200), arg("--dreps", 100), arg("--workers", 10), out=out)
    print(json.dumps({"selected": res["selected"], "admissibility": {r: {"admissible": v["admissible"], "n_reasons": len(v["reasons"]), "minCoreRecovery": v["minCoreRecovery"]} for r, v in res["admissibility"].items()},
                      "runtimeSeconds": res["runtimeSeconds"]}))


if __name__ == "__main__":
    main(sys.argv[1:])
