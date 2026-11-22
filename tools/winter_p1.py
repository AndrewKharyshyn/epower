#!/usr/bin/env python3
"""M732 (analyses/M732_spec.md Rev 2): extractor of the observed quantity of the M717 winter prediction P1 (start-temperature accuracy of the state-model chain), model-derived and propagated.
Two pure parts on a per-drive sidecar (one row per drive of the scoring window, ALL drives, clean or not, in time order):
 Part A, free run: anchor = first drive's logged start (mean of the four probes at the census start reading); every later start is simulated from the simulated end of the previous drive (vendored `exposure_state.drive_path`, logged
   current-squared slices, frozen heating) and the vendored `park_model.park_T` (frozen tau, offset; diurnal amplitude 0.7 x autumn for Dec-Feb, autumn otherwise; peak hour frozen; ambient taken from the previous drive's month).
   NO re-anchoring except at a non-finite state, an overlap / duplicate join or a missing ambient (counted, not scored). Statistic: MAE and bias of (simulated - logged) start over scored drives, day-clustered bootstrap.
 Part B, park model on restart pairs: pairs from the vendored `restart_census.build_pairs`, eligible and not flagged (M709 unlogged-use flag), predicted from the OBSERVED previous end temperature with the frozen parameters, no refit.
   Cells: gaps >= 12 h within +-1 C; logged start in [7, 13] C within +-0.5 C; logged start in [12, 18] C within +-0.5 C (never pooled).
Reading of every cell: 'within' = interval inside the tolerance; 'outside' = the point estimate outside it (interval beside); else 'inconclusive'; below 10 drives (pairs) on 5 days 'not evaluable'. P1 = within only if every cell is within; any
cell not evaluable makes P1 not evaluable. Primary window Dec-Feb (month of the scored drive); November beside. Sensitivities: flag-segmented chain, amplitude scale 1.0, 7-day block bootstrap, +-2 C windows.
All temperatures are model-derived; the logged start is the mean of the pack-probe readings at the first sample, never a measurement of the cell. Usage: python tools/winter_p1.py [--build [--raw-dir DIR]]"""
import importlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VT = os.path.join(ROOT, "analyses", "M731_frozen_engine", "root", "tools")
VERSION = 1
SEED, NB = 42, 4000
SUPPORT_DRIVES, SUPPORT_DAYS = 10, 5
ICOV_MIN = 0.8
W = 2 * np.pi / 24.0
K_SLICES = 16
WINTER = (12, 1, 2)
COLUMNS = {"P1": ["key", "day", "utc0", "utc1", "dur_s", "local0", "odo_start", "odo_end", "soc_first", "soc_last", "A0", "A1", "icov"] + ["T%d_%s" % (i, s) for i in (1, 2, 3, 4) for s in ("s", "e")] + ["Tcool_s", "Tcool_e"]
           + ["i2_%d" % k for k in range(K_SLICES)]}
SIDECAR = os.path.join(ROOT, "analyses", "M732", "p1_drives.csv")
_V = None


def vendored():
    """The vendored restart_census, park_model, exposure_state (git blobs of the M717 commit); the sys.path and sys.modules of the caller are restored, so no live module is shadowed."""
    global _V
    if _V is not None:
        return _V
    names = ("restart_census", "park_model", "exposure_state", "raw_resolver", "scenario_frame")
    saved = {n: sys.modules.pop(n) for n in names if n in sys.modules}
    path0 = list(sys.path)
    sys.path.insert(0, VT)
    try:
        mods = {n: importlib.import_module(n) for n in ("restart_census", "park_model", "exposure_state")}
        for n, m in mods.items():
            assert os.path.dirname(os.path.abspath(m.__file__)) == os.path.abspath(VT), "live module imported: " + m.__file__
    finally:
        sys.path[:] = path0
        for n in names:
            sys.modules.pop(n, None)
        sys.modules.update(saved)
    _V = mods
    return mods


