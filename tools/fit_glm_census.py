#!/usr/bin/env python3
"""F14 census (external audit 2026-10-13, finding F14; read-only): replay the published M119-v2 fit sequence with a FAITHFUL SPY in place of m119v2_model.fit_glm and count, for every
GLM fit, which path ran (primary, or the silent `except Exception` fallback with tol 1e-6 and scale=1.0), the exception raised, statsmodels warnings, convergence, iterations, design rank and NaN parameters.
The spy is a line-for-line copy of fit_glm (cluster covariance when groups are given, else the plain fit; on ANY exception the fallback fit) so the numbers it returns are the numbers fit_glm returns.

  python tools/fit_glm_census.py --tables TABLES.pkl --out analyses/F14_fit_glm_census.json [--n-basis 489]
  python tools/fit_glm_census.py --mode m320 --tables TABLES.pkl --out analyses/F14_m320_draw_census.json [--every 10] [--workers 8]   # the M320 pack-temperature ladder bootstrap draws (seeded sample)

TABLES.pkl: `python tools/m318_run.py tables --n-first 578 --out TABLES.pkl`. Replayed on the first N master rows (the frozen basis): run_ladder (both sides, k=5), sensitivity_screen, rolling_origin_cv
(min_train_days 40, step 5), _final_fit; and, on all rows, _final_fit (the clustered fit a refit would run). drive_master.csv and the tables are only read; nothing is written except --out."""
import argparse, collections, json, os, pickle, sys, time, warnings
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.genmod.families.links import CLogLog, Logit
import m119v2_model as m

REC = []
STAGE = ["init"]


def spy_fit_glm(X, y, groups=None, link='cloglog', maxiter=60):
    """Line-for-line copy of m119v2_model.fit_glm plus a record of what happened."""
    fam = sm.families.Binomial(link=CLogLog() if link == 'cloglog' else Logit())
    model = sm.GLM(y, X, family=fam)
    rec = {"stage": STAGE[0], "caller": sys._getframe(1).f_code.co_name, "n": int(X.shape[0]), "p": int(X.shape[1]), "events": int(np.sum(y)), "hasGroups": groups is not None,
           "nGroups": (int(len(np.unique(groups))) if groups is not None else None), "path": "primary", "exception": None}
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        try:
            if groups is not None:
                res = model.fit(cov_type='cluster', cov_kwds={'groups': groups}, maxiter=maxiter, tol=1e-8)
            else:
                res = model.fit(maxiter=maxiter, tol=1e-8)
        except Exception as e:
            rec["path"] = "fallback"
            rec["exception"] = "%s: %s" % (type(e).__name__, str(e)[:160])
            res = model.fit(maxiter=maxiter, tol=1e-6, scale=1.0)
    rec["warnings"] = sorted({type(x.message).__name__ for x in w})
    rec["converged"] = bool(getattr(res, "converged", True))
    fh = getattr(res, "fit_history", None) or {}
    rec["iterations"] = int(fh.get("iteration", -1)) if isinstance(fh, dict) else None
    rec["rank"] = int(np.linalg.matrix_rank(np.asarray(X).T @ np.asarray(X)))
    rec["rankDeficient"] = rec["rank"] < rec["p"]
    rec["nParamNaN"] = int(np.isnan(np.asarray(res.params)).sum())
    rec["covType"] = getattr(res, "cov_type", None)
    REC.append(rec)
    return res


def run(tables, files, n_basis, log):
    S, T = tables[0], tables[1]
    basis = set(files[:n_basis])
    Sb, Tb = S[S["file"].isin(basis)].reset_index(drop=True), T[T["file"].isin(basis)].reset_index(drop=True)
    m.fit_glm = spy_fit_glm
    t0 = time.time()
    out = {}
    fm = {}
    for side, tb in (("start", Sb), ("stop", Tb)):
        STAGE[0] = "ladder:" + side
        res, cc, fmap, pr = m.run_ladder(tb, k=5)
        fm[side] = fmap
        log("ladder %s done (%d fits so far, %.0f s)" % (side, len(REC), time.time() - t0))
    for side, tb, cands in (("start", Sb, ['socSince', 'coolant', 'keyOnS']), ("stop", Tb, ['socSince', 'accumChgKwh', 'coolant', 'keyOnS'])):
        STAGE[0] = "sensitivity:" + side
        m.sensitivity_screen(tb, fm[side], cands)
        log("sensitivity %s done (%d fits, %.0f s)" % (side, len(REC), time.time() - t0))
    for side, tb in (("start", Sb), ("stop", Tb)):
        STAGE[0] = "rollingOrigin:" + side
        m.rolling_origin_cv(tb, 40, 5)
        log("rolling origin %s done (%d fits, %.0f s)" % (side, len(REC), time.time() - t0))
    for side, tb in (("start", Sb), ("stop", Tb)):
        STAGE[0] = "finalFit-basis:" + side
        m._final_fit(tb)
    for side, tb in (("start", S), ("stop", T)):
        STAGE[0] = "finalFit-allRows:" + side
        m._final_fit(tb)
    log("final fits done (%d fits, %.0f s)" % (len(REC), time.time() - t0))
    return out


G320 = {}


def _init320(payload):
    G320.update(payload)
    m.fit_glm = spy_fit_glm


