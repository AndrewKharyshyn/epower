#!/usr/bin/env python3
"""M577 Rev 3 (analyses/M577_spec_rev3.md): nuisance-covariate (lrest, first) sensitivity and wild-cluster-bootstrap intervals for the step and slow terms of model A.
Analysis only: reads drive_master.csv and analyses/M577_levels_r2.json, writes analyses/M577_levels_r3.json; no payload key, no dashboard change, no label change.
Usage: python tools/m577_r3_sensitivity.py [--out PATH]"""
import argparse, hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import m573_cell_spread_step as m573            # noqa: E402
import m577_cell_spread_levels as m577          # noqa: E402

MASTER_MD5, N_FRAME, N_DAYS = "1574a8156a36c6ea4ea1dfdaafc7cc72", 559, 120
NBOOT, SEED = 4000, 42
BASE = m577.BASE
TERMS = ("step", "slow")
VARIANTS = {"A": BASE, "A-noLrest": [c for c in BASE if c != "lrest"], "A-noFirst": [c for c in BASE if c != "first"], "A-noBoth": [c for c in BASE if c not in ("lrest", "first")]}
DEGENERATE_LIMIT = 0.10
GRID_N = 241
WEBB = np.array([-np.sqrt(1.5), -1.0, -np.sqrt(0.5), np.sqrt(0.5), 1.0, np.sqrt(1.5)])


def _r(x, nd=4):
    return m577._r(x, nd)


def streams(seed=SEED, n=5):
    return [np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(n)]


def weights(rng, G, B, kind):
    """Cluster-level wild weights (G x B): Rademacher +/-1 or Webb six-point."""
    if kind == "rademacher":
        return rng.choice([-1.0, 1.0], size=(G, B))
    return rng.choice(WEBB, size=(G, B))


class WCB:
    """Wild cluster bootstrap-t for one coefficient via Frisch-Waugh-Lovell: Z = the other columns (with the constant), r_x = M_Z x_k, CR1 studentisation (G/(G-1) * (n-1)/(n-p))."""

    def __init__(self, X, y, groups, k):
        self.X, self.y, self.k = X, y, k
        self.n, self.p = X.shape
        codes, self.inv = np.unique(groups, return_inverse=True)
        self.G = len(codes)
        Z = np.delete(X, k, axis=1)
        self.Q = np.linalg.qr(Z)[0]
        self.M = lambda v: v - self.Q @ (self.Q.T @ v)
        self.xk = X[:, k]
        self.rx = self.M(self.xk)
        self.rxx = float(self.rx @ self.rx)
        self.ry = self.M(y)
        self.b = float(self.rx @ self.ry) / self.rxx
        self.e = self.ry - self.b * self.rx                     # full-model residuals
        self.c = self.G / (self.G - 1.0) * (self.n - 1.0) / (self.n - self.p)
        self.gm = np.zeros((self.G, self.n))
        self.gm[self.inv, np.arange(self.n)] = 1.0
        self.se = self._se(self.e[:, None])[0]

    def _se(self, E):
        S = self.gm @ (self.rx[:, None] * E)
        return np.sqrt(self.c * (S ** 2).sum(axis=0)) / self.rxx

    def _stat(self, A):
        """A: n x B matrix of w * u (u = the residual vector the weights multiply). Returns (b* - centre, t*)."""
        MA = A - self.Q @ (self.Q.T @ A)
        d = (self.rx @ A) / self.rxx                              # b* - centre
        Estar = MA - np.outer(self.rx, d)
        return d, d / self._se(Estar)

    def wcu(self, W):
        """Unrestricted percentile-t interval (95 %)."""
        w = W[self.inv]
        d, t = self._stat(w * self.e[:, None])
        lo, hi = np.percentile(t, [2.5, 97.5])
        return [_r(self.b - hi * self.se), _r(self.b - lo * self.se)]

    def pvalue(self, W, beta0=0.0):
        """Restricted (null-imposed) bootstrap-t p-value of H0: coefficient = beta0, with the same weight draws."""
        u0 = self.ry - beta0 * self.rx
        w = W[self.inv]
        d, t = self._stat(w * u0[:, None])
        tobs = (self.b - beta0) / self.se
        return float(np.mean(np.abs(t) >= abs(tobs) - 1e-12))

    def inversion(self, W, alpha=0.05, half_width=6.0, grid_n=GRID_N):
        """Test-inversion interval: beta0 values not rejected at `alpha` (grid; same draws at every beta0)."""
        grid = np.linspace(self.b - half_width * self.se, self.b + half_width * self.se, grid_n)
        ps = np.array([self.pvalue(W, g) for g in grid])
        keep = grid[ps >= alpha]
        if len(keep) == 0:
            return None, grid, ps
        lo, hi = float(keep.min()), float(keep.max())
        edge = bool(lo <= grid[0] + 1e-12 or hi >= grid[-1] - 1e-12)
        contiguous = bool(int(((grid >= lo - 1e-12) & (grid <= hi + 1e-12)).sum()) == len(keep))
        return {"ci95": [_r(lo), _r(hi)], "gridStep": _r(float(grid[1] - grid[0])), "atGridEdge": edge, "contiguous": contiguous, "note": "bounds are precise to the grid step only"}, grid, ps


