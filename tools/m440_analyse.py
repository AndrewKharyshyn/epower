#!/usr/bin/env python3
"""M440 analysis layer (spec analyses/M440_spec.md Rev 2): variants over the per-step table of tools/m440_regen_sens.py, paired deltas against the legacy reproduction with a day-clustered bootstrap
(calendar day, B = 4000, seed 42, one set of resamples per cohort shared by all variants and views; numerator and denominator resampled together). Decision labels per bin (declared before any result):
'material' = |Delta| above the half-width of the bin's published mass-uncertainty range AND the 95 % interval excludes zero; 'notComparable' = the variant retains less than 90 % of the bin's KE or days;
otherwise 'notMaterial'. Identity checked for the exclusion variants: Delta = w (eff_retained - eff_removed), w = removed KE share. Bins with fewer than 5 contributing days are 'notEvaluable' (point
values only); a draw with zero KE in a bin is unidentified and more than 2.5 % unidentified draws make the interval 'not available'."""
import numpy as np
import pandas as pd
import m440_regen_sens as X

AGES = X.AGES
B_DRAWS, SEED = X.B_DRAWS, X.SEED
MIN_DAYS = 5
UNID_MAX = 0.025
AFFECTS = {"V1_rpmKnown": ("temp", "speed"), "V2_age2": ("temp", "speed"), "V2_age5": ("temp", "speed"), "V2_age10": ("temp", "speed"), "V3_contiguous": ("temp", "speed"),
           "V4_startSpeedBin": ("speed",), "V5_fullProbe": ("temp",), "V6_offset": ("temp", "speed"), "VCa_combined": ("temp", "speed"), "VCb_combinedOffset": ("temp", "speed")}
EXCLUSION = {"V1_rpmKnown", "V2_age2", "V2_age5", "V2_age10", "V3_contiguous", "V5_fullProbe", "VCa_combined"}


def variant_defs():
    """name -> (keep-mask function, speed key, cap key). V5 acts on the temperature view only and V4 on the speed view only (AFFECTS)."""
    d = {"V1_rpmKnown": (lambda S: ~S["rpmNan"].values, "spEnd", "cap"),
         "V3_contiguous": (lambda S: S["gap"].values == 1, "spEnd", "cap"),
         "V4_startSpeedBin": (lambda S: np.ones(len(S), bool), "spStart", "cap"),
         "V5_fullProbe": (lambda S: S["nprobe"].values == 4, "spEnd", "cap"),
         "V6_offset": (lambda S: np.ones(len(S), bool), "spEnd", "capOff")}
    for k in AGES:
        d["V2_age%d" % k] = ((lambda kk: (lambda S: S["ageMax"].values <= kk))(k), "spEnd", "cap")
    comb = lambda S: (~S["rpmNan"].values) & (S["ageMax"].values <= 5) & (S["gap"].values == 1)
    d["VCa_combined"] = (comb, "spStart", "cap")              # the temperature view additionally needs the full-probe rule; the speed view bins by the start speed
    d["VCb_combinedOffset"] = (comb, "spStart", "capOff")
    return d


def pct(x, lo=2.5, hi=97.5):
    x = np.asarray(x, float)
    return [round(float(np.percentile(x, lo)), 2), round(float(np.percentile(x, hi)), 2)] if x.size else None


def per_day(day_idx, key_idx, nbins, cap, ke, mask, ndays):
    ok = mask & (key_idx >= 0) & (key_idx < nbins)
    C_ = np.zeros((ndays, nbins)); K_ = np.zeros((ndays, nbins)); N_ = np.zeros((ndays, nbins))
    np.add.at(C_, (day_idx[ok], key_idx[ok]), cap[ok]); np.add.at(K_, (day_idx[ok], key_idx[ok]), ke[ok]); np.add.at(N_, (day_idx[ok], key_idx[ok]), 1.0)
    return C_, K_, N_


def mid_index_arr(sp, mid_index):
    m = X.mid_bin(sp)
    return np.array([mid_index.get(int(x), -1) for x in m])


def ratio(c, k):
    return np.where(k > 0, 100.0 * c / np.where(k > 0, k, 1.0), np.nan)


def rd(x, d):
    return None if x is None or not np.isfinite(x) else round(float(x), d)


def ci_or_none(draws):
    """95 % percentile interval over the identified draws; None ('not available') if more than 2.5 % of the draws are unidentified."""
    fin = np.isfinite(draws)
    if fin.mean() < 1.0 - UNID_MAX or fin.sum() == 0:
        return None
    return pct(draws[fin])


