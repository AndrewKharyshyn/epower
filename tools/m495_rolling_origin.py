#!/usr/bin/env python3
"""M495 (spec analyses/M495_spec.md Rev 2): rolling-origin evaluation of the M119-v2 hazard pipeline on the current corpus (Part A) and the frozen-fit artifact for its prospective evaluation (Part B).

  python tools/m495_rolling_origin.py run    --tables TABLES606.pkl --out analyses/M495_result.json [--boot-b 4000 --boot-seed 42]
  python tools/m495_rolling_origin.py freeze --tables TABLES606.pkl --out analyses/M495_frozen_fit.json
  python tools/m495_rolling_origin.py monitor                       (flag-only: counts of held-out drives and days, threshold booleans; no event counts)

TABLES606.pkl is the output of `python tools/m318_run.py tables --out TABLES606.pkl` (the unchanged m119v2_model._corpus_tables pass on the staged raw_only/). Part A reuses the engine of tools/m428_oot.py unchanged
(fit_frozen, Pieces, assess, support_excess, d_states): per fold the declared fiveVarDur design is fit on the TRAINING rows only (spline knots and scale learned there), baselines B0 (training rate) and B1 (socOnly) likewise,
and applied to the test rows without refit. Folds are cut on calendar-day boundaries with an embargo. Events are detector-derived (M231), hazards model-derived; intervals are conditional on each fold's fitted model.
Part A is out-of-time for ESTIMATION only: the design was selected on data that include the test windows (spec A1). drive_master.csv and the raw files are only read."""
import argparse, copy, hashlib, json, os, pickle, platform, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
from scipy import stats as sst

import m119v2_model as m
import m428_oot as O

SIDES = ("start", "stop")
FIRST_OFFSET, WINDOW, EMBARGO, MIN_LAST = 56, 28, 1, 14        # days: first origin after FIRST_OFFSET days, test window, embargo, shortest kept last window
MIN_TEST_EVENTS, MIN_TEST_DAYS = 100, 10                      # evaluable fold (observed driving days with at-risk rows, events)
N_TESTS = 8                                                   # about eight fold-side tests: Bonferroni sensitivity level
BONF = (100 * 0.05 / N_TESTS / 2, 100 - 100 * 0.05 / N_TESTS / 2)
HELD_OUT_AFTER = "2026-10-17"
THRESH = {"drives": 100, "days": 40, "eventsPerSide": 300, "essDays": 15}
FITS = {"n": 0}


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def fit_counted(tr, link="cloglog"):
    FITS["n"] += 2                                            # the model and the socOnly baseline
    return O.fit_frozen(tr, link)


class PiecesQ(O.Pieces):
    """Pieces with the Bonferroni-adjusted percentile interval computed from the SAME bootstrap draws as the 95 % interval."""

    def boot_levels(self, b, seed, levels=((2.5, 97.5), BONF)):
        rng = np.random.default_rng(seed)
        nd = len(self.days)
        out = {k: [] for k in ("OE", "skillVsB0", "skillVsB1", "dLogLossB1minusModel")}
        for _ in range(b):
            a = self.additive(rng.integers(0, nd, nd))
            for k in out:
                out[k].append(a[k])
        res = {}
        for k, v in out.items():
            v = np.array([x for x in v if x is not None and np.isfinite(x)])
            res[k] = [[float(np.percentile(v, lo)), float(np.percentile(v, hi))] for lo, hi in levels] if len(v) else None
        return res


# ------------------------------------------------------------------------------------------------ folds
def make_folds(days, first_offset=FIRST_OFFSET, window=WINDOW, embargo=EMBARGO, min_last=MIN_LAST):
    """Calendar-day expanding-window folds. days: iterable of ISO date strings with at-risk rows. Origin c_k = first date + first_offset + window * k; training = date <= c_k - 1 - embargo days;
    test = c_k <= date < c_k + window days; the last window ends at the last date and is kept if it spans at least min_last calendar days, else merged into the previous one."""
    d = pd.to_datetime(pd.Series(sorted(set(days))))
    t0, t1 = d.min(), d.max()
    folds, k = [], 0
    while True:
        cut = t0 + pd.Timedelta(days=first_offset + window * k)
        if cut > t1:
            break
        end = cut + pd.Timedelta(days=window)
        if end > t1 + pd.Timedelta(days=1):
            end = t1 + pd.Timedelta(days=1)
            if (end - cut).days < min_last and folds:
                folds[-1]["testEnd"] = str(end.date())            # merge into the previous window
                break
        folds.append({"k": k, "cut": str(cut.date()), "trainEnd": str((cut - pd.Timedelta(days=1 + embargo)).date()), "testStart": str(cut.date()), "testEnd": str(end.date())})
        k += 1
    return folds


