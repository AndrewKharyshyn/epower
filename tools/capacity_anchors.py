"""M699 (spec analyses/M699_spec.md Rev 1): rest-anchored capacity indicators. Additive payload block `capacityAnchors`.

E1 rest-voltage map by SoC bin / approach direction / thermal class (map of the BMS-reported SoC, possibly circular with the BMS OCV lookup).
E2 alternative anchoring of the SAME current and SoC channels: Ah of drive k over the SoC difference of the key-on anchors k and k+1 (both after a parked gap >= R).
E3 quarterly B_primary (M403 estimator) stratified by cadence and thermal class, with the pre-set step rule.
Estimated / model-derived; never state of health, never usable capacity. Nothing here edits drive_master.csv or another payload leaf."""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import capacity_basis as CB

VERSION = 1
SEED, N_BOOT = 42, 4000
R_PRIMARY, R_SENS = 2.0, (6.0, 12.0)
DSOC_PRIMARY, DSOC_SENS = 10.0, (20.0, 30.0)        # frozen in spec Rev 1 section 11.4 (the 20-point rule is not estimable)
I_LOW_A = 1.0                                       # key-on low-current threshold (current grid step 0.05 A; frozen before any result)
V_WIN_MIN_S, V_WIN_MAX_S = 120.0, 300.0
V_SLOPE_MAX_V_MIN = 0.08                            # one voltage grid step (0.16 V) over the 120 s minimum window
COVER_MIN = 0.95                                    # share of the drive current span inside integrated segments (frozen)
UNLOGGED_KM = 1.0                                   # as parked_time_budget
MARGIN_AH = CB.TOST_MARGIN_AH                       # precedent: the M403 equivalence margin
SUPPORT_DRIVES, SUPPORT_DAYS = 10, 5
SOC_BIN = 5.0
STRATA_SUPPORT = (SUPPORT_DRIVES, SUPPORT_DAYS)


# ------------------------------------------------------------------------------------------------ per-drive anchors
def anchor_extract(csv_bytes):
    """Key-on and key-off facts of one drive: first/last SoC, integrated charge over valid current segments, coverage, and the key-on voltage regression."""
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(csv_bytes)
    I = D._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    V = D._series(df, t, "V", lo=200, hi=450)
    S = D._series(df, t, "soc")
    if I is None or S is None or len(I) <= CB.MIN_SEG_SAMPLES or len(S) < 10:
        return None
    S = S[S["v"] > 0].reset_index(drop=True)
    if len(S) < 10:
        return None
    t0 = min(I["t"].iloc[0], S["t"].iloc[0])
    sec = lambda s: ((s["t"] - t0).dt.total_seconds().to_numpy(), s["v"].to_numpy(dtype=float))
    tI, Iv = sec(I)
    tS, Sv = sec(S)
    tV, Vv = sec(V) if V is not None else (np.array([]), np.array([]))
    q, covered = 0.0, 0.0
    for a, b in CB._segments(tI, CB.GAP_S):
        q += float(CB._cumint(tI[a:b], Iv[a:b])[-1])
        covered += float(tI[b - 1] - tI[a])
    span = float(tI[-1] - tI[0])
    out = {"i_key": float(np.median(Iv[:5])), "soc_first": float(np.median(Sv[:3])), "soc_last": float(np.median(Sv[-3:])), "q_ah": q, "cover": covered / span if span > 0 else 0.0, "cover_dur": covered / max(float(tI[-1]), float(tS[-1]), float(tV[-1]) if len(tV) else 0.0, 1e-9),
           "i_step": float(np.min(np.diff(np.unique(np.round(Iv, 4))))) if len(np.unique(np.round(Iv, 4))) > 1 else float("nan"),
           "s_step": float(np.min(np.diff(np.unique(np.round(Sv, 4))))) if len(np.unique(np.round(Sv, 4))) > 1 else float("nan")}
    # key-on voltage window: the first run of samples with |I| <= I_LOW_A before any traction
    v = {"n": 0, "span_s": 0.0, "mean": float("nan"), "slope_v_min": float("nan"), "ok": False}
    if len(tV) > 10:
        hi = np.where(np.abs(Iv) > I_LOW_A)[0]
        t_end = tI[hi[0]] if len(hi) else tI[-1]
        m = (tV >= tI[0]) & (tV <= min(t_end, tI[0] + V_WIN_MAX_S))
        if m.sum() >= 5:
            tt, vv = tV[m], Vv[m]
            span_v = float(tt[-1] - tt[0])
            v.update(n=int(m.sum()), span_s=span_v, mean=float(vv.mean()))
            if span_v >= V_WIN_MIN_S:
                sl = float(np.polyfit(tt - tt[0], vv, 1)[0]) * 60.0
                v.update(slope_v_min=sl, ok=bool(abs(sl) <= V_SLOPE_MAX_V_MIN))
    out["v_key"] = v
    return out


