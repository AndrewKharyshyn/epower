#!/usr/bin/env python3
"""M435 (spec analyses/M435_spec.md Rev 2, audit F17): per-drive time-to-threshold records and the `thermalSupportLedger.timeToThreshold` block.
Every number is computed here from the slim frames (the M418 code path: C._twl_grid / C._twl_time_to); nothing is typed.
  tte_record(fr, C)            one drive: status, start value, lag to the first valid sample, per fluid and threshold (t, event, reason, afterGap)
  build_block(recs, raw, ...)  cohort x fluid x threshold cells: E1 / E2 / Manski / tilt / median / RMST / support / reading classes, plus the distance-grid support
  reconcile(block, est)        G1: counts equal the M418 ledger aggregates
CLI: python tools/m435_tte.py run --out analyses/M435_result.json  (rebuilds the records from the frames; writes the block and the per-drive table for the blind audit)"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if __name__ == "__main__":
    os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import time_to_threshold as T

METHOD_VERSION = "M435-r2"
HORIZONS = [300, 600, 900, 1200, 1800]
THRESHOLDS = [60, 70, 80]
THETAS = [0.25, 0.5, 1, 2, 4]
BAND = (0.5, 2.0)
MIN_N, MIN_DAYS = 10, 5
TRIP_END_TOL_S = 10
GAP_S = 10
B_DRAWS, SEED = 4000, 42
FLUIDS = ("coolant", "oil")
COHORTS = ("all", "warm", "shoulder")
LABEL = "this vehicle, one driver, May-October, ambient 3-38 C"


# ------------------------------------------------------------------------------------------------ per-drive record
def _fluid(v, tsec, thr_list, start, C):
    valid = ~np.isnan(v)
    vi = np.where(valid)[0]
    trip_end = float(tsec[-1])
    last_valid = float(tsec[vi[-1]])
    out = {"lastValidS": last_valid, "tripEndS": trip_end, "thr": {}}
    for thr in thr_list:
        tt = C._twl_time_to(v, tsec, thr, start)
        if np.isfinite(tt):
            gap = 0
            if tt > 0:
                hit = int(np.where(v >= thr)[0][0])
                prev = vi[vi < hit]
                gap = int(hit - prev[-1]) if len(prev) else 0            # event second minus the previous valid second (C2)
            out["thr"][str(thr)] = {"t": float(tt), "e": True, "reason": "event", "afterGap": bool(gap > GAP_S)}
        else:
            reason = "tripEnd" if trip_end - last_valid <= TRIP_END_TOL_S else "channelLoss"
            out["thr"][str(thr)] = {"t": last_valid, "e": False, "reason": reason, "afterGap": False}
    return out


def tte_record(fr, C):
    g = C._twl_grid(fr)
    if g is None or "cool" not in g.columns:
        return {"status": "noFrameOrCoolantChannel"}
    c = g["cool"].dropna()
    if len(c) < 30:
        return {"status": "fewerThan30ValidCoolantSeconds"}
    cstart = float(c.iloc[0])
    tsec = (g.index - g.index[0]).total_seconds().values
    if cstart >= C._TWL_COLD_MAX:
        return {"status": "warmStart"}
    rec = {"status": "cold", "spanS": float(tsec[-1]), "startC": cstart, "lagFirstValidS": float((c.index[0] - g.index[0]).total_seconds()),
           "coolant": _fluid(g["cool"].values, tsec, C._TWL_THR, cstart, C), "oil": None}
    if "oil" in g.columns and g["oil"].notna().sum() >= 30:
        o = g["oil"].dropna()
        f = _fluid(g["oil"].values, tsec, C._TWL_THR, float(o.iloc[0]), C)
        f["startC"] = float(o.iloc[0]); f["lagFirstValidS"] = float((o.index[0] - g.index[0]).total_seconds())
        rec["oil"] = f
    return rec


# ------------------------------------------------------------------------------------------------ cell analysis
def _q(v):
    v = np.asarray(v, float)
    return None if v.size == 0 else {"p25": round(float(np.percentile(v, 25)), 2), "median": round(float(np.percentile(v, 50)), 2), "p75": round(float(np.percentile(v, 75)), 2), "n": int(v.size)}


def _r(x, d=4):
    return None if x is None else (round(float(x), d) if np.isfinite(x) else ("+inf" if x > 0 else "-inf"))


def _ci(a, d=4):
    return [_r(a[0], d), _r(a[1], d)]


def _classes(row):
    """Both readings are scored (C4), first match: 'holds at both worst-case bounds' (95 % limit of F_high < 0.5 for R+, of F_low >= 0.5 for R-), 'holds for every theta from 0.5 to 2'
    (95 % limit of F_theta at theta = 2 < 0.5 for R+; at theta = 0.5 >= 0.5 for R-), else 'depends on the censoring assumption'."""
    t = row["tilt"]
    plus = ("holds at both worst-case bounds" if row["bounds"]["high"]["ci95"][1] < 0.5 else
            "holds for every theta from 0.5 to 2" if t["2"]["ci95"][1] < 0.5 else "depends on the censoring assumption")
    minus = ("holds at both worst-case bounds" if row["bounds"]["low"]["ci95"][0] >= 0.5 else
             "holds for every theta from 0.5 to 2" if t["0.5"]["ci95"][0] >= 0.5 else "depends on the censoring assumption")
    return {"F<0.5": plus, "F>=0.5": minus}


def analyze_cell(t, e, day, reason, after_gap, start_c, lag_s, fluid, thr, counts, universe):
    n = len(t)
    cell = T.Cell(t, e, day)
    W1 = cell.ones(); S1 = cell.surv_steps(W1)
    Wb = cell.weights(counts, universe); Sb = cell.surv_steps(Wb)
    cnt = np.bincount(cell.day_idx)
    ess = float(cnt.sum() ** 2 / (cnt ** 2).sum())
    reached = int(np.sum(e))
    reasons = {k: int(np.sum([(r == k) for r in reason])) for k in ("tripEnd", "channelLoss")}
    out = {"n": n, "days": int(len(cell.days)), "essDays": round(ess, 1), "reached": reached, "censoredTripEnd": reasons["tripEnd"], "censoredChannelLoss": reasons["channelLoss"],
           "eventsAfterGapOver10s": int(np.sum(after_gap)), "startC": _q(start_c), "lagToFirstValidS": _q(lag_s)}
    if fluid == "oil":
        out["atOrAboveAtStart"] = int(np.sum(np.asarray(t) == 0))
        out["atOrAboveAtStartShare"] = _r(np.mean(np.asarray(t) == 0))
    rt = np.asarray(t)[np.asarray(e)]
    out["reachersOnlyMedian"] = {"seconds": _r(np.median(rt), 1) if rt.size else None, "n": int(rt.size),
                                 "label": "median of reachers only; understates the time for all cold starts; not a cohort median"}
    hz, sup_h = [], []
    for h in HORIZONS:
        nr, nd = cell.at_risk(h)
        row = {"h": h, "atRisk": nr, "atRiskDays": nd, "supported": bool(nr >= MIN_N and nd >= MIN_DAYS)}
        if row["supported"]:
            sup_h.append(h)
            F = 1.0 - cell.surv_at(S1, h)[0, 0]; Fb = 1.0 - cell.surv_at(Sb, h)[:, 0]
            lo1, hi1 = cell.manski(W1, h); lob, hib = cell.manski(Wb, h)
            row["E1"] = {"point": _r(lo1[0]), "ci95": _ci(T.pct(lob)), "label": "observed share of cold-start trips reaching the threshold within h before key-off (equals the lower worst-case bound; exact if no drive was censored for channel loss, otherwise a lower bound)"}
            row["E2"] = {"point": _r(F), "ci95": _ci(T.pct(Fb)), "label": "Kaplan-Meier (product-limit) estimate of the share reached by h, hypothetical continued drive, independent censoring assumed"}
            row["bounds"] = {"low": {"point": _r(lo1[0]), "ci95": _ci(T.pct(lob))}, "high": {"point": _r(hi1[0]), "ci95": _ci(T.pct(hib))}, "outerInterval": [_r(T.pct(lob)[0]), _r(T.pct(hib)[1])],
                             "label": "worst-case (Manski) identification bounds with day-clustered outer interval; not confidence intervals of a parameter"}
            tl = {}
            for th in THETAS:
                Ft1 = 1.0 - cell.tilt_surv(W1, S1, h, th)[0]
                Ftb = 1.0 - cell.tilt_surv(Wb, Sb, h, th)
                tl[str(th)] = {"point": _r(Ft1), "ci95": _ci(T.pct(Ftb))}
            row["tilt"] = tl
            Flo = 1.0 - cell.tilt_surv(W1, S1, h, BAND[0])[0]; Fhi = 1.0 - cell.tilt_surv(W1, S1, h, BAND[1])[0]
            row["reading"] = "F<0.5" if F < 0.5 else "F>=0.5"
            row["readingClasses"] = _classes(row)
            row["readingClass"] = row["readingClasses"][row["reading"]]
            tp = T.bisect_tipping(cell, h)
            side = "upper" if F < 0.5 else "lower"
            tl_ = T.bisect_limit(cell, Wb, Sb, h, side)
            row["tippingTheta"] = None if tp is None else round(tp, 4)
            row["tippingThetaLimit95"] = None if tl_ is None else round(tl_, 3)
            row["tippingNote"] = ("theta at which the point tilted share reached crosses 0.5, and the theta at which its %s 95%% limit crosses 0.5 (bisection on log theta over [0.01, 100], limit to 0.01 in log theta); null if no crossing inside that interval" % side)
        hz.append(row)
    out["horizons"] = hz
    out["supportedHorizons"] = sup_h
    # median (section 4): Kaplan-Meier median, day-clustered interval over all draws, tilted medians for theta in the band
    med = float(cell.median_time(S1)[0]); mb = cell.median_time(Sb)
    unid = float(np.mean(np.isinf(mb)))
    mt = {}
    for th in BAND:
        grid = np.unique(cell.t)
        sv = np.array([cell.tilt_surv(W1, S1, g_, th)[0] for g_ in grid])
        k = np.where(sv <= 0.5)[0]
        mt["%g" % th] = float(grid[k[0]]) if k.size else float("inf")
    n_med, d_med = cell.at_risk(med) if np.isfinite(med) else (0, 0)
    shown = bool(np.isfinite(med) and np.isfinite(mt["%g" % BAND[0]]) and n_med >= MIN_N and d_med >= MIN_DAYS)
    ci = T.pct(mb)
    out["median"] = {"point": _r(med, 1), "ci95": [_r(ci[0], 1), "beyond supported range" if unid > 0.025 else _r(ci[1], 1)], "shareDrawsUnidentified": _r(unid), "atRiskAtMedian": [n_med, d_med],
                     "tiltedAtBand": {k: _r(v, 1) for k, v in mt.items()}, "shown": shown,
                     "text": ("Kaplan-Meier (product-limit) estimate of the median %s s" % _r(med, 0)) if shown else "cohort median not identifiable without an assumption on censoring"}
    out["_cell"] = cell      # removed by the caller after the common RMST horizon is known
    out["_S"] = (S1, Sb)
    return out


def finish_rmst(cell_out, tau):
    cell = cell_out.pop("_cell"); S1, Sb = cell_out.pop("_S")
    if tau is None or tau < 300:
        cell_out["rmst"] = {"tauS": None, "note": "restricted mean time not reported: no common supported horizon of at least 300 s"}
    else:
        r1 = cell.rmst(S1, tau)[0]; rb = cell.rmst(Sb, tau)
        cell_out["rmst"] = {"tauS": tau, "point": _r(r1, 1), "ci95": [_r(T.pct(rb)[0], 1), _r(T.pct(rb)[1], 1)],
                            "label": "mean seconds within the horizon (restricted mean time), Kaplan-Meier (product-limit) estimate; common horizon across cohorts"}


# ------------------------------------------------------------------------------------------------ distance-grid support
def grid_support(spans, days, grid):
    spans = np.asarray(spans, float); days = np.asarray(days)
    rows = []
    for g in grid:
        m = spans >= g
        rows.append({"km": g, "nDrives": int(m.sum()), "nDays": int(len(np.unique(days[m]))) if m.any() else 0})
    end = next((r["km"] for r in rows if r["nDrives"] < MIN_N or r["nDays"] < MIN_DAYS), None)
    return rows, end


# ------------------------------------------------------------------------------------------------ block
def build_block(tte, raw, days, regimes, C, meta=None):
    """tte / raw: per-drive records aligned with `days` (calendar day strings) and `regimes` (thermal_regime); meta (optional): per-drive {"distanceKm", "startHour"} for the post-hoc stopping profile."""
    idx = {"all": list(range(len(tte)))}
    for c in ("warm", "shoulder"):
        idx[c] = [i for i, r in enumerate(regimes) if r == c]
    cells, order = {}, []
    for coh in COHORTS:
        uni = np.array(sorted({days[i] for i in idx[coh] if tte[i].get("status") == "cold"}))
        counts = T.day_counts(uni, B_DRAWS, SEED) if len(uni) else None            # one set of resamples per cohort, shared by all cells (C4)
        for fl in FLUIDS:
            for thr in THRESHOLDS:
                t, e, d, rs, ag, sc, lg = [], [], [], [], [], [], []
                for i in idx[coh]:
                    r = tte[i]
                    if r.get("status") != "cold":
                        continue
                    f = r["coolant"] if fl == "coolant" else r["oil"]
                    if f is None:
                        continue
                    x = f["thr"][str(thr)]
                    t.append(x["t"]); e.append(x["e"]); d.append(days[i]); rs.append(x["reason"]); ag.append(x["afterGap"])
                    sc.append(r["startC"] if fl == "coolant" else f["startC"]); lg.append(r["lagFirstValidS"] if fl == "coolant" else f["lagFirstValidS"])
                if not t:
                    continue
                cells[(coh, fl, thr)] = analyze_cell(t, e, d, rs, ag, sc, lg, fl, thr, counts, uni)
                order.append((coh, fl, thr))
    # common RMST horizon per fluid / threshold: smallest, across the cohorts, of each cohort's longest supported declared horizon
    for fl in FLUIDS:
        for thr in THRESHOLDS:
            tops = []
            for coh in COHORTS:
                c = cells.get((coh, fl, thr))
                tops.append(max(c["supportedHorizons"]) if c and c["supportedHorizons"] else 0)
            tau = min(tops) if tops else None
            for coh in COHORTS:
                if (coh, fl, thr) in cells:
                    finish_rmst(cells[(coh, fl, thr)], tau)
    out = {}
    for (coh, fl, thr) in order:
        out.setdefault(coh, {}).setdefault(fl, {})[str(thr)] = cells[(coh, fl, thr)]
    post = None
    if meta is not None:
        post = {"label": "post-hoc descriptive, not pre-registered (blind-audit finding); not a test of independent censoring; no p-values", "cohort": "all", "cells": {}}
        for fl, thr in (("coolant", 80), ("oil", 70)):
            grp = {"reached": [], "censored": []}
            for i, r in enumerate(tte):
                if r.get("status") != "cold":
                    continue
                f = r["coolant"] if fl == "coolant" else r["oil"]
                if f is None:
                    continue
                x = f["thr"][str(thr)]
                grp["reached" if x["e"] else "censored"].append((days[i], meta[i]["distanceKm"], meta[i]["startHour"], r["startC"] if fl == "coolant" else f["startC"]))
            cell = {}
            for g, rows in grp.items():
                d_ = np.array([x[1] for x in rows], float); h_ = np.array([x[2] for x in rows], float); sc_ = np.array([x[3] for x in rows], float)
                cell[g] = {"n": len(rows), "days": len({x[0] for x in rows}), "medianDistanceKm": _r(np.nanmedian(d_), 2) if len(rows) else None,
                           "shareUnder5km": _r(np.mean(d_ < 5)) if len(rows) else None, "shareStartBefore10h": _r(np.mean(h_ < 10)) if len(rows) else None, "medianStartC": _r(np.median(sc_), 1) if len(rows) else None}
            post["cells"]["%s/%d" % (fl, thr)] = cell
    curve = {}
    for coh in COHORTS:
        per = {k: ([], []) for k in C.CLASS_ORDER}
        for i in idx[coh]:
            rc = raw[i]
            cu = rc.get("curve") if isinstance(rc, dict) else None
            if cu and cu.get("status") == "accepted":
                per[cu["class"]][0].append(cu["spanKm"]); per[cu["class"]][1].append(days[i])
        curve[coh] = {}
        for k, (sp, dy) in per.items():
            rows, end = grid_support(sp, dy, C.WARMUP_GRID)
            curve[coh][k] = {"nDrives": len(sp), "nDays": len(set(dy)), "grid": rows, "supportEndsKm": end,
                             "sentence": "beyond this point the curve averages only the drives still running" if end is not None else "support holds to the last grid point"}
    blk = {"methodVersion": METHOD_VERSION, "spec": "analyses/M435_spec.md", "label": LABEL, "horizonsS": HORIZONS, "thresholdsC": THRESHOLDS, "thetas": THETAS, "thetaBand": list(BAND),
           "supportRule": {"minAtRiskDrives": MIN_N, "minAtRiskDays": MIN_DAYS}, "tripEndToleranceS": TRIP_END_TOL_S, "gapS": GAP_S,
           "bootstrap": {"B": B_DRAWS, "seed": SEED, "cluster": "calendar day", "interval": "percentile 95%"},
           "assumption": "assumes that ending the drive is unrelated to the remaining time to the threshold (independent censoring); this cannot be checked from these data; bounds and tilt rows below",
           "hypothetical": "describes the time to c C had the drive continued (route and load undefined); the observed share before key-off is shown beside it",
           "reachersLabel": "median of reachers only; understates the time for all cold starts; not a cohort median",
           "cohorts": out, "curveSupport": curve, "postHoc": {"stoppingProfile": post},
           "populationNote": "Cold starts and event times use a 1 Hz grid with forward fill of at most 3 s (logger interval above 1 s); without the fill some drives leave the cold-start population; the headline classes are unchanged; fill and trip-end tolerance are coupled.",
           "requiredSentences": {"R1": "assumes that ending the drive is unrelated to the remaining time to the threshold (independent censoring); this cannot be checked from these data; bounds and tilt rows below",
                                 "R2": "describes the time to c C had the drive continued (route and load undefined); the observed share before key-off is shown beside it",
                                 "R4": LABEL, "R5": "cohort median not identifiable without an assumption on censoring",
                                 "R6": "median of reachers only (s); understates the time for all cold starts; not a cohort median"},
           "headline": {"cohort": "all", "cells": [{"fluid": "coolant", "thresholdC": 80, "h": 600}, {"fluid": "oil", "thresholdC": 70, "h": 600}], "note": "declared before any result; every other cell is descriptive; no contrasts between cohorts are claimed"},
           "limits": ["independent censoring cannot be tested; the bounds and the tilt measure how much it matters, they do not remove it", "single vehicle, one driver, May-October, ambient 3-38 C",
                      "the continued drive leaves route and load undefined", "the cold cohort and winter cannot be estimated", "the shares mix drives with different start temperatures"]}
    return blk


def reconcile(blk, est_by_cohort):
    """G1: n cold starts, reached and censored (= tripEnd + channelLoss) and days equal the M418 ledger aggregates; the curve grid drive counts equal gridAttrition."""
    checks = {}
    for coh, est in est_by_cohort.items():
        lag = est["warmupLag"]
        for fl in FLUIDS:
            for thr in THRESHOLDS:
                c = (blk["cohorts"].get(coh) or {}).get(fl, {}).get(str(thr))
                src = lag["coolant"][str(thr)] if fl == "coolant" else lag["oil"][str(thr)]
                n_src = lag["coldStarts"] if fl == "coolant" else lag["nWithOil"]
                if c is None:
                    checks["%s/%s/%d" % (coh, fl, thr)] = {"equal": n_src == 0}
                    continue
                ok = (c["n"] == n_src and c["reached"] == src["reached"] and c["censoredTripEnd"] + c["censoredChannelLoss"] == src["censored"])
                checks["%s/%s/%d" % (coh, fl, thr)] = {"equal": bool(ok), "tte": [c["n"], c["reached"], c["censoredTripEnd"] + c["censoredChannelLoss"]], "ledger": [n_src, src["reached"], src["censored"]]}
        if coh in blk["curveSupport"]:
            for k, g in est["warmupCurve"]["gridAttrition"].items():
                mine = [r["nDrives"] for r in blk["curveSupport"][coh][k]["grid"]]
                theirs = [r["nDrivesReachingThisDistance"] for r in g]
                checks["%s/curve/%s" % (coh, k)] = {"equal": mine == theirs}
    return {"allEqual": all(v["equal"] for v in checks.values()), "nChecks": len(checks), "checks": checks}


# ------------------------------------------------------------------------------------------------ CLI
def main(argv):
    import compute_summary_arrays as C
    import drive_raw_cache as drc
    import thermal_support_ledger as L
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else "analyses/M435_result.json"
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw_dir = os.environ.get("XT_RAW_DIR_STAGED") or os.path.join(ROOT, "raw_only")
    fl = drc.make_frame_loader(raw_dir=raw_dir)
    days = list(dm["date"].astype(str).str[:10])
    dist = dict(zip(dm["file"], dm["distance_km"])); dtype = dict(zip(dm["file"], dm["drive_type"]))
    tte, raw, lag = [], [], []
    for fn, d in zip(dm["file"], days):
        fr = fl(fn)
        tte.append(tte_record(fr, C)); lag.append({**L.lag_record(fr, C), "_d": d})
        raw.append({**L.raw_record(fr, dist.get(fn), dtype.get(fn), C), "_d": d})
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")["thermal_regime"]
    regimes = [sdm.get(fn) for fn in dm["file"]]
    # per-drive agreement with the ledger's own classification (G1, drive level)
    mism = 0
    for a, b in zip(tte, lag):
        if a["status"] != b["status"]:
            mism += 1
        elif a["status"] == "cold":
            for t_ in C._TWL_THR:
                x = a["coolant"]["thr"][str(t_)]["t"] if a["coolant"]["thr"][str(t_)]["e"] else float("nan")
                y = b["cool"][t_]
                if not ((np.isnan(x) and np.isnan(y)) or x == y):
                    mism += 1
    meta = [{"distanceKm": float(d_ or 0.0), "startHour": int(str(t_)[:2])} for d_, t_ in zip(dm["distance_km"], dm["time_start"])]
    blk = build_block(tte, raw, days, regimes, C, meta)
    est = {"all": {"warmupLag": L.aggregate_lag(lag, C), "warmupCurve": L.aggregate_raw(raw, C)[1]}}
    for coh in ("warm", "shoulder"):
        ii = [i for i, r in enumerate(regimes) if r == coh]
        est[coh] = {"warmupLag": L.aggregate_lag([lag[i] for i in ii], C), "warmupCurve": L.aggregate_raw([raw[i] for i in ii], C)[1]}
    rec = reconcile(blk, est)
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    res = {"_provenance": {"spec": "analyses/M435_spec.md", "masterMd5": md5, "script": "tools/m435_tte.py", "nDrives": len(dm), "perDriveTable": "M435_result_per_drive.csv.gz",
                           "label": "raw/ = sha256-verified originals (M366); " + LABEL},
           "G1": {"driveLevelMismatches": mism, "reconciliation": {"allEqual": rec["allEqual"], "nChecks": rec["nChecks"], "failed": {k: v for k, v in rec["checks"].items() if not v["equal"]}}},
           "block": blk}
    rows = []
    for i, (fn, r) in enumerate(zip(dm["file"], tte)):
        if r.get("status") != "cold":
            continue
        for fl_ in FLUIDS:
            f = r["coolant"] if fl_ == "coolant" else r["oil"]
            if f is None:
                continue
            for thr, x in f["thr"].items():
                rows.append((fn, days[i], regimes[i], fl_, int(thr), x["t"], int(x["e"]), x["reason"], int(x["afterGap"]), r["startC"] if fl_ == "coolant" else f["startC"],
                             r["lagFirstValidS"] if fl_ == "coolant" else f["lagFirstValidS"], f["tripEndS"], f["lastValidS"]))
    tab = pd.DataFrame(rows, columns=["file", "day", "regime", "fluid", "thresholdC", "timeS", "event", "reason", "afterGap", "startC", "lagFirstValidS", "tripEndS", "lastValidS"])
    tab.to_csv(os.path.join(os.path.dirname(out_path) or ".", "M435_result_per_drive.csv.gz"), index=False, compression="gzip")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps({"driveLevelMismatches": mism, "reconciliation": res["G1"]["reconciliation"]["allEqual"], "nChecks": rec["nChecks"]}))
    return 0 if (mism == 0 and rec["allEqual"]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
