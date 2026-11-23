#!/usr/bin/env python3
"""M747 Stage 1 (spec: analyses/M747_spec.md Rev 2): knot sensitivity of a colder pack-temperature level of the M119-v2 hazard model.

A SENSITIVITY fit, never a refit: nothing in the published block, the ladder, the surfaces, the dashboard or the gate changes; the result goes to
analyses/M747_result.json only. The pipeline functions of m119v2_model.py, tools/m318_run.py and tools/m320_ladder.py are IMPORTED and not edited
(the knot overrides, the hinge and the calendar-day term live in KnotSpec below). D, its statuses and the support rules are the M320 ones.

  python tools/m747_knot_sensitivity.py run --tables TABLES717.pkl --out analyses/M747_result.json [--draws 4000] [--workers N] [--sides start stop]
  python tools/m747_knot_sensitivity.py v1  --tables TABLES717.pkl --out V1.json [--draws 4000] [--workers N]      # K0 on the 606 ladder basis vs the stored tempLadder pairs

Sets (pack-temperature term only; all other terms, interactions and the duration handling unchanged): K0 default 4 data-quantile knots (5/35/65/95 %);
K1 5 quantile knots (5/27.5/50/72.5/95 %); K2 4 fixed knots 12.5/22.5/32.5/42.5 C; K3 4 quantile knots (2.5/34/66/97.5 %); K4 K0 + cold hinge
max(0, 15 - tpack); K5 tpack linear (reported only); K6 K0 + linear calendar-day term (reported only). Verdict from K0-K4 only.
Model-derived, associational; pack temperature is confounded with season, date and pack age; F03 label of the V2 block."""
import argparse, hashlib, json, math, os, pickle, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import m119v2_model as m
import m320_ladder as L

SETS = {
    "K0": {"kind": "default"},
    "K1": {"kind": "quantile", "qs": [0.05, 0.275, 0.5, 0.725, 0.95]},
    "K2": {"kind": "fixed", "knotsC": [12.5, 22.5, 32.5, 42.5]},
    "K3": {"kind": "quantile", "qs": [0.025, 0.34, 0.66, 0.975]},
    "K4": {"kind": "default", "extra": ["hinge15"]},
    "K5": {"kind": "linear"},
    "K6": {"kind": "default", "extra": ["daynum"]},
}
VERDICT_SETS = ("K0", "K1", "K2", "K3", "K4")
DRAWS_BY_SET = {"K0": 1.0, "K1": 1.0, "K2": 1.0, "K3": 1.0, "K4": 1.0, "K5": 0.5, "K6": 0.5}     # share of the requested draws (spec C2: K5, K6 may use half)
HINGE_C = 15.0
PROFILE_GRID = np.arange(9.0, 20.5, 1.0)
CORE = ("soc", "speed", "tpack", "demand", "durationS")


class KnotSpec(m.DesignSpec):
    """m.DesignSpec with the pack-temperature knot override and the extras hinge15 / daynum. For cfg kind 'default' with no extras it reproduces m.DesignSpec exactly."""

    def __init__(self, cfg):
        super().__init__(["soc", "speed", "tpack", "demand", "logdur"], m.INTERACTIONS)
        self.cfg = cfg
        self.myextra = list(cfg.get("extra", []))

    def _extras(self, d):
        out = {}
        for e in self.myextra:
            if e == "hinge15":
                out[e] = np.maximum(0.0, HINGE_C - d["tpack"].values.astype(float))
            elif e == "daynum":
                out[e] = d["daynum"].values.astype(float) if "daynum" in d.columns else np.full(len(d), np.nan)
        return out

    def fit(self, d):
        super().fit(d)
        mu, sd = self.scale["tpack"]
        kind = self.cfg["kind"]
        if kind == "quantile":
            z = (d["tpack"].values.astype(float) - mu) / sd
            self.knots["tpack"] = np.unique(np.quantile(z[~np.isnan(z)], self.cfg["qs"]))
        elif kind == "fixed":
            self.knots["tpack"] = (np.asarray(self.cfg["knotsC"], float) - mu) / sd
        elif kind == "linear":
            self.knots["tpack"] = None
        for e, v in self._extras(d).items():
            self.centers[e] = float(np.nanmean(v))
        return self

    def transform(self, d):
        p = self._prep(d)
        mats, names = [np.ones((len(p), 1))], ["intercept"]
        basis = {}
        for t in self.terms:
            if t in self.knots:
                mu, sd = self.scale[t]
                z = (p[t].values.astype(float) - mu) / sd
                b = z.reshape(-1, 1) if self.knots[t] is None else m.rcs_basis(z, self.knots[t])[0]
                basis[t] = b
                mats.append(b); names += ["%s_%d" % (t, i) for i in range(b.shape[1])]
        for a, b in self.interactions:
            if a in basis and b in basis:
                mats.append(basis[a][:, [0]] * basis[b][:, [0]]); names.append("%s_x_%s" % (a, b))
        for e, v in self._extras(d).items():
            c = self.centers.get(e, 0.0)
            v = np.where(np.isnan(v), c, v)               # prediction frames carry no date: the centre (zero contribution)
            mats.append((v - c).reshape(-1, 1)); names.append(e)
        return np.column_stack(mats), names

    def knots_c(self):
        if self.knots.get("tpack") is None:
            return None
        mu, sd = self.scale["tpack"]
        return [round(float(mu + sd * k), 3) for k in self.knots["tpack"]]


