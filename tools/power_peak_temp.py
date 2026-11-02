#!/usr/bin/env python3
"""M550 (spec analyses/M550_spec.md Rev 2): temperature and freshness at the peak-charge-POWER timestamp (audit 2026-10-29 F05) and timing age for the two peak pairs (N07, partial).
The risk map's kW view plotted the drive's peak charge power against the temperature at the peak charge-CURRENT moment (a different moment). This read-only extractor works on the raw bytes with the SAME helpers as the master
(D._prep_bytes, D._series, D._asof, V_ALIGN_TOL, ENG_ALIGN_TOL; I filter |I| < 900, voltage band 200..450 as in compute_drive_summary_v6) and stores, per drive: the timestamp of the minimum of P = Id * V / 1000 (first sample in
(t, row) order; a RECONSTRUCTED I x V sample), T1 at that sample (nearest native T1 sample within 3 s, no interpolation) with its signed age and class, the same for the master's current-peak pairing (replicated EXACTLY, including the
channel gates), the V age, the gap between the two moments, 10 s / 30 s sensitivities. Known answers (STOP on a miss): rebuilt peak_charge_kw and peak_I_charge equal the master columns; T1 at the replicated current-peak sample equals
master T1_at_peak_Crate on every non-fallback drive. Per-drive records cached by the raw sha256 and the extractor source hash (powerpeak_cache/, git-ignored); aggregation never rereads raw.
Modes: --check (writes analyses/M550_check.json) | --splice (check + additive write of S.powerPeakTemperature). Usage: python tools/power_peak_temp.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M550_check.json")
CACHE = os.path.join(ROOT, "powerpeak_cache")
COTIMED_S, NEARBY_S, LATE_S = 1.0, 3.0, 10.0
SENS_S = (10.0, 30.0)
SEED, DRAWS, MIN_DAYS = 42, 4000, 5


def _near(t1, t_peak, tol_s):
    """nearest native T1 sample to t_peak within tol_s (inclusive), no interpolation. Returns (value, signed age s = t1 sample - peak) or (None, None)."""
    if t1 is None or not len(t1):
        return None, None
    tt = t1["t"].values.astype("datetime64[ns]").astype("int64")
    x = pd.Timestamp(t_peak).to_datetime64().astype("datetime64[ns]").astype("int64")
    j = int(np.searchsorted(tt, x))
    cands = [k for k in (j - 1, j) if 0 <= k < len(tt)]
    k = min(cands, key=lambda c: abs(tt[c] - x))      # a tie in distance takes the earlier sample (merge_asof 'nearest' convention checked by the known answer)
    age = (tt[k] - x) / 1e9
    return (float(t1["v"].iloc[k]), float(age)) if abs(age) <= tol_s else (None, float(age))


def _cls(age):
    if age is None:
        return "none"
    a = abs(age)
    return "cotimed" if a <= COTIMED_S else ("nearby" if a <= NEARBY_S else ("late" if a <= LATE_S else "none"))


def extract_frames(df, t):
    """the per-drive record from a prepared frame (df, t) as returned by D._prep_bytes; mirrors _v5_analyze_bytes lines for e, eng_on, tq, reg, egc, dual and the T1 pairing."""
    import compute_drive_summary_v6 as D
    I = D._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    V = D._series(df, t, "V", lo=200, hi=450)
    eng = D._series(df, t, "eng_rpm", lo=0)
    rec = {"ok": False}
    if I is None or V is None or len(I) <= 2:
        return rec
    e = D._asof(I.copy(), V, "V", D.V_ALIGN_TOL).dropna(subset=["V"])
    e = D._asof(e, eng, "eng_rpm", D.ENG_ALIGN_TOL)
    if len(e) < 2:
        return rec
    e["Id"] = -e["v"]
    e["P"] = e["Id"] * e["V"] / 1000.0
    # V sample age at each e row (same asof matching, the V time carried as a value column)
    Vt = V.copy(); Vt["tv"] = Vt["t"]
    vm = pd.merge_asof(I.copy(), Vt.rename(columns={"v": "V"}), on="t", direction="nearest", tolerance=pd.Timedelta(D.V_ALIGN_TOL))
    vm = vm.dropna(subset=["V"]).reset_index(drop=True)
    e = e.reset_index(drop=True)
    assert len(vm) == len(e), "V age frame disagrees with the pairing frame"
    vage = (vm["tv"] - vm["t"]).dt.total_seconds().to_numpy()
    t1 = D._series(df, t, "T1", lo=-40, hi=90)
    t1s = t1.sort_values("t").reset_index(drop=True) if t1 is not None else None
    # peak charge POWER sample: first minimum of P in (t, row) order
    iP = int(e["P"].values.argmin())
    tP = e["t"].iloc[iP]
    minP = float(e["P"].iloc[iP])
    ties = np.flatnonzero(e["P"].values == minP)
    rec.update(ok=True, nE=int(len(e)), peakKwRebuilt=round(float(e["P"].min()), 1), peakIRebuilt=round(float(e["Id"].min()), 1),
               tPeakKw=str(tP), nTiesAtMinP=int(len(ties)), vAgeKwS=float(vage[iP]))
    v_, a_ = _near(t1s, tP, NEARBY_S)
    rec.update(T1AtPeakKw=v_, ageKwS=a_)
    if v_ is None:
        a_any = _near(t1s, tP, 1e9)[1] if t1s is not None else None
        rec["ageKwS"] = a_any
    for s in SENS_S:
        vv, aa = _near(t1s, tP, s)
        rec[f"T1AtPeakKw_{int(s)}s"], rec[f"ageKw_{int(s)}s"] = vv, aa
    if len(ties) > 1 and t1s is not None:
        vals = [x for x in (_near(t1s, e["t"].iloc[int(k)], NEARBY_S)[0] for k in ties) if x is not None]
        rec["t1TiedRange"] = [min(vals), max(vals)] if vals else None
    # the master's current-peak pairing, replicated (eng_on, tq branch, reg / egc / dual candidates)
    eng_on = e["eng_rpm"].fillna(0) > 400
    reg = e[(~eng_on) & (e["Id"] < -30)]
    egc = e[eng_on & (e["Id"] < -50)]
    tq_s = D._series(df, t, "target_torque")
    cands = []
    if len(reg):
        cands.append(("reg", reg, reg["Id"].idxmin()))
    if len(egc):
        cands.append(("egc", egc, egc["Id"].idxmin()))
    if tq_s is not None:
        e2 = D._asof(e.copy(), tq_s, "tq", "1500ms")
        m_dual = eng_on & (e2["tq"].fillna(0) < -15)
        dual = e2[m_dual & (e2["Id"] < -10)]
        if len(dual):
            cands.append(("dual", dual, dual["Id"].idxmin()))
    rec["T1DriveMax"] = round(float(t1s["v"].max()), 1) if t1s is not None else None
    if cands:
        ch, fr, ix = min(cands, key=lambda c: c[1].loc[c[2], "Id"])
        tI = fr.loc[ix, "t"]
        vI, aI = _near(t1s, tI, D.ENG_ALIGN_TOL and 3.0)
        rec.update(channelI=ch, tPeakI=str(tI), T1AtPeakI=None if vI is None else round(vI, 1), ageIS=aI, vAgeIS=float(vage[int(e.index.get_loc(ix))]),
                   gapS=float((tP - tI).total_seconds()))
        v10, a10 = _near(t1s, tI, LATE_S)          # M567: the late tier (3-10 s) for the current pair, same rule as the power pair
        rec.update(T1AtPeakI_10s=None if v10 is None else round(v10, 1), ageI_any=a10 if v10 is not None else (_near(t1s, tI, 1e9)[1] if t1s is not None else None))
    # diagnostic: the global minimum-Id sample (not the master's pairing)
    iG = int(e["Id"].values.argmin())
    vG, aG = _near(t1s, e["t"].iloc[iG], NEARBY_S)
    rec.update(T1AtGlobalMinId=None if vG is None else round(vG, 1))
    return rec


def extract(csv_bytes):
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(csv_bytes)
    return extract_frames(df, t)


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (_near, _cls, extract_frames, extract)).encode()).hexdigest()[:16]


def _boot_median(vals, days):
    ud = sorted(set(days)); by = {u: [v for v, d in zip(vals, days) if d == u] for u in ud}
    pt = float(np.median(vals)) if vals else None
    if pt is None or len(ud) < MIN_DAYS:
        return {"median": None if pt is None else round(pt, 3), "ci95": None, "nDrives": len(vals), "nDays": len(ud)}
    rng = np.random.default_rng(SEED); idx = rng.integers(0, len(ud), size=(DRAWS, len(ud)))
    bs = np.array([np.median(np.concatenate([by[ud[j]] for j in row])) for row in idx])
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return {"median": round(pt, 3), "ci95": [round(float(lo), 3), round(float(hi), 3)], "nDrives": len(vals), "nDays": len(ud)}


def _q(v, ps=(50, 90, 99)):
    v = np.asarray([x for x in v if x is not None], float)
    return {f"p{p}": round(float(np.percentile(v, p)), 3) for p in ps} if v.size else None


def load_records(only=None):
    import ah_throughput as AH
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    loader = AH.raw_loader()
    os.makedirs(CACHE, exist_ok=True)
    sh = _src_hash()
    rawdir = next((d for d in (os.environ.get("XT_RAW_DIR"), os.path.join(ROOT, "raw")) if d and os.path.isdir(d)), None)
    rawmap = {re.sub(r"\D", "", f): os.path.join(rawdir, f) for f in os.listdir(rawdir) if f.lower().endswith(".csv")} if rawdir else {}
    recs, stats = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "notOk": 0}
    for _, r in dm.iterrows():
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
            rec = extract(b)
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            stats["extracted"] += 1
        if not rec.get("ok"):
            stats["notOk"] += 1
        rec = dict(rec)
        rec.update(file=fn, rawSha256=digest, cadence=cad.get(fn) if isinstance(cad.get(fn), str) else "unknown",
                   day=(lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}")("".join(c for c in fn if c.isdigit())))
        recs[fn] = rec
    return dm, recs, stats


def known_answers(dm, recs):
    """KA2 / KA3 (STOP on a miss)."""
    bad = {"peakKw": [], "peakI": [], "t1PeakI": []}
    n = {"peakKw": 0, "peakI": 0, "t1PeakI": 0, "t1PeakIFallbackSkipped": 0}
    for _, r in dm.iterrows():
        a = recs.get(r["file"])
        if a is None or not a.get("ok"):
            continue
        if pd.notna(r.get("peak_charge_kw")):
            n["peakKw"] += 1
            if a["peakKwRebuilt"] != round(float(r["peak_charge_kw"]), 1):
                bad["peakKw"].append((r["file"], a["peakKwRebuilt"], float(r["peak_charge_kw"])))
        if pd.notna(r.get("peak_I_charge")):
            n["peakI"] += 1
            if a["peakIRebuilt"] != round(float(r["peak_I_charge"]), 1):
                bad["peakI"].append((r["file"], a["peakIRebuilt"], float(r["peak_I_charge"])))
        if pd.notna(r.get("T1_at_peak_Crate")):
            if bool(r.get("T1_at_peak_Crate_isFallback")):
                n["t1PeakIFallbackSkipped"] += 1
                continue
            n["t1PeakI"] += 1
            if a.get("T1AtPeakI") is None or a["T1AtPeakI"] != round(float(r["T1_at_peak_Crate"]), 1):
                bad["t1PeakI"].append((r["file"], a.get("T1AtPeakI"), float(r["T1_at_peak_Crate"])))
    return {"n": n, "misses": {k: len(v) for k, v in bad.items()}, "examples": {k: v[:5] for k, v in bad.items()}}


def build(dm, recs, A):
    ak = A.get("cRatePointsAK") or []
    akfiles = [p[5] for p in ak]
    assert len(set(akfiles)) == len(akfiles), "file is not unique in cRatePointsAK"
    ok = {f: r for f, r in recs.items() if r.get("ok")}
    def _kx(r):
        c = _cls(r.get("ageKwS")) if r else "none"
        v = (r.get("T1AtPeakKw") if c in ("cotimed", "nearby") else (r.get("T1AtPeakKw_10s") if c == "late" else None)) if r else None
        return {"x": v, "tier": c if v is not None else "none", "ageS": None if not r or r.get("ageKwS") is None else round(r["ageKwS"], 3)}
    kw_x = {f: _kx(ok.get(f)) for f in akfiles}
    pop = [ok[f] for f in akfiles if f in ok]
    cls_kw = [_cls(r.get("ageKwS")) for r in pop]
    cls_i = [_cls(r.get("ageIS")) if r.get("T1AtPeakI") is not None else "none" for r in pop]
    cnt = lambda L: {c: int(sum(1 for x in L if x == c)) for c in ("cotimed", "nearby", "late", "none")}
    by_cad = {}
    for c in sorted({r["cadence"] for r in pop}):
        sub = [r for r in pop if r["cadence"] == c]
        by_cad[c] = {"n": len(sub), "noneShareKw": round(sum(1 for r in sub if _cls(r.get("ageKwS")) == "none") / len(sub), 4), "tiersKw": cnt([_cls(r.get("ageKwS")) for r in sub]), "tiersI": cnt([_cls(r.get("ageIS")) if r.get("T1AtPeakI") is not None else "none" for r in sub])}
    shares = [v["noneShareKw"] for v in by_cad.values() if v["n"] >= 20]
    both = [r for r in pop if r.get("T1AtPeakKw") is not None and r.get("T1AtPeakI") is not None and _cls(r.get("ageKwS")) in ("cotimed", "nearby")]
    dT = [r["T1AtPeakKw"] - r["T1AtPeakI"] for r in both]
    late = [r for r in pop if _cls(r.get("ageKwS")) == "late"]
    sens = {"lateTier": {"n": len(late), "bounds": "3 s < |age| <= 10 s", "absDt1VsPeakI": _q([abs(r["T1AtPeakKw_10s"] - r["T1AtPeakI"]) for r in late if r.get("T1AtPeakKw_10s") is not None and r.get("T1AtPeakI") is not None], (50, 90, 99)),
                         "nWithBothValues": int(sum(1 for r in late if r.get("T1AtPeakKw_10s") is not None and r.get("T1AtPeakI") is not None)),
                         "absAgeS": _q([abs(r["ageKwS"]) for r in late if r.get("ageKwS") is not None], (50, 90))},
            "beyond10s": int(sum(1 for r in pop if _cls(r.get("ageKwS")) == "none"))}
    nA = len(pop); nKw = sum(1 for f in akfiles if kw_x[f]["x"] is not None); nKwNear = sum(1 for f in akfiles if kw_x[f]["tier"] in ("cotimed", "nearby"))
    summary = {
        "population": {"akPlotted": len(akfiles), "withExtraction": nA, "canonicalClean": None},
        "classKw": cnt(cls_kw), "classI": cnt(cls_i), "nViewA": nA, "nViewKw": nKw, "nViewKwWithin3s": nKwNear,
        "ageAbsKwS": _q([abs(r["ageKwS"]) for r in pop if r.get("ageKwS") is not None]), "ageAbsIS": _q([abs(r["ageIS"]) for r in pop if r.get("ageIS") is not None]),
        "vAgeKwS": _q([r.get("vAgeKwS") for r in pop]),
        "gapS": _q([abs(r["gapS"]) for r in pop if r.get("gapS") is not None]), "nGapOver3s": int(sum(1 for r in pop if r.get("gapS") is not None and abs(r["gapS"]) > 3.0)),
        "noneShareByCadence": by_cad, "noneShareSpreadPp": (round(100 * (max(shares) - min(shares)), 2) if len(shares) > 1 else None),
        "dT1SignedKwMinusI": _boot_median(dT, [r["day"] for r in both]), "absDt1": _q([abs(x) for x in dT]),
        "sensitivityTolerance": sens, "nTies": int(sum(1 for r in pop if r.get("nTiesAtMinP", 1) > 1)),
        "nChannel": {c: int(sum(1 for r in pop if r.get("channelI") == c)) for c in ("reg", "egc", "dual")},
        "globalMinIdDiagnosticDiffers": int(sum(1 for r in pop if r.get("T1AtPeakI") is not None and r.get("T1AtGlobalMinId") != r.get("T1AtPeakI"))),
    }
    ac_x, ac_sum, checks = _build_ac(dm, ok, A, akfiles)
    summary.update(ac_sum)
    return kw_x, summary, ac_x, checks


def _tier_ac(r):
    """tier and x of the A / C views (M567): the master's current-peak sample, nearest native T1, same tiers as the kW view."""
    if not r or r.get("tPeakI") is None:
        return {"x": None, "tier": "none", "ageS": None}
    c = _cls(r.get("ageI_any"))
    v = r.get("T1AtPeakI") if c in ("cotimed", "nearby") else (r.get("T1AtPeakI_10s") if c == "late" else None)
    return {"x": v, "tier": c if v is not None else "none", "ageS": None if r.get("ageI_any") is None else round(r["ageI_any"], 3)}