def split(cc, f):
    dd = pd.to_datetime(cc["day"])
    tr = cc[dd <= pd.Timestamp(f["trainEnd"])].reset_index(drop=True)
    te = cc[(dd >= pd.Timestamp(f["testStart"])) & (dd < pd.Timestamp(f["testEnd"]))].reset_index(drop=True)
    return tr, te


def evaluable(te):
    return int(te["y"].sum()) >= MIN_TEST_EVENTS and te["day"].nunique() >= MIN_TEST_DAYS


# ------------------------------------------------------------------------------------------------ one fold
def eval_fold(cc, f, b, seed, full=True):
    tr, te = split(cc, f)
    out = {"fold": f, "train": {"nDrives": int(tr["file"].nunique()), "nDays": int(tr["day"].nunique()), "atRiskSeconds": int(len(tr)), "events": int(tr["y"].sum())},
           "test": {"nDrives": int(te["file"].nunique()), "nDays": int(te["day"].nunique()), "atRiskSeconds": int(len(te)), "events": int(te["y"].sum())}}
    assert not (set(tr["day"]) & set(te["day"])), "training and test days overlap"
    out["evaluable"] = bool(evaluable(te))
    if not out["evaluable"]:
        return out, None
    spec, res, spec1, res1, p0 = fit_counted(tr)
    p = m._predict(res, spec.transform(te)[0])
    p1 = m._predict(res1, spec1.transform(te)[0])
    p0v = np.full(len(te), p0)
    blk, per, union = O.assess(tr, te, p, p0v, p1, b, seed)
    pq = PiecesQ(te["day"].values, te["y"].values.astype(float), p, p0v, p1)
    lv = pq.boot_levels(b, seed)
    blk["ci95PercentileBonferroni"] = {k: (O._ci_round(v[1]) if v else None) for k, v in lv.items()}
    blk["bonferroniLevelPct"] = [round(BONF[0], 4), round(BONF[1], 4)]
    out["primary"] = blk
    out["support"] = {"perPredictor": per, **union}
    if full:
        ins = ~(O.support_excess(tr, te)[2])
        for name, mask in (("inSupport", ins), ("outOfSupport", ~ins)):
            if mask.sum() and te[mask]["day"].nunique() > 2:
                bk, _, _ = O.assess(tr, te[mask].reset_index(drop=True), p[mask], p0v[mask], p1[mask], b, seed + 1, with_support=False)
                out.setdefault("supportSplit", {})[name] = {k: bk[k] for k in ("nDrives", "nDays", "atRiskSeconds", "events", "essDays", "point", "ci95Percentile", "states")} | {"share": round(float(mask.mean()), 5)}
        bands, edges = [], (-np.inf,) + O.TPACK_BANDS + (np.inf,)
        tp = te["tpack"].values.astype(float)
        for lo, hi in zip(edges[:-1], edges[1:]):
            mk = (tp >= lo) & (tp < hi)
            ev_, ex_ = float(te["y"].values[mk].sum()), float(p[mk].sum())
            lab = ("< %g C" % hi) if lo == -np.inf else ((">= %g C" % lo) if hi == np.inf else ("%g to < %g C" % (lo, hi)))
            bands.append({"band": lab, "atRiskSeconds": int(mk.sum()), "events": int(ev_), "expected": round(ex_, 2), "OE": (round(ev_ / ex_, 4) if ex_ > 0 and ev_ > 0 else None)})
        out["OEbyPackTemperatureBand"] = bands
        perd = te.assign(_ll=O._ll_vec(te["y"].values.astype(float), p), _ll0=O._ll_vec(te["y"].values.astype(float), p0v), _ev=te["y"].values.astype(float)).groupby("file").agg(ll=("_ll", "sum"), ll0=("_ll0", "sum"), ev=("_ev", "sum"))
        perd["skill"] = 1 - perd["ll"] / perd["ll0"]
        el = perd[perd["ev"] >= O.MIN_EVENTS_PER_DRIVE]
        out["perDrive"] = {"minEvents": O.MIN_EVENTS_PER_DRIVE, "nDrivesEligible": int(len(el)), "medianSkillVsB0": O._r(el["skill"].median()) if len(el) else None, "shareSkillAbove0": O._r((el["skill"] > 0).mean(), 4) if len(el) else None}
    return out, (te, p, p0v, p1)