def wcb_block(d, cols, term, rng_rad, rng_webb, group="day", B=NBOOT):
    X, y = m577.design(d, cols)
    k = 1 + cols.index(term)
    g = d[group].values
    w = WCB(X, y, g, k)
    out = {"cluster": group, "G": int(w.G), "estimate": _r(w.b), "se_cr1": _r(w.se), "draws": B}
    kinds = [("rademacher", rng_rad), ("webb", rng_webb)] if group == "day" else [("webb", rng_webb)]
    for kind, rng in kinds:
        W = weights(rng, w.G, B, kind)
        inv, _, _ = w.inversion(W)
        out[kind] = {"inversion": inv, "wcuPercentileT": w.wcu(W), "wcrPvalueZero": _r(w.pvalue(W, 0.0), 4)}
        pz = out[kind]["wcrPvalueZero"]
        out[kind]["mcSePvalue"] = _r(float(np.sqrt(pz * (1.0 - pz) / B)), 4) if pz > 0 else "p < 1/%d (no draw as extreme)" % B
    return out


def day_structure(d, term):
    day = d.groupby("day")[term].agg(["min", "max"])
    treated = int(((day["max"] > 0)).sum())
    mixed = int(((day["min"] == 0) & (day["max"] > 0)).sum()) if set(np.unique(d[term])) <= {0, 1, 0.0, 1.0} else None
    gm = d.groupby("day")[term].transform("mean")
    tot = float(((d[term] - d[term].mean()) ** 2).sum())
    return {"daysWithTerm": treated, "daysWithoutTerm": int((day["max"] == 0).sum()), "mixedDays": mixed,
            "betweenDayShare": _r(float(((gm - d[term].mean()) ** 2).sum()) / tot if tot > 0 else None, 3)}


def vif_table(d):
    t = {c: m577.vif(d, BASE, c) for c in BASE}
    out = {"vif": t, "corrLrestFirst": _r(float(np.corrcoef(d["lrest"], d["first"])[0, 1]), 3)}
    X = d[BASE].values.astype(float)
    Xs = (X - X.mean(0)) / X.std(0)
    ev = np.linalg.eigvalsh(np.corrcoef(Xs.T))
    out["conditionIndexAll"] = _r(float(np.sqrt(ev.max() / ev.min())), 2)
    rest = [c for c in BASE if c not in ("lrest", "first", "step", "slow")]
    out["partialR2OnLrestFirst"] = {}
    for t_ in TERMS:
        others = [c for c in BASE if c not in ("lrest", "first", t_)]
        Z0 = np.c_[np.ones(len(d)), d[others].values.astype(float)]
        Z1 = np.c_[Z0, d[["lrest", "first"]].values.astype(float)]
        yv = d[t_].values.astype(float)
        s0 = float(((yv - Z0 @ np.linalg.lstsq(Z0, yv, rcond=None)[0]) ** 2).sum())
        s1 = float(((yv - Z1 @ np.linalg.lstsq(Z1, yv, rcond=None)[0]) ** 2).sum())
        out["partialR2OnLrestFirst"][t_] = _r(1.0 - s1 / s0 if s0 > 0 else None, 4)
    return out


