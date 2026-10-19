#!/usr/bin/env python3
"""M446 (spec analyses/M446_spec.md Rev 1.1, sections 3-9 and 16): the cadence-stratified NATIVE v2 display layer of the apparent battery-side KE recovery (assumed masses), payload only.
Per cohort (all, warm, shoulder, cold) and polling stratum (fast-polled: master ev_rpm_dt_med_s < 1.0 s; slow-polled: otherwise defined) it writes the rows that the dashboard will bind to: observed cells of the temperature,
speed-during-braking and speed-zone views under every SOC selection (All SOC, eight bands, below 40 %), the SOC-standardized bars (All SOC only, M444 machinery with the ONE fixed all-cohort reference mix and the M444 common-support
rule applied WITHIN the stratum), the stratum-specific resolution bracket b_nat = max over f of |v2(native) - v2(decimated f)| (script-written, never borrowed), the plateau convention range, the sampling-interval description of every
cell (D3) and the narrative/extent fields. Everything is computed from the per-drive cache (regen_v2_cache) through regen_v2_agg.Cohort; no raw CSV is read here. No pooled bar is a primary figure (pooled cells are carried as
'cadence-mixed pooled, reference only'). Language: apparent KE recovery (assumed mass); never measured / corrected / effect of temperature / efficiency."""
import hashlib
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2 as R
import regen_v2_agg as G
import regen_v2_cache as K
import regen_std as RS
import m441_study as S41

SPEC = "analyses/M446_spec.md"
STRATA = ("fast", "slow")
SELS = ["allSoc"] + list(G.SOC_SELS[2:-1])                                  # All SOC, the eight bands, below40
VIEWS = ("temperature", "speed", "zones10")
ZONES10 = [("10-30", [1, 2]), ("30-60", [3, 4, 5]), ("60-90", [6, 7, 8]), ("90-120", [9, 10, 11]), (">120", [12, 13])]
PAYLOAD_ONLY_SPEED = ("0-10", ">=130")                                      # D4: kept in the payload, not drawn
DRIFT_S = 0.2                                                               # D3: within-stratum drift flag (s)
DEC_FACTORS = {"fast": (2, 3), "slow": (2,)}                                # D2
KEEP = ("n", "drives", "days", "keKwh", "eff", "ci95", "precisionHalfWidth", "massRange", "status", "flagAbove100")


# ------------------------------------------------------------------------------------------------ pure helpers (unit-tested)
def stratum_of(ev):
    """Polling stratum of one drive from the master statistic ev_rpm_dt_med_s: 'fast' (< 1.0 s), 'slow' (>= 1.0 s), None when undefined (M444 S15: belongs to neither stratum)."""
    if ev is None or not np.isfinite(ev):
        return None
    return "fast" if ev < 1.0 else "slow"


def stratum_masks(ev, held=None):
    ev = np.asarray(ev, float)
    fin = np.isfinite(ev)
    fast, slow = fin & (ev < 1.0), fin & ~(ev < 1.0)
    if held is not None:
        fast, slow = fast & ~held, slow & ~held
    return {"fast": fast, "slow": slow}


def wquantiles(x, w, qs=(0.25, 0.5, 0.75)):
    """Weighted quantiles (lower convention: the first value whose cumulative weight reaches q * total weight). None entries when the total weight is not positive."""
    x, w = np.asarray(x, float), np.asarray(w, float)
    ok = np.isfinite(x) & np.isfinite(w) & (w > 0)
    if not ok.any():
        return [None] * len(qs)
    x, w = x[ok], w[ok]
    o = np.argsort(x, kind="stable")
    x, cw = x[o], np.cumsum(w[o])
    return [float(x[min(int(np.searchsorted(cw, q * cw[-1], side="left")), len(x) - 1)]) for q in qs]


def b_nat(diffs):
    """Resolution bracket of one cell: diffs = {f: point difference (pp) native - decimated f or None}. Returns (b_nat = max |diff|, signed shift at the maximising f, that f); (None, None, None) when no difference is computable."""
    ok = {f: d for f, d in diffs.items() if d is not None and np.isfinite(d)}
    if not ok:
        return None, None, None
    f = max(ok, key=lambda k: (abs(ok[k]), -k))
    return round(abs(ok[f]), 3), round(float(ok[f]), 3), f


