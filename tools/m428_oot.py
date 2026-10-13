#!/usr/bin/env python3
"""M428 (spec analyses/M428_spec.md Rev 2): out-of-time evaluation of the frozen M119-v2 hazard model (external audit 2026-10-13, F08). No refit on later data.

  python tools/m428_oot.py run --tables TABLES.pkl --out analyses/M428_result.json [--boot-b 4000 --boot-seed 42 --n-basis 489]

TABLES.pkl is the output of `python tools/m318_run.py tables --n-first 578 --out TABLES.pkl` (the unchanged m119v2_model._corpus_tables pass on the staged raw_only/).
Per side (START, STOP): the declared fiveVarDur design (knots and scale learned on the BASIS rows only) is fit once on the first N master rows and applied unchanged to
the later rows; baselines B0 (basis event rate) and B1 (socOnly) are fit on the basis rows only. Uncertainty: day-clustered percentile bootstrap (cluster = calendar day)
plus a leave-one-day-out jackknife t-interval. Events are detector-derived (M231), hazards model-derived; intervals are conditional on the fitted basis model.
drive_master.csv and the raw files are only read."""
import argparse, hashlib, json, os, pickle, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
from scipy import stats as sst
import m119v2_model as m

SIDES = ("start", "stop")
PREDS = ("soc", "speed", "tpack", "demand", "durationS")        # the CORE5 raw predictors (support is judged on these)
SKILL_FLOOR = 0.0
OE_BAND = (0.80, 1.25)                                          # declared planning thresholds (spec section 6), not validated
EXCESS_PP_MAX = 10.0
TOL = {"countsRel": 0.01, "blockedCvLogLossRel": 0.02, "surfaceMax": 0.005, "surfaceMedian": 0.0005}   # declared planning tolerances (spec 3.3)
TPACK_BANDS = (10.0, 20.0, 30.0, 40.0)
MIN_EVENTS_PER_DRIVE = 3
BLOCK_COUNTS = {"start": ("nStartAtRisk", "nStartEvents"), "stop": ("nStopAtRisk", "nStopEvents")}
STAT_KEYS = ("OE", "skillVsB0", "skillVsB1", "dLogLossB1minusModel", "prAuc", "lift")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def _ll_vec(y, p):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