def fold_states(o):
    s = o["primary"]["states"]
    return (s["D1"], s["D2"], s["D3"])


def verdict_side(folds, embargo_states):
    """Spec A2. folds: list of fold results; embargo_states: {k: {embargo: (D1, D2, D3)}}."""
    ev = [f for f in folds if f["evaluable"]]
    if not ev:
        return {"verdict": "not assessable", "notes": ["no evaluable fold"], "flaggedOrigins": [], "extrapolationOrigins": []}
    flagged = [f["fold"]["k"] for f in ev if f["primary"]["states"]["D1"] == "FAIL" or f["primary"]["states"]["D2"] == "MATERIAL"]
    extrap = [f["fold"]["k"] for f in ev if f["primary"]["states"]["D3"] == "MATERIAL"]
    notes = []
    for f in ev:
        k, s = f["fold"]["k"], f["primary"]["states"]
        if s["D2"] != "within":
            notes.append("origin %d: D2 %s" % (k, s["D2"]))
        if (s["jackknifeD1"], s["jackknifeD2"]) != (s["D1"], s["D2"]):
            notes.append("origin %d: jackknife disagrees (D1 %s, D2 %s)" % (k, s["jackknifeD1"], s["jackknifeD2"]))
        es = embargo_states.get(k) or {}
        for e, st in es.items():
            if st != (s["D1"], s["D2"], s["D3"]):
                notes.append("origin %d: embargo %d changes the states %s" % (k, e, st))
        if s["D3"] == "MATERIAL":
            notes.append("origin %d: extrapolation (D3)" % k)
    if flagged:
        v = "degradation flagged at origin(s) %s (planning thresholds; a flag for Director review, not a refit decision)" % ", ".join(map(str, flagged))
    elif not notes:
        v = "stable across origins (planning thresholds; not equivalence)"
    else:
        v = "partial: not established (few day clusters): " + "; ".join(notes)
    return {"verdict": v, "notes": notes, "flaggedOrigins": flagged, "extrapolationOrigins": extrap}


# ------------------------------------------------------------------------------------------------ run
def load_tables(path):
    P = pickle.load(open(path, "rb"))
    S, T, cov, srcs, diag = P["tables"]
    return P, S, T


def m428_fidelity(S, T, P, files, b, seed):
    """Spec 5a / A3: the engine with the M428 split (first 489 master rows against rows 490-578 of the 578-drive snapshot) reproduces analyses/M428_result.json primary point values."""
    r = json.load(open(os.path.join(ROOT, "analyses", "M428_result.json"), encoding="utf-8"))
    f578, basis = files[:578], files[:489]
    out = {"m119v2ModelSha256": sha(os.path.join(ROOT, "m119v2_model.py")), "m428ModelSha256": r["_provenance"].get("m119v2ModelSha256"), "sides": {}}
    ok = True
    for side, tbl in (("start", S), ("stop", T)):
        t578 = tbl[tbl["file"].isin(set(f578))]
        res = O.evaluate_side(t578, basis, f578, b, seed, block=None, side=side, sens=False)
        for k in ("skillVsB0", "OE", "prevalence"):
            a, e = res["primary"]["point"][k], r[side]["primary"]["point"][k]
            same = abs(a - e) <= 1e-6
            out["sides"].setdefault(side, {})[k] = {"reproduced": a, "m428": e, "equal1e-6": bool(same)}
            ok &= bool(same)
        FITS["n"] += 2
    out["reproducesM428"] = bool(ok)
    return out