def drift_flag(cell_median, stratum_median, thr=DRIFT_S):
    return None if cell_median is None or stratum_median is None else bool(abs(cell_median - stratum_median) > thr)


def narrative(rows, order):
    """Extrema of the SUPPORTED cells only (D5); thin bins listed apart. No 'peak' wording: the extremum is a value of a displayed cell."""
    sup = [(l, rows[l]["eff"]) for l in order if l in rows and rows[l].get("status") == "supported" and rows[l].get("eff") is not None]
    thin = [l for l in order if l in rows and rows[l].get("status") == "thin"]
    out = {"nSupported": len(sup), "thin": thin}
    if sup:
        lo, hi = min(sup, key=lambda t: t[1]), max(sup, key=lambda t: t[1])
        out.update(effMin=lo[1], effMinLabel=lo[0], effMax=hi[1], effMaxLabel=hi[0])
    return out


def extent(rows, order):
    """[lo, hi] of the displayed values: estimate, day interval, assumed-mass range and the resolution bracket of every supported or thin cell."""
    v = []
    for l in order:
        c = rows.get(l)
        if not c or c.get("status") not in ("supported", "thin") or c.get("eff") is None:
            continue
        v.append(c["eff"])
        for k in ("ci95", "massRange"):
            if c.get(k):
                v += list(c[k])
        if c.get("bNat") is not None:
            v += [c["eff"] - c["bNat"], c["eff"] + c["bNat"]]
    return [round(min(v), 2), round(max(v), 2)] if v else None


# ------------------------------------------------------------------------------------------------ views and cells
def mats_of(co, view):
    """Contribution matrices of a view; 'zones10' = speed zones from the drawn 10 km/h bins (the 0-10 km/h bin is not a zone; the top zone keeps the overflow bin)."""
    if view == "zones10":
        m, _ = co.mats("speed")
        out = {}
        for k, a in m.items():
            out[k] = np.stack([((a[:, ix].sum(axis=1) > 0).astype(float) if k == "touch" else a[:, ix].sum(axis=1)) for _, ix in ZONES10], axis=1)
        return out, [z for z, _ in ZONES10]
    return co.mats(view)


def cell(c):
    return {k: c[k] for k in KEEP if k in c}


