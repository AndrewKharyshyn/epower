#!/usr/bin/env python3
"""M727 (analyses/M727_spec.md Rev 2, pre-registered): extractors of the observed quantities of the M717 winter predictions P2, P3, P5 and P7.
Pure functions on per-drive frames (analyses/M713/exposure_drives.csv joined to the master ambient and the clean flag); nothing here reads a live model output, a prediction, a band or a post-freeze observation by itself.
Every number, window, class, weight and threshold below is frozen by the spec; alternatives are labelled sensitivities and never change a status. Associations, not temperature effects (P5, P7); model-derived; logged / app-calculated, never measured.
The extractors answer a plain dict; the comparison with the frozen predictions is done by tools/winter_score.py (registry-gated)."""
import math, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SEED, NB = 42, 4000
VERSION = 1
RGAS = 8.314462618
P3_WINDOW_MAIN, P3_WINDOW_SENS = (-2.0, 2.0), (-5.0, 3.0)
P3_EXTRAPOLATION_BELOW_C = 1.0
P5_BOUND_PER_C = math.log(1.06) / 10.0                    # 0.005827
P5_MIN_DT_C, P5_MIN_CELL_DRIVES = 3.0, 3
P7_MIN_IQR_C = 3.0
AMBIENT_MAX_C = 20.0
DIST_EDGES, SPEED_EDGES = (3.0, 10.0), (30.0, 60.0)
COLUMNS = {"P2": ["ahc_T_<0", "ahc_T_0-5", "ahc_T_5-10", "ahd_T_<0", "ahd_T_0-5", "ahd_T_5-10"], "P3": ["R_pulse_mohm", "T_pulse"],
           "P5": ["km", "ah", "spd_s", "dur_h", "ambient_start_c", "ambient_end_c", "month", "start"], "P7": ["km", "ah", "spd_s", "dur_h", "eng_on_s", "rpm_s", "ambient_start_c", "ambient_end_c"]}


# ------------------------------------------------------------------------------------------------ input frame
def load_frame(root=ROOT):
    """The exposure frame with the drive ambient (seasonal_drive_master ambient_start_c / ambient_end_c) and the canonical clean flag of the master (a missing flag is kept, M707 B1). Column order and row order of the frame are kept."""
    fr = pd.read_csv(os.path.join(root, "analyses", "M713", "exposure_drives.csv"), low_memory=False, dtype={"key": str})
    fr["day"] = pd.to_datetime(fr["day"]).dt.strftime("%Y-%m-%d")
    fr["start"] = pd.to_datetime(fr["start"])
    sd = pd.read_csv(os.path.join(root, "seasonal_drive_master.csv"), low_memory=False, usecols=["file", "ambient_start_c", "ambient_end_c"])
    sd["key"] = ["".join(ch for ch in str(f) if ch.isdigit()) for f in sd["file"]]
    fr = fr.merge(sd[["key", "ambient_start_c", "ambient_end_c"]], on="key", how="left")
    dm = pd.read_csv(os.path.join(root, "drive_master.csv"), low_memory=False, usecols=["file", "ens_outlier_v2"])
    dm["key"] = ["".join(ch for ch in str(f) if ch.isdigit()) for f in dm["file"]]
    flag = dm["ens_outlier_v2"].astype(str).str.strip().str.lower().isin(["true", "1"])
    bad = set(dm.loc[flag, "key"])
    fr["clean"] = ~fr["key"].isin(bad)
    return fr


def _classes(df):
    d = np.digitize(df["km"].values, DIST_EDGES)
    v = np.digitize((df["km"] / df["dur_h"]).values, SPEED_EDGES)
    return d * 3 + v


# ------------------------------------------------------------------------------------------------ bootstraps
def proto_boot(df, ycol, xcols, nb=NB, seed=SEED):
    """The prototype's day-clustered OLS bootstrap (analyses/exposure_scenarios_2026-11-16/thermal_model.py, ols_boot): days in order of first appearance, one default_rng(seed).integers draw per replicate, lstsq on the resampled rows."""
    X = np.column_stack([np.ones(len(df))] + [df[c].values.astype(float) for c in xcols])
    y = df[ycol].values.astype(float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    days = df["day"].values
    dl = pd.unique(days)
    gi = {d: np.flatnonzero(days == d) for d in dl}
    rng = np.random.default_rng(seed)
    bs = np.empty((nb, len(b)))
    for i in range(nb):
        ix = np.concatenate([gi[dl[j]] for j in rng.integers(0, len(dl), len(dl))])
        bs[i] = np.linalg.lstsq(X[ix], y[ix], rcond=None)[0]
    return b, bs, len(dl)


def _day_stats(df, num, den=None):
    g = df.assign(_n=num, _d=(den if den is not None else 1.0)).groupby("day")[["_n", "_d"]].sum()
    return g["_n"].values, g["_d"].values


def ratio_of_sums_ci(df, num, den, nb=NB, seed=SEED):
    """Pooled ratio of sums and its day-clustered percentile interval."""
    n, d = _day_stats(df, num, den)
    est = float(n.sum() / d.sum())
    rng = np.random.default_rng(seed)
    k = len(n)
    idx = rng.integers(0, k, size=(nb, k))
    r = n[idx].sum(axis=1) / d[idx].sum(axis=1)
    return est, [float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))], k