def load_anchor_records(master_files, loader):
    out = {}
    for f in master_files:
        b = loader(f)
        out[f] = anchor_extract(b) if b is not None else None
    return out


# ------------------------------------------------------------------------------------------------ day-clustered paired bootstrap
def day_stats(day_ix, X, y, n_days):
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X[:, None]
    p = X.shape[1]
    XX, Xy = np.zeros((n_days, p, p)), np.zeros((n_days, p))
    np.add.at(XX, day_ix, X[:, :, None] * X[:, None, :])
    np.add.at(Xy, day_ix, X * np.asarray(y, float)[:, None])
    return XX, Xy


def draws(st, W, tr):
    """Point and bootstrap draws (NaN for singular draws) of tr(beta) for per-day stats (XX, Xy) under weight matrix W."""
    XX, Xy = st
    p = XX.shape[1]
    A = XX.sum(0)
    if np.linalg.matrix_rank(A) < p:
        return None, np.full(len(W), np.nan)
    est = float(tr(np.linalg.solve(A, Xy.sum(0))))
    out = np.full(len(W), np.nan)
    for i, w in enumerate(W):
        a, b = np.tensordot(w, XX, 1), np.tensordot(w, Xy, 1)
        if np.linalg.matrix_rank(a) == p:
            out[i] = tr(np.linalg.solve(a, b))
    return est, out


def interval(est, dr):
    ok = dr[np.isfinite(dr)]
    if est is None or not len(ok):
        return None
    lo, hi = np.percentile(ok, [2.5, 97.5])
    return {"est": round(float(est), 4), "ci95": [round(float(lo), 4), round(float(hi), 4)], "nDrawsUsed": int(len(ok))}


def verdict(diff_ci, margin):
    """consistent: whole interval inside +-margin; disagrees: whole interval outside +-margin on one side; otherwise not established."""
    lo, hi = diff_ci
    if lo >= -margin and hi <= margin:
        return "consistent"
    if lo > margin or hi < -margin:
        return "disagrees"
    return "not established"


# ------------------------------------------------------------------------------------------------ pairs and E2
def build_pairs(d, rec, R, dsoc_min, cover_min=None):
    cover_min = COVER_MIN if cover_min is None else cover_min
    """Anchor pairs from the key-on-sorted drive frame d (columns file, date, t0u, durH, clean, unlogged, tclass)."""
    g = np.full(len(d), np.nan)
    for i in range(1, len(d)):
        p, n = d.iloc[i - 1], d.iloc[i]
        g[i] = float((n.t0u - (p.t0u + pd.Timedelta(hours=float(p.durH)))).total_seconds() / 3600.0)
    rows, why = [], {"notClean": 0, "gapShort": 0, "unloggedGuard": 0, "noRecord": 0, "coverage": 0, "dSocBelow": 0}
    for k in range(1, len(d) - 1):
        a, b = d.iloc[k], d.iloc[k + 1]
        if not (a.clean and b.clean):
            why["notClean"] += 1
            continue
        if not (g[k] >= R and g[k + 1] >= R):
            why["gapShort"] += 1
            continue
        if (pd.notna(a.unlogged) and a.unlogged > UNLOGGED_KM) or (pd.notna(b.unlogged) and b.unlogged > UNLOGGED_KM):
            why["unloggedGuard"] += 1
            continue
        ra, rb = rec.get(a.file), rec.get(b.file)
        if ra is None or rb is None:
            why["noRecord"] += 1
            continue
        if ra["cover"] < cover_min:
            why["coverage"] += 1
            continue
        ds = rb["soc_first"] - ra["soc_first"]
        if abs(ds) < dsoc_min:
            why["dSocBelow"] += 1
            continue
        rows.append({"file": a.file, "date": str(a.date), "dsoc_anchor": ds, "q_ah": ra["q_ah"], "dsoc_drive": ra["soc_last"] - ra["soc_first"],
                     "gap_reest": rb["soc_first"] - ra["soc_last"], "gap_h": float(g[k]), "gap_next_h": float(g[k + 1]), "tclass": str(a.tclass), "fast": bool(ra.get("fast", False))})
    return pd.DataFrame(rows), why