def points(co, view, sel):
    """Point ratios (percent) of a view under a SOC selection, from the ratio of sums over the day sums; nan where the KE is zero."""
    mats, labels = mats_of(co, view)
    if len(co.drive) == 0:
        return labels, np.full(len(labels), np.nan)
    C_, _, K_ = co.sums(mats, co.sel[sel])[:3]
    c, k = C_.sum(0), K_.sum(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return labels, np.where(k > 0, 100.0 * c / np.where(k > 0, k, 1.0), np.nan)


def convention_values(co, view, sel):
    """Plateau convention range of the cells of a view (section 5): the strict-drop-only and the kept-plus-trimmed point values."""
    e0, s0 = co.est, co.strict
    out = {}
    try:
        n = len(co.drive)
        for name, est, strict in (("strictOnly", e0 & ~co.d["iv_plateau"], None), ("keptPlusTrimmed", np.ones(n, bool), ~co.d["iv_plateau"])):
            co.est = est
            co.strict = (est & ~co.d["iv_plateau"]) if strict is None else strict
            mats, labels = mats_of(co, view)
            cb = co.cell_block(view, co.sel[sel], mats, labels)
            out[name] = {l: cb.get(l, {}).get("eff") for l in labels}
    finally:
        co.est, co.strict = e0, s0
    return out


def week_interval(co, view, sel, counts_w, widx):
    """Week-block interval (ISO week cluster) of the observed cells of a view under a SOC selection (cells with data in >= MIN_WEEKS ISO weeks only)."""
    mats, labels = mats_of(co, view)
    C_, _, K_, _, Ns, Np = co.sums(mats, co.sel[sel])[:6]
    with np.errstate(invalid="ignore", divide="ignore"):
        dr = np.where((counts_w @ K_) > 0, 100.0 * (counts_w @ C_) / np.where((counts_w @ K_) > 0, counts_w @ K_, 1.0), np.nan)
    pres = (Ns + Np) > 0
    out = {}
    for j, l in enumerate(labels):
        if len(set(widx[pres[:, j]])) >= RS.MIN_WEEKS:
            out[l] = RS.interval(dr[:, j])[0]
    return out


def sampling_block(co, view, sel, ivmed, disagree, strat_median):
    """D3 for the All-SOC cells of a view: KE-weighted median and IQR of the speed sampling interval (iv_dt) and of the per-drive median current/voltage sampling interval, the within-stratum drift flag and the number of drives
    whose RPM-based stratum disagrees with their I/V sampling interval."""
    mats, labels = mats_of(co, view)
    m = (co.sel[sel] & co.est).astype(float) * co.w
    ke = R.KE_FACTOR * co.mass[:, None] * mats["dv2"] * m[:, None]
    Pd = co.sums(mats, co.sel[sel])[8]
    dis = disagree[co.drives_u]
    out = {}
    for j, l in enumerate(labels):
        w = ke[:, j]
        qs = wquantiles(co.d["iv_dt"], w)
        qi = wquantiles(ivmed[co.drive], w)
        out[l] = {"speedDtS": None if qs[1] is None else [round(qs[0], 3), round(qs[1], 3), round(qs[2], 3)], "ivDtS": None if qi[1] is None else [round(qi[0], 3), round(qi[1], 3), round(qi[2], 3)],
                  "driftFlag": drift_flag(qs[1], strat_median), "drivesRpmIvDisagree": int(((Pd[:, j] > 0) & dis).sum())}
    return out


# ------------------------------------------------------------------------------------------------ resolution bracket b_nat
def pair_points(co_a, co_b, view, sel):
    la, pa = points(co_a, view, sel)
    _, pb = points(co_b, view, sel)
    return la, pa - pb


def bnat_tables(dm, T_full, tdec, cmask, days, stratum, cs_masks):
    """b_nat of every (view, SOC selection, cell) of one cohort x stratum. Fast: f in {2, 3}, the native v2 table against the equal-weight stack of the f phase variants, all intervals (the M442 form). Slow: f = 2, the common-support
    variant (intervals eligible in both runs), mean of the two phases. Returns {view: {sel: {label: {bNat, shiftPp, f}}}}; a cell without a computable difference is absent (-> 'no resolution bracket available')."""
    out = {v: {s: {} for s in SELS} for v in VIEWS}
    diffs = {}
    for f in DEC_FACTORS[stratum]:
        if stratum == "fast":
            co_a = G.Cohort(T_full, dm, cmask, "nat", days=days)
            co_b = G.Cohort(tdec[f], dm, cmask, "dec", days=days)
            for v in VIEWS:
                for s in SELS:
                    la, d = pair_points(co_a, co_b, v, s)
                    for l, x in zip(la, d):
                        diffs.setdefault((v, s, l), {})[f] = float(x) if np.isfinite(x) else None
        else:
            per = []
            for q, (mf, md_, Td) in enumerate(cs_masks[f]):
                co_a = G.Cohort(T_full, dm, cmask, "nat", days=days, row_mask=mf)
                co_b = G.Cohort(Td, dm, cmask, "dec", days=days, row_mask=md_)
                per.append({(v, s): pair_points(co_a, co_b, v, s) for v in VIEWS for s in SELS})
            for (v, s) in per[0]:
                la = per[0][(v, s)][0]
                for j, l in enumerate(la):
                    xs = [p[(v, s)][1][j] for p in per]
                    diffs.setdefault((v, s, l), {})[f] = float(np.mean(xs)) if all(np.isfinite(xs)) else None
    for (v, s, l), dd in diffs.items():
        b, sh, f = b_nat(dd)
        if b is not None:
            out[v][s][l] = {"bNat": b, "shiftPp": sh, "f": f}
    return out


# ------------------------------------------------------------------------------------------------ one cohort x stratum
def stratum_block(co, w, bn, ivmed, disagree):
    """All rows of one population (a Cohort restricted to one cohort and one stratum)."""
    n = len(co.drive)
    if n == 0:
        return {"status": "empty", "reason": "no intervals", "design": {"days": 0, "drives": 0}}
    days = list(co.days)
    counts_w, nweeks = RS.week_counts(co, days)
    widx, _ = RS.week_index(days)
    strat_med = wquantiles(co.d["iv_dt"], R.KE_FACTOR * co.mass * co.d["iv_dv2"] * co.est * co.w)[1]
    out = {"design": {"days": len(days), "weeks": nweeks, "drives": int(len(co.drives_u)), "draws": G.B_DRAWS, "seed": G.SEED, "weightsHeldFixed": True, "minWeeksPerCell": RS.MIN_WEEKS},
           "totals": cell(co.cell_block("all", np.ones(n, bool))["all"]), "stratumSpeedDtMedianS": None if strat_med is None else round(strat_med, 3), "views": {}, "standardized": {}}
    for v in VIEWS:
        mats, labels = mats_of(co, v)
        vb = {"order": labels, "bySoc": {}}
        for s in SELS:
            cb = co.cell_block(v, co.sel[s], mats, labels)
            rows = {l: cell(cb.get(l, {"n": 0, "drives": 0, "days": 0, "status": "empty"})) for l in labels}
            conv = convention_values(co, v, s)
            wk = week_interval(co, v, s, counts_w, widx) if s == "allSoc" else {}
            for l in labels:
                r = rows[l]
                b = bn[v][s].get(l)
                r["bNat"], r["bNatShiftPp"], r["bNatF"] = (b["bNat"], b["shiftPp"], b["f"]) if b else (None, None, None)
                if r.get("eff") is not None:
                    r["conventionRange"] = {"strictOnly": None if conv["strictOnly"][l] is None else round(conv["strictOnly"][l], 2), "keptPlusTrimmed": None if conv["keptPlusTrimmed"][l] is None else round(conv["keptPlusTrimmed"][l], 2)}
                if s == "allSoc" and l in wk:
                    r["ci95Weeks"] = wk[l]
                if v == "speed" and l in PAYLOAD_ONLY_SPEED:
                    r["payloadOnly"] = True
            drawn = [l for l in labels if not (v == "speed" and l in PAYLOAD_ONLY_SPEED)]
            vb["bySoc"][s] = {"rows": rows, "narrative": narrative(rows, drawn), "extent": extent(rows, drawn)}
        vb["bySoc"]["allSoc"]["sampling"] = sampling_block(co, v, "allSoc", ivmed, disagree, strat_med)
        out["views"][v] = vb
    for v in ("temperature", "speed"):
        res, _ = RS.view_result(co, v, w, counts_w, widx)
        res = RS.strip(res)
        for g, bar in res.get("bars", {}).items():
            b = bn[v]["allSoc"].get(g)
            bar["bNat"] = None if not b else b["bNat"]
        rows = {g: {"eff": bar["standardized"], "ci95": bar.get("ci95Days"), "massRange": bar.get("massRange"), "status": "supported" if bar.get("status") == "supported" else "failed", "bNat": bar.get("bNat")} for g, bar in res.get("bars", {}).items()}
        order = [l for l in out["views"][v]["order"] if not (v == "speed" and l in PAYLOAD_ONLY_SPEED)]
        res["narrative"], res["extent"] = narrative(rows, order), extent(rows, order)
        out["standardized"][v] = res
    return out


def pooled_reference(co):
    """Cadence-mixed pooled cells (reference only, never a primary figure)."""
    out = {}
    for v in VIEWS:
        mats, labels = mats_of(co, v)
        out[v] = {}
        for s in SELS:
            cb = co.cell_block(v, co.sel[s], mats, labels)
            out[v][s] = {l: {k: cb.get(l, {}).get(k) for k in ("n", "eff", "status")} for l in labels}
    return out


# ------------------------------------------------------------------------------------------------ the build
def spec_sha():
    return hashlib.sha256(open(SPEC, "rb").read()).hexdigest()


def frozen_ok():
    return ("M446 spec sha256 " + spec_sha()) in open("CHANGELOG.md", encoding="utf-8").read(120000)


def sha_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def build(workers=5):
    dm, reg = G.load_master()
    files = list(dm["file"])
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    i_off = float(A["offsetUncertainty"]["pointEstimateA"])
    K.ensure(files, i_off, variant="base", workers=workers)
    T, hdrs = K.load(files, "base")
    variants = {f: ["d%dp%d" % (f, q) for q in range(f)] for f in (2, 3)}
    for f, vs in variants.items():
        for v in vs:
            K.ensure(files, i_off, variant=v, workers=workers)
    tdec = {f: K.load_stack(files, vs)[0] for f, vs in variants.items()}
    cs_masks = {2: []}
    for v in variants[2]:
        Td = K.load(files, v)[0]
        mf, md_ = S41.common_support_mask(T, Td)
        cs_masks[2].append((mf, md_, Td))
    hold = G.protocol_hold()
    held = (dm["date"].astype(str).str[:10] >= hold).values if hold else np.zeros(len(dm), bool)
    ev = dm["ev_rpm_dt_med_s"].values
    sm = stratum_masks(ev, held)
    ivmed = np.array([hdrs[f]["cadence"].get("ivDtMed", np.nan) if hdrs[f].get("cadence") else np.nan for f in files], float)
    ivmed = np.where(np.isfinite(ivmed), ivmed, np.nan)
    rpm_cat = np.where(np.isfinite(ev), np.where(ev < 1.0, 0, 1), -1)
    iv_cat = np.where(np.isfinite(ivmed), np.where(ivmed < 1.0, 0, 1), -2)
    disagree = (rpm_cat >= 0) & (iv_cat >= 0) & (rpm_cat != iv_cat)
    masks = {"all": np.ones(len(dm), bool), "warm": reg.values == "warm", "shoulder": reg.values == "shoulder", "cold": reg.values == "cold"}
    co_ref = G.Cohort(T, dm, masks["all"], "all")
    labels_t, Jt = RS.joint(co_ref, "temperature", RS.soc_strata(co_ref))
    w, ke_ref = RS.reference_weights(Jt, list(range(len(labels_t))))
    wsha = hashlib.sha256(json.dumps({k: round(v, 5) for k, v in w.items()}, sort_keys=True).encode()).hexdigest()
    out = {"cohorts": {}}
    gates = {"strataReconcile": {}, "pooledMatchesM441": {}}
    for c, cm in masks.items():
        if cm.sum() == 0:
            continue
        co_pool = co_ref if c == "all" else G.Cohort(T, dm, cm, c)
        blk = {"pooledReference": pooled_reference(co_pool), "strata": {}}
        tot_pool = co_pool.cell_block("all", np.ones(len(co_pool.drive), bool))["all"]
        parts = {"keKwh": 0.0, "chargeKwh": 0.0, "n": 0}
        for p in STRATA:
            pm = cm & sm[p]
            co = G.Cohort(T, dm, pm, c + "-" + p)
            if len(co.drive) == 0:
                blk["strata"][p] = {"status": "empty", "reason": "no intervals", "design": {"days": 0, "drives": 0}}
                continue
            bn = bnat_tables(dm, T, tdec, pm, list(co.days), p, cs_masks)
            blk["strata"][p] = stratum_block(co, w, bn, ivmed, disagree)
            t = co.cell_block("all", np.ones(len(co.drive), bool))["all"]
            for k in parts:
                parts[k] += t.get(k, 0)
        for lab, rest in (("unknown", cm & ~np.isfinite(ev) & ~held), ("held", cm & held)):
            if rest.sum():
                co = G.Cohort(T, dm, rest, c + "-" + lab)
                if len(co.drive):
                    t = co.cell_block("all", np.ones(len(co.drive), bool))["all"]
                    for k in parts:
                        parts[k] += t.get(k, 0)
        gates["strataReconcile"][c] = {k: round(abs(parts[k] - tot_pool.get(k, 0)), 6) for k in parts}
        v41 = A["regenCaptureV2"]["cohorts"][c]["views"]["temperature"]["allSoc"]
        pr = blk["pooledReference"]["temperature"]["allSoc"]
        gates["pooledMatchesM441"][c] = bool(all(((pr[l]["eff"] is None and v41[l].get("eff") is None) or (pr[l]["eff"] == v41[l].get("eff"))) and pr[l]["n"] == v41[l].get("n") for l in pr))
        out["cohorts"][c] = blk
    gates["pass"] = bool(all(max(d.values()) <= 1e-4 for d in gates["strataReconcile"].values()) and all(gates["pooledMatchesM441"].values()))
    ci = A["regenCaptureV2Study"]["cadenceInvariance"]["decision"]
    m442 = "analyses/M442_result_rerun.json"
    out.update({
        "milestone": "M446", "spec": SPEC, "specSha256": spec_sha(), "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "extractorVersion": R.EXTRACTOR_VERSION, "policyHash": R.POLICY_HASH,
        "socSelections": SELS, "views": list(VIEWS), "socEdges": G.SOC_EDGES, "bootstrap": {"B": G.B_DRAWS, "seed": G.SEED, "cluster": "calendar day (own days of each cohort x stratum population)"},
        "support": {"minStrictIntervals": G.MIN_N, "minDrives": G.MIN_DRIVES, "minDays": G.MIN_DAYS, "unidentifiedDrawMax": G.UNID_MAX},
        "strata": {"fast": "drives with master ev_rpm_dt_med_s < 1.0 s (fast-polled)", "slow": "drives with master ev_rpm_dt_med_s >= 1.0 s (slow-polled)", "neither": "a drive with an undefined statistic belongs to neither stratum (M444 S15); PCL-1 protocol drives are held out"},
        "zoneDefinition": {"zones": [{"label": z, "bins": ix} for z, ix in ZONES10], "note": "zones are sums of the drawn 10 km/h bins; the 0-10 km/h bin is not a zone; the top zone keeps the overflow bin (>= 130 km/h)"},
        "referenceMix": {"weights": {k: round(v, 5) for k, v in w.items()}, "sha256": wsha, "note": "the ONE all-cohort KE-weighted reference SOC mix of M444 (owner decision (c)); identical for every stratum, cohort and bar"},
        "resolutionBracket": {"definition": "b_nat = max over f of |v2(native) - v2(decimated f)| (pp, point values), per stratum and cell. Fast-polled: f in {2, 3}, native v2 table against the equal-weight stack of the f phase variants, all intervals (the M442 form). "
                                            "Slow-polled: f = 2 on the common-support variant (intervals eligible in both runs), mean of the two phases. Never borrowed across strata, cells or estimands; a cell without a computable difference shows no resolution bracket. "
                                            "A sensitivity on data already seen, never a gate.",
                              "harmonizedBracketReference": {"source": m442, "sha256": sha_file(m442), "note": "the M442 harmonized b understates the native shift (reference only)"}},
        "b6Reference": {"source": "regenCaptureV2Study.cadenceInvariance.decision", "supportedCellsFailing": len(ci["supportedCellsFailing"]), "nSupportedCells": ci["nSupportedCells"], "blocksStageME": ci["blocksStageME"],
                        "note": "the pre-registered cadence-invariance check B6 (fast-polled drives against their thinned version) FAILED; shown beside the display; the condition (2) of M441 Rev 2.2 is not discharged (M446 Rev 1.1 D1)"},
        "gates": gates,
        "label": "cadence-stratified native apparent battery-side KE recovery (assumed masses), resolution-conditional; fast-polled and slow-polled drives are not comparable; not a correction of the legacy values",
        "reading": ("Native v2 apparent KE recovery (ratio of sums over engine-off deceleration intervals, assumed class masses, 300 rpm engine-off proxy) for each polling stratum separately. A level depends on the logger's sampling "
                    "resolution; the resolution bracket b_nat is the largest change of the cell value when the drives of the stratum are thinned (fast-polled by 2 and 3, slow-polled by 2). The day-clustered interval, the assumed-mass range, "
                    "the resolution bracket and the plateau convention range are separate and are never combined. The two strata differ in date, season and temperature and are not contrasted; the fast-versus-slow comparison of M442 (G2) is not testable "
                    "and the paired-cadence protocol PCL-1 was not run. Observed uses the actual SOC mix; SOC-standardized uses one common reference mix over the stated common-support bands and adjusts for SOC composition only."),
        "disclosures": ["engine off is the RPM <= 300 proxy; assumed class masses; the field name eff is a label for the apparent KE recovery ratio, not an efficiency",
                        "temperature, SOC, speed, demand, day, season and the polling stratum are confounded in the logged data; all values are unadjusted and descriptive",
                        "the cadence-invariance study B6 FAILED for the fast-polled stratum; the M442 gate G2 is not testable; PCL-1 was not run",
                        "the 0-10 km/h and >= 130 km/h speed bins are in the payload only (payloadOnly)"],
        "refresh": "recomputed at every ingestion by the stage regen_v2 (per-drive cache; decimated variants d2p0 d2p1 d3p0 d3p1 d3p2 are extended for new drives)"})
    return out


if __name__ == "__main__":
    import time
    t0 = time.time()
    if "--smoke" not in sys.argv and not frozen_ok():
        raise SystemExit("refusing to run: CHANGELOG.md does not carry 'M446 spec sha256 %s' (spec section 15)" % spec_sha())
    res = build()
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M446_result.json"
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps({"seconds": round(time.time() - t0), "wrote": out_path, "gates": res["gates"]}))