# ------------------------------------------------------------------------------------------------ sidecar (raw files)
def build_sidecar(raw_dir, keys, out=None):
    """One row per drive of `keys` (time ordered): census endpoints (vendored restart_census.read_drive), the K=16 current-squared slices and the current coverage (vendored scenario_frame), the driver-read ambient list ends and the odometer."""
    import winter_p6 as W6
    SF = W6.vendored_frame_module()
    RC = vendored()["restart_census"]
    import raw_resolver as RR
    res = RR.resolve(raw_dir, os.path.join(ROOT, "raw_manifest.json"))
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "odo_start", "odo_end"], low_memory=False)
    dm["key"] = dm["file"].map(RC.key14)
    dm = dm.set_index("key")
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))
    amb = {RC.key14(f): v for f, v in cfg.get("ambientByDrive", {}).items()}
    rows = []
    for k in keys:
        path = res.index.get(k)
        if path is None:
            rows.append({"key": k, "error": "raw file not found"})
            continue
        r = RC.read_drive(path)
        if "error" in r:
            rows.append({"key": k, "error": r["error"]})
            continue
        g = SF.extract_drive(path)
        sl = SF.slices(g)
        v = amb.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = [v]
        a0 = a1 = np.nan
        if isinstance(v, list) and len(v) >= 1 and v[0] is not None:
            a0 = float(v[0]); a1 = float(v[-1]) if v[-1] is not None else a0
        row = {c: r.get(c, np.nan) for c in ("key", "utc0", "utc1", "dur_s", "local0", "soc_first", "soc_last", "Tcool_s", "Tcool_e")}
        for i in (1, 2, 3, 4):
            for s in ("s", "e"):
                row["T%d_%s" % (i, s)] = r.get("T%d_%s" % (i, s), np.nan)
        row.update(odo_start=dm["odo_start"].get(k, np.nan), odo_end=dm["odo_end"].get(k, np.nan), A0=a0, A1=a1, icov=float(sl["icov"]))
        for j in range(K_SLICES):
            row["i2_%d" % j] = float(sl["i2"][j])
        rows.append(row)
    df = pd.DataFrame(rows)
    df["local0"] = df["local0"].astype(str)
    df["day"] = df["local0"].str[:10]
    df = df.sort_values("utc0").reset_index(drop=True)
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        df.to_csv(out, index=False, lineterminator="\n")
    return df


# ------------------------------------------------------------------------------------------------ statistics
def _boot_cluster(cl, x, nb=NB, seed=SEED):
    """Day (or block) clustered percentile bootstrap of mean(x) and mean(|x|): returns dict with the two means and 95 % intervals. `cl`: cluster label per row."""
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    d = pd.DataFrame({"c": np.asarray(cl)[ok], "a": x[ok], "b": np.abs(x[ok])})
    if len(d) == 0:
        return None
    g = d.groupby("c").agg(sa=("a", "sum"), sb=("b", "sum"), n=("a", "count"))
    wt = np.random.default_rng(seed).multinomial(len(g), np.ones(len(g)) / len(g), size=nb).astype(float)
    den = wt @ g["n"].values
    ra, rb = (wt @ g["sa"].values) / den, (wt @ g["sb"].values) / den
    return {"bias": float(g["sa"].sum() / g["n"].sum()), "biasCi": [float(v) for v in np.nanpercentile(ra, [2.5, 97.5])],
            "mae": float(g["sb"].sum() / g["n"].sum()), "maeCi": [float(v) for v in np.nanpercentile(rb, [2.5, 97.5])], "n": int(len(d)), "nDays": int(len(g))}


def reading(point, ci, tol):
    """within: interval inside +-tol; outside: point outside +-tol; else inconclusive."""
    if abs(point) > tol:
        return "outside"
    return "within" if (ci[0] >= -tol and ci[1] <= tol) else "inconclusive"