# ---- pure statistics (importable for tests) ----
def batch_se(x, q, batch=100):
    """Monte-Carlo SE of the q-quantile by batch means (M320 rule (b): batches of 100 draws)."""
    x = np.asarray(x, float); nb = len(x) // batch
    if nb < 5:
        return float("nan")
    qs = [np.percentile(x[i * batch:(i + 1) * batch], q) for i in range(nb)]
    return float(np.std(qs, ddof=1) / math.sqrt(nb))


def status_mc(d0, x, failed, n_total):
    """M320 pair_status plus the M320 rule (b): a lower bound (percentile or basic) within 3 MC SE of delta makes the outcome BORDERLINE."""
    fin = x[np.isfinite(x)]
    if len(fin) <= 10:
        return {"D": d0, "status": "inconclusive", "failedDraws": int(failed)}
    lo, hi = np.percentile(fin, [2.5, 97.5])
    basic = 2 * d0 - hi
    st = L.pair_status(d0, lo, basic, failed, n_total)
    se_lo, se_hi = batch_se(fin, 2.5), batch_se(fin, 97.5)
    near = bool((abs(lo - L.DELTA) <= 3 * se_lo) or (abs(basic - L.DELTA) <= 3 * se_hi)) if np.isfinite(se_lo) and np.isfinite(se_hi) else False
    status = "borderline" if (near and st in ("distinct", "indistinct", "borderline")) else st
    return {"D": round(float(d0), 5), "ci95Pct": [round(float(lo), 5), round(float(hi), 5)], "basicLower": round(float(basic), 5), "bias": round(float(np.mean(fin) - d0), 5),
            "failedDraws": int(failed), "mcSeLower": round(se_lo, 5), "mcSeUpperForBasic": round(se_hi, 5), "statusM320": st, "nearDeltaWithin3Se": near, "status": status}


def verdict(statuses):
    """Spec Rev 2: robustly distinct / robustly indistinct only if ALL of K0-K4 agree; a borderline, inconclusive or mixed set gives knot-dependent."""
    s = [statuses.get(k) for k in VERDICT_SETS]
    if all(x == "distinct" for x in s):
        return "robustly distinct"
    if all(x == "indistinct" for x in s):
        return "robustly indistinct"
    return "knot-dependent"


# ---- bootstrap machinery ----
G = {}


def fit_warm(X, y, p0):
    """Same cloglog Binomial GLM as m.fit_glm (maxiter 60, tol 1e-8); the iteration starts from the point-fit coefficients of the set. The likelihood is convex, so the
    optimum does not depend on the start; the differences to a cold start are about 1e-7 in the coefficients (recorded in the result). Falls back to m.fit_glm on any failure."""
    try:
        import statsmodels.api as sm
        from statsmodels.genmod.families.links import CLogLog
        st = np.asarray(p0, float) if p0 is not None and len(p0) == X.shape[1] else None
        return sm.GLM(y, X, family=sm.families.Binomial(link=CLogLog())).fit(maxiter=60, tol=1e-8, start_params=st)
    except Exception:
        return m.fit_glm(X, y)


def _init(payload):
    G.update(payload)


