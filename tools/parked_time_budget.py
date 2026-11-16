"""M687 (N-03 part B): modelled hours at pack temperature, including parked hours (spec analyses/M686_spec.md Rev 1.1).

The logger records only while the car is on. Parked pack temperature is MODELLED by the Q3 exponential relaxation
T(t) = A_eff + (T0 - A_eff) exp(-t / tau), A = mean of the previous end ambient and the next start ambient (driver-recorded),
outdoor parking assumed (owner statement 2026-11-16). Band hours are exact (closed-form edge crossings). The uncertainty is a
pre-registered grid of assumptions, never an interval. Additive payload block `parkedTimeBudget`.
"""
import bisect, copy, datetime, hashlib, json, math, os, sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SPEC = "analyses/M686_spec.md"

EDGES = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]
NB = len(EDGES) + 1
LABELS = ["<0", "0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30-35", "35-40", ">=40"]
CLS_EDGES = [1.0, 4.0, 12.0, 36.0]
CLS_LABELS = ["below 1 h", "1 to <4 h", "4 to <12 h", "12 to <36 h", "36 h or longer"]
LONG_CLS = 4
UNLOGGED_KM = 1.0
DIURNAL_C = 4.0
INDOOR_TARGET_C = 15.0
SEED = 42
NPERM = 1000
FOLDS = 10
MIN_GAPS, MIN_DAYS, ESS_MIN = 10, 5, 10.0
SHIFTS = (-2.0, 0.0, 2.0)
OFFSETS = (-3.0, 0.0, 3.0)
INDOOR_F = (0.0, 0.05, 0.10)


# ------------------------------------------------------------------------------------------------ exact model
def band_of(T):
    return bisect.bisect_right(EDGES, T)          # a value exactly on an edge goes to the upper band


def band_hours(T0, A, g, tau):
    """Hours in each band of T(t) = A + (T0 - A) exp(-t/tau), t in [0, g]; exact from the edge-crossing times."""
    out = np.zeros(NB)
    if g <= 0:
        return out
    d0 = T0 - A
    if abs(d0) < 1e-12:
        out[band_of(A)] = g
        return out
    ts = [0.0, g]
    for E in EDGES:
        x = (E - A) / d0
        if x > 0:
            t = -tau * math.log(x)
            if 0.0 < t < g:
                ts.append(t)
    ts.sort()
    for a, b in zip(ts[:-1], ts[1:]):
        if b > a:
            out[band_of(A + d0 * math.exp(-0.5 * (a + b) / tau))] += b - a
    return out


def band_hours_numeric(T0, Afun, g, tau, dt=1.0 / 60.0):
    """Numerical band hours for a time-varying ambient Afun(t): exact exponential update per step with the step-midpoint ambient,
    piecewise-linear temperature within a step. Used for V3 and the long-gap sensitivities."""
    out = np.zeros(NB)
    if g <= 0:
        return out
    n = max(1, int(math.ceil(g / dt - 1e-12)))
    lo_e = np.array([-1e9] + EDGES)
    hi_e = np.array(EDGES + [1e9])
    T = T0
    t = 0.0
    for _ in range(n):
        h = min(dt, g - t)
        if h <= 0:
            break
        Am = Afun(t + 0.5 * h)
        T2 = Am + (T - Am) * math.exp(-h / tau)
        lo, hi = min(T, T2), max(T, T2)
        if hi - lo < 1e-12:
            out[band_of(T)] += h
        else:
            ov = np.clip(np.minimum(hi, hi_e) - np.maximum(lo, lo_e), 0.0, None)
            out += h * ov / (hi - lo)
        T, t = T2, t + h
    return out


# ------------------------------------------------------------------------------------------------ gaps
def cls_of(g):
    return bisect.bisect_right(CLS_EDGES, g)


