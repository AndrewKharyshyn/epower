#!/usr/bin/env python3
"""M560 (spec analyses/M560_spec.md Rev 2): sensitivity of the cell-spread relaxation (M194, cellSpreadRelaxation) to Max/Min pairing, forward fill, freshness and gap collapsing. Flag-only: no published value changes.
Family (a) re-measures the FIXED V0 windows (keyed by drive and load-off timestamp): V3 polling-cycle pairing, V4 nearest-1.5 s pairing, V8 native pair level (no 1 s mean). Family (b) changes the window set: V1 / V2 Max-Min fill 0 / 1,
V9 current fill 0 / 1, V6 fresh-only, V7 strict contiguity. A placebo with the same geometry (pseudo load-offs inside long rests without preceding load) is the null. Per-drive records are cached by the raw sha256 and the extractor hash (csr_cache/, git-ignored).
Modes: --check (writes analyses/M560_check.json) | --splice (check + additive write of S.cellSpreadRelaxationSensitivity). Usage: python tools/csr_sensitivity.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import m560_window_keys as W
from cell_observability import poll_pairs, nearest_pairs

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M560_check.json")
CACHE = os.path.join(ROOT, "csr_cache")
SEED, DRAWS, MIN_DAYS = 42, 4000, 5
TAU = 1.5
PLACEBO_REST, PLACEBO_QUIET = 20, 30
FILL_VARIANTS = {"V1_fillMM0": (0, 3), "V2_fillMM1": (1, 3), "V9a_fillI0": (3, 0), "V9b_fillI1": (3, 1)}


# ---------------------------------------------------------------- kernels (pure, unit-tested)
def onset_asym(spread, i, j):
    seg = spread[i:j]
    if np.isfinite(seg).sum() < 5:
        return None
    on = float(np.nanmean(spread[max(0, i - 1):i + 1]))
    asym = float(np.nanmedian(seg[-min(5, len(seg)):]))
    return on, asym, on - asym


def pair_series(tmax, vmax, tmin, vmin, kind):
    """spread (mV) per pair; returns (pair time s, spread, time of first member, time of second member)."""
    a, b = poll_pairs(tmax, tmin, TAU) if kind == "poll" else nearest_pairs(tmax, tmin, TAU)
    t1, t2 = tmax[a], tmin[b]
    return np.maximum(t1, t2), (vmax[a] - vmin[b]) * 1000.0, np.minimum(t1, t2), np.maximum(t1, t2)


def grid_from_pairs(pt, ps, index, fill=3):
    """1 s mean of the pair spreads onto the V0 grid index (forward fill limited)."""
    if len(pt) == 0:
        return np.full(len(index), np.nan)
    s = pd.Series(ps, index=pd.to_datetime(pt, unit="s")).resample("1s").mean()
    if fill > 0:
        s = s.ffill(limit=fill)
    return s.reindex(index).to_numpy(float)


def native_magnitude(pt, ps, lo, hi, t0, t1):
    """V8: onset = the last pair strictly before load-off with both members before it; asymptote = median of the pairs with both members at or after load-off in the last 5 s of the rest; returns (mag, onset, asym, straddlers, onset2)."""
    before = (hi < t0)
    after = (lo >= t0) & (hi < t1) & (pt >= t1 - 5.0)
    strad = int(((lo < t0) & (hi >= t0) & (lo >= t0 - 3.0)).sum())
    if not before.any() or after.sum() < 1:
        return None, None, None, strad, None
    last = np.flatnonzero(before)[-1]
    on = float(ps[last]); asym = float(np.median(ps[after]))
    first_after = np.flatnonzero(lo >= t0)
    on2 = float(ps[first_after[0]]) if len(first_after) else None
    return on - asym, on, asym, strad, on2


def placebo_magnitudes(g2):
    """pseudo load-offs inside long rest runs without preceding load: same onset / asymptote rule as V0."""
    spread = (g2["maxv"] - g2["minv"]).values * 1000.0
    cur = g2["I"].abs().values
    rest = cur < W.REST_I
    n = len(rest)
    out = []
    i = 0
    while i < n:
        if rest[i]:
            j = i
            while j < n and rest[j]:
                j += 1
            if j - i >= PLACEBO_REST and i >= PLACEBO_QUIET and cur[i - PLACEBO_QUIET:i].max() < W.LOAD_I:
                ii = i + 10
                r = onset_asym(spread, ii, j)
                if r:
                    out.append(round(r[2], 6))
            i = j
        else:
            i += 1
    return out


def half_category(h, mag):
    if h is None or mag <= 1.0:
        return "none"
    return "0" if h == 0 else "1" if h == 1 else "2" if h == 2 else "3plus"


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (onset_asym, pair_series, grid_from_pairs, native_magnitude, placebo_magnitudes, half_category, drive_record, W.build_grid, W.find_windows, W.read_frame)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- per-drive extraction
def drive_record(b):
    import compute_summary_arrays as C
    fr = W.read_frame(b)
    if fr is None or W.CUR not in fr.columns:
        return {"ok": False, "why": "no Max/Min or current channel"}
    g, fresh = W.build_grid(fr, 3, 3)
    g2, wins = W.find_windows(g, fresh)
    if g2 is None or len(g2) < 30:
        return {"ok": True, "covered": False, "windows": []}
    t = C._ft(fr["time"])
    tns = pd.Series(pd.to_datetime(t)).values.astype("datetime64[ns]").astype("int64") / 1e9
    def chan(col):
        v = pd.to_numeric(fr[col], errors="coerce").to_numpy(float)
        m = ~np.isnan(v)
        o = np.argsort(tns[m], kind="stable")
        return tns[m][o], v[m][o]
    tmax, vmax = chan(W.MAXV); tmin, vmin = chan(W.MINV)
    ps = {k: pair_series(tmax, vmax, tmin, vmin, k) for k in ("poll", "near")}
    sp3 = grid_from_pairs(ps["poll"][0], ps["poll"][1], g2.index)
    sp4 = grid_from_pairs(ps["near"][0], ps["near"][1], g2.index)
    idx = g2.index
    out = []
    for w in wins:
        d = {k: w[k] for k in ("key", "mag", "onset", "asym", "restRows", "gapInside", "freshAll", "onsetFilled", "negative", "trailingFill")}
        d["halfCat"] = half_category(w["half"], w["mag"])
        for name, arr in (("V3", sp3), ("V4", sp4)):
            r = onset_asym(arr, w["i"], w["j"])
            d[name] = None if r is None else round(r[2], 6)
        t0 = idx[w["i"]].value / 1e9; t1 = idx[w["j"] - 1].value / 1e9 + 1.0
        pt, psp, lo, hi = ps["poll"]
        m8, on8, as8, strad, on2 = native_magnitude(pt, psp, lo, hi, t0, t1)
        d["V8"] = None if m8 is None else round(m8, 6); d["V8onset2"] = None if on2 is None else round(on2, 6); d["straddlers"] = strad
        out.append(d)
    rec = {"ok": True, "covered": True, "windows": out, "placebo": placebo_magnitudes(g2), "variants": {}}
    for name, (fm, fi) in FILL_VARIANTS.items():
        gv, fv = W.build_grid(fr, fm, fi)
        _, wv = W.find_windows(gv, fv)
        rec["variants"][name] = [{"key": w["key"], "mag": round(w["mag"], 6)} for w in wv]
    return rec


# ---------------------------------------------------------------- loading with the cache
def load_records(only=None):
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
    dig = lambda s: "".join(ch for ch in s if ch.isdigit())[:14]
    rawmap = {dig(f): f for f in os.listdir(raw_dir) if f.endswith(".csv")}
    os.makedirs(CACHE, exist_ok=True)
    sh = _src_hash()
    recs, stats = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "notCovered": 0}
    for _, r in dm.iterrows():
        fn = r["file"]
        if only and fn not in only:
            continue
        if dig(fn) not in rawmap:
            stats["noRaw"] += 1; continue
        b = open(os.path.join(raw_dir, rawmap[dig(fn)]), "rb").read()
        digest = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE, f"{digest}_{sh}.json")
        if os.path.exists(cp):
            rec = json.load(open(cp, encoding="utf-8")); stats["cacheHits"] += 1
        else:
            rec = drive_record(b)
            json.dump(rec, open(cp, "w", encoding="utf-8")); stats["extracted"] += 1
        if not rec.get("covered"):
            stats["notCovered"] += 1; continue
        c_ = cad.get(fn)
        recs[fn] = {"rec": rec, "file": fn, "rawSha256": digest, "cadence": c_ if isinstance(c_, str) else "unknown", "day": str(r.get("date", ""))[:10]}
    return dm, recs, stats


# ---------------------------------------------------------------- aggregation
def _ci(vals, days):
    v, d = np.asarray(vals, float), np.asarray(days)
    m = np.isfinite(v)
    v, d = v[m], d[m]
    uniq = np.unique(d)
    if v.size < 3 or len(uniq) < MIN_DAYS:
        return None
    by = {x: v[d == x] for x in uniq}
    rng = np.random.default_rng(SEED)
    meds = [np.median(np.concatenate([by[x] for x in rng.choice(uniq, len(uniq), replace=True)])) for _ in range(DRAWS)]
    return [round(float(np.percentile(meds, 2.5)), 2), round(float(np.percentile(meds, 97.5)), 2)]


def _summ(vals, days):
    v = np.asarray([x for x in vals if x is not None and np.isfinite(x)], float)
    if v.size == 0:
        return {"n": 0}
    dd = [d for x, d in zip(vals, days) if x is not None and np.isfinite(x)]
    lat = {}
    for x in v:
        k = f"{x:.1f}"
        lat[k] = lat.get(k, 0) + 1
    on_lattice = float(np.mean(np.abs(v * 2 - np.round(v * 2)) < 1e-6))
    return {"n": int(v.size), "nDays": len(set(dd)), "median": round(float(np.median(v)), 2), "p25": round(float(np.percentile(v, 25)), 2), "p75": round(float(np.percentile(v, 75)), 2),
            "ci95": _ci(v, dd), "shareAbove1mV": round(float((v > 1.0).mean()), 4), "shareOnHalfMvLattice": round(on_lattice, 4)}


def stratum_block(sub):
    days_of = lambda recs: [a["day"] for a in recs for _ in a["rec"]["windows"]]
    wins = [(a["day"], w["key"], a["file"], w) for a in sub for w in a["rec"]["windows"]]
    b = {"nDrives": len(sub), "nDays": len({a["day"] for a in sub}), "nWindows": len(wins)}
    v0 = _summ([w["mag"] for _, _, _, w in wins], [d for d, _, _, _ in wins])
    b["V0"] = v0
    b["V0_halfCategoriesStrict"] = None
    # family (a): re-measurement on the fixed V0 windows
    fa = {}
    for name in ("V3", "V4", "V8"):
        vals = [w[name] for _, _, _, w in wins]
        s = _summ(vals, [d for d, _, _, _ in wins])
        s["notRemeasurable"] = int(sum(1 for x in vals if x is None))
        s["differenceOfMediansMv"] = None if "median" not in s or "median" not in v0 else round(s["median"] - v0["median"], 2)
        s["insideV0Interval"] = None if "median" not in s or not v0.get("ci95") else bool(v0["ci95"][0] <= s["median"] <= v0["ci95"][1])
        fa[name] = s
    fa["V8"]["straddlingPairsExcluded"] = int(sum(w["straddlers"] for _, _, _, w in wins))
    fa["V8"]["differenceVsV0MaxAbsMedianMv"] = None if "median" not in fa["V8"] or "median" not in v0 else abs(round(fa["V8"]["median"] - v0["median"], 2))
    b["familyA_fixedWindows"] = fa
    nt = [(d, k, f, w) for d, k, f, w in wins if w.get("trailingFill")]
    wt = [(d, k, f, w) for d, k, f, w in wins if not w.get("trailingFill")]
    b["trailingFill"] = {"windowsWithTrailingFill": len(nt), "shareOfV0": round(len(nt) / max(1, len(wins)), 4), "V0WithoutThem": _summ([w["mag"] for _, _, _, w in wt], [d for d, _, _, _ in wt]),
                         "note": "an onset or asymptote second lies after a channel's last real sample and is forward-filled (up to 3 s) past the end of that channel's data; a published-construction artefact of the 1 s grid"}
    # family (b): window-set changes (added / dropped against V0)
    v0keys = {(a, k) for _, k, a, _ in wins}
    fb = {}
    for name in FILL_VARIANTS:
        items = [(a["day"], a["file"], x) for a in sub for x in a["rec"]["variants"].get(name, [])]
        ks = {(f, x["key"]) for _, f, x in items}
        s = _summ([x["mag"] for _, _, x in items], [d for d, _, _ in items])
        s.update(added=int(len(ks - v0keys)), dropped=int(len(v0keys - ks)), keptShareOfV0=round(len(ks & v0keys) / max(1, len(v0keys)), 4))
        s["differenceOfMediansMv"] = None if "median" not in s or "median" not in v0 else round(s["median"] - v0["median"], 2)
        s["insideV0Interval"] = None if "median" not in s or not v0.get("ci95") else bool(v0["ci95"][0] <= s["median"] <= v0["ci95"][1])
        fb[name] = s
    for name, flag in (("V6_freshOnly", "freshAll"), ("V7_strictContiguity", None)):
        ws = [(d, k, f, w) for d, k, f, w in wins if (w["freshAll"] if flag else not w["gapInside"])]
        s = _summ([w["mag"] for _, _, _, w in ws], [d for d, _, _, _ in ws])
        s.update(added=0, dropped=len(wins) - len(ws), keptShareOfV0=round(len(ws) / max(1, len(wins)), 4))
        s["differenceOfMediansMv"] = None if "median" not in s or "median" not in v0 else round(s["median"] - v0["median"], 2)
        s["insideV0Interval"] = None if "median" not in s or not v0.get("ci95") else bool(v0["ci95"][0] <= s["median"] <= v0["ci95"][1])
        if name.startswith("V7"):
            cats = {}
            for _, _, _, w in ws:
                cats[w["halfCat"]] = cats.get(w["halfCat"], 0) + 1
            s["halfTimeCategoryCountsSeconds"] = cats
        fb[name] = s
    b["familyB_windowSet"] = fb
    pl = [(a["day"], m) for a in sub for m in a["rec"].get("placebo", [])]
    b["placebo"] = _summ([m for _, m in pl], [d for d, _ in pl])
    if b["placebo"].get("n"):
        b["placebo"]["v0InsidePlaceboIQR"] = bool(b["placebo"]["p25"] <= v0["median"] <= b["placebo"]["p75"]) if "median" in v0 else None
        b["placebo"]["placeboMedianAtLeastV0"] = bool(b["placebo"]["median"] >= v0["median"]) if "median" in v0 else None
    b["resolution"] = {"maxMinGridStepMv": 1.0, "magnitudeLatticeStepMv": 0.5, "note": "spread steps are 1 mV and the magnitude is an onset mean minus a median of up to 5 values, so it lies on a 0.5 mV lattice; the interval limits are lattice-bound"}
    return b


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = {w["file"] for w in json.load(open(os.path.join(ROOT, "analyses", "M560_audit_sample.json"), encoding="utf-8"))["windows"]}
    dm, recs, stats = load_records(only)
    A = json.load(open(ARR, encoding="utf-8"))["cellSpreadRelaxation"]
    allw = [w for a in recs.values() for w in a["rec"]["windows"]]
    ka = {"nDrivesCovered": len(recs), "nWindows": len(allw), "storedNDrivesCovered": A["nDrivesCovered"], "storedNRestWindows": A["nRestWindows"],
          "medianMagnitude": round(float(np.median([w["mag"] for w in allw])), 2) if allw else None, "storedMedian": A["relaxationMagnitudeMv"]["median"],
          "reproducesStored": bool(len(recs) == A["nDrivesCovered"] and len(allw) == A["nRestWindows"])}
    res = {"milestone": "M560", "mode": mode, "stats": stats, "knownAnswer": ka, "extractorSourceHash": _src_hash(), "strata": {}}
    if not only:
        res["pooledV0"] = _summ([w["mag"] for w in allw], [a["day"] for a in recs.values() for _ in a["rec"]["windows"]])
        res["pooledV0"]["storedInterval"] = A["relaxationMagnitudeBoot"]["ci95"]
        ka["pooledIntervalMatchesStored"] = bool(res["pooledV0"].get("ci95") == A["relaxationMagnitudeBoot"]["ci95"])
    for c in ("fast", "slow", "unknown"):
        sub = [a for a in recs.values() if a["cadence"] == c and a["rec"]["windows"]]
        if sub:
            res["strata"][c] = stratum_block(sub)
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((a["file"], a["rawSha256"]) for a in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    json.dump({f: a["rec"] for f, a in recs.items()}, open(os.path.join(CACHE, "_all.json" if not only else "_sample.json"), "w", encoding="utf-8"), default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka}, default=float))
    if mode == "--splice" and not only:
        if not (ka["reproducesStored"] and ka.get("pooledIntervalMatchesStored")):
            print(json.dumps({"STOP": "V0 does not reproduce the stored block", **ka}, default=float)); sys.exit(2)
        splice(res)


def splice(res):
    """additive write of S.cellSpreadRelaxationSensitivity (+ stamp); no existing key changes."""
    flags = {}
    for k, st in res["strata"].items():
        v0 = st["V0"]
        fam = {**st["familyA_fixedWindows"], **st["familyB_windowSet"]}
        flags[k] = {"placeboMedianAtLeastV0": st["placebo"].get("placeboMedianAtLeastV0"), "v0InsidePlaceboIQR": st["placebo"].get("v0InsidePlaceboIQR"),
                    "variantOutsideV0Interval": sorted(n for n, s in fam.items() if s.get("insideV0Interval") is False),
                    "windowsAddedOver5Pct": sorted(n for n, s in st["familyB_windowSet"].items() if s.get("added", 0) > 0.05 * max(1, v0.get("n", 0))),
                    "v8DiffersOver0p5mV": bool((st["familyA_fixedWindows"]["V8"].get("differenceVsV0MaxAbsMedianMv") or 0) > 0.5),
                    "freshOnlyKeepsUnder60Pct": bool(st["familyB_windowSet"]["V6_freshOnly"]["keptShareOfV0"] < 0.6)}
    meds = {k: st["V0"].get("median") for k, st in res["strata"].items() if k in ("fast", "slow")}
    flags["fastSlowSignDiffer"] = bool(len(meds) == 2 and None not in meds.values() and (meds["fast"] > 0) != (meds["slow"] > 0))
    block = {"_provenance": "GENERATED by tools/csr_sensitivity.py (M560). Do not hand-edit.", "schemaVersion": 1,
             "basis": "raw bytes; the published cellSpreadRelaxation window rule (rest |I| < 5 A for >= 5 rows after mean |I| >= 20 A over 3 rows, on the 1 s mean grid with forward fill limit 3 and removed seconds collapsed) is the V0 reference; population: every drive with a raw file and the Max / Min channels; raw/ = sha256-verified originals (M366)",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]},
             "seed": SEED, "draws": DRAWS, "minDays": MIN_DAYS, "tauS": TAU, "knownAnswer": res["knownAnswer"], "pooledV0": res["pooledV0"], "strata": res["strata"], "flags": flags,
             "limits": ["exploratory sensitivity of an exploratory block; the published block and its text are unchanged",
                        "magnitudes lie on a 0.5 mV lattice at a 1 mV channel resolution: a median of 1.0 mV is at the resolution floor, not a measured widening",
                        "the published onset averages the last loaded row and the first rest row and so contains an ohmic load term; the native pair-level estimand V8 is a separate estimand, not a variant of V0",
                        "half-time has no median or interval (the published index counts rows of the collapsed grid); only category counts under strict contiguity are given",
                        "the cadence strata are not pooled; no cell diagnosis, balance, health or ageing statement"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("cellSpreadRelaxationSensitivity", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "cellSpreadRelaxationSensitivity"}
    A2["cellSpreadRelaxationSensitivity"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M560: computed by tools/csr_sensitivity.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["cellSpreadRelaxationSensitivity"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "cellSpreadRelaxationSensitivity"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"cellSpreadRelaxationSensitivity": "written"}))


if __name__ == "__main__":
    main()