def _draw(k):
    rng = np.random.default_rng(np.random.SeedSequence(entropy=42, spawn_key=(k,)))
    nd = G["nd"]
    pick = rng.integers(0, nd, nd)
    mult = np.bincount(pick, minlength=nd).astype(np.float32)
    out = {}
    try:
        idx = np.concatenate([G["day_rows"][d] for d in pick])
        df = pd.DataFrame({c: G["cols"][c][idx] for c in G["cols"]})
        n = np.tensordot(mult, G["counts"], axes=([0], [1]))
    except Exception:
        return k, {s: None for s in G["sets"]}
    for sname in G["sets"]:
        if k >= G["max_k"][sname]:
            continue
        try:
            spec = KnotSpec(SETS[sname]).fit(df)
            X, _ = spec.transform(df)
            res = fit_warm(X, df["y"].values.astype(float), G["start"].get(sname))
            if hasattr(res, "converged") and not res.converged:
                out[sname] = None; continue
            eta, nc = L.eta_block(m, spec, res.params, G["levels"], G["dem"], G["cs"], G["cv"], prof=G["prof_frame"])
            nL = len(G["levels"]); etas = eta[: nc * nL * L.NC].reshape(nc, nL, L.NC)
            D = np.full((len(G["pairs"]), nc), np.nan)
            for pi, (a, b) in enumerate(G["pairs"]):
                for ci in range(nc):
                    D[pi, ci] = L.rms_contrast(etas[ci, a], etas[ci, b], n[a], n[b])
            out[sname] = {"D": D, "prof": np.asarray(m._predict(res, spec.transform(G["prof_frame"])[0]), np.float32)}
        except Exception:
            out[sname] = None
    return k, out


def prepare_side(tbl, files=None):
    cc = tbl.dropna(subset=list(m.CORE5)).reset_index(drop=True)
    if files is not None:
        cc = cc[cc["file"].isin(files)].reset_index(drop=True)
    day = pd.to_datetime(cc["day"].astype(str).str.slice(0, 10), errors="coerce")
    cc["daynum"] = (day - day.min()).dt.days.astype(float)
    return cc