def week_blocks(days):
    d = pd.to_datetime(pd.Series(days))
    return ((d - d.min()).dt.days // 7).values


# ------------------------------------------------------------------------------------------------ pairs and chain
def _ambient_frame(df, winter_reduction=True, hpk=None, amp_aut=None, seasonal=None):
    """Abar_s, Abar_e per drive with the FROZEN diurnal convention: amplitude amp_aut x 0.7 x amp_scale-adjusted for Dec-Feb, amp_aut otherwise; the month is the month of the drive's local start."""
    f = df.copy()
    f["month"] = f["day"].str[5:7].astype(int)
    f["amp"] = np.where(f["month"].isin(WINTER) & bool(winter_reduction), amp_aut * 0.7, amp_aut)
    f["hpkd"] = hpk
    if seasonal is not None:                                              # frozen-basis fidelity mode (C-P1b): the M709 summer / autumn amplitude and peak hour, no winter factor
        su = f["month"] <= 8
        f["amp"] = np.where(su, seasonal["summer"][0], seasonal["autumn"][0])
        f["hpkd"] = np.where(su, seasonal["summer"][1], seasonal["autumn"][1])
    lt = pd.to_datetime(f["local0"])
    f["h0"] = lt.dt.hour + lt.dt.minute / 60 + lt.dt.second / 3600
    f["h1"] = f["h0"] + f["dur_s"] / 3600
    f["Abar_s"] = f["A0"] - f["amp"] * np.cos(W * (f["h0"] - f["hpkd"]))
    f["Abar_e"] = f["A1"] - f["amp"] * np.cos(W * (f["h1"] - f["hpkd"]))
    return f


def build_pair_table(sc, params, winter_reduction=True, seasonal=None):
    """Adjacent pairs of the sidecar (vendored census code), with the model inputs of the park model; winter_reduction=True = the frozen Dec-Feb convention (0.7 x autumn amplitude), False = no reduction (sensitivity)."""
    V = vendored()
    RC, PM = V["restart_census"], V["park_model"]
    aut = params["diurnalAmbient"]["autumn"]
    A = _ambient_frame(sc, winter_reduction=winter_reduction, hpk=aut["hpk"], amp_aut=aut["amp"], seasonal=seasonal).reset_index(drop=True)
    E = A.copy()
    E["local0"] = pd.to_datetime(E["local0"])
    E["day"] = E["day"].astype(str)
    P = RC.build_pairs(E, dict(zip(A["key"], A["A0"])))
    Ai = A.set_index("key")
    D = P.copy()
    for c in ("Abar_s", "Abar_e", "amp", "hpkd", "h0", "h1", "A0", "A1"):
        D["p_" + c] = D["p_key"].map(Ai[c])
        D["n_" + c] = D["n_key"].map(Ai[c])
    pe = D[["p_%s_e" % p for p in RC.PROBES]].values
    ns = D[["n_%s_s" % p for p in RC.PROBES]].values
    D["x0"] = np.where(np.isfinite(pe).all(1), pe.mean(1), np.nan)
    D["y"] = np.where(np.isfinite(ns).all(1), ns.mean(1), np.nan)
    D["slope"] = (D["n_Abar_s"] - D["p_Abar_e"]) / D["gap_h"].clip(lower=1e-3)
    D["clock0"] = D["p_h1"] % 24
    D["month"] = D["n_day"].str[5:7].astype(int)
    ok = D[["x0", "y", "p_Abar_e", "n_Abar_s", "p_amp", "p_h1", "gap_h"]].notna().all(axis=1)
    D["after_missing"] = D["n_key"].map(dict(zip(sc["key"], sc["after_missing"]))).fillna(False).astype(bool) if "after_missing" in sc.columns else False   # a pair across a dropped (unreadable) drive is not a pair
    D["usable"] = D["elig"] & ok & ~D["after_missing"]
    D["use"] = D["usable"] & ~D["flagged"]
    pk = params["park"]
    D["pred"] = PM.park_T(D["x0"].values, D["gap_h"].values, D["clock0"].values, D["p_Abar_e"].values, D["slope"].values, D["p_amp"].values, D["p_hpkd"].values, pk["tau_h"], pk["offset_C"])
    D["bias"] = D["pred"] - D["y"]
    return D


def free_run(sc, D, params, segmented=False):
    """Propagated chain over the sidecar rows in time order (D = the pair table of the same rows). Returns a per-drive frame: day, month, y (logged start), sim (simulated start), err, anchored (re-anchored or the first drive), scored.
    segmented=True breaks (re-anchors) at every flagged, odometer-step, overlap, duplicate, long-gap or incomplete join (the sensitivity)."""
    V = vendored()
    PM, ES = V["park_model"], V["exposure_state"]
    dh, rt, aut, pk = params["driveHeating"], params["R_T"], params["diurnalAmbient"]["autumn"], params["park"]
    p = {"c0": dh["c0_C"], "c1": dh["c1"], "tau_d": dh["tau_d_h"], "alpha": dh["alpha_C_per_A2h"], "EaR": rt["EaR_kJmol"]}
    n = len(sc)
    ycols = sc[["T%d_s" % i for i in (1, 2, 3, 4)]].values
    y = np.where(np.isfinite(ycols).all(1), ycols.mean(1), np.nan)
    i2 = sc[["i2_%d" % k for k in range(K_SLICES)]].values.astype(float)
    dt_h = sc["dur_s"].values / 3600.0 / K_SLICES
    A_dr = (sc["A0"].values + sc["A1"].values) / 2
    sim = np.full(n, np.nan)
    anch = np.zeros(n, bool)
    state = np.nan
    reanchors = {"first": 0, "nonFinite": 0, "overlapOrDup": 0, "missingAmbient": 0, "missingDrive": 0, "segmented": 0}
    for k in range(n):
        if k == 0:
            state, why = y[0], "first"
        else:
            r = D.iloc[k - 1]
            assert r["n_key"] == sc["key"].iloc[k] and r["p_key"] == sc["key"].iloc[k - 1], "pair table misaligned with the sidecar order"
            why = None
            if "after_missing" in sc.columns and bool(sc["after_missing"].iloc[k]):
                why = "missingDrive"
            elif bool(r["flag_overlap"]) or bool(r["flag_dup"]):
                why = "overlapOrDup"
            elif not np.isfinite(r["p_Abar_e"]) or not np.isfinite(r["n_Abar_s"]) or not np.isfinite(r["gap_h"]):
                why = "missingAmbient"
            elif segmented and (bool(r["flagged"]) or not bool(r["elig"])):
                why = "segmented"
            elif not np.isfinite(state):
                why = "nonFinite"
            if why is None:
                state = float(PM.park_T(Tend, r["gap_h"], r["clock0"], r["p_Abar_e"], r["slope"], r["p_amp"], r["p_hpkd"], pk["tau_h"], pk["offset_C"]))
                if not np.isfinite(state):
                    why, state = "nonFinite", y[k]
            else:
                state = y[k]
        if why is not None:
            reanchors[why] += 1
            anch[k] = True
        sim[k] = state
        if np.isfinite(state) and np.isfinite(A_dr[k]):
            _, Tend = ES.drive_path(np.array([state]), i2[k:k + 1], np.array([dt_h[k]]), np.array([A_dr[k]]), p)
            Tend = float(Tend[0])
        else:
            Tend = np.nan
    out = pd.DataFrame({"key": sc["key"].values, "day": sc["day"].values, "month": sc["day"].str[5:7].astype(int).values, "y": y, "sim": sim, "anchored": anch})
    out["err"] = out["sim"] - out["y"]
    out["icov"] = sc["icov"].values
    out["prev_icov"] = np.r_[np.nan, sc["icov"].values[:-1]]
    out["scored"] = ~out["anchored"] & np.isfinite(out["err"]) & (out["icov"] >= ICOV_MIN)                       # D4: drives below 80 % current coverage are propagated, not scored
    joins = D[["flagged", "flag_odo", "flag_long"]].fillna(False).astype(bool)
    reanchors["propagatedThroughFlaggedJoins"] = int(joins["flagged"].sum()) if not segmented else 0
    reanchors["propagatedThroughOdoStepJoins"] = int(joins["flag_odo"].sum()) if not segmented else 0
    reanchors["propagatedThroughLongGapJoins"] = int(joins["flag_long"].sum()) if not segmented else 0
    return out, reanchors


# ------------------------------------------------------------------------------------------------ the cells
def _cell(name, e, tol, day_labels, nb, blocks=None, kind="meanbias"):
    n_dr, n_dy = int(len(e)), int(pd.Series(day_labels).nunique()) if len(e) else 0
    if n_dr < SUPPORT_DRIVES or n_dy < SUPPORT_DAYS:
        return {"cell": name, "status": "not evaluable", "reason": "below the support rule (%d on %d days; needs %d on %d)" % (n_dr, n_dy, SUPPORT_DRIVES, SUPPORT_DAYS)}
    b = _boot_cluster(day_labels, e, nb)
    if kind == "chain":
        ra = reading(b["bias"], b["biasCi"], tol[1])
        mae_r = "outside" if b["mae"] > tol[0] else ("within" if b["maeCi"][1] <= tol[0] else "inconclusive")
        st = "outside" if "outside" in (mae_r, ra) else ("within" if (mae_r == "within" and ra == "within") else "inconclusive")
        res = {"cell": name, "status": st, "maeStatus": mae_r, "biasStatus": ra, "tolerance": {"maeC": tol[0], "absBiasC": tol[1]}}
    else:
        st = reading(b["bias"], b["biasCi"], tol)
        res = {"cell": name, "status": st, "tolerance": {"absBiasC": tol}}
    res.update(b)
    if blocks is not None:
        bb = _boot_cluster(blocks, e, nb)
        res["blockBootstrap7d"] = {"biasCi": bb["biasCi"], "maeCi": bb["maeCi"], "nBlocks": bb["nDays"]}
    return res


def _prepare(sc):
    """Drop sidecar rows that carry an error or no start time (counted), order by time, and mark the drive after a dropped one (`after_missing`: re-anchor, reason missingDrive). The key digits sort chronologically, so a dropped row keeps its place."""
    sc = sc.sort_values("key").reset_index(drop=True)
    bad = sc["error"].notna() if "error" in sc.columns else pd.Series(False, index=sc.index)
    bad = bad | sc["utc0"].isna()
    after = bad.shift(1, fill_value=False)
    keep = ~bad
    out = sc[keep].copy()
    out["after_missing"] = after[keep].values
    out = out.sort_values("utc0").reset_index(drop=True)
    return out, int(bad.sum())


def _snapshot_sha(sc):
    import hashlib
    t = chr(10).join("%s:%r:%r" % (k, a, b) for k, a, b in zip(sc["key"], sc["A0"], sc["A1"]))
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _chain_cells(chain, months, nb, tag):
    sel = chain["scored"] & chain["month"].isin(months)
    c = _cell(tag, chain.loc[sel, "err"].values, (3.0, 2.0), chain.loc[sel, "day"].values, nb, kind="chain", blocks=week_blocks(chain.loc[sel, "day"].values) if sel.sum() else None)
    if "blockBootstrap7d" in c:
        bb = c["blockBootstrap7d"]
        c["blockReading"] = {"status": "not evaluable (fewer than 5 blocks)"} if bb["nBlocks"] < 5 else {"mae": "outside" if c["mae"] > 3.0 else ("within" if bb["maeCi"][1] <= 3.0 else "inconclusive"), "bias": reading(c["bias"], bb["biasCi"], 2.0)}
    return c


def extract_p1(sc, params, months=WINTER, nb=NB, sensitivities=True):
    """The P1 cells on a sidecar `sc` (all drives of the scoring window, clean or not). months: the months of the scored drive (primary Dec-Feb). Returns the cells, the re-anchor and exclusion counts, the sensitivities and the disclosures."""
    sc, n_dropped = _prepare(sc)
    D = build_pair_table(sc, params)
    chain, ra = free_run(sc, D, params)
    cells = {"A_freeRun": _chain_cells(chain, months, nb, "A_freeRun")}
    U = D[D["use"] & D["month"].isin(months)]
    cells["B1_gap12h"] = _cell("B1_gap12h", U.loc[U["gap_h"] >= 12, "bias"].values, 1.0, U.loc[U["gap_h"] >= 12, "n_day"].values, nb)
    for nm, lo, hi in (("B2_10C", 7, 13), ("B3_15C", 12, 18)):
        m = (U["y"] >= lo) & (U["y"] <= hi)
        cells[nm] = _cell(nm, U.loc[m, "bias"].values, 0.5, U.loc[m, "n_day"].values, nb)
    sts = [c["status"] for c in cells.values()]
    p1 = "not evaluable" if "not evaluable" in sts else ("outside" if "outside" in sts else ("within" if all(s == "within" for s in sts) else "inconclusive"))
    inwin = chain["month"].isin(months)
    notscored = {"anchored": int((chain["anchored"] & inwin).sum()), "noLoggedStart": int((~chain["anchored"] & ~np.isfinite(chain["err"]) & inwin).sum()), "lowCurrentCoverage": int((~chain["anchored"] & np.isfinite(chain["err"]) & (chain["icov"] < ICOV_MIN) & inwin).sum()), "noCurrentCoverageValue": int((~chain["anchored"] & np.isfinite(chain["err"]) & chain["icov"].isna() & inwin).sum()),
                 "scoredWithLowCoveragePredecessor": int((chain["scored"] & inwin & (chain["prev_icov"] < ICOV_MIN)).sum())}
    out = {"prediction": "P1", "status": {"within": "within the frozen tolerance", "outside": "outside the frozen tolerance", "inconclusive": "inconclusive", "not evaluable": "not evaluable"}[p1], "months": list(months), "cells": cells,
           "cellsOutside": [k for k, c in cells.items() if c["status"] == "outside"], "reanchors": ra, "droppedSidecarRows": n_dropped, "notScored": notscored, "nDrivesInChain": int(len(sc)), "nPairsEligibleNotFlagged": int(D["use"].sum()),
           "ambientSnapshotSha256": _snapshot_sha(sc),
           "disclosure": ["the logged start is the mean of the pack-probe readings at the first sample, not a measurement of the cell", "restart ambient is a heat-soaked vehicle-sensor reading (an input)", "winter amplitude 0.7 x autumn is an assumption, not a fit",
                          "parameters were fitted on May-Nov: winter is out-of-time, not a clean hold-out", "the chain carries error across days and across month boundaries (December errors carry a propagated November state; the next-drive ambient uses its own month amplitude at Nov/Dec and Feb/Mar)",
                          "model-derived, propagated start-temperature error", "cold outputs stay NOT SUPPORTED"]}
    if sensitivities:
        s = {}
        c2, r2 = free_run(sc, D, params, segmented=True)
        s["flagSegmentedChain"] = _chain_cells(c2, months, nb, "A_seg") | {"reanchors": r2}
        D0 = build_pair_table(sc, params, winter_reduction=False)
        c0, _ = free_run(sc, D0, params)
        s["noWinterAmplitudeReduction"] = _chain_cells(c0, months, nb, "A_amp1")
        for nm, w in (("B2_10C_pm2", (8, 12)), ("B3_15C_pm2", (13, 17))):
            m = (U["y"] >= w[0]) & (U["y"] <= w[1])
            s[nm] = _cell(nm, U.loc[m, "bias"].values, 0.5, U.loc[m, "n_day"].values, nb)
        for nm, w in (("B2_10C_selectedOnPredicted", (7, 13)), ("B3_15C_selectedOnPredicted", (12, 18))):
            m = (U["pred"] >= w[0]) & (U["pred"] <= w[1])
            s[nm] = _cell(nm, U.loc[m, "bias"].values, 0.5, U.loc[m, "n_day"].values, nb)
        out["sensitivities"] = s
        a_ = cells["A_freeRun"]
        if a_.get("bias") is not None and s["flagSegmentedChain"].get("bias") is not None and abs(a_["bias"] - s["flagSegmentedChain"]["bias"]) > 1.0:
            out["flaggedJoinNote"] = "the free-run bias differs by more than 1 C between the propagated and the flag-segmented chain: most of it builds up across flagged or ineligible joins (unlogged use or incomplete records cannot be told apart); the subsets differ, so this is not a clean attribution"
        out["novemberBeside"] = {"A_freeRun": _chain_cells(chain, (11,), nb, "A_nov")}
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--build" in a:
        print("build the sidecar through winter_score (needs the scoring keys); see tools/winter_score.py")