def build_gaps(d):
    """d sorted by key-on: columns t0u, durH, tFirst, tLast, amb_start, amb_end, unlogged, clean, date, hour_end (local clock hour of the key-off).
    One row per consecutive pair; assigned or unassigned with a stated reason."""
    rows = []
    for i in range(1, len(d)):
        p, n = d.iloc[i - 1], d.iloc[i]
        g = float((n.t0u - (p.t0u + pd.Timedelta(hours=float(p.durH)))).total_seconds() / 3600.0)
        T0, a0, a1 = p.tLast, p.amb_end, n.amb_start
        if g < 0:
            st, why = "unassigned", "overlap"
        elif pd.isna(T0):
            st, why = "unassigned", "missing pack end temperature"
        elif pd.isna(a0) or pd.isna(a1):
            st, why = "unassigned", "missing ambient reading"
        else:
            st, why = "assigned", ""
        rows.append({"i": i, "arrDate": n.date, "g": g, "T0": None if pd.isna(T0) else float(T0), "a0": None if pd.isna(a0) else float(a0), "a1": None if pd.isna(a1) else float(a1),
                     "A": float((a0 + a1) / 2.0) if (not pd.isna(a0) and not pd.isna(a1)) else None, "cls": cls_of(g) if g >= 0 else None, "status": st, "reason": why,
                     "unlogged": bool(pd.notna(n.unlogged) and n.unlogged > UNLOGGED_KM), "afterExcluded": bool(not p.clean), "hourEnd": float(p.hour_end),
                     "nextFirst": None if pd.isna(n.tFirst) else float(n.tFirst)})
    return rows


# ------------------------------------------------------------------------------------------------ scenario evaluation
def indoor_set(gaps, f, rule):
    """Gaps (index into the list) treated as indoor: among assigned gaps of 4 h or longer; f is the share of the assigned parked hours."""
    if f <= 0:
        return set(), 0.0
    tot = sum(x["g"] for x in gaps if x["status"] == "assigned")
    elig = [k for k, x in enumerate(gaps) if x["status"] == "assigned" and x["g"] >= 4.0]
    if rule == "everyKth":
        k = max(1, int(round(1.0 / f)))
        pick = elig[::k]
        # (every k-th in time order starting at the first eligible gap)
    else:
        order = sorted(elig, key=lambda j: gaps[j]["A"], reverse=(rule == "hottestFirst"))
        pick, acc = [], 0.0
        for j in order:
            if acc >= f * tot:
                break
            pick.append(j)
            acc += gaps[j]["g"]
    realised = sum(gaps[j]["g"] for j in pick) / tot if tot > 0 else 0.0
    return set(pick), realised


def evaluate(gaps, tau, shift=0.0, offset=0.0, f=0.0, rule="everyKth", treat_unlogged_unassigned=False, long_mode="const", t0_shift=0.0):
    """Band hours (NB) overall, without the long class, by gap class, for one scenario."""
    ind, realised = indoor_set(gaps, f, rule)
    tot = np.zeros(NB)
    noLong = np.zeros(NB)
    byCls = np.zeros((len(CLS_LABELS), NB))
    for k, x in enumerate(gaps):
        if x["status"] != "assigned" or (treat_unlogged_unassigned and x["unlogged"]):
            continue
        Aeff = x["A"] + shift + offset
        if k in ind:
            Aeff = Aeff + (INDOOR_TARGET_C - Aeff) / 2.0
        T0 = x["T0"] + t0_shift
        if long_mode != "const" and x["cls"] == LONG_CLS:
            if long_mode == "linear":
                a0, a1, g = x["a0"] + shift + offset, x["a1"] + shift + offset, x["g"]
                Af = (lambda t, a0=a0, a1=a1, g=g: a0 + (a1 - a0) * t / g)
            else:
                h0 = x["hourEnd"]
                Af = (lambda t, A=Aeff, h0=h0: A + DIURNAL_C * math.sin(2 * math.pi * (h0 + t - 9.0) / 24.0))
            h = band_hours_numeric(T0, Af, x["g"], tau)
        else:
            h = band_hours(T0, Aeff, x["g"], tau)
        tot += h
        byCls[x["cls"]] += h
        if x["cls"] != LONG_CLS:
            noLong += h
    return {"bands": tot, "noLong": noLong, "byCls": byCls, "realisedIndoor": realised}