def e2_block(pairs, why, cbrecs, W, days, dix):
    """E2 with the paired difference to the M403 B_primary estimator on the same drives."""
    n_days = len(days)
    out = {"nPairs": int(len(pairs)), "nDays": int(pairs["date"].nunique()) if len(pairs) else 0, "exclusions": why}
    if len(pairs) < SUPPORT_DRIVES or out["nDays"] < SUPPORT_DAYS:
        out["status"] = "not estimable (fewer than %d pairs or %d days)" % STRATA_SUPPORT
        return out
    di = pairs["date"].map(dix).to_numpy(int)
    st = day_stats(di, pairs["dsoc_anchor"].to_numpy(), pairs["q_ah"].to_numpy(), n_days)
    e2, d2 = draws(st, W, lambda b: 100.0 * b[0])
    out["E2_anchor"] = interval(e2, d2)
    st_dr = day_stats(di, pairs["dsoc_drive"].to_numpy(), pairs["q_ah"].to_numpy(), n_days)
    e2b, d2b = draws(st_dr, W, lambda b: 100.0 * b[0])
    out["E2_withinDriveSoc"] = interval(e2b, d2b)
    out["withinDriveSocLabel"] = "sensitivity only: uses the loaded drive-end SoC (soc_last of drive k), which departs from the Rev 1 anchor geometry; not an anchor estimate"
    out["gapReestimate"] = {"medianAbsPoints": round(float(pairs["gap_reest"].abs().median()), 3), "p90AbsPoints": round(float(pairs["gap_reest"].abs().quantile(0.9)), 3),
                            "note": "SoC change across the parked gap (BMS rest re-estimate); parked current is assumed zero (no logger while parked)"}
    sub = [(dix[r.date], cbrecs[r.file]) for r in pairs.itertuples() if cbrecs.get(r.file) is not None]
    ev = CB._event_rows(sub, "primary")
    if len(ev["lev"]) and len({x for x, _ in sub}) >= 2:
        stb = day_stats(ev["day"].astype(int), np.column_stack([ev["lev"], ev["th"]]), ev["Q"], n_days)
        bp, db = draws(stb, W, lambda b: 100.0 * b[0])
        out["B_primarySameDrives"] = interval(bp, db)
        if bp is not None and e2 is not None:
            dd = d2 - db
            diff = interval(e2 - bp, dd)
            if diff:
                diff["verdict"] = verdict(diff["ci95"], MARGIN_AH)
                diff["marginAhPer100"] = MARGIN_AH
                hw = (diff["ci95"][1] - diff["ci95"][0]) / 2.0
                diff["mdeApprox80pctPower"] = round(float(1.4 * hw), 4)
                diff["verdictCaveat"] = ("the verdict is the pre-registered label under the Rev 1 margin, not a capacity finding: the anchor SoC difference includes the BMS rest re-estimate across the parked gap, and keeping only large differences "
                                         "among mostly SoC-neutral drives fills the sample with regressor error, which pulls a through-origin slope down (attenuation); differs from the existing estimator under the rule, attributed to the anchor design, not to capacity or calibration")
            out["differenceE2MinusB"] = diff
    x, y = pairs["dsoc_anchor"].to_numpy(), pairs["q_ah"].to_numpy()
    loo = [100.0 * (np.delete(x * y, i).sum() / np.delete(x * x, i).sum()) for i in range(len(x))]
    dayk = pairs["date"].to_numpy()
    lod = [100.0 * (x[dayk != dd] * y[dayk != dd]).sum() / (x[dayk != dd] ** 2).sum() for dd in sorted(set(dayk))]
    lev = x * x / (x * x).sum()
    out["leverage"] = {"leaveOnePairOutRange": [round(float(min(loo)), 4), round(float(max(loo)), 4)], "leaveOneDayOutRange": [round(float(min(lod)), 4), round(float(max(lod)), 4)],
                       "maxPairWeightShare": round(float(lev.max()), 4), "note": "the estimate is a slope through the origin, so large anchor SoC differences carry the weight"}
    out["pairs"] = [{"file": r.file, "date": r.date, "dSocAnchor": round(float(r.dsoc_anchor), 3), "ah": round(float(r.q_ah), 4), "gapH": round(float(r.gap_h), 2), "nextGapH": round(float(r.gap_next_h), 2)} for r in pairs.itertuples()]
    out["chaining"] = "adjacent pairs can share an anchor (drive k+1 is also drive k of the next pair); the day-clustered bootstrap treats days, not pairs, as independent"
    out["coverageNote"] = "drive current coverage is the share of the first-to-last current sample span inside integrated segments (gaps <= 10 s); the pair set differs from the blind audit by one pair (file 20260717_103448.csv): under the M403 segment convention (only segments with more than 20 current samples and gaps <= 10 s are integrated and counted) its coverage is 0.939, below the frozen 0.95; the re-audit counts every segment and gets 0.980, so the cause is the segment convention (which also moves the Ah slightly, about 0.01 Ah per 100 points in E2), not the denominator; sensitivity R2h_dSoc10_cover0.90 includes the pair"
    out["selectionCaveat"] = ("pairs are selected on a large anchor SoC difference, which also selects large BMS rest re-estimates across the parked gap; the anchor-based estimate is therefore biased toward a smaller Ah per 100 points "
                              "when the re-estimate is not capacity-related; the within-drive SoC variant (E2_withinDriveSoc) removes the gap but is not an anchor estimate")
    out["status"] = "exploratory-limited (small n; 'not established' is the expected verdict)"
    return out


