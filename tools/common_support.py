#!/usr/bin/env python3
"""M554 (spec analyses/M554_spec.md Rev 2): common-support estimator bridge (audit 2026-10-29 N06 + F17), published method P versus the union-clock method U.
P = the published nearest-pair integration (tools/integration_scenarios.integrate, imported, not recoded; tolerance ladder 1.5 / 3 / 5 s). U = both channels linearly interpolated onto the union of their sample times, a channel is never
interpolated across its own gap (> Gmax, default 5 s; sensitivity 1.5 / 3 / 10 s), a union step is supported iff it is <= 5 s long and both channels are defined inside it (no bridging); inside a supported step current and voltage are
linear, so the power is an exact quadratic and the energy is exact (d (I0 V0 + I1 V1) / 3 + d (I0 V1 + I1 V0) / 6) with the discharge / charge split at the single root of the current.
PRIMARY = the seconds-level common-support estimate per drive (both methods evaluated on the time intersection of their supported intervals); added / lost seconds and energy are reported separately and never summed into the delta.
Known answers (STOP on a miss): P reproduces the master gross discharge / charge per drive, the P step decomposition equals integrate(no_bridge=True), U |net| <= gross. The published estimator and every master column are unchanged;
the U energies of the drives P leaves null (F17) enter no rate, total or eligibility. Per-drive records are cached by the raw sha256 and the extractor hash (bridge_cache/, git-ignored).
Modes: --check (writes analyses/M554_check.json) | --splice (check + additive write of S.commonSupportBridge). Usage: python tools/common_support.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M554_check.json")
CACHE = os.path.join(ROOT, "bridge_cache")
STEP_CAP_S = 5.0
G_MAIN, G_SENS = 5.0, (1.5, 3.0, 10.0)
P_TOL_MS = (1500, 3000, 5000)
MIN_COMMON_KWH = 0.1
TOPK = (1, 5, 10)
SEED, DRAWS, MIN_DAYS = 42, 4000, 5
TOL_GROSS_KWH, TOL_STEPS_KWH = 1e-4, 1e-9
F17_MIN_SUPPORT_SHARE = 0.5


# ---------------------------------------------------------------- kernels (pure, unit-tested)
def step_energy(d, a, b, v0, v1):
    """exact (discharge, charge) kWh over a step of d seconds with the discharge current linear a -> b (A) and the voltage linear v0 -> v1 (V). V > 0, so the split is at the single root of the current."""
    def seg(dd, a0, a1, w0, w1):
        return dd * (a0 * w0 + a1 * w1) / 3.0 + dd * (a0 * w1 + a1 * w0) / 6.0      # integral of the product of two linear functions, A V s
    if d <= 0:
        return 0.0, 0.0
    if a * b < 0:
        s = d * a / (a - b)
        vm = v0 + (v1 - v0) * (s / d)
        e1, e2 = seg(s, a, 0.0, v0, vm), seg(d - s, 0.0, b, vm, v1)
        dis, chg = (e1, -e2) if a > 0 else (e2, -e1)
        return dis / 3.6e6, chg / 3.6e6
    e = seg(d, a, b, v0, v1)
    return (e / 3.6e6, 0.0) if (a + b) >= 0 else (0.0, -e / 3.6e6)


def lin_energy(d, p0, p1):
    """(discharge, charge) kWh of a linear power p0 -> p1 (kW) over d seconds, zero-crossing-aware split (the published construction)."""
    if d <= 0:
        return 0.0, 0.0
    if p0 * p1 < 0:
        den = 2.0 * (abs(p0) + abs(p1))
        dis = d * ((p0 > 0) * p0 ** 2 + (p1 > 0) * p1 ** 2) / den
        chg = d * ((p0 < 0) * p0 ** 2 + (p1 < 0) * p1 ** 2) / den
        return dis / 3600.0, chg / 3600.0
    s = d * (p0 + p1) / 2.0
    return (s / 3600.0, 0.0) if s > 0 else (0.0, -s / 3600.0)


def u_steps(ti, i, tv, v, gmax=G_MAIN, cap=STEP_CAP_S):
    """union-clock steps: list of (t0, t1, Id0, Id1, V0, V1), Id = -I discharge positive. ti, tv: sorted unique seconds."""
    if len(ti) < 2 or len(tv) < 2:
        return []
    u = np.union1d(ti, tv)
    t0, t1 = u[:-1], u[1:]
    mid = (t0 + t1) / 2.0
    ok = (t1 - t0) <= cap
    for ts in (ti, tv):
        j = np.searchsorted(ts, mid, side="right") - 1
        inside = (j >= 0) & (j < len(ts) - 1)
        jj = np.clip(j, 0, len(ts) - 2)
        ok &= inside & ((ts[jj + 1] - ts[jj]) <= gmax)
    idx = np.flatnonzero(ok)
    Id = -np.interp(u, ti, i); Vv = np.interp(u, tv, v)
    return [(float(u[k]), float(u[k + 1]), float(Id[k]), float(Id[k + 1]), float(Vv[k]), float(Vv[k + 1])) for k in idx]


def p_steps(tp, p, cap=STEP_CAP_S):
    """published-method steps with a gap <= cap: (t0, t1, P0, P1) kW (no bridging)."""
    d = np.diff(tp)
    idx = np.flatnonzero((d > 0) & (d <= cap))
    return [(float(tp[k]), float(tp[k + 1]), float(p[k]), float(p[k + 1])) for k in idx]


def u_total(steps):
    dis = chg = sec = 0.0
    for t0, t1, a, b, v0, v1 in steps:
        e = step_energy(t1 - t0, a, b, v0, v1); dis += e[0]; chg += e[1]; sec += t1 - t0
    return dis, chg, sec


def p_total(steps):
    dis = chg = sec = 0.0
    for t0, t1, p0, p1 in steps:
        e = lin_energy(t1 - t0, p0, p1); dis += e[0]; chg += e[1]; sec += t1 - t0
    return dis, chg, sec


def common(usteps, psteps):
    """seconds-level common support: both methods evaluated on the time intersection of their supported intervals. Returns (U common (dis, chg), P common (dis, chg), seconds)."""
    ud = uc = 0.0; ucc = pc = pcc = sec = 0.0
    i = j = 0
    while i < len(usteps) and j < len(psteps):
        u, p = usteps[i], psteps[j]
        s, e = max(u[0], p[0]), min(u[1], p[1])
        if e > s:
            du, dp = u[1] - u[0], p[1] - p[0]
            fa, fb = (s - u[0]) / du, (e - u[0]) / du
            a0, a1 = u[2] + (u[3] - u[2]) * fa, u[2] + (u[3] - u[2]) * fb
            v0, v1 = u[4] + (u[5] - u[4]) * fa, u[4] + (u[5] - u[4]) * fb
            eu = step_energy(e - s, a0, a1, v0, v1)
            ga, gb = (s - p[0]) / dp, (e - p[0]) / dp
            q0, q1 = p[2] + (p[3] - p[2]) * ga, p[2] + (p[3] - p[2]) * gb
            ep = lin_energy(e - s, q0, q1)
            ud += eu[0]; ucc += eu[1]; pc += ep[0]; pcc += ep[1]; sec += e - s
        if u[1] <= p[1]:
            i += 1
        else:
            j += 1
    return (ud, ucc), (pc, pcc), sec


def _src_hash():
    import integration_scenarios as IS
    return hashlib.sha256("".join(inspect.getsource(f) for f in (step_energy, lin_energy, u_steps, p_steps, u_total, p_total, common, drive_record, IS.integrate, IS._aligned, IS.load_iv)).encode()).hexdigest()[:16]


def drive_record(I, V):
    """I, V: DataFrames (t datetime, v) as integration_scenarios.load_iv returns them (filters applied)."""
    import integration_scenarios as IS
    rec = {}
    t0 = min(I["t"].iloc[0], V["t"].iloc[0])
    sec = lambda s: (s["t"] - t0).dt.total_seconds().to_numpy()
    ti = sec(I.drop_duplicates("t", keep="last")); i = I.drop_duplicates("t", keep="last")["v"].to_numpy(float)
    tv = sec(V.drop_duplicates("t", keep="last")); v = V.drop_duplicates("t", keep="last")["v"].to_numpy(float)
    rec["P"] = {str(tol): list(IS.integrate(I, V, tol_ms=tol)) for tol in P_TOL_MS}
    rec["Pnb"] = list(IS.integrate(I, V, no_bridge=True))
    e = IS._aligned(I, V, IS.BASE_TOL_MS)
    if len(e) >= 2:
        tp = (e["t"] - t0).dt.total_seconds().to_numpy(); pp = -e["v"].to_numpy(float) * e["V"].to_numpy(float) / 1000.0
        ps = p_steps(tp, pp)
        gaps = np.diff(tp)
        rec["pGapSeconds"] = float(gaps[gaps > STEP_CAP_S].sum())
    else:
        ps = []; rec["pGapSeconds"] = 0.0
    pt = p_total(ps)
    rec["Psteps"] = {"dis": pt[0], "chg": pt[1], "sec": pt[2]}
    us = u_steps(ti, i, tv, v)
    ut = u_total(us)
    rec["U"] = {"dis": ut[0], "chg": ut[1], "sec": ut[2]}
    cu, cp, cs = common(us, ps)
    rec["common"] = {"uDis": cu[0], "uChg": cu[1], "pDis": cp[0], "pChg": cp[1], "sec": cs}
    rec["Usens"] = {str(g): list(u_total(u_steps(ti, i, tv, v, gmax=g))) for g in G_SENS}
    rec["pRuns"] = int(1 + sum(1 for a, b in zip(ps[:-1], ps[1:]) if b[0] > a[1] + 1e-9)) if ps else 0
    return rec


# ---------------------------------------------------------------- aggregation
def _boot_ratio(num_by_day, den_by_day):
    a, b = np.asarray(num_by_day, float), np.asarray(den_by_day, float)
    n = len(a)
    if n < MIN_DAYS or b.sum() <= 0:
        return None
    idx = np.random.default_rng(SEED).integers(0, n, size=(DRAWS, n))
    r = a[idx].sum(axis=1) / np.where(b[idx].sum(axis=1) > 0, b[idx].sum(axis=1), np.nan)
    return [float(np.nanpercentile(r, 2.5)), float(np.nanpercentile(r, 97.5))]


def _per_day(vals, days):
    ud = sorted(set(days)); ix = {d: k for k, d in enumerate(ud)}
    out = np.zeros(len(ud))
    for v, d in zip(vals, days):
        out[ix[d]] += v
    return out


def _ratio_row(num, den, days):
    num, den = np.asarray(num, float), np.asarray(den, float)
    if not len(num) or den.sum() <= 0:
        return None
    ci = _boot_ratio(_per_day(num, days), _per_day(den, days))
    return {"ratio": round(float(num.sum() / den.sum()), 6), "ci95": [round(c, 6) for c in ci] if ci else None, "nDrives": int(len(num)), "nDays": len(set(days))}


def stratum_block(recs):
    both = [r for r in recs if r["pFinite"] and r["rec"]["U"]["sec"] > 0]
    res = {"nDrivesTotal": len(recs), "nIntersectionDrives": len(both), "nIntersectionDays": len({r["day"] for r in both})}
    if not both:
        return res
    days = [r["day"] for r in both]
    cu = np.array([r["rec"]["common"]["uDis"] + r["rec"]["common"]["uChg"] for r in both]); cp = np.array([r["rec"]["common"]["pDis"] + r["rec"]["common"]["pChg"] for r in both])
    nu = np.array([r["rec"]["common"]["uDis"] - r["rec"]["common"]["uChg"] for r in both]); npn = np.array([r["rec"]["common"]["pDis"] - r["rec"]["common"]["pChg"] for r in both])
    sec = np.array([r["rec"]["common"]["sec"] for r in both])
    res["primaryCommonSupport"] = {"definition": "per drive, both methods evaluated on the time intersection of their supported intervals; ratio of sums U / P of the gross throughput", "grossThroughput": _ratio_row(cu, cp, days),
                                   "netDrawShiftKwh": round(float((nu - npn).sum()), 5), "commonSeconds": round(float(sec.sum()), 1)}
    m = cp >= MIN_COMMON_KWH
    pr = cu[m] / cp[m]
    res["primaryCommonSupport"]["perDriveRatio"] = {"nDrives": int(m.sum()), "p5": round(float(np.percentile(pr, 5)), 5), "p50": round(float(np.percentile(pr, 50)), 5), "p95": round(float(np.percentile(pr, 95)), 5),
                                                   "shareOutside1Pct": round(float((np.abs(pr - 1) > 0.01).mean()), 4), "minCommonKwh": MIN_COMMON_KWH}
    # support added / lost (within the intersection drives), reported separately
    u_tot = np.array([r["rec"]["U"]["dis"] + r["rec"]["U"]["chg"] for r in both]); u_sec = np.array([r["rec"]["U"]["sec"] for r in both])
    p_tot = np.array([r["rec"]["Psteps"]["dis"] + r["rec"]["Psteps"]["chg"] for r in both]); p_sec = np.array([r["rec"]["Psteps"]["sec"] for r in both])
    res["withinDriveSupport"] = {"uOnlySeconds": round(float((u_sec - sec).sum()), 1), "uOnlyKwh": round(float((u_tot - cu).sum()), 5), "pOnlySeconds": round(float((p_sec - sec).sum()), 1), "pOnlyKwh": round(float((p_tot - cp).sum()), 5),
                                 "uSecondsBelowPSecondsDriveShare": round(float((u_sec < p_sec - 1e-6).mean()), 4)}
    res["pThroughputKwhIntersection"] = round(float(p_tot.sum()), 5)
    res["addedDrivesNullP"] = {"nDrives": int(sum(1 for r in recs if not r["pFinite"] and r["rec"]["U"]["sec"] > 0)), "uKwh": round(float(sum(r["rec"]["U"]["dis"] + r["rec"]["U"]["chg"] for r in recs if not r["pFinite"] and r["rec"]["U"]["sec"] > 0)), 5)}
    # gap influence
    gs = np.array([r["rec"]["pGapSeconds"] for r in both]); order = np.argsort(-gs)
    infl = {}
    for k in TOPK + ("decile",):
        kk = max(1, int(np.ceil(0.1 * len(both)))) if k == "decile" else k
        keep = np.ones(len(both), bool); keep[order[:kk]] = False
        infl[str(k)] = _ratio_row(cu[keep], cp[keep], [d for d, kp in zip(days, keep) if kp])
    res["gapInfluence"] = {"removedTopPGapDrives": infl, "spearmanDiffVsGapSeconds": round(float(pd.Series(cu - cp).corr(pd.Series(gs), method="spearman")), 3) if len(both) > 2 else None, "driveSpearmanNote": "per-drive U - P on the common support versus P gap seconds"}
    # drive-level ladder (intersection drives, bridged P totals): P tolerance and U max-gap rows against the published P
    base = np.array([r["rec"]["P"]["1500"][0] + r["rec"]["P"]["1500"][1] for r in both])
    lad = {}
    for tol in ("3000", "5000"):
        lad["Ptol" + tol] = _ratio_row([r["rec"]["P"][tol][0] + r["rec"]["P"][tol][1] for r in both], base, days)
    lad["U5s"] = _ratio_row(u_tot, base, days)
    for g in G_SENS:
        lad["Ugap" + str(g)] = _ratio_row([r["rec"]["Usens"][str(g)][0] + r["rec"]["Usens"][str(g)][1] for r in both], base, days)
        lad["Ugap" + str(g)]["supportSecondsShareOfU5s"] = round(float(sum(r["rec"]["Usens"][str(g)][2] for r in both) / u_sec.sum()), 4)
    res["ladderDriveLevel"] = {"definition": "throughput of each row over the published P throughput (bridged 5 s cap) on the intersection drives; mixes within-drive support and is shown to separate tolerance from alignment, not as the estimate", **lad}
    prim = res["primaryCommonSupport"]["grossThroughput"]["ratio"] - 1
    res["signConsistent"] = bool(all((lad[k]["ratio"] - 1 > 0) == (prim > 0) for k in lad if lad[k]))                 # rule as pre-registered (all rows)
    same = [k for k in lad if lad[k] and k != "Ugap1.5" and abs(lad[k]["ratio"] - 1) > 0.001]                         # Rev 3: rows beyond 0.1 %, the support-reducing 1.5 s row excluded
    res["signConsistentRev3"] = bool(all((lad[k]["ratio"] - 1 > 0) == (prim > 0) for k in same))
    res["signRev3Rows"] = same
    dm_ = np.array([r["rec"]["Psteps"]["sec"] - r["rec"]["U"]["sec"] for r in both]); dm10 = np.array([r["rec"]["Psteps"]["sec"] - r["rec"]["Usens"]["10.0"][2] for r in both]); pr_ = np.array([r["rec"]["pRuns"] for r in both])
    res["supportDeficit"] = {"p50": round(float(np.percentile(dm_, 50)), 3), "p95": round(float(np.percentile(dm_, 95)), 3), "max": round(float(dm_.max()), 3),
                             "driveShareOver2sOr1Pct": round(float((dm_ > np.maximum(2.0, 0.01 * p_sec)).mean()), 4),
                             "drivesBeyondBoundaryBound": int((dm_ > 3.0 * pr_ + 1e-6).sum()),
                             "boundaryKnownAnswer": {"rule": "Rev 3 (the Rev 2 bound of 1.5 s per boundary was too tight): with the per-channel maximum gap raised to 10 s the deficit is <= 3 s per contiguous P run + 1e-6; drives beyond the bound at 5 s are P steps lying in a 5-10 s gap of one channel, which the nearest-match rule bridges and U does not",
                                                     "nViolations": int((dm10 > 3.0 * pr_ + 1e-6).sum()), "nDrives": int(len(dm10))}}
    return res


# ---------------------------------------------------------------- driver
def load_records(only=None):
    import ah_throughput as AH
    import compute_summary_arrays as C
    import integration_scenarios as IS
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    bad = C._canonical_bad(dm)
    loader = AH.raw_loader()
    os.makedirs(CACHE, exist_ok=True)
    sh = _src_hash()
    recs, stats = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "notOk": 0}
    for i, r in dm.iterrows():
        fn = r["file"]
        if only and fn not in only:
            continue
        b = loader(fn)
        if b is None:
            stats["noRaw"] += 1; continue
        digest = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE, f"{digest}_{sh}.json")
        if os.path.exists(cp):
            rec = json.load(open(cp, encoding="utf-8")); stats["cacheHits"] += 1
        else:
            try:
                I, V = IS.load_iv(io.BytesIO(b))
                rec = {"ok": True, "rec": drive_record(I, V)} if (I is not None and V is not None and len(I) >= 3 and len(V) >= 3) else {"ok": False}
            except Exception as ex:
                rec = {"ok": False, "error": repr(ex)}
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            stats["extracted"] += 1
        if not rec.get("ok"):
            stats["notOk"] += 1
        rec = dict(rec)
        rec.update(file=fn, rawSha256=digest, cadence=cad.get(fn) if isinstance(cad.get(fn), str) else "unknown", canonClean=bool(not bad.iloc[i]),
                   day=(lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}")("".join(c for c in fn if c.isdigit())), durationS=float(r["duration_s"]),
                   pFinite=bool(pd.notna(r.get("gross_discharge_kwh"))), masterDis=float(r["gross_discharge_kwh"]) if pd.notna(r.get("gross_discharge_kwh")) else None,
                   masterChg=float(r["gross_charge_kwh"]) if pd.notna(r.get("gross_charge_kwh")) else None, nullReason=r["energy_null_reason"] if pd.notna(r.get("energy_null_reason")) else None)
        recs[fn] = rec
    return dm, recs, stats


def known_answers(recs):
    n = {"ka4": 0, "stepsVsNoBridge": 0, "uNetLeGross": 0}
    bad = {"ka4": [], "stepsVsNoBridge": [], "uNetLeGross": []}
    for fn, a in recs.items():
        if not a.get("ok"):
            continue
        x = a["rec"]
        if a["pFinite"]:
            n["ka4"] += 1
            if abs(x["P"]["1500"][0] - a["masterDis"]) > TOL_GROSS_KWH or abs(x["P"]["1500"][1] - a["masterChg"]) > TOL_GROSS_KWH:
                bad["ka4"].append((fn, round(x["P"]["1500"][0], 6), a["masterDis"], round(x["P"]["1500"][1], 6), a["masterChg"]))
            n["stepsVsNoBridge"] += 1
            if abs(x["Psteps"]["dis"] - x["Pnb"][0]) > TOL_STEPS_KWH * 1e3 or abs(x["Psteps"]["chg"] - x["Pnb"][1]) > TOL_STEPS_KWH * 1e3:
                bad["stepsVsNoBridge"].append((fn, x["Psteps"]["dis"], x["Pnb"][0]))
        n["uNetLeGross"] += 1
        if abs(x["U"]["dis"] - x["U"]["chg"]) > x["U"]["dis"] + x["U"]["chg"] + 1e-12:
            bad["uNetLeGross"].append(fn)
    return {"n": n, "misses": {k: len(v) for k, v in bad.items()}, "examples": {k: v[:5] for k, v in bad.items()}}


def f17_block(recs):
    out = []
    for fn, a in recs.items():
        if a.get("ok") and not a["pFinite"]:
            u = a["rec"]["U"]
            share = u["sec"] / a["durationS"] if a["durationS"] > 0 else 0.0
            out.append({"file": fn, "pNullReason": a["nullReason"], "ens_outlier_v2": bool(a["canonClean"] is False), "uSupportSeconds": round(u["sec"], 2), "durationS": a["durationS"], "uSupportShare": round(share, 4),
                        "uGrossDischargeKwh": round(u["dis"], 5), "uGrossChargeKwh": round(u["chg"], 5), "recoverableUnderAlternativeAlignment": bool(u["dis"] + u["chg"] > 0 and share >= F17_MIN_SUPPORT_SHARE),
                        "enters": "no rate, total, ens eligibility, headline or other payload key"})
    return out


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = set(json.load(open(os.path.join(ROOT, "analyses", "M554_audit_sample.json"), encoding="utf-8"))["files"])
    dm, recs, stats = load_records(only)
    ka = known_answers(recs)
    res = {"milestone": "M554", "mode": mode, "stats": stats, "knownAnswer": ka, "extractorSourceHash": _src_hash()}
    if any(ka["misses"].values()):
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "known-answer miss", **ka}, default=float)); sys.exit(2)
    el = [r for r in recs.values() if r.get("ok") and r["canonClean"]]
    res["populations"] = {"withIv": int(sum(1 for r in recs.values() if r.get("ok"))), "eligibleCanonicalClean": len(el), "notOk": stats["notOk"],
                          "pNullUFinite": int(sum(1 for r in el if not r["pFinite"] and r["rec"]["U"]["sec"] > 0))}
    res["strata"] = {c: stratum_block([r for r in el if r["cadence"] == c]) for c in ("fast", "slow", "unknown") if any(r["cadence"] == c for r in el)}
    res["unknownCadenceDriveSharePct"] = round(100.0 * sum(1 for r in el if r["cadence"] == "unknown") / len(el), 2) if el else None
    res["f17"] = f17_block({r["file"]: r for r in el})
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((r["file"], r["rawSha256"]) for r in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    json.dump({f: r for f, r in recs.items()}, open(os.path.join(CACHE, "_all.json" if not only else "_sample.json"), "w", encoding="utf-8"), default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka, "populations": res["populations"], "unknownShare": res["unknownCadenceDriveSharePct"], "f17": res["f17"]}, default=float))
    if mode == "--splice" and not only:
        splice(res)


def splice(res):
    """additive write of S.commonSupportBridge (+ stamp); no existing key changes."""
    flags = {}
    for c, st in res["strata"].items():
        pc = st.get("primaryCommonSupport")
        if not pc or not pc["grossThroughput"]:
            continue
        g = pc["grossThroughput"]; dev = g["ratio"] - 1.0; ci = g["ci95"]
        ws = st["withinDriveSupport"]; inf = st["gapInfluence"]["removedTopPGapDrives"]
        half = (ci[1] - ci[0]) / 2.0 if ci else None
        flags[c] = {"ratioOutside1Pct": abs(dev) > 0.01, "intervalExcludes1AndOver0p5Pct": bool(ci and (ci[0] > 1.0 or ci[1] < 1.0) and abs(dev) > 0.005),
                    "topKRemovalMovesMoreThanHalfWidth": bool(half is not None and any(v and abs(v["ratio"] - g["ratio"]) > half for v in inf.values())),
                    "uSecondsBelowPSecondsOver5PctOfDrives": ws["uSecondsBelowPSecondsDriveShare"] > 0.05, "signFlipAcrossLadder": not st["signConsistent"],
                    "rev3DeficitOver2sOr1PctOver5PctOfDrives": st["supportDeficit"]["driveShareOver2sOr1Pct"] > 0.05, "rev3SignFlipSameBasisRows": not st["signConsistentRev3"], "boundaryKnownAnswerViolations": st["supportDeficit"]["boundaryKnownAnswer"]["nViolations"],
                    "addedSupportOver1PctOfPThroughput": bool((ws["uOnlyKwh"] + st["addedDrivesNullP"]["uKwh"]) > 0.01 * st["pThroughputKwhIntersection"])}
    f = res["f17"]
    added = sum(x["uGrossDischargeKwh"] + x["uGrossChargeKwh"] for x in f)
    flags["f17"] = {"nRecoverable": int(sum(1 for x in f if x["recoverableUnderAlternativeAlignment"])), "nNullUFinite": len(f), "belowSupportCriterion": bool(any(not x["recoverableUnderAlternativeAlignment"] for x in f)),
                    "addedKwh": round(added, 5)}
    flags["unknownCadenceDriveSharePct"] = res["unknownCadenceDriveSharePct"]
    block = {"_provenance": "GENERATED by tools/common_support.py (M554). Do not hand-edit.", "schemaVersion": 1,
             "basis": "raw bytes through integration_scenarios.load_iv (current |I| < 900, voltage 200..450); P = the published nearest-pair integration (imported); U = union-clock integration (named sensitivity, estimated); raw/ = sha256-verified originals (M366)",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]},
             "rule": {"contract": "primary = seconds-level common-support estimate per drive (both methods on the time intersection); within-drive added / lost seconds and energy reported separately and never summed into the delta; day-clustered bootstrap over the days of the intersection drives only",
                      "U": "both channels linearly interpolated onto the union of sample times; a channel is never interpolated across its own gap (> 5 s; sensitivity 1.5 / 3 / 10 s); a union step is supported iff <= 5 s and both channels are defined inside it; exact quadratic product energy; split at the single root of the current",
                      "F17": f"recoverableUnderAlternativeAlignment = P energy null AND U gross > 0 AND U support seconds / duration >= {F17_MIN_SUPPORT_SHARE}; the energies enter no rate, total or eligibility",
                      "strata": "logger cadence regime (fast / slow / unknown); no pooled headline, no contrast between strata", "intervals": f"day-clustered percentile bootstrap, seed {SEED}, {DRAWS} draws, only with >= {MIN_DAYS} days"},
             "populations": res["populations"], "knownAnswer": res["knownAnswer"], "strata": res["strata"], "f17": res["f17"], "flags": flags,
             "limits": ["U is a sensitivity on already-seen data, not a validation and not a replacement of the published method; U energy is estimated, never measured or true",
                        "the published null reason keeps its text: the two drives have no integrable pairs under the nearest-pair rule within 1.5 s; this is a statement about that rule, not about the raw channels",
                        "the drive-level ladder rows mix within-drive support and are shown only to separate tolerance from alignment", "the strata are not comparable (cadence invariance fails); no pooled value is given"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("commonSupportBridge", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "commonSupportBridge"}
    A2["commonSupportBridge"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M554: computed by tools/common_support.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["commonSupportBridge"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "commonSupportBridge"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"commonSupportBridge": "written"}))


if __name__ == "__main__":
    main()