def metrics(res):
    b, nl = res["bands"], res["noLong"]
    m = {"parkedHours": float(b.sum()), "cold10": float(b[:3].sum()), "cold15": float(b[:4].sum()), "hot35": float(b[8:].sum()), "hot40": float(b[9:].sum()),
         "cold10NoLong": float(nl[:3].sum()), "cold15NoLong": float(nl[:4].sum()), "hot35NoLong": float(nl[8:].sum()), "hot40NoLong": float(nl[9:].sum()),
         "longShareOfParked": float(res["byCls"][LONG_CLS].sum() / b.sum()) if b.sum() > 0 else None}
    for j, lab in enumerate(LABELS):
        m["band:" + lab] = float(b[j])
    for c in range(len(CLS_LABELS)):
        bc = res["byCls"][c]
        m["cls%d:cold10" % c], m["cls%d:cold15" % c], m["cls%d:hot35" % c], m["cls%d:hot40" % c] = float(bc[:3].sum()), float(bc[:4].sum()), float(bc[8:].sum()), float(bc[9:].sum())
    return m


# ------------------------------------------------------------------------------------------------ grid
def tau_axis(q3):
    """Named tau axis (spec section 9 item 6): the ambient shift is paired with the Q3 tau refitted at that shift."""
    if not q3 or q3.get("primary", {}).get("tauH") is None:
        return [], False, "no Q3 primary"
    s = q3.get("sensitivities", {})
    gate = bool(q3.get("heldOut", {}).get("gatePassed"))
    g = lambda k: (s.get(k) or {}).get("tauH")
    ent = []
    if gate:
        ent.append(("primary", q3["primary"]["tauH"], 0.0))
    for lab, k in (("stratum4hOrLonger", "gap4hOrLonger"), ("L2", "L2Loss"), ("previousDriveMax", "previousDriveMaxProxy")):
        if g(k) is not None:
            ent.append((lab, g(k), 0.0))
    for sh in (-2.0, 2.0):
        v = g("ambientRefShift%+.0fC" % sh)
        if v is not None:
            ent.append(("ambientShift%+.0fC(refit)" % sh, v, sh))
    return ent, gate, ""


def run_grid(gaps, ent):
    cells = []
    for lab, tau, sh in ent:
        for o in OFFSETS:
            for f in INDOOR_F:
                for rule in (("everyKth",) if f == 0 else ("everyKth", "coldestFirst", "hottestFirst")):
                    r = evaluate(gaps, tau, shift=sh, offset=o, f=f, rule=rule)
                    cells.append(({"tau": lab, "tauH": tau, "ambientShiftC": sh, "offsetC": o, "indoorFraction": f, "indoorRule": rule if f else "none", "realisedIndoorFraction": round(r["realisedIndoor"], 4)}, metrics(r)))
    return cells


def grid_summary(cells):
    out = {}
    keys = cells[0][1].keys() if cells else []
    for k in keys:
        vals = [(c[1][k], c[0]) for c in cells if c[1][k] is not None]
        lo, hi = min(vals, key=lambda v: v[0]), max(vals, key=lambda v: v[0])
        out[k] = {"min": round(lo[0], 3), "minCell": lo[1], "max": round(hi[0], 3), "maxCell": hi[1]}
    return out


# ------------------------------------------------------------------------------------------------ support
def ess(w):
    w = np.asarray(w, float)
    return float(w.sum() ** 2 / np.sum(w ** 2)) if len(w) and np.sum(w ** 2) > 0 else 0.0


def band_support(gaps, tau):
    """Cluster = arrival day of the gap, weight = hours in the cell per gap; 'contributing' = more than 0 h in the cell; primary only."""
    per = [dict() for _ in range(NB)]
    cnt = [0] * NB
    for x in gaps:
        if x["status"] != "assigned":
            continue
        h = band_hours(x["T0"], x["A"], x["g"], tau)
        for j in range(NB):
            if h[j] > 1e-9:
                cnt[j] += 1
                per[j][x["arrDate"]] = per[j].get(x["arrDate"], 0.0) + float(h[j])
    out = []
    for j in range(NB):
        nd, e = len(per[j]), ess(list(per[j].values()))
        st = "not shown" if (cnt[j] < MIN_GAPS or nd < MIN_DAYS) else ("exploratory" if e < ESS_MIN else "supported")
        out.append({"nGaps": cnt[j], "nDays": nd, "essDays": round(e, 3), "status": st})
    return out