# ------------------------------------------------------------------------------------------------ E1
def e1_block(d, rec):
    rows = []
    prev = None
    for k in range(len(d)):
        a = d.iloc[k]
        r = rec.get(a.file)
        if r is None or not a.clean or r["v_key"]["n"] == 0:
            prev = None if r is None else r
            continue
        pr = rec.get(d.iloc[k - 1].file) if k > 0 else None
        if r["v_key"]["ok"] and pr is not None:
            dirn = "from above" if pr["soc_last"] - pr["soc_first"] < 0 else "from below"
            rows.append({"date": str(a.date), "tclass": str(a.tclass), "bin": float(np.floor(r["soc_first"] / SOC_BIN) * SOC_BIN), "dir": dirn, "v": r["v_key"]["mean"]})
    f = pd.DataFrame(rows)
    nrel = int(sum(1 for k in range(len(d)) if rec.get(d.iloc[k].file) is not None and rec[d.iloc[k].file]["v_key"]["ok"]))
    out = {"nAnchorsRelaxedByRegression": nrel, "nAnchorsWithVoltageWindow": int(sum(1 for k in range(len(d)) if rec.get(d.iloc[k].file) is not None and rec[d.iloc[k].file]["v_key"]["span_s"] >= V_WIN_MIN_S)),
           "cells": []}
    if len(f):
        for (tc, b, di), g in f.groupby(["tclass", "bin", "dir"]):
            nd, ndays = len(g), g["date"].nunique()
            if nd >= SUPPORT_DRIVES and ndays >= SUPPORT_DAYS:
                out["cells"].append({"thermalClass": tc, "socBinLo": b, "approach": di, "nDrives": int(nd), "nDays": int(ndays), "medianV": round(float(g["v"].median()), 3)})
        out["nCellsAttempted"] = int(f.groupby(["tclass", "bin", "dir"]).ngroups)
    out["status"] = "shown cells meet the support floor (>= %d drives and >= %d days); " % STRATA_SUPPORT + ("none meet it" if not out["cells"] else "%d cell(s) shown" % len(out["cells"]))
    ik = np.array([rec[x]["i_key"] for x in d["file"] if rec.get(x) is not None])
    if len(ik):
        out["keyOnCurrentA"] = {"nDrives": int(len(ik)), "median": round(float(np.median(ik)), 3), "p10": round(float(np.percentile(ik, 10)), 3), "p90": round(float(np.percentile(ik, 90)), 3),
                                "shareAbsBelowThreshold": round(float(np.mean(np.abs(ik) <= I_LOW_A)), 4),
                                "note": "median of the first 5 current samples of each drive; the HV battery carries an auxiliary load at key-on, so a key-on voltage is not a rest voltage when this share is small"}
    out["hysteresis"] = "not shown (needs both approach directions supported in the same cell)"
    ok_dir = {}
    for c in out["cells"]:
        ok_dir.setdefault((c["thermalClass"], c["socBinLo"]), set()).add(c["approach"])
    both = [k for k, v in ok_dir.items() if len(v) == 2]
    if both:
        out["hysteresis"] = "%d cell(s) have both directions supported; compare medianV in the table, no pooled curve" % len(both)
    return out


