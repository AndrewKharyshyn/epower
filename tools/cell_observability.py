#!/usr/bin/env python3
"""M555 (spec analyses/M555_spec.md Rev 2): observability of the logged cell-voltage channels against the pack-voltage namespace (audit 2026-10-29 N12, second half).
Per drive and channel (BMS-reported Max / Min cell voltage, the logged G01 channel, the per-cell channels of three early files): sample counts, coverage of the pack-voltage samples within +-1.5 s, nearest-offset to the pack samples,
age (time since the last channel SAMPLE at or before each pack sample, censored share), the share of 1 s grid points the published cell-spread resampling would carry forward, and the internal consistency Max >= Min - resolution under the
logger's polling-cycle pairing (primary) and nearest-within-tau pairing (sensitivity 0.25 / 0.5 / 1.5 s). The G01 channel is scale-checked against the Max / Min mid-range BEFORE any band test; no sum-of-cells probe; no spread statistic.
Per-drive records are cached by the raw sha256 and the extractor hash (cell_cache/, git-ignored); aggregation never rereads raw. Modes: --check (writes analyses/M555_check.json) | --splice (check + additive write of S.cellObservability).
Usage: python tools/cell_observability.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, io, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M555_check.json")
CACHE = os.path.join(ROOT, "cell_cache")
PACK = "[BMS] HV Battery voltage (V)"
MAXC, MINC = "[BMS] Max Cell Voltage (V)", "[BMS] Min Cell Voltage (V)"
TAU_MAIN, TAUS = 1.5, (0.25, 0.5, 1.5)
CLASS_EDGES = (0.95, 0.50)
SEED, DRAWS, MIN_DAYS = 42, 4000, 5
G01_SCALE_BAND = (0.9, 1.1)
FFILL_LIMIT = 3


# ---------------------------------------------------------------- kernels (pure, unit-tested)
def nearest_offset(tc, tp):
    """absolute offset (s) from each element of tc to the nearest element of the sorted array tp."""
    if len(tp) == 0:
        return np.full(len(tc), np.inf)
    j = np.clip(np.searchsorted(tp, tc), 1, max(len(tp) - 1, 1)) if len(tp) > 1 else np.zeros(len(tc), int)
    if len(tp) == 1:
        return np.abs(tc - tp[0])
    return np.minimum(np.abs(tc - tp[j - 1]), np.abs(tc - tp[j]))


def coverage(tp, tc, tau):
    """share of the pack samples tp that have a channel sample within +-tau."""
    if len(tp) == 0:
        return float("nan")
    return float((nearest_offset(tp, tc) <= tau + 1e-9).mean()) if len(tc) else 0.0


def ages(tp, tc):
    """age (s) of the last channel sample at or before each pack sample; NaN where there is none (censored)."""
    if len(tc) == 0:
        return np.full(len(tp), np.nan)
    j = np.searchsorted(tc, tp, side="right") - 1
    a = np.where(j >= 0, tp - tc[np.clip(j, 0, None)], np.nan)
    return a


def poll_pairs(tmax, tmin, tau=TAU_MAIN):
    """polling-cycle pairing, one-to-one: each Max sample takes the first Min sample at or after it and before the next Max sample, capped at tau. Returns (index of Max, index of Min)."""
    if len(tmax) == 0 or len(tmin) == 0:
        return np.array([], int), np.array([], int)
    j = np.searchsorted(tmin, tmax, side="left")
    nxt = np.append(tmax[1:], np.inf)
    ok = (j < len(tmin))
    jj = np.clip(j, 0, len(tmin) - 1)
    ok &= (tmin[jj] < nxt) & ((tmin[jj] - tmax) <= tau + 1e-9)
    return np.flatnonzero(ok), jj[ok]


def nearest_pairs(tmax, tmin, tau):
    """nearest Min sample within tau for each Max sample (reuse allowed). Returns (index of Max, index of Min)."""
    if len(tmax) == 0 or len(tmin) == 0:
        return np.array([], int), np.array([], int)
    j = np.clip(np.searchsorted(tmin, tmax), 1, max(len(tmin) - 1, 1)) if len(tmin) > 1 else np.zeros(len(tmax), int)
    if len(tmin) == 1:
        best = np.zeros(len(tmax), int)
    else:
        best = np.where(np.abs(tmax - tmin[j - 1]) <= np.abs(tmax - tmin[j]), j - 1, j)
    ok = np.abs(tmax - tmin[best]) <= tau + 1e-9
    return np.flatnonzero(ok), best[ok]


def carry_forward(tc, limit=FFILL_LIMIT):
    """share of 1 s grid points (first to last sample) that the published resampling (1 s mean, forward fill limited to `limit` points) carries forward, and the share left empty beyond the limit."""
    if len(tc) < 2:
        return 0.0, 0.0
    sec = np.unique(np.floor(tc - tc[0]).astype(np.int64))
    n = int(sec[-1]) + 1
    obs = np.zeros(n, bool); obs[sec] = True
    since = np.full(n, np.iinfo(np.int64).max, np.int64)
    last = -1
    for k in range(n):
        if obs[k]:
            last = k
        since[k] = k - last if last >= 0 else np.iinfo(np.int64).max
    carried = (~obs) & (since <= limit)
    beyond = (~obs) & (since > limit)
    return float(carried.sum() / n), float(beyond.sum() / n)


def resolution_from_decimals(v):
    s = pd.Series(v).round(6).astype(str)
    d = s.str.split(".").str[1].fillna("").str.rstrip("0").str.len()
    return 10.0 ** (-int(d.max())) if len(d) and d.max() > 0 else 1.0


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (nearest_offset, coverage, ages, poll_pairs, nearest_pairs, carry_forward, resolution_from_decimals, channel_record, drive_record, _load_channels)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- per-drive extraction
def _load_channels(b):
    from drive_raw_cache import fast_time
    hdr = list(pd.read_csv(io.BytesIO(b), nrows=0).columns)
    percell = [c for c in hdr if re.search(r"Battery Cell #\d+", c)]
    g01 = [c for c in hdr if "G01" in c and "Cell" in c]
    cols = [c for c in ([PACK, MAXC, MINC] + g01 + percell) if c in hdr]
    if "time" not in hdr or PACK not in hdr:
        return hdr, None, cols
    raw = pd.read_csv(io.BytesIO(b), usecols=["time"] + cols, low_memory=False)
    t = fast_time(raw["time"], mixed=True)
    tns = pd.Series(pd.to_datetime(t)).values.astype("datetime64[ns]").astype("int64")
    # second, independent count route: the raw text fields that are non-empty
    txt = pd.read_csv(io.BytesIO(b), usecols=cols, dtype=str, keep_default_na=False)
    out = {}
    for c in cols:
        v = pd.to_numeric(raw[c], errors="coerce").to_numpy(float)
        m = ~np.isnan(v)
        order = np.argsort(tns[m], kind="stable")
        tt, vv = tns[m][order], v[m][order]
        if len(tt):                                                   # duplicate timestamps keep the last sample
            keep = np.append(tt[1:] != tt[:-1], True)
            tt, vv = tt[keep], vv[keep]
        out[c] = (tt, vv, int(m.sum()), int((txt[c].str.strip() != "").sum()))
    return hdr, out, cols


def channel_record(name, ch, tpack, tp_ns, t0, res):
    tt, vv, nraw, ntxt = ch
    tc = (tt - t0) / 1e9
    rec = {"n": int(len(tt)), "nNonMissingRaw": nraw, "nNonMissingText": ntxt, "resolution": res}
    if len(tt) == 0:
        return rec, tc, vv
    tp = tpack
    off = nearest_offset(tc, tp)
    ag = ages(tp, tc)
    cens = np.isnan(ag)
    agv = ag[~cens]
    rec.update({"rateRatio": len(tt) / len(tp), "coverage": coverage(tp, tc, TAU_MAIN), "coverage0p25": coverage(tp, tc, 0.25),
                "exactCoTimed": float(np.isin(tt, tp_ns).mean()),
                "offsetMedian": float(np.median(off)), "offsetP95": float(np.percentile(off, 95)), "within0p25": float((off <= 0.25).mean()), "within1p5": float((off <= 1.5).mean()),
                "ageCensoredShare": float(cens.mean()), "ageMedian": float(np.median(agv)) if len(agv) else None, "ageP95": float(np.percentile(agv, 95)) if len(agv) else None,
                "ageOver3sShare": float((agv > 3.0).mean()) if len(agv) else None, "ageOver5sShare": float((agv > 5.0).mean()) if len(agv) else None})
    cf = carry_forward(tc)
    rec["carriedForwardShare"], rec["beyondLimitShare"] = cf
    return rec, tc, vv


def drive_record(b, sr_channels=None):
    hdr, ch, cols = _load_channels(b)
    rec = {"headerCellChannels": [c for c in hdr if "Cell" in c], "ok": False}
    if ch is None or PACK not in ch:
        return rec
    tp_ns, vp, nraw, ntxt = ch[PACK]
    keep = (vp >= 200) & (vp <= 450)
    rec["packSamples"] = int(len(tp_ns)); rec["packFilterRemoved"] = int((~keep).sum())
    tp_ns = tp_ns[keep]
    if len(tp_ns) < 2:
        return rec
    t0 = int(tp_ns[0]); tpack = (tp_ns - t0) / 1e9
    res_of = lambda c, vv: (sr_channels or {}).get(c) or resolution_from_decimals(vv)
    rec["ok"] = True; rec["channels"] = {}; rec["resolutionAgrees"] = {}
    tcs = {}
    for c in cols:
        if c == PACK:
            continue
        tt, vv, nraw, ntxt = ch[c]
        dec = resolution_from_decimals(vv) if len(vv) else None
        srv = (sr_channels or {}).get(c)
        r, tc, v = channel_record(c, ch[c], tpack, tp_ns, t0, srv or dec)
        r["resolutionDecimals"] = dec; r["resolutionSignalRep"] = srv
        rec["channels"][c] = r; tcs[c] = (tc, v, r["resolution"])
    rec["headerOnlyEmpty"] = [c for c in rec["headerCellChannels"] if c in rec["channels"] and rec["channels"][c]["n"] == 0]
    if MAXC in tcs and MINC in tcs and len(tcs[MAXC][0]) and len(tcs[MINC][0]):
        tmax, vmax, rx = tcs[MAXC]; tmin, vmin, rn = tcs[MINC]
        res = max(rx or 0.0, rn or 0.0)
        ia, ib = poll_pairs(tmax, tmin)
        cons = {"poll": {"pairs": int(len(ia)), "viol": int((vmax[ia] < vmin[ib] - res - 1e-12).sum()), "unmatchedMax": int(len(tmax) - len(ia)), "unmatchedMin": int(len(tmin) - len(np.unique(ib)))}}
        for tau in TAUS:
            ja, jb = nearest_pairs(tmax, tmin, tau)
            cons[f"nearest{tau}"] = {"pairs": int(len(ja)), "viol": int((vmax[ja] < vmin[jb] - res - 1e-12).sum()), "reuse": int(len(jb) - len(np.unique(jb)))}
        rec["consistency"] = cons; rec["consistencyResolution"] = res
        mid_t, mid_v = tmax[ia], (vmax[ia] + vmin[ib]) / 2.0
        mx_v, mn_v = vmax[ia], vmin[ib]
        extra = {}
        for c, (tc, v, rr) in tcs.items():
            if c in (MAXC, MINC) or len(tc) == 0 or len(mid_t) == 0:
                continue
            ja, jb = nearest_pairs(tc, mid_t, TAU_MAIN)          # channel sample -> nearest Max/Min pair
            if len(ja) == 0:
                extra[c] = {"pairs": 0}; continue
            ratio = v[ja] / mid_v[jb]
            rr_ = max(rr or 0.0, res)
            extra[c] = {"pairs": int(len(ja)), "ratioMedian": float(np.median(ratio)), "ratioP5": float(np.percentile(ratio, 5)), "ratioP95": float(np.percentile(ratio, 95)),
                        "bandViol": int(((v[ja] < mn_v[jb] - rr_ - 1e-12) | (v[ja] > mx_v[jb] + rr_ + 1e-12)).sum()),
                        "absDiffToMaxPlusMinP50": float(np.median(np.abs(v[ja] - (mx_v[jb] + mn_v[jb])))), "absDiffToMaxPlusMinP95": float(np.percentile(np.abs(v[ja] - (mx_v[jb] + mn_v[jb])), 95)), "resolution": rr_}
        rec["otherChannels"] = extra
    return rec


# ---------------------------------------------------------------- aggregation
def _boot_share(num_by_day, den_by_day):
    a, b = np.asarray(num_by_day, float), np.asarray(den_by_day, float)
    n = len(a)
    if n < MIN_DAYS or b.sum() <= 0:
        return None
    idx = np.random.default_rng(SEED).integers(0, n, size=(DRAWS, n))
    den = b[idx].sum(axis=1)
    r = a[idx].sum(axis=1) / np.where(den > 0, den, np.nan)
    return [float(np.nanpercentile(r, 2.5)), float(np.nanpercentile(r, 97.5))]


def _pooled_share(viol, pairs, days):
    viol, pairs = np.asarray(viol, float), np.asarray(pairs, float)
    if pairs.sum() <= 0:
        return None
    ud = sorted(set(days)); ix = {d: k for k, d in enumerate(ud)}
    v = np.zeros(len(ud)); p = np.zeros(len(ud))
    for a, b, d in zip(viol, pairs, days):
        v[ix[d]] += a; p[ix[d]] += b
    ci = _boot_share(v, p)
    return {"share": round(float(viol.sum() / pairs.sum()), 6), "ci95": [round(c, 6) for c in ci] if ci else None, "pairs": int(pairs.sum()), "violations": int(viol.sum()), "nDrives": int((pairs > 0).sum()), "nDays": len(set(days))}


def _med(vals):
    v = [x for x in vals if x is not None and not (isinstance(x, float) and np.isnan(x))]
    return round(float(np.median(v)), 4) if v else None


def _cls(c):
    return "complete" if c >= CLASS_EDGES[0] else ("partial" if c >= CLASS_EDGES[1] else "sparse")


def stratum_block(recs, channels):
    res = {"nDrives": len(recs), "nDays": len({r["day"] for r in recs})}
    days = [r["day"] for r in recs]
    res["channels"] = {}
    for c in channels:
        have = [r for r in recs if c in r["rec"]["channels"] and r["rec"]["channels"][c]["n"] > 0]
        if not have:
            res["channels"][c] = {"drivesWithSamples": 0}; continue
        cv = [r["rec"]["channels"][c]["coverage"] for r in have]
        res["channels"][c] = {"drivesWithSamples": len(have), "coverageClassCounts": {k: int(sum(1 for x in cv if _cls(x) == k)) for k in ("complete", "partial", "sparse")},
                              "coverageMedianOfDrives": _med(cv), "rateRatioMedianOfDrives": _med([r["rec"]["channels"][c]["rateRatio"] for r in have]),
                              "exactCoTimedShareMedianOfDrives": _med([r["rec"]["channels"][c]["exactCoTimed"] for r in have]),
                              "offsetMedianS": _med([r["rec"]["channels"][c]["offsetMedian"] for r in have]), "offsetP95OfDrivesS": _med([r["rec"]["channels"][c]["offsetP95"] for r in have]),
                              "within0p25MedianOfDrives": _med([r["rec"]["channels"][c]["within0p25"] for r in have]),
                              "ageMedianS": _med([r["rec"]["channels"][c]["ageMedian"] for r in have]), "ageP95MedianOfDrivesS": _med([r["rec"]["channels"][c]["ageP95"] for r in have]),
                              "ageCensoredShareMedianOfDrives": _med([r["rec"]["channels"][c]["ageCensoredShare"] for r in have]),
                              "driveShareWithAgeP95Over3s": round(float(np.mean([(r["rec"]["channels"][c]["ageP95"] or 0) > 3.0 for r in have])), 4),
                              "carriedForwardShareMedianOfDrives": _med([r["rec"]["channels"][c]["carriedForwardShare"] for r in have]), "beyondLimitShareMedianOfDrives": _med([r["rec"]["channels"][c]["beyondLimitShare"] for r in have])}
    cons = [r for r in recs if "consistency" in r["rec"]]
    if cons:
        cd = [r["day"] for r in cons]
        res["maxMinConsistency"] = {"statistic": "day-clustered pooled share of Max < Min - resolution among paired samples", "polling": _pooled_share([r["rec"]["consistency"]["poll"]["viol"] for r in cons], [r["rec"]["consistency"]["poll"]["pairs"] for r in cons], cd),
                                    "unmatchedMax": int(sum(r["rec"]["consistency"]["poll"]["unmatchedMax"] for r in cons)), "unmatchedMin": int(sum(r["rec"]["consistency"]["poll"]["unmatchedMin"] for r in cons))}
        for tau in TAUS:
            res["maxMinConsistency"][f"nearest{tau}"] = _pooled_share([r["rec"]["consistency"][f"nearest{tau}"]["viol"] for r in cons], [r["rec"]["consistency"][f"nearest{tau}"]["pairs"] for r in cons], cd)
            res["maxMinConsistency"][f"nearest{tau}"]["reuse"] = int(sum(r["rec"]["consistency"][f"nearest{tau}"]["reuse"] for r in cons))
    # complete set: Max and Min coverage >= 0.95 (plus the extra logged channel of the era)
    extra = [c for c in channels if c not in (MAXC, MINC)]
    def complete(r):
        ch = r["rec"]["channels"]
        need = [MAXC, MINC] + extra
        return all(c in ch and ch[c]["n"] > 0 and ch[c]["coverage"] >= CLASS_EDGES[0] for c in need)
    res["completeSetDriveShare"] = {"share": round(float(np.mean([complete(r) for r in recs])), 4), "needs": [MAXC, MINC] + extra}
    res["headerOnlyEmptyDrives"] = int(sum(1 for r in recs if r["rec"].get("headerOnlyEmpty")))
    # the logged extra channels: scale pre-check before any band test
    res["otherChannels"] = {}
    for c in extra:
        have = [r for r in recs if c in r["rec"].get("otherChannels", {}) and r["rec"]["otherChannels"][c].get("pairs", 0) > 0]
        if not have:
            continue
        med = _med([r["rec"]["otherChannels"][c]["ratioMedian"] for r in have])
        band_ok = bool(med is not None and G01_SCALE_BAND[0] <= med <= G01_SCALE_BAND[1])
        blk = {"descriptiveAbsDiffToMaxPlusMinV": {"p50MedianOfDrives": _med([r["rec"]["otherChannels"][c]["absDiffToMaxPlusMinP50"] for r in have]), "p95MedianOfDrives": _med([r["rec"]["otherChannels"][c]["absDiffToMaxPlusMinP95"] for r in have]),
                                                  "note": "descriptive only (added in the run after the scale pre-check; not a hypothesis test): the pre-check ratio to the mid-range is close to 2"},
               "scaleRatioToMaxMinMidMedianOfDrives": med, "ratioP5MedianOfDrives": _med([r["rec"]["otherChannels"][c]["ratioP5"] for r in have]), "ratioP95MedianOfDrives": _med([r["rec"]["otherChannels"][c]["ratioP95"] for r in have]),
               "pairs": int(sum(r["rec"]["otherChannels"][c]["pairs"] for r in have)), "bandTestRun": band_ok}
        if band_ok:
            blk["bandViolations"] = _pooled_share([r["rec"]["otherChannels"][c]["bandViol"] for r in have], [r["rec"]["otherChannels"][c]["pairs"] for r in have], [r["day"] for r in have])
        else:
            blk["note"] = "values are about %s times the Max / Min mid-range: no band verdict and no cell wording" % (round(med, 2) if med is not None else "n/a")
        res["otherChannels"][c] = blk
    return res


# ---------------------------------------------------------------- driver
def _sr_lookup():
    p = os.path.join(ROOT, "signal_representation.json")
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))["files"]
    return {"".join(ch for ch in f if ch.isdigit())[:14]: {c: v.get("grid_step") for c, v in x.get("channels", {}).items()} for f, x in d.items()}


def load_records(only=None):
    import compute_summary_arrays as C
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    bad = C._canonical_bad(dm)
    raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
    dig = lambda s: "".join(ch for ch in s if ch.isdigit())[:14]
    rawmap = {}
    for f in os.listdir(raw_dir):
        if f.endswith(".csv"):
            rawmap.setdefault(dig(f), []).append(f)
    srl = _sr_lookup()
    os.makedirs(CACHE, exist_ok=True)
    sh = _src_hash()
    recs, stats = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "notOk": 0}
    for i, r in dm.iterrows():
        fn = r["file"]
        if only and fn not in only:
            continue
        cand = rawmap.get(dig(fn))
        if not cand:
            stats["noRaw"] += 1; continue
        rawname = cand[0]
        b = open(os.path.join(raw_dir, rawname), "rb").read()
        digest = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE, f"{digest}_{sh}_{hashlib.sha256(json.dumps(srl.get(dig(rawname)), sort_keys=True).encode()).hexdigest()[:8]}.json")
        if os.path.exists(cp):
            rec = json.load(open(cp, encoding="utf-8")); stats["cacheHits"] += 1
        else:
            rec = drive_record(b, srl.get(dig(rawname)))
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            stats["extracted"] += 1
        if not rec.get("ok"):
            stats["notOk"] += 1
        recs[fn] = {"rec": rec, "file": fn, "rawName": rawname, "rawSha256": digest, "cadence": cad.get(fn) if isinstance(cad.get(fn), str) else "unknown", "canonClean": bool(not bad.iloc[i]),
                    "day": (lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}")("".join(c for c in fn if c.isdigit())), "durationS": float(r["duration_s"])}
    return dm, recs, stats, rawmap


def era_of(rec):
    ch = rec.get("channels", {})
    if not rec.get("ok"):
        return "none"
    if any(re.search(r"Battery Cell #\d+", c) and v["n"] > 0 for c, v in ch.items()):
        return "perCell"
    if any("G01" in c and v["n"] > 0 for c, v in ch.items()):
        return "maxMinG01"
    if MAXC in ch and MINC in ch and ch[MAXC]["n"] > 0 and ch[MINC]["n"] > 0:
        return "maxMin"
    return "noCellValues"


def known_answers(recs):
    n = {"counts": 0, "resolutionAgrees": 0}
    bad = {"counts": [], "resolutionAgrees": []}
    for fn, a in recs.items():
        r = a["rec"]
        if not r.get("ok"):
            continue
        for c, v in r["channels"].items():
            n["counts"] += 1
            if v["n"] != v["nNonMissingRaw"] or v["nNonMissingRaw"] != v["nNonMissingText"]:
                if not (v["nNonMissingText"] >= v["n"] and v["nNonMissingRaw"] == v["nNonMissingText"]):       # duplicates collapse n; the two raw counts must agree
                    bad["counts"].append((fn, c, v["n"], v["nNonMissingRaw"], v["nNonMissingText"]))
            if v["nNonMissingRaw"] != v["nNonMissingText"]:
                bad["counts"].append((fn, c, "routes", v["nNonMissingRaw"], v["nNonMissingText"]))
            if v.get("resolutionSignalRep") is not None and v.get("resolutionDecimals") is not None:
                n["resolutionAgrees"] += 1
                if abs(v["resolutionSignalRep"] - v["resolutionDecimals"]) > 1e-9:
                    bad["resolutionAgrees"].append((fn, c, v["resolutionSignalRep"], v["resolutionDecimals"]))
    return {"n": n, "misses": {k: len(v) for k, v in bad.items()}, "examples": {k: v[:5] for k, v in bad.items()}}


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = set(json.load(open(os.path.join(ROOT, "analyses", "M555_audit_sample.json"), encoding="utf-8"))["files"])
    dm, recs, stats, rawmap = load_records(only)
    ka = known_answers(recs)
    res = {"milestone": "M555", "mode": mode, "stats": stats, "knownAnswer": ka, "extractorSourceHash": _src_hash()}
    if ka["misses"]["counts"]:
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "known-answer miss", **ka}, default=float)); sys.exit(2)
    eras = {fn: era_of(a["rec"]) for fn, a in recs.items()}
    el = {fn: a for fn, a in recs.items() if a["rec"].get("ok") and a["canonClean"]}
    raw_all = sorted({f for v in rawmap.values() for f in v}); matched = {a["rawName"] for a in recs.values()}
    res["reconciliation"] = {"rawFilesInRaw": len(raw_all), "masterRows": int(len(dm)), "masterRowsWithRaw": len(recs), "rawNotInMaster": len(set(raw_all) - matched),
                             "eraCounts": {e: sum(1 for x in eras.values() if x == e) for e in sorted(set(eras.values()))}, "notCanonicalClean": int(sum(1 for a in recs.values() if a["rec"].get("ok") and not a["canonClean"]))}
    mf = json.load(open("raw_manifest.json", encoding="utf-8"))
    dg = lambda s_: "".join(ch for ch in s_ if ch.isdigit())[:14]
    excl = {dg(x["raw_name"]) for x in mf.get("typedExclusions", [])}
    notin = sorted(set(raw_all) - matched)
    res["reconciliation"]["rawNotInMasterByRole"] = {"auxiliary (e4ORCE exports)": sum(1 for f in notin if f.startswith("e4ORCE")), "comparison_only (typedExclusions)": sum(1 for f in notin if not f.startswith("e4ORCE") and dg(f) in excl),
                                                    "unexplained": sum(1 for f in notin if not f.startswith("e4ORCE") and dg(f) not in excl), "manifestRoles": mf.get("roles")}
    res["packFilter"] = {"packSamples": int(sum(a["rec"].get("packSamples", 0) for a in recs.values())), "removed": int(sum(a["rec"].get("packFilterRemoved", 0) for a in recs.values()))}
    res["packFilter"]["removedShare"] = round(res["packFilter"]["removed"] / max(res["packFilter"]["packSamples"], 1), 6)
    res["strata"] = {}
    for e, chs in (("maxMin", [MAXC, MINC]), ("maxMinG01", [MAXC, MINC, "G01 Cell Voltage  (V)"])):
        for c in ("fast", "slow", "unknown"):
            sub = [a for fn, a in el.items() if eras[fn] == e and a["cadence"] == c]
            if sub:
                res["strata"][f"{e}|{c}"] = stratum_block(sub, chs)
    pc = [a for fn, a in recs.items() if eras[fn] == "perCell"]
    res["perCellExample"] = [{"file": a["file"], "nCellChannels": sum(1 for c, v in a["rec"]["channels"].items() if re.search(r"Battery Cell #\d+", c) and v["n"] > 0),
                              "headerCellChannels": len(a["rec"]["headerCellChannels"]), "headerOnlyEmpty": len(a["rec"].get("headerOnlyEmpty", [])),
                              "coverageClassCounts": {k: int(sum(1 for c, v in a["rec"]["channels"].items() if re.search(r"Battery Cell #\d+", c) and v["n"] > 0 and _cls(v["coverage"]) == k)) for k in ("complete", "partial", "sparse")},
                              "scaleRatioMedianRange": [round(min(v["ratioMedian"] for v in a["rec"].get("otherChannels", {}).values() if v.get("pairs")), 3), round(max(v["ratioMedian"] for v in a["rec"].get("otherChannels", {}).values() if v.get("pairs")), 3)] if any(v.get("pairs") for v in a["rec"].get("otherChannels", {}).values()) else None}
                             for a in pc]
    res["unknownCadenceDriveSharePct"] = round(100.0 * sum(1 for fn, a in el.items() if eras[fn] in ("maxMin", "maxMinG01") and a["cadence"] == "unknown") / max(1, sum(1 for fn in el if eras[fn] in ("maxMin", "maxMinG01"))), 2)
    res["resolutionCrossCheck"] = ka["n"]["resolutionAgrees"], ka["misses"]["resolutionAgrees"]
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((a["file"], a["rawSha256"]) for a in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    json.dump({f: a["rec"] for f, a in recs.items()}, open(os.path.join(CACHE, "_all.json" if not only else "_sample.json"), "w", encoding="utf-8"), default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka, "reconciliation": res["reconciliation"], "packFilter": res["packFilter"], "unknownShare": res["unknownCadenceDriveSharePct"]}, default=float))
    if mode == "--splice" and not only:
        splice(res)


def splice(res):
    """additive write of S.cellObservability (+ stamp); no existing key changes."""
    flags = {}
    for k, st in res["strata"].items():
        mm = st.get("maxMinConsistency")
        pol = mm["polling"] if mm else None
        verdicts = {}
        if mm:
            for key in ("polling", "nearest0.25", "nearest0.5", "nearest1.5"):
                s = mm[key]
                verdicts[key] = bool(s and (s["share"] > 0.01 or (s["ci95"] and s["ci95"][1] > 0.01)))
        flags[k] = {"inversionOver1PctOrUpperBound": bool(pol and (pol["share"] > 0.01 or (pol["ci95"] and pol["ci95"][1] > 0.01))),
                    "verdictDiffersAcrossToleranceOrPairing": bool(mm and len(set(verdicts.values())) > 1),
                    "pairingsDifferOver0p5pp": bool(mm and pol and mm["nearest0.5"] and abs(pol["share"] - mm["nearest0.5"]["share"]) > 0.005),
                    "completeSetShareUnder90Pct": bool(st["nDays"] >= 20 and st["completeSetDriveShare"]["share"] < 0.9),
                    "headerOnlyEmptyOver5PctOfEra": bool(st["headerOnlyEmptyDrives"] > 0.05 * st["nDrives"]),
                    "ageP95Over3sInOver10PctOfDrives": bool(any((v.get("driveShareWithAgeP95Over3s") or 0) > 0.10 for v in st["channels"].values())),
                    "extraChannelOutsideBandNotTested": bool(any(not v.get("bandTestRun", True) for v in st["otherChannels"].values()))}
    flags["rawNotInMasterUnexplained"] = int(res["reconciliation"]["rawNotInMasterByRole"]["unexplained"])
    flags["packFilterDropsOver1Pct"] = bool(res["packFilter"]["removedShare"] > 0.01)
    flags["unknownCadenceDriveSharePct"] = res["unknownCadenceDriveSharePct"]
    block = {"_provenance": "GENERATED by tools/cell_observability.py (M555). Do not hand-edit.", "schemaVersion": 1,
             "basis": "raw bytes; BMS-reported, logged channels (Max / Min cell voltage, the logged G01 channel, the per-cell channels of three early files); pack-voltage namespace = [BMS] HV Battery voltage 200..450 V; raw/ = sha256-verified originals (M366)",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]},
             "rule": {"era": "the header set AND at least one non-missing value of the channel", "coverage": "share of pack samples with a channel sample within +-1.5 s (classes complete >= 0.95, partial 0.50-0.95, sparse < 0.50: analysis classes)",
                      "age": "time since the last channel SAMPLE at or before each pack sample (not since the value changed); censored share reported", "pairing": "primary = the logger's polling cycle (each Max takes the first Min at or after it before the next Max, capped at 1.5 s, one-to-one); sensitivity = nearest within 0.25 / 0.5 / 1.5 s with reuse",
                      "consistency": "Max >= Min - resolution, resolution = signal_representation grid step (decimals as cross-check)", "G01": "scale-checked against the Max / Min mid-range before any band test",
                      "carryForward": "share of 1 s grid points the published cell-spread resampling (1 s mean, forward fill limit 3) would carry forward; no cell-spread value changes",
                      "strata": "channel-set era x logger cadence regime; no pooled headline, no contrast", "intervals": f"day-clustered percentile bootstrap, seed {SEED}, {DRAWS} draws, only with >= {MIN_DAYS} days"},
             "reconciliation": res["reconciliation"], "packFilter": res["packFilter"], "knownAnswer": res["knownAnswer"], "strata": res["strata"], "perCellExample": res["perCellExample"], "flags": flags,
             "limits": ["BMS-reported, logged channels; the logger polls channels in a cycle, so channels are not simultaneous and co-timed means exactly equal timestamps only",
                        "no spread, balance, health, ageing or capacity statement; no sum-of-cells probe; missing channels stay missing", "the per-cell channels come from three early drives: a selected-channel example, not the corpus",
                        "the 0.95 / 0.50 coverage classes are analysis classes, not identified thresholds", "the strata are not comparable and no pooled value is given"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("cellObservability", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "cellObservability"}
    A2["cellObservability"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M555: computed by tools/cell_observability.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["cellObservability"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "cellObservability"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"cellObservability": "written"}))


if __name__ == "__main__":
    main()