# ------------------------------------------------------------------------------------------------ P2
def extract_p2(df, nb=NB):
    """Pooled Ah share below 10 C = Ah (charge plus discharge) with pack temperature below 10 C / total Ah over the temperature bins of the frame; ratio of sums, day-clustered interval."""
    lo = df[COLUMNS["P2"]].fillna(0.0).sum(axis=1).values
    allc = [c for c in df.columns if (c.startswith("ahc_T_") or c.startswith("ahd_T_"))]
    tot = df[allc].fillna(0.0).sum(axis=1).values
    if len(df) == 0 or tot.sum() <= 0:
        return {"nDrives": int(len(df)), "nDays": 0, "estimate": None, "ci95": None}
    est, ci, k = ratio_of_sums_ci(df, lo, tot, nb)
    return {"nDrives": int(len(df)), "nDays": int(k), "estimate": est, "ci95": ci, "kind": "ahShareBelow10C"}


# ------------------------------------------------------------------------------------------------ P3
def extract_p3(df, ea_kjmol, r25_mohm, window=P3_WINDOW_MAIN, nb=NB, own25_mohm=None):
    """Pulse-resistance proxy ratio at 0 C against the 25 C value: each pulse (R_pulse_mohm in 20..600 with T_pulse in the window) is brought to 0 C with the frozen EaR and R25; ratio_i = R_i / R25 x exp(-Ea/Rgas x (1/T_i - 1/273.15)) with T in kelvin;
    estimate = unweighted mean over drives, day-clustered interval. Also the UNCORRECTED mean of R_i / R25 and the label 'extrapolation test' for pulses below 1.0 C."""
    p = df[(df["R_pulse_mohm"] > 20) & (df["R_pulse_mohm"] < 600) & df["T_pulse"].notna() & (df["T_pulse"] >= window[0]) & (df["T_pulse"] <= window[1])].copy()
    if len(p) == 0:
        return {"nDrives": 0, "nDays": 0, "estimate": None, "ci95": None, "window": list(window)}
    T = p["T_pulse"].values + 273.15
    raw = p["R_pulse_mohm"].values / r25_mohm
    ratio = raw * np.exp(-(ea_kjmol * 1000.0) / RGAS * (1.0 / T - 1.0 / 273.15))
    est, ci, k = ratio_of_sums_ci(p, ratio, np.ones(len(p)), nb)
    unc = ratio_of_sums_ci(p, raw, np.ones(len(p)), nb)
    own = None
    if own25_mohm:                                                  # M727 8.2: labelled sensitivity, never changes the status
        r_own = ratio * (r25_mohm / own25_mohm)
        oe = ratio_of_sums_ci(p, r_own, np.ones(len(p)), nb)
        own = {"estimate": oe[0], "ci95": oe[1], "nDays": int(oe[2]), "denominatorMohm": float(own25_mohm), "label": "sensitivity: Ea-corrected ratio against the frame's own 25 C level; never changes the status"}
    return {"nDrives": int(len(p)), "nDays": int(k), "estimate": est, "ci95": ci, "window": list(window), "uncorrected": {"estimate": unc[0], "ci95": unc[1]}, "ownLevelSensitivity": own,
            "nPulsesBelow1C": int((p["T_pulse"] < P3_EXTRAPOLATION_BELOW_C).sum()), "label": "extrapolation test" if (p["T_pulse"] < P3_EXTRAPOLATION_BELOW_C).any() else "interpolation check"}


# ------------------------------------------------------------------------------------------------ P7 and the shared prototype set
def prototype_set(df):
    """The prototype's Q set: km > 0.5, ah > 0, ambient present, spd_s > 60; A = (ambient_start_c + ambient_end_c) / 2; lnkm, vmean = km / dur_h, ln(ah / km), eng = eng_on_s / max(rpm_s, 1)."""
    q = df[(df["km"] > 0.5) & (df["ah"] > 0) & df["ambient_start_c"].notna() & (df["spd_s"] > 60)].copy()
    q["A"] = (q["ambient_start_c"] + q["ambient_end_c"]) / 2
    q["lnahkm"] = np.log(q["ah"] / q["km"])
    q["lnkm"] = np.log(q["km"])
    q["vmean"] = q["km"] / q["dur_h"]
    q["eng"] = q["eng_on_s"] / q["rpm_s"].clip(lower=1)
    return q