# ------------------------------------------------------------------------------------------------ E3
def quarter_of(date):
    dt = pd.Timestamp(date)
    return "%dQ%d" % (dt.year, (dt.month - 1) // 3 + 1)


def e3_block(cbrecs, master, tclass, W, days, dix):
    n_days = len(days)
    date = dict(zip(master["file"], master["date"].astype(str)))
    base = [(f, r) for f, r in cbrecs.items() if r is not None and any(r["variants"]["primary"]) and f in date]
    for f, r in base:
        r["_q"] = quarter_of(date[f])
        r["_tc"] = tclass.get(f, "unknown")
    quarters = sorted({r["_q"] for _, r in base})
    strata = {"all": lambda r: True, "fast": lambda r: r["fast"], "slow": lambda r: not r["fast"], "warm": lambda r: r["_tc"] == "warm", "shoulder": lambda r: r["_tc"] == "shoulder", "cold": lambda r: r["_tc"] == "cold"}

    def stat(sel):
        sub = [(dix[date[f]], r) for f, r in base if sel(f, r)]
        if len({d for d, _ in sub}) < SUPPORT_DAYS or len(sub) < SUPPORT_DRIVES:
            return None, len(sub), len({d for d, _ in sub})
        ev = CB._event_rows(sub, "primary")
        if not len(ev["lev"]):
            return None, len(sub), len({d for d, _ in sub})
        return day_stats(ev["day"].astype(int), np.column_stack([ev["lev"], ev["th"]]), ev["Q"], n_days), len(sub), len({d for d, _ in sub})

    out = {"quarters": quarters, "strata": {}}
    for sname, sf in strata.items():
        rowsq = {}
        for q in quarters:
            st, nd, ndays = stat(lambda f, r, q=q, sf=sf: r["_q"] == q and sf(r))
            cell = {"nDrives": nd, "nDays": ndays}
            if st is None:
                cell["status"] = "not shown (below the support floor)"
            else:
                e, dr = draws(st, W, lambda b: 100.0 * b[0])
                cell["ahPer100"] = interval(e, dr)
                cell["_dr"] = (e, dr)
                cell["status"] = "supported"
            rowsq[q] = cell
        # pre-set step rule: quarter q judged against the pooled PRIOR quarters (difference interval), confirmed in the next quarter (same sign); needs a prior and a next quarter
        steps = {}
        for i, q in enumerate(quarters):
            if i == 0 or i == len(quarters) - 1:
                steps[q] = "not judged (needs a prior and a following quarter)"
                continue
            prior = set(quarters[:i])
            stp, _, _ = stat(lambda f, r, prior=prior, sf=sf: r["_q"] in prior and sf(r))
            cq = rowsq[q]
            nxt = rowsq[quarters[i + 1]]
            if stp is None or "_dr" not in cq or "_dr" not in nxt:
                steps[q] = "not judged (a compared cell is below the support floor)"
                continue
            ep, dp = draws(stp, W, lambda b: 100.0 * b[0])
            d1 = interval(cq["_dr"][0] - ep, cq["_dr"][1] - dp)
            d2 = interval(nxt["_dr"][0] - ep, nxt["_dr"][1] - dp)
            sig1 = d1 and (d1["ci95"][0] > 0 or d1["ci95"][1] < 0)
            sign_ok = d1 and d2 and np.sign(d1["est"]) == np.sign(d2["est"])
            hw = (d1["ci95"][1] - d1["ci95"][0]) / 2.0 if d1 else float("nan")
            steps[q] = {"differenceVsPriorPooled": d1, "mdeApprox80pctPower": round(float(1.4 * hw), 4), "nextQuarterSameSign": bool(sign_ok),
                        "decision": "step established under the pre-set rule" if (sig1 and sign_ok) else "no step established"}
        for q in rowsq:
            rowsq[q].pop("_dr", None)
        out["strata"][sname] = {"byQuarter": rowsq, "stepRule": steps}
    out["readingE3"] = "no step established (only the middle quarter is judgeable; the last quarter is partial); this is not 'no degradation': the window is too short"
    out["note"] = ("quarterly is the decision unit; a step needs a prior and a following quarter, so with %d quarter(s) at most %d can be judged; period, season, cadence and SoC window move together (cadence B6 check stays failed): "
                   "stratified cells are the comparison, the all-drives row is descriptive" % (len(quarters), max(0, len(quarters) - 2)))
    return out


# ------------------------------------------------------------------------------------------------ assemble
def assemble(master, d, rec, cbrecs, md5):
    days = sorted({str(x) for x in d.loc[d["clean"], "date"]})
    dix = {x: i for i, x in enumerate(days)}
    W = CB.boot_weights(len(days), N_BOOT, SEED)
    tclass = dict(zip(d["file"], d["tclass"]))
    for f, r in rec.items():
        if r is not None and cbrecs.get(f) is not None:
            r["fast"] = bool(cbrecs[f]["fast"])
    primary_pairs, primary_why = build_pairs(d, rec, R_PRIMARY, DSOC_PRIMARY)
    e2 = {"primary": e2_block(primary_pairs, primary_why, cbrecs, W, days, dix), "sensitivities": {}}
    for R in (R_PRIMARY,) + R_SENS:
        for ds in (DSOC_PRIMARY,) + DSOC_SENS:
            if R == R_PRIMARY and ds == DSOC_PRIMARY:
                continue
            p, w = build_pairs(d, rec, R, ds)
            lab = "R%gh_dSoc%g" % (R, ds)
            if len(p) < SUPPORT_DRIVES or (p["date"].nunique() if len(p) else 0) < SUPPORT_DAYS:
                e2["sensitivities"][lab] = {"status": "not estimable", "nPairs": int(len(p)), "nDays": int(p["date"].nunique()) if len(p) else 0}
            else:
                e2["sensitivities"][lab] = e2_block(p, w, cbrecs, W, days, dix)
    p9, w9 = build_pairs(d, rec, R_PRIMARY, DSOC_PRIMARY, 0.90)
    e2["sensitivities"]["R2h_dSoc10_cover0.90"] = e2_block(p9, w9, cbrecs, W, days, dix) if len(p9) >= SUPPORT_DRIVES else {"status": "not estimable", "nPairs": int(len(p9))}
    e2["sensitivities"]["R2h_dSoc10_cover0.90"]["note"] = "adds the pair(s) with drive current coverage between 0.90 and 0.95 under the M403 segment convention (the blind audit's 18th pair, file 20260717_103448.csv at 0.939; the audit counts all segments and gets 0.980); the 17-versus-18 difference follows from the segment convention against the frozen 0.95 threshold"
    # cold at R = 2 h: exploratory, no verdict
    e2["coldAtR2h"] = {"nPairs": int((primary_pairs["tclass"] == "cold").sum()) if len(primary_pairs) else 0, "status": "exploratory without a verdict (spec Rev 1: needs R >= 6 h)"}
    base_all = [(dix[str(master.set_index("file").loc[f, "date"])], r) for f, r in cbrecs.items() if r is not None and any(r["variants"]["primary"]) and f in set(d.loc[d["clean"], "file"])]
    ev = CB._event_rows(base_all, "primary")
    stb = day_stats(ev["day"].astype(int), np.column_stack([ev["lev"], ev["th"]]), ev["Q"], len(days))
    bp, db = draws(stb, W, lambda b: 100.0 * b[0])
    steps = [r["i_step"] for r in rec.values() if r and np.isfinite(r["i_step"])]
    ssteps = [r["s_step"] for r in rec.values() if r and np.isfinite(r["s_step"])]
    blk = {
        "_provenance": "GENERATED by tools/capacity_anchors.py (M699, spec analyses/M699_spec.md Rev 1); do not hand-edit. Additive block: no headline, master column or other payload leaf depends on it.",
        "methodVersion": VERSION,
        "quantity": "alternative anchoring of the apparent capacity of the logged BMS SoC scale (estimated, same current and SoC channels as capacityBasis); not state of health, not usable capacity, not CAP_KWH",
        "population": {"nDrivesWithRecord": int(sum(1 for r in rec.values() if r is not None)), "nDaysClean": len(days), "rule": "canonical clean (ens_outlier_v2 False); consecutive drives, parked gaps from clock times"},
        "resolution": {"currentGridStepA": round(float(np.min(steps)), 4) if steps else None, "socGridStepPoints": round(float(np.min(ssteps)), 4) if ssteps else None,
                       "voltageGridStepV": 0.16, "voltageGridSource": "signal_representation.json"},
        "frozenParameters": {"rPrimaryHours": R_PRIMARY, "dSocPrimaryPoints": DSOC_PRIMARY, "lowCurrentA": I_LOW_A, "voltageWindowS": [V_WIN_MIN_S, V_WIN_MAX_S], "voltageSlopeMaxVPerMin": V_SLOPE_MAX_V_MIN,
                             "coverMin": COVER_MIN, "unloggedKm": UNLOGGED_KM, "marginAhPer100": MARGIN_AH, "supportFloor": {"drives": SUPPORT_DRIVES, "days": SUPPORT_DAYS}, "seed": SEED, "nDraws": N_BOOT},
        "M403RecomputedOnCurrentCorpus": interval(bp, db),
        "E1_restVoltage": e1_block(d, rec),
        "E2_anchorPairs": e2,
        "E3_quarterly": e3_block(cbrecs, master, tclass, W, days, dix),
        "deviationsRecorded": ["the numeric parameters marginAhPer100 (0.25, precedent TOST_MARGIN_AH), voltageSlopeMaxVPerMin (0.08), lowCurrentA (1.0), coverMin (0.95) and the 120-300 s window were written into the tool before the first run but were NOT committed to the repository before it; the spec Rev 1 (commit afd3615) froze their rules, not their numbers",
                               "the within-drive SoC variant departs from the Rev 1 anchor geometry and is a sensitivity only", "coverage uses the first-to-last current sample span as the denominator; the audit's extra pair is at coverage 0.939 under the M403 segment convention (more than 20 samples per segment), below the frozen 0.95; the re-audit counts all segments and gets 0.980; see sensitivity R2h_dSoc10_cover0.90"],
        "assumptions": ["parked battery current is zero (no logger while parked)", "the logged BMS SoC at key-on is the anchor SoC; it may be re-estimated by the BMS at key-on", "E1 is a map of the BMS-reported SoC and may be circular with the BMS OCV lookup"],
        "reading": "Exploratory. Read the substantive outputs (E1 cells where supported, E3 stratified cells); E2 with the pre-registered small support is expected to end 'not established'. No capacity fade, state-of-health or degradation statement follows.",
        "provenance": {"driveMasterMd5": md5, "script": "tools/capacity_anchors.py", "scriptSha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest()},
    }
    return blk


ALLOWED = ["/capacityAnchors", "/_artifactStamps/capacityAnchors"]


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new["capacityAnchors"] = blk
    old = (A.get("_artifactStamps") or {}).get("capacityAnchors")
    if old and A.get("capacityAnchors") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["capacityAnchors"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M699: derived by tools/capacity_anchors.py from the raw logs of the canonical-clean drives; additive; exploratory, apparent scale of the logged SoC, estimated.",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"]["capacityAnchors"] = _sc.carry_declared(old, st)
    ch = CB._paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    import ah_throughput as AH
    import parked_time_budget as P
    raw_dir = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    d, _N = P.load_frame(raw_dir)
    master = pd.read_csv("drive_master.csv", low_memory=False)
    sm = pd.read_csv("seasonal_drive_master.csv", usecols=["file", "thermal_regime_raw"])
    d = d.merge(sm, on="file", how="left").rename(columns={"thermal_regime_raw": "tclass"})
    d["tclass"] = d["tclass"].astype(str)
    d = d.sort_values("t0u").reset_index(drop=True)
    loader = AH.raw_loader()
    rec = load_anchor_records(list(d["file"]), loader)
    cbrecs = CB.load_records(master, loader, AH.manifest_sha_lookup())
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    blk = assemble(master, d, rec, cbrecs, md5)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    new, changed, bad = splice(json.loads(raw), blk, md5)
    p = blk["E2_anchorPairs"]["primary"]
    print(json.dumps({"changedPaths": changed[:4], "nChanged": len(changed), "outsideAllowList": bad, "M403": blk["M403RecomputedOnCurrentCorpus"], "E2status": p.get("status"), "nPairs": p.get("nPairs"),
                      "E1": blk["E1_restVoltage"]["status"]}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