def _build_ac(dm, ok, A, akfiles):
    ac_x = {f: _tier_ac(ok.get(f)) for f in akfiles}
    ak = {p[5]: p for p in A["cRatePointsAK"]}
    fb = dm.set_index("file")["T1_at_peak_Crate_isFallback"].to_dict()
    # R3 hard assertion: legacy non-fallback <=> cotimed / nearby, legacy fallback <=> late / none (plotted drives with a recorded flag)
    bad = [(f, fb[f], ac_x[f]["tier"]) for f in akfiles if f in fb and pd.notna(fb[f]) and (bool(fb[f]) == (ac_x[f]["tier"] in ("cotimed", "nearby")))]
    cnt = lambda L: {c: int(sum(1 for x in L if x == c)) for c in ("cotimed", "nearby", "late", "none")}
    cad = {f: ok[f]["cadence"] for f in akfiles if f in ok}
    by_cad = {}
    for c in sorted(set(cad.values())):
        fs = [f for f in akfiles if cad.get(f) == c]
        by_cad[c] = {"n": len(fs), "tiersAC": cnt([ac_x[f]["tier"] for f in fs]), "noneShareAC": round(sum(1 for f in fs if ac_x[f]["tier"] == "none") / len(fs), 4)}
    shares = [v["noneShareAC"] for v in by_cad.values() if v["n"] >= 20]
    moved = {"fallback": [], "nonFallback": []}
    for f in akfiles:
        x, leg = ac_x[f]["x"], ak[f][0]
        if x is None or leg is None:
            continue
        moved["fallback" if (f in fb and pd.notna(fb[f]) and bool(fb[f])) else "nonFallback"].append((x - leg, ok[f]["day"]))
    qm = lambda L: ({"n": len(L), "nDays": len({d for _, d in L}), "signedMedian": round(float(np.median([m for m, _ in L])), 2), "absMedian": round(float(np.median([abs(m) for m, _ in L])), 2),
                     "absP90": round(float(np.percentile([abs(m) for m, _ in L], 90)), 2), "nMoved": int(sum(1 for m, _ in L if abs(m) > 1e-9)), "maxSigned": round(float(max(m for m, _ in L)), 2)} if L else None)
    zones = (A.get("cRateRefLines") or {}).get("zones") or {}
    cold = zones.get("coldBelowC")
    pts = [(ak[f][0], ak[f][1], f) for f in akfiles]
    new3 = [(ac_x[f]["x"], ak[f][1], f) for f in akfiles if ac_x[f]["tier"] in ("cotimed", "nearby")]
    late = [(ac_x[f]["x"], ak[f][1], f) for f in akfiles if ac_x[f]["tier"] == "late"]
    top = max(pts, key=lambda p: p[1]) if pts else None
    cmp = {"coldBelowC": cold,
           "legacy": {"nPoints": len(pts), "nCold": sum(1 for p in pts if cold is not None and p[0] < cold), "minT": min((p[0] for p in pts), default=None)},
           "within3s": {"nPoints": len(new3), "nCold": sum(1 for p in new3 if cold is not None and p[0] < cold), "minT": min((p[0] for p in new3), default=None)},
           "late": {"nPoints": len(late), "nCold": sum(1 for p in late if cold is not None and p[0] < cold)},
           "highestCratePeak": None if not top else {"cRate": top[1], "legacyT": top[0], "tier": ac_x[top[2]]["tier"], "newT": ac_x[top[2]]["x"], "ageS": ac_x[top[2]]["ageS"]}}
    # like-for-like on the same plotted drives (Director, A3 ruling): the within-3 s count alone has a different denominator than the legacy count
    allx = [(ac_x[f]["x"], f) for f in akfiles if ac_x[f]["x"] is not None]
    cmp["likeForLike"] = {"n": len(akfiles), "legacyNCold": cmp["legacy"]["nCold"], "tierRuleNCold": sum(1 for x, f in allx if cold is not None and x < cold),
                          "byCadence": {c: {"n": sum(1 for f in akfiles if cad.get(f) == c), "legacyNCold": sum(1 for f in akfiles if cad.get(f) == c and cold is not None and ak[f][0] < cold),
                                            "within3sNCold": sum(1 for x, f in allx if cad.get(f) == c and ac_x[f]["tier"] in ("cotimed", "nearby") and cold is not None and x < cold),
                                            "lateNCold": sum(1 for x, f in allx if cad.get(f) == c and ac_x[f]["tier"] == "late" and cold is not None and x < cold)} for c in sorted(set(cad.values()))}}
    cmp["coldCountChanged"] = bool(cmp["likeForLike"]["legacyNCold"] != cmp["likeForLike"]["tierRuleNCold"])
    cmp["highestPeakTChanged"] = bool(cmp["highestCratePeak"] and cmp["highestCratePeak"]["legacyT"] != cmp["highestCratePeak"]["newT"])
    summ = {"tiersAC": cnt([ac_x[f]["tier"] for f in akfiles]), "tiersACByCadence": by_cad, "noneShareACSpreadPp": (round(100 * (max(shares) - min(shares)), 2) if len(shares) > 1 else None),
            "noneShareAC": round(sum(1 for f in akfiles if ac_x[f]["tier"] == "none") / len(akfiles), 4) if akfiles else None,
            "acVsLegacy": {"movedFallbackDrives": qm(moved["fallback"]), "movedNonFallbackDrives": qm(moved["nonFallback"]), "coldZoneAndPeak": cmp,
                           "note": "signed move = new x minus legacy x (T1_at_peak_Crate, the drive-maximum T1 for fallback drives)"}}
    return ac_x, summ, bad


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = set(json.load(open(os.path.join(ROOT, "analyses", "M550_audit_sample.json"), encoding="utf-8"))["files"])
    dm, recs, stats = load_records(only)
    A = json.load(open(ARR, encoding="utf-8"))
    ka = known_answers(dm, recs)
    res = {"milestone": "M550", "mode": mode, "stats": stats, "knownAnswer": ka, "extractorSourceHash": _src_hash()}
    if any(ka["misses"].values()):
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "known-answer miss", **ka}, default=float)); sys.exit(2)
    kw_x, summary, ac_x, ac_checks = build(dm, recs, A)
    res.update(summary=summary, nKwViewX=len(kw_x), nAcViewX=len(ac_x), acConsistencyMisses=ac_checks)
    if ac_checks:
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "A / C tier vs legacy fallback flag disagree (R3)", "examples": ac_checks[:5], "n": len(ac_checks)}, default=float)); sys.exit(2)
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((r["file"], r["rawSha256"]) for r in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    json.dump({f: r for f, r in recs.items()}, open(os.path.join(CACHE, "_all.json" if not only else "_sample.json"), "w", encoding="utf-8"), default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka, "summary": summary}, default=float)[:3000])
    if mode == "--splice" and not only:
        splice(res, recs, kw_x, A, ac_x)