class Pieces:
    """Per-day additive sufficient statistics of a set of later rows plus the arrays PR-AUC needs."""

    def __init__(self, day, y, p, p0, p1):
        self.day, self.y, self.p = np.asarray(day), np.asarray(y, float), np.asarray(p, float)
        self.days = list(pd.unique(self.day))
        code = {d: i for i, d in enumerate(self.days)}
        di = np.array([code[d] for d in self.day])
        nd = len(self.days)
        bc = lambda w: np.bincount(di, weights=w, minlength=nd)
        self.n = bc(np.ones(len(self.y)))
        self.ev = bc(self.y)
        self.exp = bc(self.p)
        self.ll = bc(_ll_vec(self.y, self.p))
        self.ll0 = bc(_ll_vec(self.y, np.asarray(p0, float)))
        self.ll1 = bc(_ll_vec(self.y, np.asarray(p1, float)))
        self.br = bc((self.p - self.y) ** 2)
        pbar = self.ev.sum() / self.n.sum()                     # descriptive: constant at the LATER-period rate
        self.llL = bc(_ll_vec(self.y, np.full(len(self.y), pbar)))
        self.idx = [np.where(di == i)[0] for i in range(nd)]
        self.undefined = 0

    def additive(self, pick):
        s = lambda a: a[pick].sum()
        n, ev, ex = s(self.n), s(self.ev), s(self.exp)
        ll, ll0, ll1 = s(self.ll), s(self.ll0), s(self.ll1)
        return {"prevalence": ev / n, "OE": (ev / ex) if (ex > 0 and ev > 0) else np.nan, "logLoss": ll / n,
                "skillVsB0": 1 - ll / ll0 if ll0 > 0 else np.nan, "skillVsB1": 1 - ll / ll1 if ll1 > 0 else np.nan,
                "dLogLossB1minusModel": (ll1 - ll) / n, "brier": s(self.br) / n,
                "skillVsLaterConstant": 1 - ll / s(self.llL) if s(self.llL) > 0 else np.nan}

    def prauc(self, pick):
        ii = np.concatenate([self.idx[i] for i in pick])
        y, p = self.y[ii], self.p[ii]
        pa = m.pr_auc(y, p)
        prev = y.mean()
        return (pa, pa / prev if pa is not None and prev > 0 else None)

    def point(self):
        pick = np.arange(len(self.days))
        a = self.additive(pick)
        pa, lift = self.prauc(pick)
        sl, ic = m.calibration(self.y, self.p)
        a.update(prAuc=pa, lift=lift, calSlope=sl, calIntercept=ic)
        return a

    def ess_days(self):
        return float(self.n.sum() ** 2 / (self.n ** 2).sum())

    def boot(self, b, seed):
        rng = np.random.default_rng(seed)
        nd = len(self.days)
        out = {k: [] for k in STAT_KEYS}
        undefined = {"OE": 0, "prAuc": 0}
        for _ in range(b):
            pick = rng.integers(0, nd, nd)
            a = self.additive(pick)
            for k in ("OE", "skillVsB0", "skillVsB1", "dLogLossB1minusModel"):
                out[k].append(a[k])
            if not np.isfinite(a["OE"]):
                undefined["OE"] += 1
            pa, lift = self.prauc(pick)
            if pa is None:
                undefined["prAuc"] += 1
            else:
                out["prAuc"].append(pa); out["lift"].append(lift)
        res = {}
        for k, v in out.items():
            v = np.array([x for x in v if x is not None and np.isfinite(x)])
            res[k] = [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if len(v) else None
        return res, undefined

    def jackknife(self, keys=("OE", "skillVsB0", "dLogLossB1minusModel")):
        """Leave-one-day-out jackknife (pseudo-values) t-interval, G-1 df, and the leave-one-day-out range."""
        nd = len(self.days)
        full = self.additive(np.arange(nd))
        res = {}
        for k in keys:
            loo = np.array([self.additive(np.array([i for i in range(nd) if i != d]))[k] for d in range(nd)])
            ps = nd * full[k] - (nd - 1) * loo
            ok = np.isfinite(ps)
            if ok.sum() < 3:
                res[k] = {"tInterval": None, "leaveOneDayOutRange": None}
                continue
            mu, se = ps[ok].mean(), ps[ok].std(ddof=1) / np.sqrt(ok.sum())
            t = sst.t.ppf(0.975, ok.sum() - 1)
            res[k] = {"tInterval": [float(mu - t * se), float(mu + t * se)], "leaveOneDayOutRange": [float(np.nanmin(loo)), float(np.nanmax(loo))], "df": int(ok.sum() - 1)}
        return res


def fit_frozen(tr, link="cloglog"):
    """The declared fiveVarDur design exactly as _final_fit builds it, on the BASIS rows only; B1 = socOnly on the same rows."""
    spec = m.DesignSpec(["soc", "speed", "tpack", "demand", "logdur"], m.INTERACTIONS).fit(tr)
    X, _ = spec.transform(tr)
    y = tr["y"].values.astype(float)
    res = m.fit_glm(X, y, groups=tr["day"].values, link=link)
    spec1 = m.DesignSpec(["soc"], []).fit(tr)
    X1, _ = spec1.transform(tr)
    res1 = m.fit_glm(X1, y, groups=tr["day"].values, link=link)
    return spec, res, spec1, res1, float(y.mean())


def support_excess(tr, te):
    """Per predictor: share outside the basis [P1,P99] on the BASIS rows (its own share) and on the LATER rows; excess in percentage points (point estimates, row-weighted).
    The union over predictors is reported separately and has no decision role."""
    per, anyb, anyl = {}, np.zeros(len(tr), bool), np.zeros(len(te), bool)
    for c in PREDS:
        v, t = tr[c].values.astype(float), te[c].values.astype(float)
        lo, hi, p1, p99 = float(np.nanmin(v)), float(np.nanmax(v)), float(np.nanpercentile(v, 1)), float(np.nanpercentile(v, 99))
        ob, ol = (v < p1) | (v > p99), (t < p1) | (t > p99)
        anyb |= ob; anyl |= ol
        per[c] = {"basisMin": lo, "basisMax": hi, "basisP1": p1, "basisP99": p99, "basisShareOutsideP1P99": float(ob.mean()), "laterShareOutsideP1P99": float(ol.mean()),
                  "excessPp": float(100 * (ol.mean() - ob.mean())), "laterShareBelowP1": float((t < p1).mean()), "laterShareAboveP99": float((t > p99).mean()),
                  "laterShareOutsideMinMax": float(((t < lo) | (t > hi)).mean())}
    return per, {"basisUnionOutsideP1P99": float(anyb.mean()), "laterUnionOutsideP1P99": float(anyl.mean())}, anyl


def d_states(skill_ci, oe_ci, per_support):
    d1 = "PASS" if (skill_ci is not None and skill_ci[0] > SKILL_FLOOR) else "FAIL"
    if oe_ci is None:
        d2 = "indeterminate"
    elif oe_ci[0] >= OE_BAND[0] and oe_ci[1] <= OE_BAND[1]:
        d2 = "within"
    elif oe_ci[1] < OE_BAND[0] or oe_ci[0] > OE_BAND[1]:
        d2 = "MATERIAL"
    else:
        d2 = "indeterminate"
    d3 = "MATERIAL" if (per_support is not None and max(v["excessPp"] for v in per_support.values()) > EXCESS_PP_MAX) else "not material"
    return d1, d2, d3


def _r(x, d=6):
    return None if x is None else (round(float(x), d) if np.isfinite(x) else None)


def _ci_round(ci):
    return None if ci is None else [round(ci[0], 5), round(ci[1], 5)]


def assess(tr, te, p, p0v, p1, b, seed, with_support=True):
    """Primary-style assessment of one set of later rows: point, percentile CI, jackknife, D-states."""
    piece = Pieces(te["day"].values, te["y"].values.astype(float), p, p0v, p1)
    pt = piece.point()
    ci, und = piece.boot(b, seed)
    jk = piece.jackknife()
    per, union, _ = support_excess(tr, te) if with_support else (None, None, None)
    d1, d2, d3 = d_states(ci["skillVsB0"], ci["OE"], per)
    jk_d1, jk_d2, _ = d_states(jk["skillVsB0"]["tInterval"], jk["OE"]["tInterval"], None)
    blk = {"nDrives": int(te["file"].nunique()), "nDays": len(piece.days), "atRiskSeconds": int(piece.n.sum()), "events": int(piece.ev.sum()), "essDays": round(piece.ess_days(), 2),
           "point": {k: _r(v) for k, v in pt.items()}, "ci95Percentile": {k: _ci_round(v) for k, v in ci.items()}, "undefinedDraws": und, "bootstrapB": b,
           "jackknife": {k: {kk: (_ci_round(vv) if isinstance(vv, list) else vv) for kk, vv in v.items()} for k, v in jk.items()},
           "states": {"D1": d1, "D2": d2, "D3": d3, "jackknifeD1": jk_d1, "jackknifeD2": jk_d2}}
    return blk, per, union


def combine(primary, s3):
    """Outcome sentence (spec section 6). primary / s3 = states dicts."""
    p, q = primary["states"], s3["states"]
    if p["D1"] == "FAIL" or p["D2"] == "MATERIAL" or p["D3"] == "MATERIAL":
        return "refit criterion met (planning threshold)", []
    notes = []
    if p["D2"] != "within":
        notes.append("D2 %s (the O/E interval is not inside the declared band)" % p["D2"])
    if (p["jackknifeD1"], p["jackknifeD2"]) != (p["D1"], p["D2"]):
        notes.append("jackknife disagrees (D1 %s, D2 %s)" % (p["jackknifeD1"], p["jackknifeD2"]))
    if s3 and (q["D1"], q["D2"], q["D3"]) != (p["D1"], p["D2"], p["D3"]):
        notes.append("dropping the shared day changes the states (D1 %s, D2 %s, D3 %s)" % (q["D1"], q["D2"], q["D3"]))
    if notes:
        return "partial: not established (few day clusters): " + "; ".join(notes), notes
    return "no material out-of-time degradation detected (planning thresholds; not equivalence)", []


def blocked_cv_logloss(tr, link="cloglog"):
    spec = m.DesignSpec(["soc", "speed", "tpack", "demand", "logdur"], m.INTERACTIONS)
    fm = m.blocked_day_folds(tr["day"].values, 5)
    pred = m.oos_predict(tr, spec, fm, link)
    ok = ~np.isnan(pred)
    return float(m.logloss(tr["y"].values.astype(float)[ok], pred[ok])), int(ok.sum())


def _flat(g, prefix=""):
    out = {}
    for k, v in g.items():
        a = np.array(v, float)
        for i, row in enumerate(a):
            for j, x in enumerate(row):
                out["%s%s/%d/%d" % (prefix, k, i, j)] = x
    return out


def surface_fidelity(spec, res, cc_basis, stored):
    new = m._surfaces(res, spec, cc_basis, temp_levels=stored["tempLevels"])
    a, b = _flat(new["grids"]), _flat(stored["grids"])
    if set(a) != set(b):
        return {"error": "grid keys differ", "nNew": len(a), "nStored": len(b)}
    d = np.array([abs(a[k] - b[k]) for k in a])
    sv = np.array([b[k] for k in a])
    return {"nCells": int(len(d)), "maxAbsDiff": float(d.max()), "medianAbsDiff": float(np.median(d)), "medianStoredHazard": float(np.median(sv)),
            "relMedianDiff": float(np.median(d) / np.median(sv)) if np.median(sv) > 0 else None}


def evaluate_side(tbl, basis_files, files_all, b=4000, seed=42, link="cloglog", block=None, side=None, sens=True):
    present = set(tbl["file"].unique())
    cc = tbl.dropna(subset=m.CORE5).reset_index(drop=True)
    isb = cc["file"].isin(set(basis_files)).values
    tr, te = cc[isb].reset_index(drop=True), cc[~isb].reset_index(drop=True)
    spec, res, spec1, res1, p0 = fit_frozen(tr, link)
    p = m._predict(res, spec.transform(te)[0])
    p1 = m._predict(res1, spec1.transform(te)[0])
    p0v = np.full(len(te), p0)
    out = {"basis": {"atRiskSecondsCompleteCase": int(len(tr)), "eventsCompleteCase": int(tr["y"].sum()), "nDays": int(tr["day"].nunique()), "nDrives": int(tr["file"].nunique()), "eventRate": round(p0, 6)},
           "skippedFilesNotInTable": {"basis": int(sum(1 for f in basis_files if f not in present)), "later": int(sum(1 for f in files_all if f not in set(basis_files) and f not in present))}}
    prim, per, union = assess(tr, te, p, p0v, p1, b, seed)
    out["primary"] = prim
    out["support"] = {"perPredictor": per, **union, "note": "tpack is not a blind case (the M321 monitor already flags W2/W3); excess = later share outside the basis [P1,P99] minus the basis's own share, in percentage points"}
    # S3: drop the day(s) shared with the basis
    shared = sorted(set(tr["day"]) & set(te["day"]))
    m3 = ~te["day"].isin(shared).values
    s3, _, _ = assess(tr, te[m3].reset_index(drop=True), p[m3], p0v[m3], p1[m3], b, seed + 3) if m3.sum() and te[m3]["day"].nunique() > 2 else ({"states": prim["states"], "note": "too few days after dropping"}, None, None)
    s3["droppedDays"] = [str(x) for x in shared]
    outcome, notes = combine(prim, s3)
    out["decision"] = {**prim["states"], "outcome": outcome, "notes": notes,
                       "thresholds": {"skillLowerBound": SKILL_FLOOR, "OEband": list(OE_BAND), "excessPpMax": EXCESS_PP_MAX, "note": "declared planning thresholds, not validated"}}
    # fidelity (spec 3.3)
    fid = {"tolerances": TOL}
    rawb = tbl[tbl["file"].isin(set(basis_files))]
    if block:
        ar, ev = BLOCK_COUNTS[side]
        fid["counts"] = {"reproducedRawTable": {"atRiskSeconds": int(len(rawb)), "events": int(rawb["y"].sum())}, "carriedBlock": {"atRiskSeconds": block.get(ar), "events": block.get(ev)}}
        if block.get(ar):
            fid["counts"]["diffAtRisk"] = int(len(rawb) - block[ar]); fid["counts"]["diffEvents"] = int(rawb["y"].sum() - block[ev])
            fid["counts"]["relDiffAtRisk"] = round(len(rawb) / block[ar] - 1, 6)
        lad = (block.get("ladder", {}) or {}).get(side, {}).get("fiveVarDur", {})
        cv_ll, cv_n = blocked_cv_logloss(tr, link)
        fid["blockedCv"] = {"reproducedLogLoss": round(cv_ll, 6), "reproducedN": cv_n, "carriedLogLoss": lad.get("logLoss"), "carriedN": lad.get("n"), "carriedEvents": lad.get("events"),
                            "relDiff": (round(cv_ll / lad["logLoss"] - 1, 6) if lad.get("logLoss") else None)}
        st = (block.get("surfaces", {}) or {}).get(side)
        fid["surfaces"] = surface_fidelity(spec, res, tr, st) if st else None
        ok = True
        c = fid.get("counts", {})
        if c.get("relDiffAtRisk") is not None and abs(c["relDiffAtRisk"]) > TOL["countsRel"]:
            ok = False
        if fid["blockedCv"]["relDiff"] is not None and abs(fid["blockedCv"]["relDiff"]) > TOL["blockedCvLogLossRel"]:
            ok = False
        sf = fid.get("surfaces") or {}
        if sf.get("error") or (sf.get("maxAbsDiff", 0) > TOL["surfaceMax"]) or (sf.get("medianAbsDiff", 0) > TOL["surfaceMedian"]):
            ok = False
        fid["withinTolerance"] = ok
        fid["evaluatedObject"] = "the frozen design as carried" if ok else "the reproduced frozen design (a tolerance failed; the displayed surfaces are not the evaluated object)"
        if not ok:
            out["decision"]["outcome"] = out["decision"]["outcome"] + " [evaluated object: the reproduced frozen design; fidelity tolerance failed]"
        ro = ((block.get("sensitivity", {}) or {}).get("rollingOrigin", {}) or {}).get(side, {}) or {}
        out["inTimeReference"] = {"rollingOriginPooled": ro.get("pooled"), "blockedCvFiveVarDur": {k: lad.get(k) for k in ("logLoss", "prAuc", "brier", "calSlope", "calIntercept", "logLossCI", "prAucCI") if k in lad},
                                  "flagOutOfTimeLogLossAboveInTimeCiUpper": (prim["point"]["logLoss"] > lad["logLossCI"][1]) if lad.get("logLossCI") else None,
                                  "note": "published carried-block values; a different protocol (blocked-day CV / forward chaining on the basis drives, different prevalence); descriptive only"}
    out["fidelity"] = fid
    if sens:
        s = {"S3_dropSharedDays": s3}
        ins = ~(support_excess(tr, te)[2])
        for name, mask in (("inSupport", ins), ("outOfSupport", ~ins)):
            if mask.sum() and te[mask]["day"].nunique() > 2:
                blk, _, _ = assess(tr, te[mask].reset_index(drop=True), p[mask], p0v[mask], p1[mask], b, seed + 1, with_support=False)
                blk["share"] = round(float(mask.mean()), 5)
                s[name] = {k: blk[k] for k in ("nDrives", "nDays", "atRiskSeconds", "events", "essDays", "point", "ci95Percentile")} | {"share": blk["share"]}
        days = sorted(pd.unique(te["day"].values)); h = len(days) // 2
        for name, dset in (("S2_firstHalf", days[:h]), ("S2_secondHalf", days[h:])):
            mask = te["day"].isin(dset).values
            if mask.sum() and len(dset) > 2:
                blk, _, _ = assess(tr, te[mask].reset_index(drop=True), p[mask], p0v[mask], p1[mask], b, seed + 2, with_support=False)
                s[name] = {k: blk[k] for k in ("nDrives", "nDays", "atRiskSeconds", "events", "essDays", "point", "ci95Percentile")} | {"days": [str(x) for x in dset], "note": "descriptive only, no D-rule"}
        # O/E by pack-temperature band
        bands, edges = [], (-np.inf,) + TPACK_BANDS + (np.inf,)
        tp = te["tpack"].values.astype(float)
        for lo, hi in zip(edges[:-1], edges[1:]):
            mk = (tp >= lo) & (tp < hi)
            ev_, ex_ = float(te["y"].values[mk].sum()), float(p[mk].sum())
            lab = ("< %g C" % hi) if lo == -np.inf else ((">= %g C" % lo) if hi == np.inf else ("%g to < %g C" % (lo, hi)))
            bands.append({"band": lab, "lo": None if lo == -np.inf else lo, "hi": None if hi == np.inf else hi, "atRiskSeconds": int(mk.sum()), "events": int(ev_),
                          "expected": round(ex_, 2), "OE": (round(ev_ / ex_, 4) if ex_ > 0 and ev_ > 0 else None)})
        s["OEbyPackTemperatureBand"] = bands
        # S1 per-drive
        perd = te.assign(_ll=_ll_vec(te["y"].values.astype(float), p), _ll0=_ll_vec(te["y"].values.astype(float), p0v), _ev=te["y"].values.astype(float)).groupby("file").agg(
            ll=("_ll", "sum"), ll0=("_ll0", "sum"), ev=("_ev", "sum"), day=("day", "first"))
        perd["skill"] = 1 - perd["ll"] / perd["ll0"]
        el = perd[perd["ev"] >= MIN_EVENTS_PER_DRIVE]
        s["S1_perDrive"] = {"minEvents": MIN_EVENTS_PER_DRIVE, "nDrivesAll": int(len(perd)), "nDrivesEligible": int(len(el)), "medianSkillVsB0": _r(el["skill"].median()) if len(el) else None,
                            "shareSkillAbove0": _r((el["skill"] > 0).mean(), 4) if len(el) else None}
        out["sensitivities"] = s
        out["perDriveEvents"] = {f: int(v) for f, v in te.groupby("file")["y"].sum().items()}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("--tables", required=True); r.add_argument("--out", required=True)
    r.add_argument("--boot-b", type=int, default=4000); r.add_argument("--boot-seed", type=int, default=42); r.add_argument("--n-basis", type=int, default=489)
    a = ap.parse_args(argv)
    os.chdir(ROOT)
    t0 = time.time()
    P = pickle.load(open(a.tables, "rb"))
    S, T, cov, srcs, diag = P["tables"]
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    files = list(dm["file"])
    if list(P["files"]) != files:
        raise SystemExit("tables were built for a different master (file list differs)")
    basis = files[:a.n_basis]
    block = json.load(open("summary_arrays.json", encoding="utf-8"))["socHysteresisV2"]
    res = {"_provenance": {"spec": "analyses/M428_spec.md", "specSha256": sha(os.path.join(ROOT, "analyses", "M428_spec.md")), "masterMd5": md5, "scriptSha256": sha(__file__),
                           "m119v2ModelSha256": sha(os.path.join(ROOT, "m119v2_model.py")), "tablesSha256": sha(a.tables), "tablesProv": P.get("prov"), "bootB": a.boot_b, "bootSeed": a.boot_seed,
                           "nBasisDrives": len(basis), "nLaterDrives": len(files) - len(basis), "lastBasisFile": files[a.n_basis - 1], "firstLaterFile": files[a.n_basis],
                           "label": "model-derived hazards, detector-derived events (M231); out-of-time evaluation of the frozen design reproduced on the basis drives from raw/ = sha256-verified originals (M366); not M299-reproducible; intervals conditional on the fitted basis model"}}
    for side, tbl in (("start", S), ("stop", T)):
        res[side] = evaluate_side(tbl, basis, files, a.boot_b, a.boot_seed, block=block, side=side)
    res["elapsedSeconds"] = round(time.time() - t0)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({s: res[s]["decision"] for s in SIDES}, indent=1))


if __name__ == "__main__":
    main()