def _draw320(k):
    """One M320 bootstrap draw exactly as tools/m320_ladder._draw builds it (same SeedSequence, whole-day resample, design, GLM), recording what the fit did."""
    rng = np.random.default_rng(np.random.SeedSequence(entropy=42, spawn_key=(k,)))
    nd = G320["nd"]
    pick = rng.integers(0, nd, nd)
    idx = np.concatenate([G320["day_rows"][d] for d in pick])
    df = pd.DataFrame({c: G320["cols"][c][idx] for c in G320["cols"]})
    del REC[:]
    STAGE[0] = "m320:%s:%d" % (G320["side"], k)
    err = None
    try:
        spec = m.DesignSpec(['soc', 'speed', 'tpack', 'demand', 'logdur'], m.INTERACTIONS).fit(df)
        X, _ = spec.transform(df)
        m.fit_glm(X, df["y"].values.astype(float))
    except Exception as e:                                   # the production _draw swallows this silently and returns None
        err = "%s: %s" % (type(e).__name__, str(e)[:160])
    return {"k": k, "side": G320["side"], "fits": list(REC), "swallowedException": err}


def run_m320(tables, files, n_basis, every, workers, log):
    import multiprocessing as mp
    S, T = tables[0], tables[1]
    basis = set(files[:n_basis])
    out = []
    for side, tb in (("start", S[S["file"].isin(basis)]), ("stop", T[T["file"].isin(basis)])):
        cc = tb.dropna(subset=m.CORE5).reset_index(drop=True)
        days, day_codes = np.unique(cc["day"].values, return_inverse=True)
        payload = {"cols": {c: cc[c].values.astype(float) for c in ("soc", "speed", "tpack", "demand", "durationS", "y")}, "day_rows": [np.where(day_codes == d)[0] for d in range(len(days))],
                   "nd": len(days), "side": side}
        ks = list(range(0, 4000, every))
        t0 = time.time()
        with mp.get_context("spawn").Pool(workers, initializer=_init320, initargs=(payload,)) as pool:
            for i, r in enumerate(pool.imap_unordered(_draw320, ks, chunksize=2)):
                out.append(r)
                if (i + 1) % 50 == 0:
                    log("m320 %s: %d / %d draws (%.0f s)" % (side, i + 1, len(ks), time.time() - t0))
    return out


def summarise(rec):
    by = collections.defaultdict(lambda: collections.Counter())
    for r in rec:
        k = r["stage"].split(":")[0]
        by[k]["fits"] += 1
        by[k]["fallback"] += r["path"] == "fallback"
        by[k]["notConverged"] += not r["converged"]
        by[k]["rankDeficient"] += r["rankDeficient"]
        by[k]["nanParams"] += r["nParamNaN"] > 0
        by[k]["withWarnings"] += bool(r["warnings"])
        by[k]["withGroups"] += r["hasGroups"]
    allc = collections.Counter()
    for c in by.values():
        allc.update(c)
    return {"byStage": {k: dict(v) for k, v in by.items()}, "total": dict(allc),
            "warningKinds": sorted({w for r in rec for w in r["warnings"]}),
            "fallbackExceptions": sorted({r["exception"] for r in rec if r["exception"]}),
            "maxIterations": max((r["iterations"] or 0) for r in rec) if rec else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables", required=True); ap.add_argument("--out", required=True); ap.add_argument("--n-basis", type=int, default=489)
    ap.add_argument("--mode", choices=("main", "m320"), default="main"); ap.add_argument("--every", type=int, default=10); ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    P = pickle.load(open(a.tables, "rb"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    files = list(dm["file"])
    if list(P["files"]) != files:
        raise SystemExit("tables were built for a different master")
    log = lambda s: print(s, flush=True)
    if a.mode == "m320":
        draws = run_m320(P["tables"], files, a.n_basis, a.every, a.workers, log)
        fl = [f for d in draws for f in d["fits"]]
        swallowed = [d for d in draws if d["swallowedException"]]
        res = {"_provenance": {"purpose": "F14 census, M320 ladder bootstrap draws (every %d-th of 4000 per side, deterministic)" % a.every, "masterMd5": __import__("hashlib").md5(open("drive_master.csv", "rb").read()).hexdigest(),
                               "nBasis": a.n_basis, "script": "tools/fit_glm_census.py --mode m320", "note": "draws rebuilt exactly as tools/m320_ladder._draw (SeedSequence(42, spawn_key=(k,)), whole-day resample, design, GLM)"},
               "summary": {"nDraws": len(draws), "nFits": len(fl), "fallback": sum(f["path"] == "fallback" for f in fl), "notConverged": sum(not f["converged"] for f in fl), "rankDeficient": sum(f["rankDeficient"] for f in fl),
                           "nanParams": sum(f["nParamNaN"] > 0 for f in fl), "withWarnings": sum(bool(f["warnings"]) for f in fl), "swallowedExceptions": len(swallowed),
                           "fallbackExceptions": sorted({f["exception"] for f in fl if f["exception"]}), "warningKinds": sorted({w for f in fl for w in f["warnings"]}), "maxIterations": max((f["iterations"] or 0) for f in fl) if fl else None},
               "draws": draws}
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
        print(json.dumps(res["summary"], indent=1))
        return
    run(P["tables"], files, a.n_basis, log)
    res = {"_provenance": {"purpose": "F14 census: how often the silent fallback / non-convergence / rank deficiency occurred in the published M119-v2 fit sequence", "masterMd5": __import__("hashlib").md5(open("drive_master.csv", "rb").read()).hexdigest(),
                           "nBasis": a.n_basis, "script": "tools/fit_glm_census.py", "spy": "line-for-line copy of m119v2_model.fit_glm with a record"},
           "summary": summarise(REC), "fits": REC}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(res["summary"], indent=1))


if __name__ == "__main__":
    main()