def run_side(side, cc, levels, pairs, a, label, sets=None):
    sets = sets or list(SETS)
    t0 = time.time()
    dem = [float(x) for x in np.round(np.nanpercentile(cc["demand"], [25, 50, 90]), 2)]
    cs, cv = L.cell_frame(m)
    days, day_codes = np.unique(cc["day"].values, return_inverse=True)
    nd = len(days)
    counts = L.day_cell_counts(cc, levels, day_codes, nd)
    n_pt = counts.sum(axis=1)
    med = {c: float(np.nanmedian(cc[c])) for c in ("soc", "speed")}
    prof_frame = pd.DataFrame({"soc": med["soc"], "speed": med["speed"], "tpack": PROFILE_GRID, "demand": dem[1], "durationS": 15.0})
    # point stage
    pt, info, start_params = {}, {}, {}
    for sname in sets:
        spec = KnotSpec(SETS[sname]).fit(cc)
        X, _ = spec.transform(cc)
        res = m.fit_glm(X, cc["y"].values.astype(float))
        eta, nc = L.eta_block(m, spec, res.params, levels, dem, cs, cv, prof=prof_frame)
        nL = len(levels); etas = eta[: nc * nL * L.NC].reshape(nc, nL, L.NC)
        D = np.array([[L.rms_contrast(etas[ci, i], etas[ci, j], n_pt[i], n_pt[j]) for ci in range(nc)] for i, j in pairs])
        pt[sname] = {"D": D, "prof": np.asarray(m._predict(res, spec.transform(prof_frame)[0]), float)}
        start_params[sname] = np.asarray(res.params, float)
        info[sname] = {"knotsC": spec.knots_c(), "converged": bool(getattr(res, "converged", True)), "nRows": int(len(cc))}
        print("[%s %s] point %s done %ds" % (label, side, sname, round(time.time() - t0)), flush=True)
    cols = {c: cc[c].values.astype(float) for c in list(CORE) + ["y", "daynum"]}
    day_rows = [np.where(day_codes == d)[0] for d in range(nd)]
    max_k = {s: int(round(a.draws * DRAWS_BY_SET[s])) for s in sets}
    payload = {"cols": cols, "day_rows": day_rows, "nd": nd, "levels": levels, "cs": cs, "cv": cv, "dem": dem, "pairs": pairs, "counts": counts,
               "prof_frame": prof_frame, "sets": sets, "max_k": max_k, "start": start_params}
    import multiprocessing as mp
    res_list = {}
    with mp.get_context("spawn").Pool(a.workers, initializer=_init, initargs=(payload,)) as pool:
        for k, r in pool.imap_unordered(_draw, range(a.draws), chunksize=4):
            res_list[k] = r
            if len(res_list) % 200 == 0:
                print("[%s %s] %d/%d draws, %ds" % (label, side, len(res_list), a.draws, round(time.time() - t0)), flush=True)
    names = ["primary"] + [s[0] for s in L.SEC_CELLS]
    out = {"sets": {}}
    for sname in sets:
        ks = [k for k in range(max_k[sname])]
        ok = [k for k in ks if res_list[k].get(sname) is not None]
        failed = len(ks) - len(ok)
        Dd = np.stack([res_list[k][sname]["D"] for k in ok]) if ok else np.zeros((0, len(pairs), len(names)))
        Pd = np.stack([res_list[k][sname]["prof"] for k in ok]) if ok else np.zeros((0, len(PROFILE_GRID)))
        prs = []
        for pi, (i, j) in enumerate(pairs):
            row = {"a": levels[i], "b": levels[j]}
            for ci, nm in enumerate(names):
                x = Dd[:, pi, ci] if len(ok) else np.array([])
                row[nm] = status_mc(float(pt[sname]["D"][pi, ci]), x, failed + int((~np.isfinite(x)).sum()) if len(ok) else failed, len(ks))
            cells = (n_pt[i] >= L.MIN_N) & (n_pt[j] >= L.MIN_N)
            wsum = float((n_pt[i] + n_pt[j]).sum())
            row["commonCells"] = {"nCells": int(cells.sum()), "of": int(L.NC), "atRiskShareOfCommonCells": (float((n_pt[i] + n_pt[j])[cells].sum()) / wsum) if wsum > 0 else None}
            prs.append(row)
        lo, hi = (np.percentile(Pd, [2.5, 97.5], axis=0) if len(ok) else (np.full(len(PROFILE_GRID), np.nan),) * 2)
        out["sets"][sname] = {"knotsC": info[sname]["knotsC"], "converged": info[sname]["converged"], "nDraws": len(ks), "failedDraws": failed, "failedRate": round(failed / len(ks), 5) if ks else None,
                              "pairs": prs, "profile": {"x": PROFILE_GRID.tolist(), "hazard": np.round(pt[sname]["prof"], 6).tolist(), "lo": np.round(lo, 6).tolist(), "hi": np.round(hi, 6).tolist()}}
        if len(ok) and sname in ("K0",):
            np.savez_compressed(os.path.join(os.path.dirname(a.out) or ".", "M747_draws_%s_%s.npz" % (label, side)), D=Dd) if getattr(a, "save_draws", False) else None
    out["support"] = {str(lv): L.support_stats(cc, lv) for lv in levels}
    out["secs"] = round(time.time() - t0)
    out["nDays"] = int(nd)
    out["nDaysWithEvents"] = int(pd.unique(cc["day"].values[cc["y"].values > 0]).size)
    out["atRiskSecondsTotal"] = int(len(cc))
    return out


def carried(arr, side):
    t = arr["socHysteresisV2"]["tempLadder"][side]
    mon = arr["socHysteresisV2"]["tempLadderMonitor"]["sides"][side]
    cand = float(mon["coldCandidate"]["level"])
    lv = {c["role"]: float(c["value"]) for c in t["levels"]}
    carried_levels = sorted(float(c["value"]) for c in t["levels"])
    p5 = next(float(c["snapped"]) for c in t["candidates"] if c["name"] == "P5")
    return {"candidate": cand, "carriedLevels": carried_levels, "roles": lv, "p5Level": p5, "lowestCarried": carried_levels[0]}


def pair_plan(arr, side):
    c = carried(arr, side)
    cand, low = c["candidate"], c["lowestCarried"]
    prim = (cand, low)
    if side == "start":
        sec = (cand, c["p5Level"])                    # the unshown P5-level
    else:
        high = c["roles"].get("high")
        sec = (cand, high)                            # the carried high level
    diag = (cand, 15.0)
    pl = [prim, sec, diag]
    lv = sorted({x for p in pl for x in p})
    idx = {v: i for i, v in enumerate(lv)}
    return lv, [(idx[a], idx[b]) if idx[a] < idx[b] else (idx[b], idx[a]) for a, b in pl], {"primary": prim, "secondary": sec, "diagnostic": diag}, c


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def load_tables(path):
    P = pickle.load(open(path, "rb"))
    S, T, cov, srcs, diag = P["tables"]
    return {"start": S, "stop": T}, P