# ------------------------------------------------------------------------------------------------ B4 endpoint validation
def l1_tau(e0, e1, gap):
    grid = np.exp(np.linspace(np.log(0.2), np.log(200.0), 200))
    def L(t):
        return np.abs(e0[:, None] * np.exp(-gap[:, None] / t[None, :]) - e1[:, None]).sum(0)
    i = int(np.argmin(L(grid)))
    fine = np.exp(np.linspace(np.log(grid[max(i - 1, 0)]), np.log(grid[min(i + 1, len(grid) - 1)]), 80))
    return float(fine[int(np.argmin(L(fine)))])


def endpoint_validation(gaps, train_mask, nperm=NPERM, seed=SEED):
    """All consecutive pairs with both endpoints and both ambient readings, any gap class; tau fitted on the training pairs (the Q3 eligibility
    set, `train_mask` per gap) on the other day-blocked folds. Placebo: tau fixed, A shuffled within the gap class."""
    P = [(k, x) for k, x in enumerate(gaps) if x["status"] == "assigned" and x["nextFirst"] is not None]
    if not P:
        return {"nPairs": 0}
    days = np.array(sorted({x["arrDate"] for _, x in P}))
    blocks = np.array_split(days, min(FOLDS, len(days)))
    tau_of = {}
    for blk in blocks:
        bs = set(blk)
        tr = [(k, x) for k, x in P if x["arrDate"] not in bs and train_mask[k]]
        if len(tr) < 20:
            continue
        e0 = np.array([x["T0"] - x["A"] for _, x in tr]); e1 = np.array([x["nextFirst"] - x["A"] for _, x in tr]); gg = np.array([x["g"] for _, x in tr])
        t = l1_tau(e0, e1, gg)
        for k, x in P:
            if x["arrDate"] in bs:
                tau_of[k] = t
    P = [(k, x) for k, x in P if k in tau_of]
    rng = np.random.default_rng(seed)
    out = {"nPairs": len(P), "nDays": len({x["arrDate"] for _, x in P}), "cv": "day-blocked contiguous folds over arrival days (k=10); tau refitted on the other folds (L1, Q3 eligibility set)", "byClass": {}}
    for c, lab in enumerate(CLS_LABELS):
        Q = [(k, x) for k, x in P if x["cls"] == c]
        if len(Q) < 5:
            out["byClass"][lab] = {"n": len(Q), "note": "fewer than 5 pairs"}
            continue
        T0 = np.array([x["T0"] for _, x in Q]); A = np.array([x["A"] for _, x in Q]); obs = np.array([x["nextFirst"] for _, x in Q]); g = np.array([x["g"] for _, x in Q]); ta = np.array([tau_of[k] for k, _ in Q])
        pred = A + (T0 - A) * np.exp(-g / ta)
        mae = float(np.abs(pred - obs).mean())
        pm = np.empty(nperm)
        for r in range(nperm):
            As = rng.permutation(A)
            pm[r] = np.abs(As + (T0 - As) * np.exp(-g / ta) - obs).mean()
        p5 = float(np.percentile(pm, 5))
        out["byClass"][lab] = {"n": len(Q), "maeModelC": round(mae, 3), "signedBiasModelC": round(float((pred - obs).mean()), 3), "maePersistenceC": round(float(np.abs(T0 - obs).mean()), 3),
                               "maeFullRelaxationC": round(float(np.abs(A - obs).mean()), 3), "placeboMaeMedianC": round(float(np.median(pm)), 3), "placeboMae5thPercentileC": round(p5, 3),
                               "modelBeatsBetterReference": bool(mae < min(float(np.abs(T0 - obs).mean()), float(np.abs(A - obs).mean()))), "skillDropsUnderPlacebo": bool(mae < p5), "outOfSample": "all pairs are held-out; gaps of 36 h or longer lie outside the fitted gap range (0.02 to 36 h)" if c == LONG_CLS else "held-out"}
    return out


# ------------------------------------------------------------------------------------------------ assembly
def accounting(d, gaps, tauP):
    dur = float(d.durH.sum())
    asg = sum(x["g"] for x in gaps if x["status"] == "assigned")
    un = sum(x["g"] for x in gaps if x["status"] == "unassigned" and x["reason"] != "overlap")
    ov = sum(x["g"] for x in gaps if x["reason"] == "overlap")
    end = float(((d.t0u.iloc[-1] + pd.Timedelta(hours=float(d.durH.iloc[-1]))) - d.t0u.iloc[0]).total_seconds() / 3600.0)
    return {"drivingHours": round(dur, 4), "parkedAssignedHours": round(asg, 4), "unassignedGapHours": round(un, 4), "overlapHoursSigned": round(ov, 4), "sumHours": round(dur + asg + un + ov, 4), "windowHours": round(end, 4),
            "absDifferenceH": abs(dur + asg + un + ov - end), "v1Passed": bool(abs(dur + asg + un + ov - end) < 1e-6)}