def _tod(ts):
    """M567: clock time of day only. The logger exports a clock time without a date and the frame loader attaches the date of the run, so the full timestamp changed with the day the producer ran (a determinism defect of the M550 payload); ages and tiers never depended on it."""
    return None if ts is None else pd.Timestamp(ts).strftime("%H:%M:%S.%f")


def splice(res, recs, kw_x, A, ac_x):
    """additive write of S.powerPeakTemperature (+ stamp); every existing key (cRatePoints, cRatePointsAK, cRateRefLines*, cRateAxes) stays byte-identical."""
    ok = {f: r for f, r in recs.items() if r.get("ok")}
    rows = []
    for f in sorted(ok):
        r = ok[f]
        rows.append([f, _tod(r.get("tPeakKw")), r.get("T1AtPeakKw"), r.get("ageKwS"), _cls(r.get("ageKwS")), _tod(r.get("tPeakI")), r.get("T1AtPeakI"), r.get("ageIS"),
                     _cls(r.get("ageIS")) if r.get("T1AtPeakI") is not None else "none", r.get("gapS"), r.get("vAgeKwS"), r.get("channelI"), r.get("nTiesAtMinP")])
    block = {"_provenance": "GENERATED by tools/power_peak_temp.py (M550). Do not hand-edit.", "schemaVersion": 1,
             "basis": "raw bytes through the master's own helpers (_prep_bytes, _series, _asof); raw/ = sha256-verified originals (M366); app-reported BMS channels (logged, not measured); the power peak is a reconstructed I x V sample",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]},
             "rule": {"nearestSampleNoInterpolation": True, "tiers": {"cotimed": "|age| <= 1 s", "nearby": "1 s < |age| <= 3 s", "late": "3 s < |age| <= 10 s", "none": "beyond 10 s or no T1 sample (omitted)"},
                      "ageSign": "T1 sample time minus peak sample time (seconds)", "ties": "first sample in (t, row) order", "currentPair": "the master's channel-gated peak-C-rate sample, replicated exactly (reg / egc / dual), T1 within 3 s"},
             "perDriveColumns": ["file", "tPeakKw", "T1AtPeakKw(<=3 s)", "ageKwS", "classKw", "tPeakI", "T1AtPeakI", "ageIS", "classI", "gapS", "vAgeKwS", "channelI", "nTiesAtMinP"],
             "perDrive": rows, "kwViewX": kw_x, "acViewX": ac_x, "summary": res["summary"], "knownAnswer": res["knownAnswer"],
             "limits": ["tPeakKw / tPeakI are clock times of day (M567; the logger exports no date)", "P = Id x V is reconstructed from a current sample and the voltage sample paired within 1.5 s (vAgeKwS), not a native power sample", "T1 is logged at 1 degC resolution: differences below 1 degC cannot be shown",
                        "summary statistics use the <= 3 s tiers only; the late tier (3-10 s) is a labelled sensitivity, paired 3-10 s apart under slow polling",
                        "M567: the A / C views plot acViewX (T1 sample nearest the master's current-peak sample, tiers within 1 s / 3 s / hollow 3-10 s / omitted beyond 10 s); the drive-maximum fallback of T1_at_peak_Crate stays in the master and in cRatePoints* (unchanged) but is no longer drawn; the late tier departs from the master's 3 s convention (inherited from M550 as pre-registered)",
                        "N07 is partial: only the peak charge current and peak charge power pairs carry ages and classes; the other peak pairings are inventoried in analyses/M550_spec.md follow-ups",
                        "a drive whose minimum P is not negative has no charge sample; its 'peak' is the smallest positive P"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("powerPeakTemperature", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "powerPeakTemperature"}
    assert [p[5] for p in A2["cRatePointsAK"]] == [p[5] for p in A["cRatePointsAK"]] and set(block["kwViewX"]) == {p[5] for p in A2["cRatePointsAK"]} and set(block["acViewX"]) == set(block["kwViewX"]), "keyed map join assertion"
    A2["powerPeakTemperature"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M550: computed by tools/power_peak_temp.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["powerPeakTemperature"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "powerPeakTemperature"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"powerPeakTemperature": "written"}))


if __name__ == "__main__":
    main()