def extract_p7(df, nb=NB):
    """Slope of the engine-on share (points) on cooling over the prototype set with A below 20 C: OLS of 100 x eng on [1, A, ln km, vmean], day-clustered interval (the prototype bootstrap); cooling slope = minus the coefficient of A.
    A winter ambient interquartile range below 3 C -> 'not evaluable'."""
    q = prototype_set(df)
    q = q[q["A"] < AMBIENT_MAX_C].copy()
    if len(q) < 5:
        return {"nDrives": int(len(q)), "nDays": int(q["day"].nunique()), "estimate": None, "ci95": None, "status": "not evaluable"}
    iqr = float(np.percentile(q["A"], 75) - np.percentile(q["A"], 25))
    if iqr < P7_MIN_IQR_C:
        return {"nDrives": int(len(q)), "nDays": int(q["day"].nunique()), "estimate": None, "ci95": None, "status": "not evaluable", "reason": "winter ambient IQR %.2f C below %.1f C" % (iqr, P7_MIN_IQR_C)}
    q["eng100"] = 100.0 * q["eng"]
    b, bs, nd = proto_boot(q, "eng100", ["A", "lnkm", "vmean"], nb)
    est = -float(b[1])
    ci = [-float(np.percentile(bs[:, 1], 97.5)), -float(np.percentile(bs[:, 1], 2.5))]
    return {"nDrives": int(len(q)), "nDays": int(nd), "estimate": est, "ci95": ci, "ambientIqrC": iqr, "ambientRangeC": [float(q["A"].min()), float(q["A"].max())], "coefficientOfA": float(b[1]), "unit": "points per C of cooling"}


# ------------------------------------------------------------------------------------------------ P5
def _p5_stat(wcell, wy, wA, wmult, acell, ay, aA, amult, ncell=9, per_draw=True, fixed_cells=None, fixed_wt=None):
    """(s, dln, dT) of one (re)sample. per_draw=True (primary, spec 8.1): the cells with >= 3 drives (multiplicities counted) in BOTH sets are recomputed from this sample, the winter cell counts of this sample are the weights, dT over the kept drives.
    per_draw=False (variant reported beside): the cells and weights are fixed from the observed data; a cell empty in this sample is skipped and the weights renormalised."""
    nw = np.bincount(wcell, weights=wmult, minlength=ncell)
    na = np.bincount(acell, weights=amult, minlength=ncell)
    sw = np.bincount(wcell, weights=wmult * wy, minlength=ncell)
    sa = np.bincount(acell, weights=amult * ay, minlength=ncell)
    if per_draw:
        el = (nw >= P5_MIN_CELL_DRIVES) & (na >= P5_MIN_CELL_DRIVES)
        wts = np.where(el, nw, 0.0)
    else:
        el = np.zeros(ncell, bool)
        el[fixed_cells] = True
        el &= (nw > 0) & (na > 0)
        wts = np.where(el, fixed_wt, 0.0)
    if not el.any():
        return np.nan, np.nan, np.nan
    wts = wts / wts.sum()
    dln = float(np.sum(wts[el] * (sw[el] / nw[el])) - np.sum(wts[el] * (sa[el] / na[el])))
    kw, ka = np.isin(wcell, np.flatnonzero(el)), np.isin(acell, np.flatnonzero(el))
    dt = float(np.sum((amult * aA)[ka]) / amult[ka].sum() - np.sum((wmult * wA)[kw]) / wmult[kw].sum())
    return dln - P5_BOUND_PER_C * dt, dln, dt