def cmd_run(a):
    t0 = time.time()
    P, S, T = load_tables(a.tables)
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    files = list(dm["file"])
    if list(P["files"]) != files:
        raise SystemExit("tables were built for a different master (file list differs)")
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    fid = m428_fidelity(S, T, P, files, a.boot_b, a.boot_seed)
    if not fid["reproducesM428"]:
        raise SystemExit("M495 STOP: the engine does not reproduce analyses/M428_result.json primary values: %r" % (fid,))
    res = {"_provenance": {"spec": "analyses/M495_spec.md", "specSha256": sha(os.path.join(ROOT, "analyses", "M495_spec.md")), "masterMd5": md5, "scriptSha256": sha(__file__),
                           "m428ScriptSha256": sha(os.path.join(ROOT, "tools", "m428_oot.py")), "m119v2ModelSha256": sha(os.path.join(ROOT, "m119v2_model.py")), "tablesSha256": sha(a.tables), "tablesProv": P.get("prov"),
                           "bootB": a.boot_b, "bootSeed": a.boot_seed, "python": platform.python_version(), "label": "model-derived hazards, detector-derived events (M231); rolling-origin evaluation of the declared pipeline design (design selected on the full data); out-of-time for estimation only"},
           "fidelityM428": fid, "geometry": {"firstOffsetDays": FIRST_OFFSET, "windowDays": WINDOW, "embargoDays": EMBARGO, "minLastWindowDays": MIN_LAST, "evaluable": {"events": MIN_TEST_EVENTS, "observedDays": MIN_TEST_DAYS}}}
    for side, tbl in (("start", S), ("stop", T)):
        cc = tbl.dropna(subset=m.CORE5).reset_index(drop=True)
        folds_def = make_folds(cc["day"].values)
        sres, pooled_parts, emb = [], [], {}
        for f in folds_def:
            o, parts = eval_fold(cc, f, a.boot_b, a.boot_seed + f["k"])
            sres.append(o)
            if parts is not None:
                pooled_parts.append(parts)
        # sensitivity S1: embargo 0 and 3 (states only)
        sens = {"S1_embargo": {}, "S2_windows": {}}
        for e in (0, 3):
            fe = make_folds(cc["day"].values, embargo=e)
            for f in fe:
                o, _ = eval_fold(cc, f, a.boot_b, a.boot_seed + f["k"], full=False)
                if o["evaluable"]:
                    emb.setdefault(f["k"], {})[e] = fold_states(o)
                    sens["S1_embargo"].setdefault(str(e), []).append({"k": f["k"], "cut": f["cut"], "states": list(fold_states(o))})
        for w in (14, 42):
            fw = make_folds(cc["day"].values, window=w)
            rows = []
            for f in fw:
                o, _ = eval_fold(cc, f, a.boot_b, a.boot_seed + 100 + f["k"], full=False)
                rows.append({"k": f["k"], "cut": f["cut"], "evaluable": o["evaluable"], "states": list(fold_states(o)) if o["evaluable"] else None, "test": o["test"]})
            sens["S2_windows"][str(w)] = rows
        # S5: the M222.1 geometry (40 training days, 5-day steps, observed days, no embargo) on the current tables
        sens["S5_m2221Geometry"] = m.rolling_origin_cv(tbl, 40, 5)
        v = verdict_side(sres, emb)
        pooled = None
        if pooled_parts:
            te_all = pd.concat([x[0] for x in pooled_parts], ignore_index=True)
            p_all = np.concatenate([x[1] for x in pooled_parts]); p0_all = np.concatenate([x[2] for x in pooled_parts]); p1_all = np.concatenate([x[3] for x in pooled_parts])
            pq = O.Pieces(te_all["day"].values, te_all["y"].values.astype(float), p_all, p0_all, p1_all)
            ci, und = pq.boot(a.boot_b, a.boot_seed + 500)
            pooled = {"nDrives": int(te_all["file"].nunique()), "nDays": len(pq.days), "events": int(pq.ev.sum()), "point": {k: O._r(x) for k, x in pq.point().items()}, "ci95Percentile": {k: O._ci_round(x) for k, x in ci.items()},
                      "note": "descriptive: pooled test rows of the evaluable folds (mixed models, training uncertainty not propagated); no decision role"}
        res[side] = {"folds": sres, "pooled": pooled, "sensitivities": sens, "verdict": v,
                     "trendTable": [{"k": f["fold"]["k"], "testStart": f["fold"]["testStart"], "testEnd": f["fold"]["testEnd"], "skillVsB0": f["primary"]["point"]["skillVsB0"], "OE": f["primary"]["point"]["OE"],
                                     "events": f["test"]["events"], "nDays": f["test"]["nDays"]} for f in sres if f["evaluable"]]}
    res["fits"] = FITS["n"]
    res["elapsedSeconds"] = round(time.time() - t0)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(res, indent=1, ensure_ascii=False, default=lambda x: x.item() if hasattr(x, "item") else str(x)) + "\n")
    print(json.dumps({s: res[s]["verdict"]["verdict"] for s in SIDES} | {"fits": res["fits"], "elapsedSeconds": res["elapsedSeconds"]}, indent=1))
    return 0