def assemble(d, gaps, q3, ev_bins, train_mask, nperm=NPERM):
    ent, gate, why = tau_axis(q3)
    prim = next((e for e in ent if e[0] == "primary"), None)
    block = {"label": "modelled time at pack temperature including parked hours (modelled; estimated, never measured; one May-to-November window)", "spec": SPEC, "status": "exploratory"}
    acc = accounting(d, gaps, prim[1] if prim else None)
    window = acc["windowHours"]
    cells = run_grid(gaps, ent)
    gs = grid_summary(cells)
    block["assumptions"] = {"parking": "outdoors in nearly all cases; indoor parking is a rare exception (owner statement 2026-11-16)", "temperatureLogger": "none; ambient is registered at drives only (owner statement 2026-11-16)",
                            "ambientReference": "A = mean of the previous key-off ambient and the next key-on ambient (driver-recorded dashboard readings); A_eff = A + shift + offset; indoor: A_in = A_eff + (15 - A_eff) / 2",
                            "parkedModel": "T(t) = A_eff + (T0 - A_eff) exp(-t / tau); tau from seasonalFits.Q3 (owner decision D-05)", "indoorTargetC": INDOOR_TARGET_C, "verified": False,
                            "d05Support": bool(gate), "definitionDependent": bool((q3.get("spread") or {}).get("definitionDependent", True)) if q3 else True}
    block["tauAxis"] = [{"name": e[0], "tauH": e[1], "ambientShiftC": e[2]} for e in ent]
    block["d05Fallback"] = None if gate else "seasonalFits.Q3.heldOut.gatePassed is not true: no primary; the grid only"
    block["window"] = {"startUtc": str(d.t0u.iloc[0]), "endUtc": str(d.t0u.iloc[-1] + pd.Timedelta(hours=float(d.durH.iloc[-1]))), "nDrives": int(len(d)), "nGaps": len(gaps), "nGapsAssigned": sum(x["status"] == "assigned" for x in gaps),
                       "nGapsUnassigned": sum(x["status"] == "unassigned" for x in gaps),
                       "unassignedByReason": {r: sum(1 for x in gaps if x["reason"] == r) for r in sorted({x["reason"] for x in gaps if x["reason"]})},
                       "nGapsAfterExcludedDrive": sum(1 for x in gaps if x["status"] == "assigned" and x["afterExcluded"]), "nGapsNextDriveUnlogged": sum(1 for x in gaps if x["status"] == "assigned" and x["unlogged"])}
    block["accounting"] = acc
    if prim:
        tauP = prim[1]
        sup = band_support(gaps, tauP)
        pr = evaluate(gaps, tauP)
        pm = metrics(pr)
        cleanDur = float(d.durH[d.clean].sum())
        exclDur = float(d.durH[~d.clean].sum())
        banded = float(sum(b["hours"] for b in ev_bins))
        rows = []
        for j, lab in enumerate(LABELS):
            evb = next((b for b in ev_bins if b["bin"] == lab), None)
            rows.append({"band": lab, "drivingCleanHours": None if evb is None else round(float(evb["hours"]), 4), "drivingSensor": "T1 (exposureVector)", "parkedModelledHours": round(pm["band:" + lab], 4),
                         "parkedShareOfWindow": round(pm["band:" + lab] / window, 5), "drivingShareOfWindow": None if evb is None else round(float(evb["hours"]) / window, 5), **sup[j],
                         "grid": gs["band:" + lab], "parkedSensor": "probe mean (modelled)"})
        block["B1"] = {"bands": rows, "drivingExcludedDrivesHours": round(exclDur, 4), "drivingUnbandedCleanHours": round(cleanDur - banded, 4),
                       "unassignedGapHours": acc["unassignedGapHours"], "overlapHoursSigned": acc["overlapHoursSigned"],
                       "note": "driving bands use sensor T1 and parked bands the probe mean; they are not summed into one total (a mixed-sensor sum would be labelled mixed-sensor)",
                       "sensorOffsetT1MinusProbeMean": "not estimable from the cache (per-probe values are not stored); +-1 C stays a labelled assumption, applied as a one-at-a-time shift of the parked start temperature in the sensitivities"}
        bycls = []
        for c, lab in enumerate(CLS_LABELS):
            hrs = float(pr["byCls"][c].sum())
            bycls.append({"gapClass": lab, "nGaps": sum(1 for x in gaps if x["status"] == "assigned" and x["cls"] == c), "parkedHours": round(hrs, 4), "shareOfParkedHours": round(hrs / pm["parkedHours"], 4) if pm["parkedHours"] > 0 else None})
        un = [x for x in gaps if x["status"] == "assigned" and x["unlogged"]]
        block["B2"] = {"parkedShareOfWindow": round(pm["parkedHours"] / window, 4), "grid": gs["parkedHours"], "byGapClass": bycls, "longGapShareOfParkedHours": round(pm["longShareOfParked"], 4),
                       "gapsWithNextDriveUnlogged": {"nGaps": len(un), "hours": round(float(sum(x["g"] for x in un)), 4)},
                       "gapsAfterExcludedDrive": {"nGaps": sum(1 for x in gaps if x["status"] == "assigned" and x["afterExcluded"]), "hours": round(float(sum(x["g"] for x in gaps if x["status"] == "assigned" and x["afterExcluded"])), 4)}}
        block["B3"] = {"wording": "same thresholds as S1 and S2; no charging occurs while parked", **{k: {"primary": round(pm[k], 3), "grid": gs[k]} for k in ("cold10", "cold15", "hot35", "hot40", "cold10NoLong", "cold15NoLong", "hot35NoLong", "hot40NoLong")}}
        sens = {}
        for lab, kw in (("nextDriveUnloggedTreatedAsUnassigned", {"treat_unlogged_unassigned": True}), ("longGapAmbientLinear", {"long_mode": "linear"}), ("longGapAmbientDiurnal4C", {"long_mode": "diurnal"}),
                        ("parkedStartShiftMinus1C", {"t0_shift": -1.0}), ("parkedStartShiftPlus1C", {"t0_shift": 1.0})):
            m = metrics(evaluate(gaps, tauP, **kw))
            sens[lab] = {k: round(m[k], 3) for k in ("parkedHours", "cold10", "cold15", "hot35", "hot40", "cold10NoLong", "cold15NoLong")}
        block["sensitivities"] = sens
        rank = {"not shown": 0, "exploratory": 1, "supported": 2}
        def weakest(lo, hi):
            st = [sup[j]["status"] for j in range(lo, hi) if sup[j]["nGaps"] > 0]
            return min(st, key=lambda x: rank[x]) if st else "not shown"
        for k, (lo, hi) in {"cold10": (0, 3), "cold15": (0, 4), "hot35": (8, 10), "hot40": (9, 10)}.items():
            block["B3"][k]["support"] = weakest(lo, hi)
            block["B3"][k]["supportBasis"] = "weakest status among the contributing bands (a band with no contributing gap is ignored)"
        bg = []
        for c, lab in enumerate(CLS_LABELS):
            row = {"gapClass": lab, "companionRowNotPrimary": True}
            for k in ("cold10", "cold15", "hot35", "hot40"):
                row[k] = {"primary": round(pm["cls%d:%s" % (c, k)], 3), "grid": gs["cls%d:%s" % (c, k)]}
            bg.append(row)
        for k in ("cold10", "cold15", "hot35", "hot40"):
            assert abs(sum(r[k]["primary"] for r in bg) - block["B3"][k]["primary"]) < 0.01, "B3 class rows must sum to the primary"
        block["B3"]["byGapClass"] = bg
        block["B3"]["identity"] = "the class rows sum to the primary (checked at build)"
        block["support"] = {"basis": "cluster = arrival day of the gap; weight = hours in the cell per gap; not shown below 10 gaps or 5 days; exploratory below 10 effective days; primary only"}
    else:
        block["B1"] = block["B2"] = block["B3"] = None
        block["gridOnly"] = {"summary": gs}
    block["B4"] = endpoint_validation(gaps, train_mask, nperm=nperm)
    block["grid"] = {"nCells": len(cells), "axes": "tau entries (ambient shift paired with its refitted tau) x offset {-3,0,3} C x indoor fraction {0, 0.05, 0.10} with rules everyKth / coldestFirst / hottestFirst; min and max with their cells; no interval"}
    return block