def extract_p5(winter, autumn, nb=NB, seed=SEED):
    """Winter against autumn cooling statistic of ln(Ah per km) on matched trip-length x speed cells (spec section 3 and 8.1): dln = weighted mean ln(Ah/km) winter - the same autumn; dT = mean autumn A - mean winter A (over the kept drives);
    s = dln - ln(1.06)/10 x dT. Days resampled independently per set; in EACH draw the cell eligibility (>= 3 drives in both sets) and the weights are recomputed (primary); the fixed-cell variant is reported beside. 'rejected' iff the 2.5th percentile
    of s (primary) is above zero. Prototype filters and A for both sets; winter drives need A below 20 C; observed dT below 3 C -> 'not evaluable'; a draw without an eligible cell is dropped and counted (> 1 % -> 'not evaluable'); the dropped share of winter drives is reported."""
    w = prototype_set(winter)
    w = w[w["A"] < AMBIENT_MAX_C].copy()
    a = prototype_set(autumn)
    if len(w) == 0 or len(a) == 0:
        return {"status": "not evaluable", "reason": "an empty set", "nWinter": int(len(w)), "nAutumn": int(len(a))}
    w["cell"] = _classes(w)
    a["cell"] = _classes(a)
    cw, ca = w["cell"].value_counts(), a["cell"].value_counts()
    keep = sorted(c for c in cw.index if cw[c] >= P5_MIN_CELL_DRIVES and ca.get(c, 0) >= P5_MIN_CELL_DRIVES)
    dropped = float(1.0 - w["cell"].isin(keep).mean())
    if not keep:
        return {"status": "not evaluable", "reason": "no cell with >= %d drives in both sets" % P5_MIN_CELL_DRIVES, "nWinter": int(len(w)), "nAutumn": int(len(a)), "droppedShareOfWinterDrives": dropped}
    wk, ak = w[w["cell"].isin(keep)].copy(), a[a["cell"].isin(keep)].copy()
    dT = float(ak["A"].mean() - wk["A"].mean())
    if dT < P5_MIN_DT_C:
        return {"status": "not evaluable", "reason": "winter-autumn ambient difference %.2f C below %.1f C" % (dT, P5_MIN_DT_C), "nWinter": int(len(wk)), "nAutumn": int(len(ak)), "droppedShareOfWinterDrives": dropped}
    # Rev 3 / spec 8.1: the bootstrap works on the FULL winter and autumn sets (every cell, every filtered drive); in each draw the eligible cells (>= 3 drives in both sets, multiplicities counted) and the weights are recomputed
    # from the draw; the point estimate is the same statistic on the observed data (unit multiplicities), which keeps exactly the observed cells with >= 3 drives in both sets.
    wc, ac = w["cell"].values.astype(int), a["cell"].values.astype(int)
    wy, ay, wA, aA = w["lnahkm"].values, a["lnahkm"].values, w["A"].values, a["A"].values
    est, dln0, dt0 = _p5_stat(wc, wy, wA, np.ones(len(w)), ac, ay, aA, np.ones(len(a)))
    fixed_wt = np.bincount(wc, minlength=9).astype(float)
    wdays, adays = pd.unique(w["day"].values), pd.unique(a["day"].values)
    wd_idx = [np.flatnonzero(w["day"].values == d) for d in wdays]
    ad_idx = [np.flatnonzero(a["day"].values == d) for d in adays]
    rng = np.random.default_rng(seed)
    prim, fixed = np.empty(nb), np.empty(nb)
    keep_arr = np.array(keep)
    for i in range(nb):
        wm, am = np.zeros(len(w)), np.zeros(len(a))
        for j in rng.integers(0, len(wdays), len(wdays)):
            wm[wd_idx[j]] += 1.0
        for j in rng.integers(0, len(adays), len(adays)):
            am[ad_idx[j]] += 1.0
        prim[i] = _p5_stat(wc, wy, wA, wm, ac, ay, aA, am)[0]
        fixed[i] = _p5_stat(wc, wy, wA, wm, ac, ay, aA, am, per_draw=False, fixed_cells=keep_arr, fixed_wt=fixed_wt)[0]
    undefined = int(np.sum(~np.isfinite(prim)))
    if undefined > 0.01 * nb:
        return {"status": "not evaluable", "reason": "%d of %d draws undefined (> 1 %%)" % (undefined, nb), "nUndefinedDraws": undefined}
    p = prim[np.isfinite(prim)]
    f = fixed[np.isfinite(fixed)]
    p025, p975 = float(np.percentile(p, 2.5)), float(np.percentile(p, 97.5))
    f025, f975 = float(np.percentile(f, 2.5)), float(np.percentile(f, 97.5))
    status = "rejected" if p025 > 0.0 else "not rejected"
    fstatus = "rejected" if f025 > 0.0 else "not rejected"
    return {"status": status, "scheme": "per-draw recomputation of cell eligibility and weights (primary, spec 8.1)", "statistic": float(est), "p025": p025, "p975": p975, "dln": float(dln0), "dTc": float(dt0), "boundPerC": P5_BOUND_PER_C,
            "nUndefinedDraws": undefined, "fixedCellVariant": {"p025": f025, "p975": f975, "status": fstatus, "disagreesWithPrimary": bool(fstatus != status)},
            "nWinter": int(len(wk)), "nAutumn": int(len(ak)), "nWinterAll": int(len(w)), "nAutumnAll": int(len(a)), "nWinterDays": int(len(wdays)), "nAutumnDays": int(len(adays)), "cells": int(len(keep)), "droppedShareOfWinterDrives": dropped,
            "reading": "association (season, route and period move together), not a temperature effect; not rejected is not no increase"}