# ------------------------------------------------------------------------------------------------ freeze (Part B)
def _spec_dict(spec):
    return {"terms": spec.terms, "interactions": [list(x) for x in spec.interactions], "knots": {k: [float(x) for x in np.asarray(v).ravel()] for k, v in spec.knots.items()},
            "scale": {k: [float(v[0]), float(v[1])] for k, v in spec.scale.items()}, "centers": {k: float(v) for k, v in spec.centers.items()}}


def _fit_dict(res, names=None):
    return {"coefficients": [float(x) for x in res.params], "covarianceClusterByDay": [[float(x) for x in row] for row in np.asarray(res.cov_params())], "nObs": int(res.nobs),
            "converged": bool(getattr(res, "converged", True)), "covType": str(getattr(res, "cov_type", "")), "usedClusterCovariance": str(getattr(res, "cov_type", "")) == "cluster"}


def cmd_freeze(a):
    P, S, T = load_tables(a.tables)
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    files = list(dm["file"])
    if list(P["files"]) != files:
        raise SystemExit("tables were built for a different master (file list differs)")
    block = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["socHysteresisV2"]
    import scipy, statsmodels
    art = {"_provenance": {"spec": "analyses/M495_spec.md", "specSha256": sha(os.path.join(ROOT, "analyses", "M495_spec.md")), "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(),
                           "scriptSha256": sha(__file__), "m119v2ModelSha256": sha(os.path.join(ROOT, "m119v2_model.py")), "tablesSha256": sha(a.tables), "detector": block.get("detector"),
                           "python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__, "statsmodels": statsmodels.__version__, "pandas": pd.__version__},
           "lastTrainingDate": str(max(pd.to_datetime(S["day"]).max(), pd.to_datetime(T["day"]).max()).date()), "heldOutRule": "date > lastTrainingDate and logged after the freeze (master MD5 recorded)", "link": "cloglog",
           "design": {"terms": ["soc", "speed", "tpack", "demand", "logdur"], "interactions": [list(x) for x in m.INTERACTIONS], "splineKnots": m.DesignSpec.SPLINE_KNOTS}}
    for side, tbl, (ar, evk) in (("start", S, O.BLOCK_COUNTS["start"]), ("stop", T, O.BLOCK_COUNTS["stop"])):
        cc = tbl.dropna(subset=m.CORE5).reset_index(drop=True)
        counts_ok = {"tableAtRiskSeconds": int(len(tbl)), "tableEvents": int(tbl["y"].sum()), "carriedAtRisk": block.get(ar), "carriedEvents": block.get(evk)}
        counts_ok["exactMatch"] = (counts_ok["tableAtRiskSeconds"] == counts_ok["carriedAtRisk"]) and (counts_ok["tableEvents"] == counts_ok["carriedEvents"])
        fits = []
        for rep in range(2):
            spec, res, spec1, res1, p0 = O.fit_frozen(cc)
            fits.append((spec, res, spec1, res1, p0))
        same = bool(np.array_equal(np.asarray(fits[0][1].params), np.asarray(fits[1][1].params)) and np.array_equal(np.asarray(fits[0][3].params), np.asarray(fits[1][3].params)))
        spec, res, spec1, res1, p0 = fits[0]
        X, names = spec.transform(cc)
        tr_pred = m._predict(res, X)
        P1P99 = {c: [float(np.nanpercentile(cc[c].values.astype(float), 1)), float(np.nanpercentile(cc[c].values.astype(float), 99))] for c in O.PREDS}
        stored = (block.get("surfaces", {}) or {}).get(side)
        sfid = O.surface_fidelity(spec, res, cc, stored) if stored else {"error": "no stored surfaces"}
        sfid["withinTolerance"] = bool(not sfid.get("error") and sfid.get("maxAbsDiff", 1) <= O.TOL["surfaceMax"] and sfid.get("medianAbsDiff", 1) <= O.TOL["surfaceMedian"])
        sfid["tolerances"] = {k: O.TOL[k] for k in ("surfaceMax", "surfaceMedian")}
        sfid["note"] = "reproduced surfaces against the stored socHysteresisV2.surfaces grids (M428 tolerances); partialDependence is not separately checked"
        art[side] = {"surfaceFidelity": sfid, "trainingRows": {"atRiskSecondsCompleteCase": int(len(cc)), "events": int(cc["y"].sum()), "nDays": int(cc["day"].nunique()), "nDrives": int(cc["file"].nunique())},
                     "countFidelity": counts_ok, "bitIdenticalRefit": same, "designNames": names, "spec": _spec_dict(spec), "fit": _fit_dict(res), "baselineB0Rate": float(p0),
                     "baselineB1SocOnly": {"spec": _spec_dict(spec1), "fit": _fit_dict(res1)}, "trainingP1P99": P1P99,
                     "trainingPredictionCheck": {"meanPredicted": float(tr_pred.mean()), "sumPredicted": float(tr_pred.sum()), "firstFile": str(cc["file"].iloc[0])}}
        if not counts_ok["exactMatch"]:
            art[side]["STOP"] = "event / at-risk counts differ from the carried socHysteresisV2 block"
        if not same:
            art[side]["STOP"] = "the refit is not bit-identical"
        if not sfid["withinTolerance"]:
            art[side]["STOP"] = "the reproduced surfaces differ from the stored surfaces beyond the declared tolerances"
        if not art[side]["fit"]["usedClusterCovariance"] or not art[side]["fit"]["converged"]:
            art[side]["STOP"] = "fit_glm used its fallback or did not converge"
    stops = {s: art[s].get("STOP") for s in SIDES if art[s].get("STOP")}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(art, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"artifactSha256": sha(a.out), "stops": stops}, indent=1))
    return 1 if stops else 0


