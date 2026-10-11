#!/usr/bin/env python3
"""M404 (analyses/M403_spec.md v4, Rev 1b): the remaining pre-registered pieces of the capacity basis, all additive leaves of the payload block capacityBasis (written by tools/capacity_basis.py):
  shadow_eligibility  the hard domain rules (|energy residual| > threshold, the pipeline's own _domain_rules and two-pass offset iteration) recomputed under a candidate SoC energy scale; the scale is
                      fitted ONCE (no iteration between scale and population); both thresholds reported; flip count of the canonical-clean status. At K = 2.1 kWh the shadow reproduces the master exactly.
  offset_test (b)     per-drive terminal net energy vs the SoC drop: {global offset, I2R + offset} x {2.1 kWh fixed, estimated scale}; folds are whole calendar days (>= 5) with scale and R fitted
                      INSIDE each training fold, plus two chronological folds; metric = held-out per-drive residual RMS; acceptance (i)-(iv) of the spec; failure of any means dual report only.
  level_test (c)      ONE pre-registered test: linear slope of the apparent Ah per 100 points on the segment-centre SoC (per 10 SoC points), unadjusted and adjusted for mean |I|, temperature, logging regime
                      and engine state; equivalence to 0 within +-0.10 Ah per 10 points only if the adjusted slope is equivalent, the VIF of the SoC term is < 5 and the test is powered.
  keyon_test (h)      SoC jump at key-on vs the net charge of the previous drive, by rest time and by direction of the last current (consistency check; not an estimate of the scale).
  zero_current        leading stationary samples (|I| < 5 A, speed < 1 km/h, engine < 400 rpm, first 120 s): median current with a day-clustered CI (an operational proxy, not a verified Ready state).
  exposure            raw Ah and kWh throughput (primary) and the reference-normalised counts under each reference, from ah_throughput.csv and the master.
A test whose own interval half-width is not smaller than its margin is 'not powered' and takes the conservative outcome. Nothing here changes a headline."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.dirname(__file__) not in sys.path:
    sys.path.insert(0, os.path.dirname(__file__))
import capacity_basis as CB

CAP_KWH_LEGACY = 2.1
OFFSET_MARGIN_A = 0.10
LEVEL_MARGIN_AH_PER10 = 0.10
R_RATIO_MAX = 1.25
VIF_I2R_MAX, VIF_LEVEL_MAX = 10.0, 5.0
NFOLD = 5
OEM_R_80_OHM = 0.210


# ------------------------------------------------------------------------------------------------ shadow eligibility
def _domain_shadow(dm, K, thr):
    """(excluded flags, converged offset A, passes) of the pipeline's two-pass domain rule with residual = net draw - (soc_start - soc_end)/100*K and threshold thr (seeded by the master's f_domain)."""
    import compute_drive_summary_v6 as D
    res = dm["net_draw_kwh"] - (dm["soc_start"] - dm["soc_end"]) / 100.0 * K
    m = res.notna() & dm["duration_s"].notna() & dm["V_pack_median"].notna()
    h_all = dm["integr_time_h"].fillna(dm["duration_s"] / 3600.0)
    Vw = float((dm.loc[m, "V_pack_median"] * dm.loc[m, "integr_time_h"]).sum() / dm.loc[m, "integr_time_h"].sum())
    io = dm[dm["gross_throughput_kwh"].notna()]
    excl = dm["f_domain"].fillna(False).astype(bool)
    old, i2, passes = D.RESIDUAL_MAX_KWH, None, 0
    D.RESIDUAL_MAX_KWH = thr
    try:
        for passes in range(1, D.OFFSET_MAX_PASSES + 1):
            mm = m & ~excl
            i2 = float(res[mm].sum() * 1000.0 / (dm.loc[mm, "integr_time_h"].sum() * Vw))
            r2 = res - i2 * dm["V_pack_median"] * h_all / 1000.0
            f2 = pd.Series(False, index=dm.index)
            f2.loc[io.index] = D._domain_rules(io, r2.loc[io.index].values)
            if f2.equals(excl):
                break
            excl = f2
    finally:
        D.RESIDUAL_MAX_KWH = old
    return excl, i2, passes


def shadow_eligibility(dm, k_est):
    ref = dm["f_domain_2p"].fillna(False).astype(bool)
    base, off0, _ = _domain_shadow(dm, CAP_KWH_LEGACY, 0.35)
    out = {"scaleKwhPer100": k_est, "legacyScaleKwh": CAP_KWH_LEGACY, "reproducesMasterAtLegacyScale": bool((base == ref).all()), "legacyOffsetA": round(off0, 4),
           "nExcludedMaster": int(ref.sum()), "variants": {},
           "note": "scale fitted once on the legacy population (no iteration between scale and population); eligibility is NOT changed by this milestone; reported as 0 flips of N drives under both thresholds, with the shadow reproducing the master at 2.1 kWh; rerun on every ingestion while the dual report stands, any flip escalates to the Director",
           "comparabilityNote": "the shadow offsets, the legacy offset and the offsets of test (b) belong to different models and scales and are never displayed side by side"}
    for name, thr in (("thresholdUnchanged_0.35", 0.35), ("thresholdScaleOver6", k_est / 6.0)):
        e, off, passes = _domain_shadow(dm, k_est, thr)
        out["variants"][name] = {"threshold": round(float(thr), 4), "nExcluded": int(e.sum()), "flips": int((e != ref).sum()), "toExcluded": int((e & ~ref).sum()), "toClean": int((~e & ref).sum()),
                                 "flippedFiles": dm.loc[e != ref, "file"].tolist()[:20], "offsetA": round(off, 4), "passes": int(passes)}
    out["flipsAny"] = any(v["flips"] for v in out["variants"].values())
    return out


# ------------------------------------------------------------------------------------------------ exposure
def exposure(dm, side, q_est, e_est):
    flag = dm["ens_outlier_v2"].map(lambda v: str(v).strip().lower())
    ok = (flag == "false") & dm["gross_discharge_kwh"].notna()
    d = dm[ok].merge(side[["file", "ah_discharge", "ah_charge"]], on="file", how="inner").dropna(subset=["ah_discharge", "ah_charge"])
    Ed, Ec = float(d["gross_discharge_kwh"].sum()), float(d["gross_charge_kwh"].sum())
    Ahd, Ahc = float(d["ah_discharge"].sum()), float(d["ah_charge"].sum())
    vconv = e_est / q_est
    q_equiv_21 = CAP_KWH_LEGACY / vconv
    f_min = q_est / q_equiv_21

    def energy_row(ref):
        return {"referenceKwh": ref, "dischargeEFC": Ed / ref, "bidirectionalFCE": (Ed + Ec) / (2 * ref), "grossTurnoverGTC": (Ed + Ec) / ref}

    def charge_row(ref):
        return {"referenceAh": ref, "chargeThroughputEFC": (Ahd + Ahc) / (2 * ref), "grossTurnoverAhPerRef": (Ahd + Ahc) / ref}
    rf = float(dm.loc[flag == "false", "rf_efc"].sum()) if "rf_efc" in dm else None
    return {"population": {"nDrives": int(len(d)), "rule": "ens_outlier_v2 explicitly False with Ah and kWh from the same integrable pairs"},
            "primaryRaw": {"dischargeKwh": Ed, "chargeKwh": Ec, "throughputKwh": Ed + Ec, "dischargeAh": Ahd, "chargeAh": Ahc, "throughputAh": Ahd + Ahc,
                           "note": "integrated from logged current samples (estimated throughput, raw-current integral before any offset); the reference-normalised counts below are secondary and inversely proportional to the chosen reference"},
            "energyReferences": {"legacy_2.1kWh": energy_row(CAP_KWH_LEGACY), "apparentSoCScale": energy_row(e_est)},
            "chargeReferences": {"rated_5.0Ah": charge_row(5.0), "apparentSoCScale": charge_row(q_est), "windowFractionBand_fMinEnd": charge_row(q_equiv_21)},
            "windowFractionBand": {"fMin": f_min, "fMinEndReferenceAh": q_equiv_21, "qSocEstAhPer100": q_est, "referenceAhRangeFromQSocEstOverF": [q_est, q_equiv_21], "vConvKwhPerAh": vconv,
                                   "note": "scenario parameter, not an estimate: f = Q_SOC_EST / Q_full; the lower bound reads 2.1 kWh as a gross figure converted with the same V_CONV; not testable from BMS-scale data"},
            "socRainflowEFC": {"value": rf, "reference": "logged BMS SoC scale (unchanged)"},
            "formulas": {"dischargeEFC": "Ed / Eref", "bidirectionalFCE": "(Ed + Ec) / (2 Eref)", "grossTurnoverGTC": "(Ed + Ec) / Eref (twice FCE; not a conventional cycle count)",
                         "chargeThroughputEFC": "(Ahd + Ahc) / (2 Qref)", "socRainflowEFC": "sum(depth/100 x cycle count) on the logged SoC scale"},
            "reading": "changing the reference from 2.1 kWh to 1.8 kWh raises every normalised count by the same factor with unchanged physical throughput; weakest-cell caveat: pack-level counts are a lower bound for the weakest cell only if that cell's capacity is at or below the reference"}


# ------------------------------------------------------------------------------------------------ test (b): offset vs I2R
def _folds(days, nfold, seed):
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(days))
    return {days[i]: k % nfold for k, i in enumerate(perm)}


def _design(d, name):
    z, off, loss = d["z"].to_numpy(), d["off"].to_numpy(), d["loss"].to_numpy()
    y = d["y"].to_numpy()
    lt = d["lossT"].to_numpy()
    if name == "offset_est":
        return np.column_stack([z, off]), y
    if name == "offset_fix":
        return np.column_stack([off]), y - CAP_KWH_LEGACY * z
    if name == "i2r_est":
        return np.column_stack([z, off, -loss]), y
    if name == "i2r_fix":
        return np.column_stack([off, -loss]), y - CAP_KWH_LEGACY * z
    if name == "i2rT_est":
        return np.column_stack([z, off, -loss, -lt]), y
    raise ValueError(name)


MODELS = ("offset_est", "offset_fix", "i2r_est", "i2r_fix", "i2rT_est")


def _fit_predict(tr, te, name):
    X, y = _design(tr, name)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    Xt, yt = _design(te, name)
    return yt - Xt @ beta, beta


def offset_test(dm, extras, nfold=NFOLD, seed=CB.SEED, nb=None):
    """Test (b). dm: master frame; extras: {file: drive-extras dict with i2h and temp}."""
    flag = dm["ens_outlier_v2"].map(lambda v: str(v).strip().lower())
    d = dm[flag == "false"].copy()
    d["i2h"] = d["file"].map(lambda f: (extras.get(f) or {}).get("i2h"))
    d["temp"] = d["file"].map(lambda f: (extras.get(f) or {}).get("temp"))
    d = d.dropna(subset=["net_draw_kwh", "soc_start", "soc_end", "V_pack_median", "integr_time_h", "i2h"]).reset_index(drop=True)
    if len(d) < 50:
        return {"evaluable": False, "reason": "fewer than 50 drives"}
    d["y"] = d["net_draw_kwh"]
    d["z"] = (d["soc_start"] - d["soc_end"]) / 100.0
    d["off"] = d["V_pack_median"] * d["integr_time_h"] / 1000.0
    d["loss"] = d["i2h"] / 1000.0
    tfill = d["temp"].fillna(d["temp"].median())
    d["lossT"] = d["loss"] * (tfill - 25.0) / 10.0
    days = sorted(d["date"].astype(str).unique())
    dix = {x: i for i, x in enumerate(days)}
    d["day_ix"] = d["date"].astype(str).map(dix)
    fold = _folds(days, nfold, seed)
    d["fold"] = d["date"].astype(str).map(fold)
    W = CB.boot_weights(len(days), nb)
    resid = {m: np.full(len(d), np.nan) for m in MODELS}
    r_by_fold = []
    for k in range(nfold):
        tr, te = d[d["fold"] != k], d[d["fold"] == k]
        for m in MODELS:
            e, b = _fit_predict(tr, te, m)
            resid[m][te.index] = e
            if m == "i2r_est":
                r_by_fold.append(float(b[2]))
    rms = {m: float(np.sqrt(np.mean(resid[m] ** 2))) for m in MODELS}

    def paired(a, b):
        diff = resid[a] ** 2 - resid[b] ** 2
        sd = np.bincount(d["day_ix"].to_numpy(), weights=diff, minlength=len(days))
        n = np.bincount(d["day_ix"].to_numpy(), minlength=len(days)).astype(float)
        est = float(diff.sum() / len(diff))
        bs = (W @ sd) / np.maximum(W @ n, 1.0)
        lo, hi = np.percentile(bs, [2.5, 97.5])
        return {"meanSquaredResidualReduction_kWh2": est, "ci95": [float(lo), float(hi)], "lowerBoundAbovezero": bool(lo > 0)}
    pe, pf = paired("offset_est", "i2r_est"), paired("offset_fix", "i2r_fix")
    # chronological folds
    cut = CB.CHRONO_CUT
    chrono = {}
    for label, trm, tem in (("earlyToLate", d["date"].astype(str) < cut, d["date"].astype(str) >= cut), ("lateToEarly", d["date"].astype(str) >= cut, d["date"].astype(str) < cut)):
        tr, te = d[trm], d[tem]
        if len(tr) >= 30 and len(te) >= 30:
            chrono[label] = {"nTrain": int(len(tr)), "nTest": int(len(te)), "rmsKwh": {m: float(np.sqrt(np.mean(_fit_predict(tr, te, m)[0] ** 2))) for m in MODELS}}
    # full-data fits with day-cluster CIs
    di = d["day_ix"].to_numpy(int)
    X3, y3 = _design(d, "i2r_est")
    fit_c = CB.grouped_fit(di, X3, y3, len(days), W, lambda b: b[1])
    fit_r = CB.grouped_fit(di, X3, y3, len(days), W, lambda b: b[2])
    fit_k = CB.grouped_fit(di, X3, y3, len(days), W, lambda b: b[0])
    X4, y4 = _design(d, "i2rT_est")
    fit_r0 = CB.grouped_fit(di, X4, y4, len(days), W, lambda b: b[2])
    fit_r1 = CB.grouped_fit(di, X4, y4, len(days), W, lambda b: b[3])
    Xo, yo = _design(d, "offset_est")
    fit_c0 = CB.grouped_fit(di, Xo, yo, len(days), W, lambda b: b[1])
    cols = np.column_stack([d["z"], d["off"], d["loss"]])
    Z = (cols - cols.mean(0)) / cols.std(0)
    vif = np.diag(np.linalg.inv(np.corrcoef(Z.T)))
    ratio = (max(r_by_fold) / min(r_by_fold)) if min(r_by_fold) > 0 else float("inf")
    # acceptance (i)-(iv)
    c_ci = fit_c["ci90"] if fit_c else [float("nan")] * 2
    cond_i = bool(pe["lowerBoundAbovezero"])
    cond_ii = bool(fit_c and c_ci[0] > -OFFSET_MARGIN_A and c_ci[1] < OFFSET_MARGIN_A)
    cond_iii = bool(min(r_by_fold) > 0 and ratio <= R_RATIO_MAX)
    cond_iv = bool(vif[1] <= VIF_I2R_MAX and vif[2] <= VIF_I2R_MAX)
    return {"evaluable": True, "nDrives": int(len(d)), "nDays": len(days), "nFolds": nfold,
            "scaleNote": "the drive-level scale in this regression is attenuated by SoC reading noise (errors in variables) and by loss terms of a different form: it is a model term of this test, not the capacity estimate, and must not be compared with E_PER_SOC100_EST", "folding": "whole calendar days, assigned by a seeded permutation; scale and R fitted inside each training fold",
            "heldOutRmsKwh": rms, "pairedAtEstimatedScale": pe, "pairedAtFixed2.1": pf, "chronological": chrono,
            "full": {"scaleKwhPer100": fit_k, "offsetA": fit_c, "offsetAWithoutI2R": fit_c0, "R_ohm": fit_r, "R0_ohm": fit_r0, "R_per10C_ohm": fit_r1,
                     "rByFold": r_by_fold, "rFoldMaxOverMin": ratio, "vif": {"scale": float(vif[0]), "offsetTerm": float(vif[1]), "i2Term": float(vif[2])}},
            "oemR80Ohm": OEM_R_80_OHM, "rGapToOemNote": "the fitted R is a drive-level terminal-energy loss coefficient, a different definition from the OEM 0.210 ohm at 80 % SoC; the gap is disclosed, not tuned away",
            "acceptance": {"i_lowerHeldOutErrorAtSameScale": cond_i, "ii_offsetEquivalentToZero_pm0.10A_ci90": cond_ii, "iii_rStableAcrossFolds_max_over_min_le_1.25": cond_iii,
                           "iv_identifiable_vif_le_10": cond_iv, "acceptI2R": bool(cond_i and cond_ii and cond_iii and cond_iv)},
            "decision": "I2R model accepted for the offset term" if (cond_i and cond_ii and cond_iii and cond_iv) else "dual report only: the global offset basis is unchanged",
            "comparabilityNote": "offset values from different models and scales (with or without the I2R term; legacy 2.1 kWh, the drive-level scale, the shadow scale) are not comparable and are never displayed side by side; the drive-level R is an effective I2-loss coefficient, model-derived, not an internal-resistance measurement",
            "note": "(ii) uses the 90 % TOST interval, harmonised with (c) (the outcome is the same on the 95 % interval); a test that cannot be powered defaults to the conservative outcome"}


# ------------------------------------------------------------------------------------------------ test (c): level dependence
def level_test(recs, n_days, W):
    ev = CB._event_rows(recs, "primary")
    if not len(ev["lev"]):
        return {"evaluable": False}
    lev = ev["lev"]
    c1 = lev * (ev["centre"] - 55.0) / 10.0
    def f(v):
        mu = np.nanmean(v) if np.isfinite(v).any() else 0.0
        return np.where(np.isfinite(v), v, mu)
    absI, eng, temp, fast = f(ev["absI"]), f(ev["eng"]), f(ev["temp"]), ev["fast"]
    adj = [lev * (absI - absI.mean()) / 10.0, lev * (temp - temp.mean()) / 10.0, lev * (fast - fast.mean()), lev * (eng - eng.mean())]
    adj = [a_ for a_ in adj if np.std(a_) > 1e-9]                      # a covariate with no variation (e.g. a missing channel) is not part of the adjustment
    di = ev["day"].astype(int)
    slope = lambda b: 100.0 * b[2]
    un = CB.grouped_fit(di, np.column_stack([lev, ev["th"], c1]), ev["Q"], n_days, W, slope)
    at55 = CB.grouped_fit(di, np.column_stack([lev, ev["th"], c1]), ev["Q"], n_days, W, lambda b: 100.0 * b[0])
    Xa = np.column_stack([lev, ev["th"], c1] + adj)
    ad = CB.grouped_fit(di, Xa, ev["Q"], n_days, W, slope)
    Z = (Xa - Xa.mean(0)) / Xa.std(0)
    vif = float(np.diag(np.linalg.inv(np.corrcoef(Z.T)))[2])
    mg = LEVEL_MARGIN_AH_PER10

    def equiv(f_):
        return bool(f_ and f_["ci90"][0] > -mg and f_["ci90"][1] < mg)
    powered = bool(ad and (ad["ci90"][1] - ad["ci90"][0]) / 2.0 < mg)
    conclude = bool(equiv(ad) and vif < VIF_LEVEL_MAX and powered)
    present = bool(ad and (ad["ci95"][0] > 0 or ad["ci95"][1] < 0) and not equiv(ad))      # a slope whose interval excludes zero and is not equivalent: power matters only for concluding equivalence
    terc = {}
    for name, lo, hi in (("below55", -1e9, 55.0), ("55to65", 55.0, 65.0), ("atLeast65", 65.0, 1e9)):
        m = (ev["centre"] >= lo) & (ev["centre"] < hi)
        terc[name] = (CB.grouped_fit(di[m], np.column_stack([lev[m], ev["th"][m]]), ev["Q"][m], n_days, W, lambda b: 100.0 * b[0]) if m.sum() > 100 else None)
    return {"evaluable": True, "marginAhPer10SoCPoints": mg, "unadjustedSlope": un, "unadjustedScaleAtCentre55AhPer100": at55, "adjustedSlope": ad, "unadjustedEquivalent": equiv(un), "adjustedEquivalent": equiv(ad),
            "vifSoCTerm": vif, "vifMax": VIF_LEVEL_MAX, "powered": powered, "poweredMeans": "the 90 % half-width is below the margin; it concerns the equivalence conclusion only, not whether a slope is present",
            "averagedOver": "the constant scale is an average over the observed SoC distribution (about 44-83 %)", "covariates": ["mean |I| per segment", "pack temperature (sensor 1 median)", "logging regime", "engine-on fraction"],
            "outcome": ("equivalent to zero (constant scale)" if conclude else ("SoC-level-associated variation of the apparent scale, attribution unresolved (adjusted slope not equivalent to zero): Option C stays a pre-registered sensitivity only" if present else "unresolved")),
            "terciles": {"descriptive": True, "byAhPer100": terc, "note": "descriptive only; engine state and regime are themselves driven by SoC, so adjustment pulls the slope toward 0 (false-equivalence risk): equivalence needs VIF < 5 and power"},
            "note": "a nonlinear scale cannot be told from residual confounding with this data"}


# ------------------------------------------------------------------------------------------------ test (h): key-on reset
REST_BINS = (("<10min", 0.0, 600.0), ("10-60min", 600.0, 3600.0), ("1-6h", 3600.0, 21600.0), (">6h", 21600.0, 1e12))


def keyon_test(dm, side, extras, n_boot=None):
    """Adjacency is taken in the FULL master ordering (every drive, any flag): a pair (i, j) is kept only when j directly follows i in time, both are canonical-clean (ens_outlier_v2 explicitly False)
    and i has a net charge, so a key-on jump is never paired with a drive that was not the previous key-off (no bridging across excluded or no-pair drives)."""
    d = dm.copy()
    d["elig"] = d["ens_outlier_v2"].map(lambda v: str(v).strip().lower()) == "false"
    d["start"] = pd.to_datetime(d["date"].astype(str) + " " + d["time_start"].astype(str), errors="coerce")
    d = d.dropna(subset=["start", "duration_s"]).sort_values("start").reset_index(drop=True)
    d["end"] = d["start"] + pd.to_timedelta(d["duration_s"], unit="s")
    sidx = side.set_index("file")
    d["q_net"] = d["file"].map(lambda f: -(sidx.loc[f, "ah_net"]) if f in sidx.index and pd.notna(sidx.loc[f, "ah_net"]) else np.nan)     # charge-positive net Ah of the previous drive
    d["last_i"] = d["file"].map(lambda f: (extras.get(f) or {}).get("last_i60"))
    rows = []
    for a, b in zip(range(len(d) - 1), range(1, len(d))):
        if not (d.loc[a, "elig"] and d.loc[b, "elig"]) or pd.isna(d.loc[a, "soc_end"]) or pd.isna(d.loc[b, "soc_start"]):
            continue
        rest = (d.loc[b, "start"] - d.loc[a, "end"]).total_seconds()
        if rest < 30.0 or not np.isfinite(d.loc[a, "q_net"]):
            continue
        rows.append({"file": d.loc[b, "file"], "day": str(d.loc[b, "date"]), "rest_s": rest, "jump": float(d.loc[b, "soc_start"] - d.loc[a, "soc_end"]), "q_net": float(d.loc[a, "q_net"]),
                     "last_i": d.loc[a, "last_i"]})
    r = pd.DataFrame(rows)
    if len(r) < 20:
        return {"evaluable": False, "reason": "fewer than 20 key-off intervals with a net charge"}
    days = sorted(r["day"].unique())
    dix = {x: i for i, x in enumerate(days)}
    r["day_ix"] = r["day"].map(dix)
    W = CB.boot_weights(len(days), n_boot)

    def slope(sub):
        if len(sub) < 15 or sub["q_net"].std() == 0:
            return None
        di = sub["day_ix"].to_numpy(int)
        X = np.column_stack([np.ones(len(sub)), sub["q_net"].to_numpy()])
        f1 = CB.grouped_fit(di, X, sub["jump"].to_numpy(), len(days), W, lambda b: b[1])
        f0 = CB.grouped_fit(di, X, sub["jump"].to_numpy(), len(days), W, lambda b: b[0])
        return {"n": int(len(sub)), "nDays": int(sub["day_ix"].nunique()), "slopeSoCPointsPerAh": f1, "interceptSoCPoints": f0, "medianJumpSoCPoints": float(sub["jump"].median())}
    out = {"evaluable": True, "nIntervals": int(len(r)), "all": slope(r),
           "byRestTime": {n: slope(r[(r["rest_s"] >= lo) & (r["rest_s"] < hi)]) for n, lo, hi in REST_BINS},
           "byLastCurrentDirection": {"lastCurrentCharging": slope(r[r["last_i"] > 0.5]), "lastCurrentDischarging": slope(r[r["last_i"] < -0.5])},
           "dtCapNote": "the net charge of the previous drive is integrated with the pre-specified 5 s dt cap; the slope is sensitive to that cap (blind audit: analyses/M404_audit/), so it is reported as descriptive only",
           "adjacency": "pairs are taken in the full master ordering (no bridging across excluded or no-pair drives)",
           "note": "consistency check tied to cell voltage rather than to the same current sensor; its slope is (unknown reset weight) x (scale mismatch), not 'Ah per point'; confounded by relaxation and hysteresis (hence the strata); not an estimate of the scale"}
    return out


# ------------------------------------------------------------------------------------------------ zero-current check
def zero_current(base, dix, n_days, W):
    per, day = [], []
    for (f, r), d in zip(base, dix):
        lead = (r.get("drive") or {}).get("lead")
        if lead and len(lead) >= 3:
            per.append(float(np.median(lead)))
            day.append(d)
    if len(per) < 10:
        return {"evaluable": False, "nDrivesWithSamples": len(per), "outcome": "no samples" if not per else "too few drives with samples",
                "note": "operational proxy for pre-Ready samples (|I| < 5 A, speed < 1 km/h, engine < 400 rpm, first 120 s); not a verified identification of the Ready state"}
    f = CB.grouped_fit(np.array(day, int), np.ones((len(per), 1)), np.array(per), n_days, W, lambda b: b[0])
    nonzero = bool(f and (f["ci95"][0] > 0 or f["ci95"][1] < 0))
    return {"evaluable": True, "nDrivesWithSamples": len(per), "meanOfDriveMediansA": f, "descriptive": True,
            "interpretation": ("the mean differs from zero: the leading stationary samples carry load (auxiliary or Ready-mode draw) and are NOT a sensor-zero reference" if nonzero
                               else "consistent with zero within the interval; a consistency check only, not a calibration"),
            "note": "sensor-zero consistency check, not used in fitting; operational proxy for pre-Ready samples, not a verified identification of the Ready state"}