def fwl_check(d):
    """Frisch-Waugh-Lovell identity (known-answer check, not a sensitivity): step / slow coefficients of A equal those of y on {1, months, T, I, soc, socr, step, slow, resid(lrest), resid(first)}."""
    W = np.c_[np.ones(len(d)), d[["months", "T", "I", "soc", "socr"]].values.astype(float)]
    res = {c: d[c].values.astype(float) - W @ np.linalg.lstsq(W, d[c].values.astype(float), rcond=None)[0] for c in ("lrest", "first")}
    XA, y = m577.design(d, BASE)
    bA = np.linalg.lstsq(XA, y, rcond=None)[0]
    Xo = np.c_[W, d[["step", "slow"]].values.astype(float), res["lrest"], res["first"]]
    bo = np.linalg.lstsq(Xo, y, rcond=None)[0]
    diff = max(abs(bA[1 + BASE.index("step")] - bo[6]), abs(bA[1 + BASE.index("slow")] - bo[7]))
    return {"maxAbsDiff": float(diff), "passed": bool(diff < 1e-9)}


def paired_boot(d, variants, rng, n=NBOOT):
    """Day-clustered pairs bootstrap; the SAME day draws refit every variant. Returns {variant: {term: array of (variant - A)}} and the degenerate share."""
    days = d["day"].values
    u = np.unique(days)
    idx = {x: np.flatnonzero(days == x) for x in u}
    mats = {v: m577.design(d, c)[0] for v, c in variants.items()}
    y = d["y"].values.astype(float)
    ks = {v: {t: 1 + c.index(t) for t in TERMS} for v, c in variants.items()}
    out = {v: {t: [] for t in TERMS} for v in variants if v != "A"}
    deg = 0
    for _ in range(n):
        s = np.concatenate([idx[x] for x in rng.choice(u, len(u))])
        bad, coefs = False, {}
        for v, X in mats.items():
            Xs = X[s]
            if np.linalg.matrix_rank(Xs) < Xs.shape[1]:
                bad = True
                break
            coefs[v] = np.linalg.lstsq(Xs, y[s], rcond=None)[0]
        if bad:
            deg += 1
            continue
        for v in out:
            for t in TERMS:
                out[v][t].append(coefs[v][ks[v][t]] - coefs["A"][ks["A"][t]])
    return {v: {t: np.array(a) for t, a in tt.items()} for v, tt in out.items()}, deg / n


def paired_reading(arr, margin, point):
    lo95, hi95 = np.percentile(arr, [2.5, 97.5])
    lo90, hi90 = np.percentile(arr, [5, 95])
    excl = bool(lo95 > 0 or hi95 < 0)
    inside = bool(lo90 >= -margin and hi90 <= margin)
    if excl:
        r = "changes by about %.2f mV (interval %.2f, %.2f)" % (point, lo95, hi95)
        if inside:
            r += "; the 90 percent interval also lies inside +/- %.2f mV" % margin
    elif inside:
        r = "no change beyond %.2f mV detected" % margin
    else:
        r = "not resolved at this precision"
    return {"pairedDiff": _r(point), "ci95": [_r(lo95), _r(hi95)], "ci90": [_r(lo90), _r(hi90)], "margin": _r(margin), "reading": r}


