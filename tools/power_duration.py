#!/usr/bin/env python3
"""M552 (spec analyses/M552_spec.md Rev 2): observed net mean power over 5 / 10 / 30 / 60 / 120 s windows (audit 2026-10-29 N02), per drive and pooled across drives, both directions, per logger-cadence stratum.
Substrate = the master's own current / voltage pair stream (energy_packets.pair_stream), power piecewise linear between pair samples, a raw step > 5 s is a gap that ends the segment (no window spans a gap, nothing is bridged).
PRIMARY value = the EXACT continuous-start extremum of the window mean M(s) = (E(s + W) - E(s)) / W over each segment (E is piecewise quadratic; M'(s) = (P(s + W) - P(s)) / W is piecewise linear, so the candidates are every
breakpoint and the roots of P(s + W) = P(s) inside each piece); LOWER BRACKET = the 1 s start grid anchored at each segment start; SENSITIVITY = the same grid shifted by 0.5 s. Discharge extreme = max(0, max M), charge extreme = max(0, -min M).
Known answers (STOP on a miss): window mean <= the master sample extreme (KA4), energy closure to net_draw_kwh (KA5), monotone in W over segments eligible for both windows (KA6). Per-drive records are cached by the raw sha256
and the extractor source hash (duration_cache/, git-ignored); aggregation never rereads raw.
Modes: --check (writes analyses/M552_check.json) | --splice (check + additive write of S.powerDuration). Usage: python tools/power_duration.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M552_check.json")
CACHE = os.path.join(ROOT, "duration_cache")
WINDOWS = (5, 10, 30, 60, 120)
GAP_S = 5.0
EXPO_S = 600.0
MIN_ELIG_S = (600.0, 1800.0)
SEED, DRAWS = 42, 4000
MIN_DAYS, MIN_DAYS_P99 = 5, 20
PCTS = (50, 90, 95, 99)
TOL_CLOSURE_KWH, TOL_PEAK_KW, TOL_MONO = 1e-4, 0.05, 1e-9


# ---------------------------------------------------------------- kernel (pure, unit-tested)
def _prep(t, p):
    """knots of one segment: times (s), powers (kW), per-interval slope, cumulative energy E at the knots (kW s). Duplicate timestamps give zero-length intervals that carry no energy (never divided by d)."""
    t = np.asarray(t, float); p = np.asarray(p, float)
    d = np.diff(t)
    slope = np.where(d > 0, (p[1:] - p[:-1]) / np.where(d > 0, d, 1.0), 0.0)
    Ek = np.concatenate([[0.0], np.cumsum(d * (p[:-1] + p[1:]) / 2.0)])
    return t, p, d, slope, Ek


def _E(x, k):
    t, p, d, slope, Ek = k
    x = np.asarray(x, float)
    i = np.clip(np.searchsorted(t, x, side="right") - 1, 0, len(t) - 2)
    tau = x - t[i]
    return Ek[i] + p[i] * tau + slope[i] * tau ** 2 / 2.0


def window_extremes(t, p, W, end=None):
    """exact continuous-start extremes of the window mean over one segment; end limits the segment to [t0, end] (exposure-standardised sensitivity). Returns None when no window of length W fits."""
    k = _prep(t, p)
    t, p, d, slope, Ek = k
    T0, T1 = float(t[0]), float(t[-1] if end is None else min(t[-1], end))
    if T1 - T0 < W or len(t) < 2:
        return None
    lo, hi = T0, T1 - W
    b = np.unique(np.concatenate([t, t - W, [lo, hi]]))
    b = b[(b >= lo - 1e-12) & (b <= hi + 1e-12)]
    cand = [b]
    if len(b) > 1:
        mids = (b[:-1] + b[1:]) / 2.0
        i = np.clip(np.searchsorted(t, mids, side="right") - 1, 0, len(t) - 2)
        j = np.clip(np.searchsorted(t, mids + W, side="right") - 1, 0, len(t) - 2)
        a = (p[j] - p[i]) + slope[j] * (W - t[j]) + slope[i] * t[i]
        bb = slope[j] - slope[i]
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(bb != 0, -a / bb, np.nan)
        keep = (r > b[:-1]) & (r < b[1:])
        cand.append(r[keep])
    s = np.concatenate(cand)
    M = (_E(s + W, k) - _E(s, k)) / W
    imax, imin = int(np.argmax(M)), int(np.argmin(M))
    out = {"max": float(M[imax]), "sMax": float(s[imax] - T0), "min": float(M[imin]), "sMin": float(s[imin] - T0), "len": float(T1 - T0)}
    for name, off in (("grid", 0.0), ("shift", 0.5)):
        g = np.arange(lo + off, hi + 1e-9, 1.0)
        if len(g):
            Mg = (_E(g + W, k) - _E(g, k)) / W
            out[name + "Max"], out[name + "Min"], out[name + "N"] = float(Mg.max()), float(Mg.min()), int(len(g))
        else:
            out[name + "Max"] = out[name + "Min"] = None; out[name + "N"] = 0
    return out


def segments(ts, P):
    """supported segments: split where the raw step exceeds the 5 s support rule (gaps)."""
    ts = np.asarray(ts, float); P = np.asarray(P, float)
    cut = np.flatnonzero(np.diff(ts) > GAP_S) + 1
    return [(ts[a:b] - ts[a], P[a:b]) for a, b in zip(np.concatenate([[0], cut]), np.concatenate([cut, [len(ts)]])) if b - a >= 2]


def _dir(v_max, v_min):
    return max(0.0, v_max), max(0.0, -v_min)


def drive_record(ts, P, peak_dis_kw=None, peak_chg_kw=None):
    """per-drive record from a pair stream."""
    segs = segments(ts, P)
    rec = {"nSegments": len(segs), "segSeconds": [round(float(s[0][-1]), 3) for s in segs], "closureKwhSegments": float(sum(_E(s[0][-1], _prep(*s)) for s in segs) / 3600.0)}
    dts = np.diff(np.asarray(ts, float)); dts = dts[(dts > 0) & (dts <= GAP_S)]
    rec["medDtS"] = float(np.median(dts)) if len(dts) else None
    rec["byW"] = {}
    per_seg = {}
    for W in WINDOWS:
        best = {"dis": 0.0, "chg": 0.0, "sDis": None, "sChg": None, "segDis": None, "segChg": None, "gridDis": 0.0, "gridChg": 0.0, "shiftDis": 0.0, "shiftChg": 0.0,
                "nGrid": 0, "eligS": 0.0, "nSegEligible": 0}
        ps = []
        for si, (t, p) in enumerate(segs):
            r = window_extremes(t, p, W)
            if r is None:
                ps.append(None); continue
            dv, cv = _dir(r["max"], r["min"])
            best["eligS"] += r["len"]; best["nSegEligible"] += 1; best["nGrid"] += r["gridN"]
            if dv > best["dis"] or best["sDis"] is None:
                best["dis"], best["sDis"], best["segDis"] = dv, r["sMax"], si
            if cv > best["chg"] or best["sChg"] is None:
                best["chg"], best["sChg"], best["segChg"] = cv, r["sMin"], si
            gd, gc = _dir(r["gridMax"] if r["gridMax"] is not None else -1e18, r["gridMin"] if r["gridMin"] is not None else 1e18)
            sd, sc = _dir(r["shiftMax"] if r["shiftMax"] is not None else -1e18, r["shiftMin"] if r["shiftMin"] is not None else 1e18)
            best["gridDis"], best["gridChg"] = max(best["gridDis"], gd), max(best["gridChg"], gc)
            best["shiftDis"], best["shiftChg"] = max(best["shiftDis"], sd), max(best["shiftChg"], sc)
            ps.append((dv, cv, r["len"]))
        per_seg[W] = ps
        # local sample spacing around s* (for the audit): the knot spacing at the argmax
        for key, sk, gk in (("dtAtSDis", "sDis", "segDis"), ("dtAtSChg", "sChg", "segChg")):
            if best[sk] is not None:
                t = segs[best[gk]][0]; i = int(np.clip(np.searchsorted(t, best[sk], side="right") - 1, 0, len(t) - 2))
                best[key] = float(t[i + 1] - t[i])
        # exposure-standardised: the extreme within the first EXPO_S seconds of eligible time
        rem, ed, ec = EXPO_S, 0.0, 0.0
        for t, p in segs:
            if rem <= 0 or t[-1] < W:
                continue
            take = min(t[-1], rem)
            r = window_extremes(t, p, W, end=take)
            if r is not None:
                dv, cv = _dir(r["max"], r["min"]); ed, ec = max(ed, dv), max(ec, cv)
            rem -= t[-1]
        best["expDis"], best["expChg"] = ed, ec
        rec["byW"][str(W)] = best
    # KA6: over segments eligible for both windows, with the longer an integer multiple of the shorter, the exact extremes are non-increasing in W
    viol = 0
    for a in WINDOWS:
        for b in WINDOWS:
            if b > a and b % a == 0:
                for sa, sb in zip(per_seg[a], per_seg[b]):
                    if sa is not None and sb is not None and (sb[0] > sa[0] + TOL_MONO or sb[1] > sa[1] + TOL_MONO):
                        viol += 1
    rec["ka6Violations"] = viol
    return rec


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (_prep, _E, window_extremes, segments, _dir, drive_record)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- aggregation
def _pct_boot(vals, days, q):
    """percentile q of per-drive values; day-clustered percentile bootstrap (days resampled, drives kept inside a day); the interval needs n_drives*(1-q/100) >= 5 and >= 5 days (p99: >= 20 days); the maximum never has an interval."""
    v = np.asarray(vals, float)
    if not len(v):
        return None
    pt = float(np.percentile(v, q))
    ud = sorted(set(days)); by = {u: v[[i for i, d in enumerate(days) if d == u]] for u in ud}
    need_days = MIN_DAYS_P99 if q >= 99 else MIN_DAYS
    out = {"value": round(pt, 3), "ci95": None, "nDrives": int(len(v)), "nDays": len(ud)}
    if len(ud) < need_days or len(v) * (1 - q / 100.0) < 5:
        return out
    rng = np.random.default_rng(SEED); idx = rng.integers(0, len(ud), size=(DRAWS, len(ud)))
    bs, degenerate = [], 0
    for row in idx:
        x = np.concatenate([by[ud[j]] for j in row])
        if x.size == 0:
            degenerate += 1; continue
        bs.append(np.percentile(x, q))
    lo, hi = np.quantile(bs, [0.025, 0.975])
    out["ci95"] = [round(float(lo), 3), round(float(hi), 3)]; out["degenerateReplicateShare"] = round(degenerate / DRAWS, 4)
    return out


def stratum_block(recs):
    res = {"nDrives": len(recs), "nDays": len({r["day"] for r in recs})}
    medp = [r["rec"]["medDtS"] for r in recs if r["rec"]["medDtS"] is not None]
    res["samplePeriodS"] = {"median": round(float(np.median(medp)), 3), "p95": round(float(np.percentile(medp, 95)), 3)} if medp else None
    res["byW"] = {}
    for W in WINDOWS:
        sub = [r for r in recs if r["rec"]["byW"][str(W)]["nSegEligible"] > 0]
        row = {"nDrivesSupported": len(sub), "nDaysSupported": len({r["day"] for r in sub}), "supportShareOfStratum": round(len(sub) / len(recs), 4) if recs else None}
        row["resolutionLimited"] = bool(res["samplePeriodS"] and W < 2 * res["samplePeriodS"]["median"])
        days = [r["day"] for r in sub]
        for dirn, key in (("discharge", "dis"), ("charge", "chg")):
            ex = [r["rec"]["byW"][str(W)][key] for r in sub]
            gr = [r["rec"]["byW"][str(W)]["grid" + key.capitalize()] for r in sub]
            sh = [r["rec"]["byW"][str(W)]["shift" + key.capitalize()] for r in sub]
            xp = [r["rec"]["byW"][str(W)]["exp" + key.capitalize()] for r in sub]
            blk = {"exact": {f"p{q}": (_pct_boot(ex, days, q) if not row["resolutionLimited"] else {"value": round(float(np.percentile(ex, q)), 3) if ex else None, "ci95": None, "nDrives": len(ex), "nDays": len(set(days))}) for q in PCTS},
                   "max": round(float(max(ex)), 3) if ex else None, "zeroDrives": int(sum(1 for x in ex if x <= 0)),
                   "gridLowerBracket": {f"p{q}": round(float(np.percentile(gr, q)), 3) for q in (50, 95)} if gr else None,
                   "shifted0p5": {f"p{q}": round(float(np.percentile(sh, q)), 3) for q in (50, 95)} if sh else None,
                   "exactMinusGrid": {"p50": round(float(np.percentile(np.array(ex) - np.array(gr), 50)), 4), "p95": round(float(np.percentile(np.array(ex) - np.array(gr), 95)), 4)} if ex else None,
                   "exposure600s": {f"p{q}": round(float(np.percentile(xp, q)), 3) for q in (50, 95)} if xp else None}
            if len(ex) > 2:
                el = [r["rec"]["byW"][str(W)]["eligS"] for r in sub]
                blk["spearmanWithEligibleDuration"] = round(float(pd.Series(ex).corr(pd.Series(el), method="spearman")), 3)
            for m in MIN_ELIG_S:
                s2 = [r for r in sub if r["rec"]["byW"][str(W)]["eligS"] >= m]
                e2 = [r["rec"]["byW"][str(W)][key] for r in s2]
                blk[f"eligibleAtLeast{int(m)}s"] = {"nDrives": len(s2), "p50": round(float(np.percentile(e2, 50)), 3) if e2 else None, "p95": round(float(np.percentile(e2, 95)), 3) if e2 else None}
            row[dirn] = blk
        el = [r["rec"]["byW"][str(W)]["eligS"] for r in sub]
        row["eligibleSeconds"] = {"p50": round(float(np.percentile(el, 50)), 1), "p90": round(float(np.percentile(el, 90)), 1)} if el else None
        res["byW"][str(W)] = row
    return res


# ---------------------------------------------------------------- driver
def load_records(only=None):
    import energy_packets as EP
    import ah_throughput as AH
    import compute_summary_arrays as C
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    bad = C._canonical_bad(dm)
    loader = AH.raw_loader()
    os.makedirs(CACHE, exist_ok=True)
    sh = hashlib.sha256((_src_hash() + EP._src_hash()).encode()).hexdigest()[:16]
    import compute_drive_summary_v6 as D
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
            df, t = D._prep_bytes(b)
            ps = EP.pair_stream(df, t)
            if ps is None:
                rec = {"ok": False}
            else:
                ts, P, _ = ps
                rec = {"ok": True, "rec": drive_record(ts, P)}
                st = EP.stream_runs(ts, P)
                rec["rec"]["gapNetKwh"] = float(st["gapDisc"] - st["gapChg"]); rec["rec"]["ledgerNetKwh"] = float(st["disc"] - st["chg"])
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            stats["extracted"] += 1
        if not rec.get("ok"):
            stats["notOk"] += 1
        rec = dict(rec)
        rec.update(file=fn, rawSha256=digest, cadence=cad.get(fn) if isinstance(cad.get(fn), str) else "unknown", canonClean=bool(not bad.iloc[i]),
                   day=(lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}")("".join(c for c in fn if c.isdigit())),
                   excluded=bool(pd.notna(r.get("energy_null_reason")) or r.get("sign_check") == "ANOMALY"))
        recs[fn] = rec
    return dm, recs, stats


def known_answers(dm, recs):
    n = {"ka4": 0, "ka5": 0, "ka6Drives": 0}
    bad = {"ka4": [], "ka5": [], "ka6": []}
    for _, r in dm.iterrows():
        a = recs.get(r["file"])
        if a is None or not a.get("ok") or a["excluded"]:
            continue
        x = a["rec"]; w5 = x["byW"]["5"]
        if pd.notna(r.get("peak_discharge_kw")) and pd.notna(r.get("peak_charge_kw")):
            n["ka4"] += 1
            if w5["dis"] > float(r["peak_discharge_kw"]) + TOL_PEAK_KW or w5["chg"] > max(0.0, -float(r["peak_charge_kw"])) + TOL_PEAK_KW:
                bad["ka4"].append((r["file"], round(w5["dis"], 3), float(r["peak_discharge_kw"]), round(w5["chg"], 3), float(r["peak_charge_kw"])))
        if pd.notna(r.get("net_draw_kwh")):
            n["ka5"] += 1
            tot = x["closureKwhSegments"] + x["gapNetKwh"]
            if abs(tot - float(r["net_draw_kwh"])) > TOL_CLOSURE_KWH or abs(tot - x["ledgerNetKwh"]) > TOL_CLOSURE_KWH:
                bad["ka5"].append((r["file"], round(tot, 6), float(r["net_draw_kwh"]), round(x["ledgerNetKwh"], 6)))
        n["ka6Drives"] += 1
        if x["ka6Violations"]:
            bad["ka6"].append((r["file"], x["ka6Violations"]))
    return {"n": n, "misses": {k: len(v) for k, v in bad.items()}, "examples": {k: v[:5] for k, v in bad.items()}}


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = set(json.load(open(os.path.join(ROOT, "analyses", "M552_audit_sample.json"), encoding="utf-8"))["files"])
    dm, recs, stats = load_records(only)
    ka = known_answers(dm, recs)
    res = {"milestone": "M552", "mode": mode, "stats": stats, "knownAnswer": ka, "extractorSourceHash": _src_hash()}
    if any(ka["misses"].values()):
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "known-answer miss", **ka}, default=float)); sys.exit(2)
    el = [r for r in recs.values() if r.get("ok") and not r["excluded"] and r["canonClean"]]
    res["populations"] = {"withPairs": int(sum(1 for r in recs.values() if r.get("ok"))), "excludedNullOrAnomaly": int(sum(1 for r in recs.values() if r.get("ok") and r["excluded"])),
                          "eligibleCanonicalClean": len(el), "notOk": stats["notOk"]}
    res["strata"] = {c: stratum_block([r for r in el if r["cadence"] == c]) for c in ("fast", "slow", "unknown") if any(r["cadence"] == c for r in el)}
    res["unknownCadenceDriveSharePct"] = round(100.0 * sum(1 for r in el if r["cadence"] == "unknown") / len(el), 2) if el else None
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((r["file"], r["rawSha256"]) for r in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    json.dump({f: r for f, r in recs.items()}, open(os.path.join(CACHE, "_all.json" if not only else "_sample.json"), "w", encoding="utf-8"), default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka, "populations": res["populations"], "unknownShare": res["unknownCadenceDriveSharePct"]}, default=float))
    if mode == "--splice" and not only:
        splice(res)


def splice(res):
    """additive write of S.powerDuration (+ stamp); no existing key changes."""
    flags = {}
    for c, st in res["strata"].items():
        f = {"shiftMovesP95MoreThanHalfWidth": False, "exactMinusGridP95Over5PctAtW5": False, "support120Under90Pct": False, "resolutionLimitedAt5s": bool(st["byW"]["5"]["resolutionLimited"])}
        for W, row in st["byW"].items():
            for dirn in ("discharge", "charge"):
                b = row[dirn]; ci = b["exact"]["p95"]["ci95"]
                if ci and b["gridLowerBracket"] and b["shifted0p5"]:
                    half = (ci[1] - ci[0]) / 2.0
                    if abs(b["shifted0p5"]["p95"] - b["gridLowerBracket"]["p95"]) > half:
                        f["shiftMovesP95MoreThanHalfWidth"] = True
                if W == "5" and b["exactMinusGrid"] and b["exact"]["p95"]["value"] and b["exactMinusGrid"]["p95"] > 0.05 * b["exact"]["p95"]["value"]:
                    f["exactMinusGridP95Over5PctAtW5"] = True
        f["support120Under90Pct"] = bool(st["byW"]["120"]["supportShareOfStratum"] is not None and st["byW"]["120"]["supportShareOfStratum"] < 0.9)
        flags[c] = f
    flags["unknownCadenceDriveSharePct"] = res["unknownCadenceDriveSharePct"]
    block = {"_provenance": "GENERATED by tools/power_duration.py (M552). Do not hand-edit.", "schemaVersion": 1,
             "basis": "raw bytes through the master's own current / voltage pairing (nearest voltage within 1.5 s), power piecewise linear between pair samples, support step <= 5 s; raw/ = sha256-verified originals (M366); app-reported BMS channels (logged, not measured); the power is a reconstructed I x V product",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]},
             "rule": {"windowsS": list(WINDOWS), "primary": "exact continuous-start extremum of the window mean per segment (breakpoints plus roots of P(s + W) = P(s))", "lowerBracket": "1 s start grid anchored at each segment start",
                      "sensitivity": "the same grid shifted by 0.5 s; eligible-duration subsets >= 600 s / 1800 s; the extreme within the first 600 s of eligible time",
                      "discharge": "max(0, max window mean)", "charge": "max(0, -min window mean), reported as a magnitude", "gap": "raw step > 5 s ends the segment; no window spans a gap",
                      "strata": "logger cadence regime (fast / slow / unknown); no pooled headline, no contrast between strata",
                      "intervals": f"day-clustered percentile bootstrap, seed {SEED}, {DRAWS} draws; per-drive-weighted percentile; only if n_drives*(1-q) >= 5 and days >= {MIN_DAYS} (p99 days >= {MIN_DAYS_P99}); never for the maximum"},
             "populations": res["populations"], "knownAnswer": res["knownAnswer"], "strata": res["strata"], "flags": flags,
             "limits": ["observed, window-based extrema of a logged, reconstructed I x V power: not ratings, capabilities, limits, operating-condition percentiles or time-weighted percentiles; longer windows can include reversals (net moving means)",
                        "the per-drive maximum rises with the eligible time of the drive (more windows): the Spearman correlation with eligible duration, the 600 s exposure-standardised extreme and the duration-restricted subsets are given beside the primary",
                        "the 1 s grid value is a start-grid dependent lower approximation of the exact value", "the strata are not comparable (cadence invariance fails); no pooled value is given",
                        "the percentiles are per-drive-weighted: a long drive and a short drive count once each",
                        "the uninterrupted-direction variant of the audit is not built here (named follow-up); speed, SoC and temperature at the argmax are cached, unanalysed"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("powerDuration", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "powerDuration"}
    A2["powerDuration"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M552: computed by tools/power_duration.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["powerDuration"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "powerDuration"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"powerDuration": "written"}))


if __name__ == "__main__":
    main()