def analyse(steps, A, label, temp_bins):
    nT = len(temp_bins)
    pub_mids = [int(r[0]) for r in A["regenCaptureMeasured"]]
    mid_index = {m: i for i, m in enumerate(pub_mids)}
    hw_t = {r["label"]: ((r["effRangeMassUncertainty"][1] - r["effRangeMassUncertainty"][0]) / 2.0 if r.get("effRangeMassUncertainty") else None) for r in A["regenByTempMeasured"]}
    hw_s = {str(int(r[0])): (r[2] - r[1]) / 2.0 for r in A["regenCaptureMeasuredMassUncertainty"]}
    days = np.array(sorted(steps["day"].unique()))
    day_idx = np.searchsorted(days, steps["day"].values)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(days), (B_DRAWS, len(days)))
    counts = np.zeros((B_DRAWS, len(days)))
    for b in range(B_DRAWS):
        counts[b] = np.bincount(idx[b], minlength=len(days))
    cap0 = steps["cap"].values; ke0 = steps["ke"].values; full = np.ones(len(steps), bool)
    keys = {"temp": (steps["tbin"].values, nT), "speedEnd": (mid_index_arr(steps["spEnd"].values, mid_index), len(pub_mids)), "speedStart": (mid_index_arr(steps["spStart"].values, mid_index), len(pub_mids))}
    base = {kn: per_day(day_idx, key, nb, cap0, ke0, full, len(days)) for kn, (key, nb) in keys.items()}

    def view(mask, cap_key, kind, key_name, exclusion, identity, cmp_mask=None):
        key, nb = keys[key_name]
        cap = steps[cap_key].values
        C0, K0, N0 = base["temp" if kind == "temp" else "speedEnd"]
        Cv, Kv, Nv = per_day(day_idx, key, nb, cap, ke0, mask, len(days))
        c0t, k0t, n0t = C0.sum(0), K0.sum(0), N0.sum(0); cvt, kvt, nvt = Cv.sum(0), Kv.sum(0), Nv.sum(0)
        E0, Ev = ratio(c0t, k0t), ratio(cvt, kvt)
        d_b = ratio(counts @ Cv, counts @ Kv) - ratio(counts @ C0, counts @ K0)
        rem_k, rem_c = k0t - kvt, c0t - cvt
        Er = np.where(rem_k > 1e-12, 100.0 * rem_c / np.where(rem_k > 1e-12, rem_k, 1.0), np.nan)
        days0, daysv = (N0 > 0).sum(0), (Nv > 0).sum(0)
        if cmp_mask is not None:                                   # R2: comparability of VCa on the speed view is judged on its exclusion part (end-speed bins), not on the start-speed re-binning
            _, Kc, Nc = per_day(day_idx, keys["speedEnd"][0], keys["speedEnd"][1], cap, ke0, cmp_mask, len(days))
            kvt_cmp, daysv_cmp = Kc.sum(0), (Nc > 0).sum(0)
        else:
            kvt_cmp, daysv_cmp = kvt, daysv
        out = {}
        for j in range(nb):
            if n0t[j] == 0:
                continue
            name = temp_bins[j] if kind == "temp" else str(pub_mids[j])
            hw = hw_t.get(name) if kind == "temp" else hw_s.get(name)
            delta = Ev[j] - E0[j] if np.isfinite(E0[j]) and np.isfinite(Ev[j]) else float("nan")
            evaluable = bool(k0t[j] > 0 and days0[j] >= MIN_DAYS and daysv[j] >= MIN_DAYS)
            ci = ci_or_none(d_b[:, j]) if evaluable else None
            ke_sh = kvt[j] / k0t[j] if k0t[j] > 0 else float("nan"); day_sh = daysv[j] / days0[j] if days0[j] else float("nan")
            ke_cmp = kvt_cmp[j] / k0t[j] if k0t[j] > 0 else float("nan"); day_cmp = daysv_cmp[j] / days0[j] if days0[j] else float("nan")
            if not evaluable or ci is None:
                dec = "notEvaluable"                                            # R1: no legacy KE, fewer than 5 days under the legacy or the variant, or the interval is not available
            elif exclusion and not (ke_cmp >= 0.9 and day_cmp >= 0.9):
                dec = "notComparable"                                           # R2: only exclusion variants can be non-comparable (V4 and V6 are exempt)
            elif hw is not None and ci is not None and np.isfinite(delta) and abs(delta) > hw and (ci[0] > 0 or ci[1] < 0):
                dec = "material"
            else:
                dec = "notMaterial"
            row = {"n0": int(n0t[j]), "n": int(nvt[j]), "days0": int(days0[j]), "days": int(daysv[j]), "eff0": rd(E0[j], 2), "eff": rd(Ev[j], 2), "delta": rd(delta, 3), "deltaCi95": ci,
                   "massHalfWidth": rd(hw, 2) if hw is not None else None, "retainedStepShare": rd(nvt[j] / n0t[j], 4), "retainedKeShare": rd(ke_sh, 4), "retainedDayShare": rd(day_sh, 4),
                   "effRemoved": rd(Er[j], 2) if exclusion else None, "validLegacy": bool(n0t[j] >= 200), "validVariant": bool(nvt[j] >= 200), "decision": dec,
                   "unidentifiedDrawShare": rd(1.0 - float(np.isfinite(d_b[:, j]).mean()), 4)}
            if identity and np.isfinite(delta) and np.isfinite(Er[j]):
                w = rem_k[j] / k0t[j]
                row["identityResidual"] = float("%.3g" % abs(delta - w * (Ev[j] - Er[j])))
            if cap_key == "capOff" and k0t[j] > 0:
                row["offsetShiftPp"] = rd(100.0 * (cvt[j] - c0t[j]) / k0t[j], 3)           # sum(capOff - cap) / sum ke
            out[name] = row
        return out

    res = {"cohort": label, "nSteps": int(len(steps)), "nDrives": int(steps["file"].nunique()), "nDays": int(len(days)), "variants": {}}
    kes = steps["ke"].sum()
    cad = steps["cadence"].values if "cadence" in steps else np.array(["unknown"] * len(steps))
    for name, (fn_, sp_key, cap_key) in variant_defs().items():
        mask = fn_(steps)
        v = {}
        for kind in AFFECTS[name]:
            m = mask & (steps["nprobe"].values == 4) if (name.startswith("VC") and kind == "temp") else mask
            ident = name in EXCLUSION and (kind == "temp" or not name.startswith("VC"))      # R3: V1, V2(k), V3, V5 and the temperature view of VCa; VCa speed bins by the start speed
            cmp_m = mask if (name.startswith("VC") and kind == "speed") else None
            v[kind] = view(m, cap_key, kind, "temp" if kind == "temp" else ("speedStart" if sp_key == "spStart" else "speedEnd"), name in EXCLUSION, ident, cmp_m)
        v["retained"] = {"steps": rd(mask.mean(), 4), "ke": rd(steps["ke"].values[mask].sum() / kes, 4), "drives": int(steps.loc[mask, "file"].nunique()), "days": int(steps.loc[mask, "day"].nunique()),
                         "byCadence": {c: {"steps": rd(mask[cad == c].mean(), 4), "ke": rd(steps["ke"].values[mask & (cad == c)].sum() / max(steps["ke"].values[cad == c].sum(), 1e-12), 4)} for c in sorted(set(cad))}}
        if name == "V4_startSpeedBin":
            eb, sb = keys["speedEnd"][0], keys["speedStart"][0]
            both = (eb >= 0) & (sb >= 0)
            v["binMigration"] = {"stepShare": rd((eb != sb).mean(), 4), "keMovedUpShare": rd(ke0[(sb > eb) & both].sum() / ke0.sum(), 4), "keMovedDownShare": rd(ke0[(sb < eb) & both].sum() / ke0.sum(), 4)}
        # R5: a defect is 'material' if it is material in at least one VALID legacy bin (temperature n >= 200; speed bins as published); invalid bins and the other cohorts are descriptive
        mat = []
        for kind in ("temp", "speed"):
            for b, row in (v.get(kind) or {}).items():
                if row["decision"] == "material" and (kind == "speed" or row["validLegacy"]):
                    mat.append("%s:%s" % (kind, b))
        v["materialBins"] = mat
        v["materialDefect"] = bool(mat)
        res["variants"][name] = v
    a = steps["ageMax"].values
    res["ageMaxShare"] = {"le2s": rd((a <= 2).mean(), 4), "le5s": rd((a <= 5).mean(), 4), "le10s": rd((a <= 10).mean(), 4), "gt10s": rd(((a > 10) & np.isfinite(a)).mean(), 4), "unbounded": rd(np.isinf(a).mean(), 4)}
    # age-stratified legacy ratios and the cadence split (Director ruling: written by the tool, not typed)
    bands = [("le1s", -1.0, 1.0), ("gt1_le2s", 1.0, 2.0), ("gt2_le3s", 2.0, 3.0), ("gt3_le5s", 3.0, 5.0), ("gt5_le10s", 5.0, 10.0), ("gt10s", 10.0, np.inf)]
    ke_all = steps["ke"].sum(); strata = {}
    for nm, lo, hi in bands:
        m = (a > lo) & (a <= hi) & np.isfinite(a) if np.isfinite(hi) else (a > lo) & np.isfinite(a)
        strata[nm] = {"steps": int(m.sum()), "keShare": rd(steps["ke"].values[m].sum() / ke_all, 4), "ratio": rd(100.0 * steps["cap"].values[m].sum() / max(steps["ke"].values[m].sum(), 1e-12), 2) if m.any() else None,
                      "slowCadenceShare": rd((cad[m] == "slow").mean(), 4) if m.any() else None}
    res["ageStrata"] = strata
    res["legacyByCadence"] = {c: {"steps": int((cad == c).sum()), "keShare": rd(steps["ke"].values[cad == c].sum() / ke_all, 4), "ratio": rd(100.0 * steps["cap"].values[cad == c].sum() / max(steps["ke"].values[cad == c].sum(), 1e-12), 2)} for c in sorted(set(cad))}
    res["flagShare"] = {"rpmMissing": rd(steps["rpmNan"].mean(), 4), "nonContiguous": rd((steps["gap"] != 1).mean(), 4), "partialProbe": rd((steps["nprobe"] < 4).mean(), 4),
                        "startBinDiffers": rd((keys["speedStart"][0] != keys["speedEnd"][0]).mean(), 4)}
    return res