def coverage_sim(nsim=400, G=30, per=3, B=299):
    """Known-answer simulation (spec KAT a/e): zero-effect outcome, day-level regressor; WCR rejection rate and the coverage of the CR2 t(G-1) and WCR-inversion intervals, independent days and AR(1) days (rho 0.5)."""
    res = {}
    for rho, name in ((0.0, "independentDays"), (0.5, "ar1Rho0.5")):
        rej = cc = cw = 0
        for s in range(nsim):
            rng = np.random.default_rng(np.random.SeedSequence([SEED, 7, int(rho * 10), s]))
            rows, u = [], 0.0
            for g in range(G):
                u = rho * u + rng.normal(0, 1.0)
                for j in range(per):
                    rows.append({"day": "d%03d" % g, "step": float(g >= G // 2), "slow": float(rng.random() < .4), "months": g / 10.0, "T": rng.uniform(15, 35), "I": rng.uniform(60, 140), "soc": rng.uniform(40, 80),
                                 "socr": rng.uniform(10, 30), "lrest": rng.uniform(0, 3), "first": float(j == 0), "y": 20 + u + rng.normal(0, 1.0)})
            dd = pd.DataFrame(rows)
            X, y = m577.design(dd, BASE)
            kk = 1 + BASE.index("step")
            w = WCB(X, y, dd["day"].values, kk)
            W = weights(rng, w.G, B, "rademacher")
            rej += int(w.pvalue(W, 0.0) < 0.05)
            f = m577.fit_term(dd, BASE, "step")
            cc += int(f["ci95"][0] <= 0 <= f["ci95"][1])
            iv, _, _ = w.inversion(W, grid_n=41)
            cw += int(iv is not None and iv["ci95"][0] <= 0 <= iv["ci95"][1])
        res[name] = {"nSim": nsim, "G": G, "draws": B, "wcrRejectionRate": _r(rej / nsim, 3), "coverageCr2T": _r(cc / nsim, 3), "coverageWcrInversion": _r(cw / nsim, 3)}
    return res


def build_frame(dm):
    d0 = m573.build_frame(dm)
    d = d0.dropna(subset=["soc", "socr", "lrest", "I_sample_period_s"]).copy()
    lo, hi = m577.common_support(d)
    return d[(d["T"] >= lo) & (d["T"] <= hi)].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M577_levels_r3.json"))
    ap.add_argument("--draws", type=int, default=NBOOT)
    ap.add_argument("--sims", type=int, default=400)
    a = ap.parse_args()
    mp = os.path.join(ROOT, "drive_master.csv")
    md5 = hashlib.md5(open(mp, "rb").read()).hexdigest()
    if md5 != MASTER_MD5:
        raise SystemExit("M577 Rev 3 STOP: master MD5 %s != %s" % (md5, MASTER_MD5))
    dm = pd.read_csv(mp)
    ins = build_frame(dm)
    if len(ins) != N_FRAME or ins["day"].nunique() != N_DAYS:
        raise SystemExit("M577 Rev 3 STOP: frame %d drives / %d days != %d / %d" % (len(ins), ins["day"].nunique(), N_FRAME, N_DAYS))
    r2 = json.load(open(os.path.join(ROOT, "analyses", "M577_levels_r2.json"), encoding="utf-8"))
    rng_pair, rng_rad, rng_webb, rng_week, _ = streams()
    out = {"milestone": "M590 (M577 Rev 3 run)", "spec": "analyses/M577_spec_rev3.md", "masterMd5": md5, "frame": {"nDrives": int(len(ins)), "nDays": int(ins["day"].nunique())},
           "seedSequence": SEED, "draws": a.draws, "streams": ["pairedBootstrap", "wcbRademacher", "wcbWebb", "wcbWeek", "reserved"]}
    for nm, p in (("specSha256", "analyses/M577_spec_rev3.md"), ("specRev2Sha256", "analyses/M577_spec_rev2.md"), ("specRev1Sha256", "analyses/M577_spec.md"), ("scriptSha256", "tools/m577_r3_sensitivity.py")):
        out[nm] = hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest()
    out["vifTable"] = vif_table(ins)
    out["fwlCheck"] = fwl_check(ins)
    if not out["fwlCheck"]["passed"]:
        raise SystemExit("M577 Rev 3 STOP: FWL identity failed %s" % out["fwlCheck"])
    # A reproduction: the unchanged Rev 2 code (m577.run) on the CURRENT master. The stored analyses/M577_levels_r2.json predates the M585 regime-reader change (one drive moved slow -> fast, which enters the `slow` covariate), so it is compared and the difference recorded, not used as the identity.
    A = {t: m577.fit_term(ins, BASE, t) for t in TERMS}
    cur = m577.run(dm)
    rep = {t: (A[t]["est"] == cur["modelA"]["terms"][t]["est"] and A[t]["ci95"] == cur["modelA"]["terms"][t]["ci95"]) for t in TERMS}
    out["reproducesRev2CodeOnCurrentMaster"] = rep
    if not all(rep.values()):
        raise SystemExit("M577 Rev 3 STOP: model A does not reproduce m577.run on the current master")
    out["storedRev2FileDifference"] = {t: {"storedEst": r2["modelA"]["terms"][t]["est"], "storedCi95": r2["modelA"]["terms"][t]["ci95"], "currentEst": A[t]["est"], "currentCi95": A[t]["ci95"], "storedLabel": r2["labels"][t]["label"], "currentLabel": cur["labels"][t]["label"]} for t in TERMS}
    margins = {t: float(cur["labels"][t]["mde80_A"]) for t in TERMS}
    out["labelsRev2CodeCurrentMaster"] = {t: cur["labels"][t]["label"] for t in TERMS}
    # variants
    fits = {v: {t: m577.fit_term(ins, c, t) for t in TERMS} for v, c in VARIANTS.items()}
    diffs, deg = paired_boot(ins, VARIANTS, rng_pair, a.draws)
    out["variants"] = {"degenerateShare": _r(deg, 4), "evaluable": bool(deg <= DEGENERATE_LIMIT), "fits": {}}
    for v in VARIANTS:
        out["variants"]["fits"][v] = {}
        for t in TERMS:
            f = fits[v][t]
            row = {"est": f["est"], "ci95": f["ci95"], "ciSatterthwaite": f["ciSatterthwaite"], "dfSatterthwaite": f["dfSatterthwaite"], "excludesZero": m577.excl(f["ci95"])}
            if v != "A" and deg <= DEGENERATE_LIMIT:
                row["paired"] = paired_reading(diffs[v][t], margins[t], fits[v][t]["est"] - fits["A"][t]["est"])
            out["variants"]["fits"][v][t] = row
    # wild cluster bootstrap
    out["wildClusterBootstrap"] = {}
    for t in TERMS:
        blk = wcb_block(ins, BASE, t, rng_rad, rng_webb, "day", a.draws)
        blk["cr2Ci95"], blk["cr2CiSatterthwaite"] = A[t]["ci95"], A[t]["ciSatterthwaite"]
        inv = (blk["rademacher"]["inversion"] or {}).get("ci95")
        blk["intervalDependent"] = (None if inv is None else bool(m577.excl(A[t]["ci95"]) != m577.excl(inv)))
        blk["dayStructure"] = day_structure(ins, t)
        blk["weekSensitivity"] = wcb_block(ins.assign(wk=ins["wk"].astype(str)), BASE, t, rng_rad, rng_week, "wk", a.draws)
        out["wildClusterBootstrap"][t] = blk
    for tt in TERMS:
        b_ = out["wildClusterBootstrap"][tt]
        procs = {"cr2T": A[tt]["ci95"], "cr2Satterthwaite": A[tt]["ciSatterthwaite"], "dayWcrInversion": (b_["rademacher"]["inversion"] or {}).get("ci95"), "dayWcuPercentileT": b_["rademacher"]["wcuPercentileT"],
                 "weekWcrInversionWebb": (b_["weekSensitivity"]["webb"]["inversion"] or {}).get("ci95")}
        for v in ("A-noLrest", "A-noFirst", "A-noBoth"):
            procs[v + "_cr2T"] = out["variants"]["fits"][v][tt]["ci95"]
        b_["proceduresIncludingZero"] = sorted(k for k, ci in procs.items() if ci is not None and ci[0] <= 0 <= ci[1])
        b_["proceduresExcludingZero"] = sorted(k for k, ci in procs.items() if ci is not None and not (ci[0] <= 0 <= ci[1]))
        b_["note"] = "descriptive list, not a label"
    out["simulation"] = coverage_sim(a.sims)
    out["multiplicity"] = "3 paired variants (A-noLrest, A-noFirst, A-noBoth; the spec's 4 counts the reference A) x 2 terms plus 2 terms x several interval types, reported as such, not adjusted"
    out["note"] = "sensitivity only: no label is changed; the day-clustered wild bootstrap assumes independent days like CR2; variant differences are omitted-covariate projections"
    assert hashlib.md5(open(mp, "rb").read()).hexdigest() == md5, "drive_master.csv changed: STOP"
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({"fwl": out["fwlCheck"], "vif": out["vifTable"]["vif"], "variants": {v: {t: (x.get("paired") or {}).get("reading") for t, x in tt.items()} for v, tt in out["variants"]["fits"].items()},
                      "wcb": {t: {"inv": b["rademacher"]["inversion"], "p": b["rademacher"]["wcrPvalueZero"], "flag": b["intervalDependent"]} for t, b in out["wildClusterBootstrap"].items()}}, indent=1)[:5000])


if __name__ == "__main__":
    main()