def _spec_from_dict(d):
    s = m.DesignSpec(d["terms"], [tuple(x) for x in d["interactions"]])
    s.knots = {k: np.asarray(v, float) for k, v in d["knots"].items()}
    s.scale = {k: (float(v[0]), float(v[1])) for k, v in d["scale"].items()}
    s.centers = {k: float(v) for k, v in d["centers"].items()}
    return s


def apply_frozen(art_side, df):
    """Predicted hazards of the frozen fit (artifact side block) on a table, with no refit: the saved spline knots / scale, the saved coefficients and the inverse cloglog link. Returns (model, B1 socOnly, B0 constant)."""
    spec = _spec_from_dict(art_side["spec"])
    X, _ = spec.transform(df)
    eta = np.clip(X @ np.asarray(art_side["fit"]["coefficients"], float), -30, 20)
    p = 1.0 - np.exp(-np.exp(eta))
    spec1 = _spec_from_dict(art_side["baselineB1SocOnly"]["spec"])
    X1, _ = spec1.transform(df)
    eta1 = np.clip(X1 @ np.asarray(art_side["baselineB1SocOnly"]["fit"]["coefficients"], float), -30, 20)
    return p, 1.0 - np.exp(-np.exp(eta1)), np.full(len(df), float(art_side["baselineB0Rate"]))


# ------------------------------------------------------------------------------------------------ monitor (flag-only)
def monitor_counts(dm, last_training_date=HELD_OUT_AFTER):
    d = dm[pd.to_datetime(dm["date"]) > pd.Timestamp(last_training_date)]
    return {"heldOutDrives": int(len(d)), "heldOutDays": int(d["date"].nunique())}


def cmd_monitor(a):
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    c = monitor_counts(dm)
    c["driveAndDayThresholdMet"] = bool(c["heldOutDrives"] >= THRESH["drives"] and c["heldOutDays"] >= THRESH["days"])
    c["note"] = "flag-only: counts of held-out drives and days; the event and effective-day-cluster conditions are checked by the evaluation itself; no hazard value or event count is read here"
    print(json.dumps(c))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "freeze"):
        r = sp.add_parser(name); r.add_argument("--tables", required=True); r.add_argument("--out", required=True)
        r.add_argument("--boot-b", type=int, default=4000); r.add_argument("--boot-seed", type=int, default=42)
    sp.add_parser("monitor")
    a = ap.parse_args(argv)
    os.chdir(ROOT)
    return {"run": cmd_run, "freeze": cmd_freeze, "monitor": cmd_monitor}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
