#!/usr/bin/env python3
"""M444 (spec analyses/M444_spec.md Rev 2): SOC-standardized apparent KE recovery by pack temperature and speed, braking-demand check (episode deceleration ladder), chronological holdouts, week-block sensitivity and sensitivities. Payload only.
Everything is computed from the per-drive cache through tools/regen_v2_agg.Cohort (same eligibility, assumed masses, ratio of sums and day-clustered bootstrap as the observed layer M441).
R_std[g] = sum over s in S* of w~[s] R[g,s]; R[g,s] = 100 sum(charge) / sum(KE) of the joint cell (group g x SOC band s); w = the KE weights of ONE reference population (cohort all, valid temperature and SOC), renormalised ONCE over the common-support bands S*."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2 as R
import regen_v2_agg as G

COVERAGE_MIN, COVERAGE_ALT, N_BLOCKS, MIN_WEEKS = 0.80, (0.70, 0.90), 4, 5
SPEED_CLASSES = [(10.0, 40.0, "10-40"), (40.0, 70.0, "40-70"), (70.0, 1e9, ">=70")]
BANDS = list(G.SOC_SELS[2:-1])                                       # the eight bands and below40
MERGED = {"40-55": ["band 40-50", "band 50-55"], "55-66": ["band 55-60", "band 60-63", "band 63-66"], "66-100": ["band 66-69", "band 69-72", "band 72-100"]}


# ------------------------------------------------------------------------------------------------ joint sums, reference, common support
def joint(co, view, strata):
    """For each stratum key -> boolean row mask: the per-day sums of the Cohort for the groups of the view. Returns (labels, {key: dict}); sup uses the M441 floors; present = day-by-group presence of data."""
    mats, labels = co.mats(view)
    out = {}
    for key, mask in strata.items():
        C_, Co_, K_, Ku_, Ns, Np, Zs, Sec, Pd = co.sums(mats, mask)
        n = Ns.sum(axis=0)
        drives = (Pd > 0).sum(axis=0)
        present = (Ns + Np) > 0
        sup = (n >= G.MIN_N) & (drives >= G.MIN_DRIVES) & (present.sum(axis=0) >= G.MIN_DAYS)
        out[key] = {"C": C_, "Co": Co_, "K": K_, "Ku": Ku_, "sup": sup, "n": n, "drives": drives, "present": present}
    return labels, out


def reference_weights(J, cols):
    """KE weights of a reference population over the strata (summed over the compared groups `cols`)."""
    ke = {k: float(v["K"][:, cols].sum()) for k, v in J.items()}
    tot = sum(ke.values())
    return {k: (x / tot if tot > 0 else 0.0) for k, x in ke.items()}, ke


def common_support(J, w, cand, thr=COVERAGE_MIN):
    """Spec section 3: S* = strata supported for EVERY group of the set; coverage = reference weight of S*; drop the group with the fewest supported strata (ties: lower total KE, then the LOWEST bin) until coverage >= thr or fewer than 2 groups remain."""
    T = list(cand)
    dropped = []
    keys = list(J)
    ke_g = {g: sum(float(J[k]["K"][:, g].sum()) for k in keys) for g in cand}
    while True:
        S = [k for k in keys if all(J[k]["sup"][g] for g in T)]
        cov = sum(w[k] for k in S)
        if len(T) >= 2 and cov >= thr and S:
            return {"available": True, "groups": T, "strata": S, "coverage": cov, "dropped": dropped}
        if len(T) <= 2:
            return {"available": False, "groups": T, "strata": S, "coverage": cov, "dropped": dropped,
                    "reason": "coverage %.3f of the reference KE with %d group(s) after dropping %s (minimum %.2f with at least 2 groups)" % (cov, len(T), dropped, thr)}
        g_drop = min(T, key=lambda g: (sum(bool(J[k]["sup"][g]) for k in keys), ke_g[g], g))
        dropped.append(g_drop)
        T.remove(g_drop)


# ------------------------------------------------------------------------------------------------ resampling
def week_index(days):
    wk = []
    for d in days:
        iso = pd.Timestamp(str(d)).isocalendar()
        wk.append((int(iso[0]), int(iso[1])))
    uw = sorted(set(wk))
    return np.array([uw.index(w) for w in wk]), len(uw)


def week_counts(co, days, B=G.B_DRAWS, seed=G.SEED):
    """ISO-week cluster resampling: weeks drawn with replacement, expanded to a (B x D) matrix of day counts."""
    widx, W = week_index(days)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, W, (B, W))
    cw = np.zeros((B, W))
    for b in range(B):
        cw[b] = np.bincount(idx[b], minlength=W)
    return cw[:, widx], W


def weeks_ok(J, S, g, widx):
    """B8: every cell of S* has data in at least MIN_WEEKS distinct ISO weeks."""
    return all(len(set(widx[J[k]["present"][:, g]])) >= MIN_WEEKS for k in S)


def standardize(J, w, cs, counts, offset=False):
    """Standardized bars for the groups cs['groups'] with fixed weights renormalised once over cs['strata']. counts = (B x D) resample matrix. Returns ({group: dict(point, lo, hi, draws)}, weights over S*)."""
    S = cs["strata"]
    wt = np.array([w[k] for k in S])
    wt = wt / wt.sum()
    out = {}
    for g in cs["groups"]:
        cell_pt, lo_pt, hi_pt, dr = [], [], [], []
        for k in S:
            c = J[k]["Co"][:, g] if offset else J[k]["C"][:, g]
            ke, ku = J[k]["K"][:, g], J[k]["Ku"][:, g]
            kt, kut, ct = float(ke.sum()), float(ku.sum()), float(c.sum())
            cell_pt.append(100.0 * ct / kt)
            kh = kt - kut
            hi_pt.append(100.0 * ct / (kh + kut * G.MASS_LO / 1890.0))
            lo_pt.append(100.0 * ct / (kh + kut * G.MASS_HI / 1890.0))
            num, den = counts @ c, counts @ ke
            with np.errstate(invalid="ignore", divide="ignore"):
                dr.append(np.where(den > 0, 100.0 * num / np.where(den > 0, den, 1.0), np.nan))
        out[g] = {"point": float(np.dot(wt, cell_pt)), "lo": float(np.dot(wt, lo_pt)), "hi": float(np.dot(wt, hi_pt)), "draws": np.sum(wt[:, None] * np.vstack(dr), axis=0)}      # NaN if any cell of S* is unidentified in the draw
    return out, wt


def observed_on_s(J, cs, g, offset=False):
    """B4: the observed value of group g on the common-support bands only (charge and KE of S* pooled)."""
    c = sum(float((J[k]["Co"] if offset else J[k]["C"])[:, g].sum()) for k in cs["strata"])
    ke = sum(float(J[k]["K"][:, g].sum()) for k in cs["strata"])
    return None if ke <= 0 else 100.0 * c / ke


def interval(draws):
    fin = np.isfinite(draws)
    failed = 1.0 - float(fin.mean())
    if failed > G.UNID_MAX or not fin.sum():
        return None, failed
    return [round(float(np.percentile(draws[fin], 2.5)), 2), round(float(np.percentile(draws[fin], 97.5)), 2)], failed


def soc_strata(co, extra=None):
    return {k: (co.sel[k] if extra is None else (co.sel[k] & extra)) for k in BANDS}


# ------------------------------------------------------------------------------------------------ one view
def view_result(co, view, w, counts_w, widx, fast_rows=None, offset=False):
    """Availability, observed / observed-on-S* / standardized bars (day and week-block intervals), mass ranges, fast-polled KE share and adjacent differences of one view."""
    labels, J = joint(co, view, soc_strata(co))
    cb = co.cell_block(view, co.sel["allSoc"])
    cols = [g for g in range(len(labels)) if (view == "temperature" or 1 <= g <= 12)]               # speed view: no 0-10 km/h and no >= 130 km/h (B5)
    cand = [g for g in cols if cb.get(labels[g], {}).get("status") == "supported"]
    cs = common_support(J, w, cand)
    out = {"availability": {"available": cs["available"], "coverage": round(cs["coverage"], 4), "droppedGroups": [labels[g] for g in cs["dropped"]],
                            "alternativeThresholds": {str(t): common_support(J, w, cand, t)["available"] for t in COVERAGE_ALT}},
           "reason": cs.get("reason"), "commonSupportBands": [str(k) for k in cs["strata"]], "excludedReferenceKeShare": round(1.0 - cs["coverage"], 4),
           "observedAllSoc": {labels[g]: {k: cb[labels[g]].get(k) for k in ("n", "drives", "days", "eff", "ci95", "status")} for g in cols if cb.get(labels[g], {}).get("n")}, "bars": {}, "adjacentDifferences": []}
    if not cs["available"]:
        return out, (labels, J, cs)
    std, wt = standardize(J, w, cs, co.counts, offset)
    std_w, _ = standardize(J, w, cs, counts_w, offset)
    if fast_rows is not None:
        _, Jf = joint(co, view, {k: soc_strata(co)[k] & fast_rows for k in BANDS})
    for g in cs["groups"]:
        ci, failed = interval(std[g]["draws"])
        wk_ok = weeks_ok(J, cs["strata"], g, widx)
        ciw, failed_w = interval(std_w[g]["draws"]) if wk_ok else (None, None)
        ke_s = sum(float(J[k]["K"][:, g].sum()) for k in cs["strata"])
        obs_s = observed_on_s(J, cs, g, offset)
        out["bars"][labels[g]] = {"standardized": round(std[g]["point"], 2), "ci95Days": ci, "failedDrawShare": round(failed, 4), "ci95Weeks": ciw, "failedDrawShareWeeks": None if failed_w is None else round(failed_w, 4),
                                  "weekSupport": bool(wk_ok), "massRange": [round(std[g]["lo"], 2), round(std[g]["hi"], 2)], "observedAllSoc": cb[labels[g]].get("eff"), "observedOnCommonBands": None if obs_s is None else round(obs_s, 2),
                                  "fastPolledKeShare": None if fast_rows is None or ke_s <= 0 else round(sum(float(Jf[k]["K"][:, g].sum()) for k in cs["strata"]) / ke_s, 4), "status": "failed" if ci is None else "supported"}
    gs = cs["groups"]
    for a, b in zip(gs[:-1], gs[1:]):
        dd = std[b]["draws"] - std[a]["draws"]                                                 # NaN where either bar's draw failed (B9)
        ci, failed = interval(dd)
        wk_pair = weeks_ok(J, cs["strata"], a, widx) and weeks_ok(J, cs["strata"], b, widx)       # S3: unavailable if either bar's week interval is
        ciw = interval(std_w[b]["draws"] - std_w[a]["draws"])[0] if wk_pair else None
        oa, ob = cb.get(labels[a], {}).get("eff"), cb.get(labels[b], {}).get("eff")
        out["adjacentDifferences"].append({"a": labels[a], "b": labels[b], "standardizedDiffPp": round(std[b]["point"] - std[a]["point"], 2), "ci95Days": ci, "ci95Weeks": ciw, "failedDrawShare": round(failed, 4),
                                           "observedDiffPp": None if oa is None or ob is None else round(ob - oa, 2), "gapBetween": bool(b - a > 1)})
    return out, (labels, J, cs)


def ci_signs(std, labels, groups):
    """Sign of each adjacent difference of the standardized bars: +1 / -1 if its day-clustered interval excludes 0, 'indeterminate' otherwise (spec S5)."""
    out = {}
    for a, b in zip(groups[:-1], groups[1:]):
        ci, _ = interval(std[b]["draws"] - std[a]["draws"])
        pt = std[b]["point"] - std[a]["point"]
        out["%s>%s" % (labels[a], labels[b])] = "indeterminate" if (ci is None or (ci[0] <= 0 <= ci[1])) else int(np.sign(pt))
    return out


def order_signs(bars, labels_order):
    """Sign of each adjacent difference of the standardized bars (+1 / -1 / 0), keyed 'a>b'."""
    out = {}
    for a, b in zip(labels_order[:-1], labels_order[1:]):
        if a in bars and b in bars:
            out["%s>%s" % (a, b)] = int(np.sign(bars[b]["standardized"] - bars[a]["standardized"]))
    return out


# ------------------------------------------------------------------------------------------------ braking demand (episode deceleration)
def episode_decel(co):
    """Mean deceleration (m/s^2) of the EPISODE of every kept interval: (v_start - v_end) / 3.6 / duration over the kept intervals of the episode (key = drive, episode)."""
    d = co.d
    idx = np.where(co.est)[0]
    key = co.drive.astype(np.int64) * 10_000_000 + d["iv_episode"].astype(np.int64)
    df = pd.DataFrame({"key": key[idx], "v0": d["iv_v0"][idx], "v1": d["iv_v1"][idx], "dt": d["iv_dt"][idx]})
    ag = df.groupby("key", sort=False).agg(v_start=("v0", "first"), v_end=("v1", "last"), dur=("dt", "sum"))
    a_ep = (ag["v_start"] - ag["v_end"]) / 3.6 / ag["dur"].clip(lower=1e-9)
    a = np.full(len(co.drive), np.nan)
    a[idx] = df["key"].map(a_ep).values
    return a


def demand_cuts(co):
    """KE-weighted terciles of the episode deceleration over the reference population (strict-drop intervals, start speed >= 10 km/h)."""
    a = episode_decel(co)
    ke = R.KE_FACTOR * co.mass * co.d["iv_dv2"]
    ref = co.strict & (co.d["iv_v0"] >= 10.0) & (ke > 0) & np.isfinite(a)
    o = np.argsort(a[ref])
    cw = np.cumsum(ke[ref][o]) / ke[ref].sum()
    return [float(a[ref][o][np.searchsorted(cw, q)]) for q in (1.0 / 3.0, 2.0 / 3.0)]


def demand_masks(co, cuts):
    a = episode_decel(co)
    sm = {c[2]: (co.d["iv_v0"] >= c[0]) & (co.d["iv_v0"] < c[1]) for c in SPEED_CLASSES}
    dmk = {"low": a < cuts[0], "mid": (a >= cuts[0]) & (a < cuts[1]), "high": a >= cuts[1]}
    return sm, dmk


def ladder_strata(co, level, sm, dmk, base):
    sel = co.sel
    if level == 1:
        return {(b, sc, dc): sel[b] & sm[sc] & dmk[dc] & base for b in BANDS for sc in sm for dc in dmk}
    if level == 2:
        return {(b, sc): sel[b] & sm[sc] & base for b in BANDS for sc in sm}
    return {(m, sc, dc): np.logical_or.reduce([sel[b] for b in bs]) & sm[sc] & dmk[dc] & base for m, bs in MERGED.items() for sc in sm for dc in dmk}


def demand_reference(co, cuts):
    """Reference weights of the SOC-only and of the three ladder levels on the base population (start speed >= 10 km/h) of cohort `co` (cohort all)."""
    sm, dmk = demand_masks(co, cuts)
    base = co.d["iv_v0"] >= 10.0
    n_t = len(co.mats("temperature")[1])
    out = {"socOnly": reference_weights(joint(co, "temperature", soc_strata(co, base))[1], list(range(n_t)))[0]}
    for lv in (1, 2, 3):
        out["L%d" % lv] = reference_weights(joint(co, "temperature", ladder_strata(co, lv, sm, dmk, base))[1], list(range(n_t)))[0]
    return out


def demand_block(co, cuts, wref):
    """Spec section 5: overlap table, SOC-only standardization and the first available ladder level on the same population (start speed >= 10 km/h); sign comparison on the common groups."""
    sm, dmk = demand_masks(co, cuts)
    base = co.d["iv_v0"] >= 10.0
    out = {"decelerationCutsMps2": [round(c, 4) for c in cuts], "speedClasses": [c[2] for c in SPEED_CLASSES], "population": "start speed >= 10 km/h"}
    labels, J0 = joint(co, "temperature", soc_strata(co, base))
    cb = co.cell_block("temperature", co.sel["allSoc"] & base)
    cand = [g for g, l in enumerate(labels) if cb.get(l, {}).get("status") == "supported"]
    _, Jo = joint(co, "temperature", {"%s|%s" % (sc, dc): sm[sc] & dmk[dc] & base for sc in sm for dc in dmk})
    tot = {g: sum(float(Jo[k]["K"][:, g].sum()) for k in Jo) for g in range(len(labels))}
    out["overlapKeShare"] = {labels[g]: {k: round(float(Jo[k]["K"][:, g].sum()) / tot[g], 4) for k in Jo} for g in range(len(labels)) if tot[g] > 0}
    out["overlapSupported"] = {labels[g]: {k: bool(Jo[k]["sup"][g]) for k in Jo} for g in range(len(labels)) if tot[g] > 0}

    def bars(std, cs):
        return {labels[g]: {"standardized": round(std[g]["point"], 2), "ci95Days": interval(std[g]["draws"])[0]} for g in cs["groups"]}

    cs0 = common_support(J0, wref["socOnly"], cand)
    std0 = standardize(J0, wref["socOnly"], cs0, co.counts)[0] if cs0["available"] else {}
    out["socOnly"] = {"available": cs0["available"], "coverage": round(cs0["coverage"], 4), "reason": cs0.get("reason"), "bars": bars(std0, cs0) if cs0["available"] else {}}
    out["ladder"] = []
    used = None
    for lv in (1, 2, 3):
        st = ladder_strata(co, lv, sm, dmk, base)
        _, Jl = joint(co, "temperature", st)
        cs = common_support(Jl, wref["L%d" % lv], cand)
        row = {"level": lv, "nStrata": len(st), "available": cs["available"], "coverage": round(cs["coverage"], 4), "reason": cs.get("reason")}
        if cs["available"] and used is None:
            std = standardize(Jl, wref["L%d" % lv], cs, co.counts)[0]
            row["bars"] = bars(std, cs)
            used = (lv, cs, std)
        out["ladder"].append(row)
    if used is None:
        out["result"] = "not checked for braking demand"
        out["orderCheck"] = {"available": False}
    else:
        lv, cs, std = used
        out["result"] = "checked at ladder level %d%s" % (lv, "" if lv == 1 else " (partial)")
        if cs0["available"]:
            common = [g for g in cs["groups"] if g in cs0["groups"]]
            s1 = ci_signs(std0, labels, common)
            s2 = ci_signs(std, labels, common)
            both = [p for p in s1 if s1[p] != "indeterminate" and s2[p] != "indeterminate"]
            out["orderCheck"] = {"available": True, "level": lv, "groups": [labels[g] for g in common], "signsSocOnly": s1, "signsDemandLevel": s2, "nPairsBothDeterminate": len(both),
                                 "nSameSign": int(sum(s1[p] == s2[p] for p in both)), "sameOrderWhereDeterminate": bool(all(s1[p] == s2[p] for p in both)), "nIndeterminate": int(len(s1) - len(both))}
        else:
            out["orderCheck"] = {"available": False, "reason": "SOC-only standardization unavailable on this population"}
    return out


# ------------------------------------------------------------------------------------------------ holdouts
def holdout_block(mk, full_view, w, days_all):
    """Spec section 6: four chronological blocks (array_split of the sorted days); the FULL fixed weights; S*_k = the full-sample S* bands supported in block k for every comparable group supported there; reference signs from the full sample on the same S*_k."""
    labels, Jf, cs_full = full_view
    order = sorted(days_all)
    parts = np.array_split(np.arange(len(order)), N_BLOCKS)
    out = {"blocks": []}
    full_cohort = mk(order)
    for k, idx in enumerate(parts):
        held = [order[i] for i in idx]
        sidx = set(int(i) for i in idx)
        rest = [order[i] for i in range(len(order)) if i not in sidx]
        co_h = mk(held)
        _, Jh = joint(co_h, "temperature", soc_strata(co_h))
        cb = co_h.cell_block("temperature", co_h.sel["allSoc"])
        Tk = [g for g in cs_full["groups"] if cb.get(labels[g], {}).get("status") == "supported"]
        Jh_sub = {s_: Jh[s_] for s_ in cs_full["strata"]}                                      # S*_k lives inside the full-sample S*
        csk = common_support(Jh_sub, w, Tk) if len(Tk) >= 2 else {"available": False, "groups": Tk, "strata": [], "coverage": 0.0, "dropped": [], "reason": "fewer than 2 comparable groups supported in the block"}
        Gk, Sk, cov_k = csk["groups"], csk["strata"], csk["coverage"]
        row = {"block": k + 1, "firstDay": held[0], "lastDay": held[-1], "nDays": len(held), "groups": [labels[g] for g in Gk], "droppedGroups": [labels[g] for g in csk["dropped"]], "commonBands": [str(s_) for s_ in Sk], "coverage": round(cov_k, 4)}
        if csk["available"]:
            std, _ = standardize(Jh, w, csk, co_h.counts)
            std_full, _ = standardize(Jf, w, csk, full_cohort.counts)
            bars = {labels[g]: {"standardized": std[g]["point"]} for g in Gk}
            ref = {labels[g]: {"standardized": std_full[g]["point"]} for g in Gk}
            sg, sr = order_signs(bars, [labels[g] for g in Gk]), order_signs(ref, [labels[g] for g in Gk])
            row.update({"available": True, "bars": {l: round(v["standardized"], 2) for l, v in bars.items()}, "nAdjacentPairs": len(sg), "nSameSign": int(sum(sg[p] == sr[p] for p in sg)), "pairs": {p: bool(sg[p] == sr[p]) for p in sg}})
            co_r = mk(rest)                                                                    # sensitivity: leave-block-out weights
            wr, _ = reference_weights(joint(co_r, "temperature", soc_strata(co_r))[1], list(range(len(labels))))
            std_r, _ = standardize(Jh, wr, csk, co_h.counts)
            sgr = order_signs({labels[g]: {"standardized": std_r[g]["point"]} for g in Gk}, [labels[g] for g in Gk])
            row["leaveBlockOutWeightsSensitivity"] = {"nSameSignAsFixedWeights": int(sum(sgr[p] == sg[p] for p in sg)), "nPairs": len(sg)}
        else:
            row["available"] = False
        out["blocks"].append(row)
    out["summary"] = {"nAdjacentPairs": int(sum(b.get("nAdjacentPairs", 0) for b in out["blocks"])), "nSameSign": int(sum(b.get("nSameSign", 0) for b in out["blocks"])),
                      "note": "a STABILITY CHECK, not an out-of-sample validation (w and S* include the block): same sign in k of n supported adjacent pairs; no decision rests on it; chronological blocks are partly seasonal; a held-out difference is not physical ground truth"}
    return out


# ------------------------------------------------------------------------------------------------ runner
def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, list):
        return [strip(x) for x in o]
    return o


def load_inputs(workers=5):
    import regen_v2_cache as K
    dm, reg = G.load_master()
    files = list(dm["file"])
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    K.ensure(files, float(A["offsetUncertainty"]["pointEstimateA"]), variant="base", workers=workers)
    T, hdrs = K.load(files, "base")
    return dm, reg, files, T


def run(workers=5, study=True):
    """Returns (primary block, study block or None). The primary block is cheap and refreshed at every ingestion; the study block (demand ladder, holdouts, sensitivities) is computed on demand."""
    import m442_gate as MG
    dm, reg, files, T = load_inputs(workers)
    hold = G.protocol_hold()
    held_drive = (dm["date"].astype(str).str[:10] >= hold).values if hold else np.zeros(len(dm), bool)
    masks = {"all": np.ones(len(dm), bool), "warm": (reg.values == "warm"), "shoulder": (reg.values == "shoulder"), "cold": (reg.values == "cold")}

    def cohort(c, days=None, tbl=None, extra_mask=None):
        m = masks[c] if extra_mask is None else (masks[c] & extra_mask)
        return G.Cohort(T if tbl is None else tbl, dm, m, c, days=days, hold_from=hold)

    co_all = cohort("all")
    labels_t, Jt = joint(co_all, "temperature", soc_strata(co_all))
    w, ke_ref = reference_weights(Jt, list(range(len(labels_t))))
    primary = {"reference": {"cohort": "all", "population": "intervals with a valid pack temperature and a valid SOC", "weights": {k: round(v, 5) for k, v in w.items()}, "keKwh": {k: round(v, 4) for k, v in ke_ref.items()},
                             "note": "ONE reference for both views, every cohort and bar (owner decision (c)); recomputed from cohort all at each refresh; fixed within a payload and under the assumed-mass range"}, "cohorts": {}}
    views = {}
    for c in ("all", "warm", "shoulder", "cold"):
        if masks[c].sum() == 0:
            continue
        co = co_all if c == "all" else cohort(c)
        days = list(co.days)
        counts_w, nweeks = week_counts(co, days)
        widx, _ = week_index(days)
        fast_rows = (co.cad == "fast")
        blk = {"cohort": c, "design": {"days": len(days), "weeks": nweeks, "draws": G.B_DRAWS, "seed": G.SEED, "weightsHeldFixed": True, "minWeeksPerCell": MIN_WEEKS}}
        for view in ("temperature", "speed"):
            blk[view], views[(c, view)] = view_result(co, view, w, counts_w, widx, fast_rows)
        primary["cohorts"][c] = blk
    primary = strip(primary)
    if not study:
        return primary, None
    cuts = demand_cuts(co_all)
    wref = demand_reference(co_all, cuts)
    st = {"cohorts": {}, "demandReference": {"decelerationCutsMps2": [round(c, 4) for c in cuts], "weights": {k: {str(s): round(v, 5) for s, v in d.items()} for k, d in wref.items()}}}
    for c in primary["cohorts"]:
        co = co_all if c == "all" else cohort(c)
        st["cohorts"][c] = {"demand": demand_block(co, cuts, wref)}
    st["cohorts"]["all"]["holdout"] = holdout_block(lambda d_: cohort("all", days=d_), views[("all", "temperature")], w, list(co_all.days))
    sens = {}
    ev = dm["ev_rpm_dt_med_s"].values
    fast = (ev < 1.0) & ~held_drive                                                           # B2: protocol drives stay out of the cadence strata
    slow = np.isfinite(ev) & ~(ev < 1.0) & ~held_drive

    def table(co):
        days = list(co.days)
        counts_w, _ = week_counts(co, days)
        widx, _ = week_index(days)
        return {v: strip(view_result(co, v, w, counts_w, widx)[0]) for v in ("temperature", "speed")}

    sens["cadenceFastPolledDrives"] = table(cohort("all", extra_mask=fast))
    sens["cadenceSlowPolledDrives"] = table(cohort("all", extra_mask=slow))
    oos, _info = G.oos_info(files, MG.DELTA)
    sens["harmonizedInterp3WithOutOfSupportMask"] = table(cohort("all", tbl=MG.tables(files, MG.HARM, workers), extra_mask=~oos))
    co_s = cohort("all")
    co_s.est = co_s.est & ~co_s.d["iv_plateau"]
    co_s.strict = co_s.strict & co_s.est
    sens["strictDropOnly"] = table(co_s)
    co_t = cohort("all")
    co_t.est = np.ones(len(co_t.drive), bool)
    co_t.strict = ~co_t.d["iv_plateau"]
    sens["allInEpisodeIncludingTrimmedPlateaus"] = table(co_t)
    if "ens_outlier_v2" in dm:
        sens["ensCleanDrives"] = table(cohort("all", extra_mask=(~dm["ens_outlier_v2"].astype(bool)).values))
    days_a = list(co_all.days)
    cwa, _ = week_counts(co_all, days_a)
    wia, _ = week_index(days_a)
    sens["offsetCorrectedCharge"] = {v: strip(view_result(co_all, v, w, cwa, wia, offset=True)[0]) for v in ("temperature", "speed")}
    st["sensitivities"] = {"note": "full day-clustered tables with the FIXED primary weights and the same support rule, beside the pooled primary; ranges over declared conventions; no fast-versus-slow contrast is computed; never combined with the statistical interval", "cohortAll": sens}
    return primary, strip(st)


def spec_sha():
    import hashlib
    return hashlib.sha256(open("analyses/M444_spec.md", "rb").read()).hexdigest()


def frozen_ok():
    return ("M444 spec sha256 " + spec_sha()) in open("CHANGELOG.md", encoding="utf-8").read(80000)


if __name__ == "__main__":
    import time
    t0 = time.time()
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M444_result.json"
    lock = "analyses/M444_first.lock"
    smoke = "--smoke" in sys.argv                                           # code test: no freeze check, no lock, never a result
    if not smoke:
        if not frozen_ok():
            raise SystemExit("refusing to run: CHANGELOG.md does not carry 'M444 spec sha256 %s' (spec section 8, B5)" % spec_sha())
        if os.path.exists(lock):
            if "--rerun-deviation" not in sys.argv:
                raise SystemExit("the first run already exists (%s); a re-run needs --rerun-deviation <recorded reason>, keeps the first output and goes to the Director" % lock)
            out_path = "analyses/M444_result_rerun.json"
        else:
            with open(lock, "w", encoding="utf-8", newline=chr(10)) as f:
                f.write(json.dumps({"specSha256": spec_sha(), "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    prim, stu = run(study="--primary-only" not in sys.argv)
    res = {"_provenance": {"spec": "analyses/M444_spec.md", "specSha256": spec_sha(), "masterMd5": __import__("hashlib").md5(open("drive_master.csv", "rb").read()).hexdigest(),
                           "bootstrap": {"B": G.B_DRAWS, "seed": G.SEED}, "label": "SOC-standardized apparent KE recovery (assumed mass), standardized to the all-cohort reference SOC mix over the common-support bands; payload only"},
           "primary": prim, "study": stu}
    if out_path and not smoke:
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
        if out_path == "analyses/M444_result.json":
            import hashlib
            with open(lock, "w", encoding="utf-8", newline=chr(10)) as f:
                f.write(json.dumps({"specSha256": spec_sha(), "resultSha256": hashlib.sha256(open(out_path, "rb").read()).hexdigest()}))
    elif smoke:
        with open(sys.argv[sys.argv.index("--smoke") + 1], "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps({"seconds": round(time.time() - t0), "wrote": None if smoke else out_path}))
