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
    return kw_x, summary


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
    kw_x, summary = build(dm, recs, A)
    res.update(summary=summary, nKwViewX=len(kw_x))
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((r["file"], r["rawSha256"]) for r in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    json.dump({f: r for f, r in recs.items()}, open(os.path.join(CACHE, "_all.json" if not only else "_sample.json"), "w"), default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka, "summary": summary}, default=float)[:3000])


if __name__ == "__main__":
    main()