def cmd_run(a):
    arr = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    tabs, P = load_tables(a.tables)
    res = {"spec": "analyses/M747_spec.md Rev 2", "label": "model-derived sensitivity fit, not a refit; associational, pack temperature confounded with season, date and pack age; F03 label of the V2 block", "sides": {}}
    for side in a.sides:
        levels, pairs, named, c = pair_plan(arr, side)
        cc = prepare_side(tabs[side])
        o = run_side(side, cc, levels, pairs, a, "717", sets=list(SETS))
        v = {nm: {s: o["sets"][s]["pairs"][pi]["primary"]["status"] for s in SETS} for pi, nm in enumerate(["primary", "secondary", "diagnostic"])}
        o.update({"levels": levels, "pairLevels": named, "carried": c, "statusBySetPrimaryCell": v, "verdict": {"primaryPair": verdict(v["primary"]), "secondaryPair": verdict(v["secondary"]), "diagnosticPair": "reported only"}})
        res["sides"][side] = o
    res["provenance"] = {"driveMasterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "scriptSha256": sha256_file(os.path.abspath(__file__)),
                         "specSha256": sha256_file(os.path.join(ROOT, "analyses", "M747_spec.md")), "tablesProv": P["prov"], "draws": a.draws, "seed": 42,
                         "m119v2ModelSha256": sha256_file(os.path.join(ROOT, "m119v2_model.py")), "m320LadderSha256": sha256_file(os.path.join(ROOT, "tools", "m320_ladder.py")),
                         "delta": round(L.DELTA, 6)}
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        json.dump(res, f, indent=1, default=str)
    print(json.dumps({s: res["sides"][s]["verdict"] for s in res["sides"]}))


def cmd_v1(a):
    """K0 on the 606 ladder basis reproduces the stored tempLadder pairs (spec V1)."""
    arr = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    cache = json.load(open(os.path.join(ROOT, "analyses", "M321_tpack_cache.json"), encoding="utf-8"))
    basis = list(cache["basis"]["files"]) if isinstance(cache["basis"].get("files"), list) else sorted(cache["basis"]["files"])
    tabs, P = load_tables(a.tables)
    out = {"basisNFiles": len(basis), "sides": {}}
    for side in a.sides:
        stored = arr["socHysteresisV2"]["tempLadder"][side]
        levels = sorted({c["value"] for c in stored["candidates"]} | set(L.LEGACY))
        pairs = [(i, j) for i in range(len(levels)) for j in range(i + 1, len(levels))]
        cc = prepare_side(tabs[side], files=set(basis))
        o = run_side(side, cc, levels, pairs, a, "606", sets=["K0"])
        rows = o["sets"]["K0"]["pairs"]
        diffs = []
        for r in stored["pairs"]:
            mine = next(x for x in rows if x["a"] == r["a"] and x["b"] == r["b"])
            for nm in ("primary",):
                diffs.append({"a": r["a"], "b": r["b"], "storedD": r[nm]["D"], "mineD": mine[nm]["D"], "dD": abs(r[nm]["D"] - mine[nm]["D"]),
                              "storedCi": r[nm].get("ci95Pct"), "mineCi": mine[nm].get("ci95Pct"), "storedStatus": r[nm]["status"], "mineStatus": mine[nm]["statusM320"]})
        out["sides"][side] = {"maxAbsDiffD": max(d["dD"] for d in diffs), "diffs": diffs, "nRows": int(len(cc)), "run": o}
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        json.dump(out, f, indent=1, default=str)
    print(json.dumps({s: out["sides"][s]["maxAbsDiffD"] for s in out["sides"]}))


def cmd_merge(a):
    """Merge per-side result files written by separate `run --sides X` calls into one result JSON."""
    out = None
    for p in a.parts:
        d = json.load(open(p, encoding="utf-8"))
        if out is None:
            out = d
        else:
            out["sides"].update(d["sides"])
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        json.dump(out, f, indent=1, default=str)
    print(json.dumps({s: out["sides"][s]["verdict"] for s in out["sides"]}))


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    mg = sp.add_parser("merge"); mg.add_argument("--parts", nargs="+", required=True); mg.add_argument("--out", required=True); mg.set_defaults(f=cmd_merge)
    for nm, fn in (("run", cmd_run), ("v1", cmd_v1)):
        p = sp.add_parser(nm); p.add_argument("--tables", required=True); p.add_argument("--out", required=True)
        p.add_argument("--draws", type=int, default=4000); p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
        p.add_argument("--sides", nargs="+", default=["start", "stop"]); p.add_argument("--save-draws", action="store_true"); p.set_defaults(f=fn)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