def validity(gaps, tauP):
    """V3 exact versus 1-min numeric for up to 20 assigned gaps; V5 band hours sum to the gap length; V2 every consecutive pair is a gap row."""
    sub = [x for x in gaps if x["status"] == "assigned"][::max(1, len(gaps) // 20)][:20]
    worst, worst5 = 0.0, 0.0
    for x in sub:
        ex = band_hours(x["T0"], x["A"], x["g"], tauP)
        nu = band_hours_numeric(x["T0"], (lambda t, A=x["A"]: A), x["g"], tauP)
        worst = max(worst, float(np.abs(ex - nu).max()))
        worst5 = max(worst5, abs(float(ex.sum()) - x["g"]))
    return {"V3_exactVsNumericMaxAbsDiffH": round(worst, 7), "V3_passed": bool(worst < 1e-3), "V5_bandHoursSumToGapMaxAbsDiffH": round(worst5, 9), "V5_passed": bool(worst5 < 1e-9), "nGapsChecked": len(sub)}


# ------------------------------------------------------------------------------------------------ I/O
def load_frame(raw_dir):
    sys.path.insert(0, HERE)
    sys.path.insert(0, ROOT)
    import n02_seasonal_fits as N
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file"])
    eps = N.corpus_endpoints(raw_dir, sorted(dm["file"]), verbose=True)
    d = N.load_drives(eps)
    sm = pd.read_csv(os.path.join(ROOT, "seasonal_drive_master.csv"), usecols=["file", "utc_offset_h"])
    d = d.merge(sm, on="file", how="left")
    d["t0u"] = d["t0"] - pd.to_timedelta(d["utc_offset_h"], unit="h")
    d["durH"] = d["duration_s"] / 3600.0
    d["amb_start"], d["amb_end"], d["unlogged"] = d["ambient_start_c"], d["ambient_end_c"], d["unlogged_distance_est_km"]
    t1 = d["t0"] + pd.to_timedelta(d["duration_s"], unit="s")
    d["hour_end"] = t1.dt.hour + t1.dt.minute / 60.0 + t1.dt.second / 3600.0
    d = d.sort_values("t0u").reset_index(drop=True)
    return d, N


def train_mask_for(gaps, d, N):
    """Q3 eligibility (consecutive canonical-clean drives, gap 0.02 to 36 h) per gap row."""
    out = []
    for x in gaps:
        p, n = d.iloc[x["i"] - 1], d.iloc[x["i"]]
        out.append(bool(p.clean and n.clean and N.GAP_LO_H <= x["g"] <= N.GAP_HI_H and x["status"] == "assigned" and x["nextFirst"] is not None))
    return out


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get("parkedTimeBudget")
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M687: derived by tools/parked_time_budget.py from drive_master.csv, seasonal_drive_master.csv, cached end-of-drive pack temperatures, seasonalFits.Q3 and exposureVector (spec analyses/M686_spec.md Rev 1.1); modelled, exploratory")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["parkedTimeBudget"] = _sc.carry_declared(old, st)


def main(argv):
    raw_dir = argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else (os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    d, N = load_frame(raw_dir)
    gaps = build_gaps(d)
    q3 = A["seasonalFits"]["Q3"]
    ev_bins = A["exposureVector"]["Q1_Q2_Q4_clean"]["bins"]
    tm = train_mask_for(gaps, d, N)
    nperm = 100 if "--dry-run" in argv else NPERM
    block = assemble(d, gaps, q3, ev_bins, tm, nperm=nperm)
    ent, gate, _ = tau_axis(q3)
    prim = next((e for e in ent if e[0] == "primary"), None)
    block["validity"] = {"V1_timeAccounting": {"passed": block["accounting"]["v1Passed"], "absDifferenceH": block["accounting"]["absDifferenceH"]}, "V2_everyConsecutivePairIsAGapRow": bool(len(gaps) == len(d) - 1),
                         **(validity(gaps, prim[1]) if prim else {}), "V4_determinism": "seed 42; the grid is deterministic"}
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    block["reading"] = ["parked hours are MODELLED from the Q3 cool-down relaxation and the driver-recorded ambient at the two bounding drives; they are not measured and are validated only at the two ends of a gap (held-out next key-on temperature)",
                        "the uncertainty is the stated grid of assumptions (min and max with their cells), not a confidence interval; a statement such as 'below 10 deg C for x hours' is allowed only with its bracket",
                        "the ambient is read at drive times (daytime) and the dashboard sensor heat-soaks at key-on, so A is likely biased warm against the 24 h mean and the cold parked hours are likely understated",
                        "an hours-by-temperature budget of one May-to-November window; not lifetime exposure, not annualised, not an ageing estimate",
                        "no charging occurs while parked; the cold and hot parked hours use the same temperature thresholds as the S1 and S2 screens of exposureVector",
                        "the block does not feed or compare with the Arrhenius index Q4 or the monthly temperature table"]
    nb = [k for k, v in block["B4"].get("byClass", {}).items() if v.get("modelBeatsBetterReference") is False]
    if nb:
        block["reading"].append("at the gap-class ends the model does not beat the better of persistence and full relaxation for: " + ", ".join(nb) + "; the parked hours of those classes (%s of the parked hours) rest on the weakest part of the model" % ("%.0f%%" % (100.0 * sum(c["shareOfParkedHours"] for c in (block["B2"] or {}).get("byGapClass", []) if c["gapClass"] in nb))))
    sh = sum(c["shareOfParkedHours"] for c in (block["B2"] or {}).get("byGapClass", []) if c["gapClass"] in nb) if block["B2"] else None
    block["flags"] = {"longGapSkillNotAboveReference": bool(nb), "classes": nb, "parkedHoursShare": None if sh is None else round(sh, 3),
                      "directionOfKnownBias": "warm: the ambient reference comes from daytime readings and the short-pair tau over-persists drive-end heat in the 12 to <36 h class; cold hours are likely understated and the hot tails likely overstated",
                      "coldHoursInGapsOf36hOrLonger": None if not block["B3"] else round(block["B3"]["byGapClass"][LONG_CLS]["cold10"]["primary"], 3)}
    block["conventions"] = {"timestamps": "key-on = local_iso[:19] minus utc_offset_h (UTC, DST-aware; the window contains 2026-10-25); key-off = key-on + duration_s; drives sorted by UTC key-on; a negative gap is 'unassigned: overlap' and counts as signed hours in the time accounting",
                            "endpointBias": "signed bias = predicted minus observed next key-on pack temperature",
                            "afterExcludedDrive": "the cached end temperature is used when 3 of 4 probes exist; none of the excluded drives has one, so those gaps are unassigned (see window.unassignedByReason)",
                            "unloggedDriving": "gaps whose next drive has unlogged driving above 1.0 km are assigned in the primary and listed in B2.gapsWithNextDriveUnlogged; the sensitivity treats them as unassigned",
                            "sensorOffsetBasis": "T1 minus probe mean is not estimable from the cache; +-1 C shifts of the parked start temperature are the labelled stand-in"}
    block["provenance"] = {"masterMd5": md5, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "seed": SEED, "nPermutations": nperm, "nDrives": int(len(d))}
    if "--out" in argv:
        json.dump(block, open(argv[argv.index("--out") + 1], "w", encoding="utf-8"), indent=1)
        print("wrote block")
        return
    if "--dry-run" in argv:
        print(json.dumps({"window": block["window"], "accounting": block["accounting"], "B3": block["B3"] and {k: v["primary"] for k, v in block["B3"].items() if isinstance(v, dict)}, "validity": block["validity"]}, default=str)[:3000])
        return
    old = copy.deepcopy(A)
    A["parkedTimeBudget"] = block
    stamp(A, md5)
    chk = copy.deepcopy(A); chk.pop("parkedTimeBudget"); chk["_artifactStamps"].pop("parkedTimeBudget")
    o2 = copy.deepcopy(old); o2.pop("parkedTimeBudget", None); o2["_artifactStamps"].pop("parkedTimeBudget", None)
    assert chk == o2, "unexpected change outside /parkedTimeBudget"
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    main(sys.argv[1:])
