#!/usr/bin/env python3
"""M553 (spec analyses/M553_spec.md Rev 2): how much of the assumed battery window the drives use (audit 2026-10-29 N13), per logger-cadence stratum.
Substrate = the master's own current / voltage pair stream (same pairing as energy_packets.pair_stream, but the signed discharge current is kept), signal piecewise linear between pair samples,
a raw step > 5 s is a gap that ends the segment (nothing is bridged). Per drive: the net charge Q(t) = integral of Id dt (Ah, integrated, estimated) and the terminal energy E(t) = integral of P dt (kWh) per segment;
the excursion of a segment is max - min of its trace (exact: the interior extremum at a zero crossing of the linear signal is included). Upper bracket = sum of segment excursions (primary, conservative against the thesis),
lower bracket = the largest single segment. Offset sensitivities use Id - I_offset_A_applied and Id - I_offset_2p_A_applied.
Known answers (STOP on a miss): closure to net_draw_kwh, |sum of segment nets| <= excursion <= gross_throughput_kwh (basis stated). Per-drive records are cached by the raw sha256 and the extractor source hash (window_cache/, git-ignored).
Modes: --check (writes analyses/M553_check.json) | --splice (check + additive write of S.windowUse). Usage: python tools/window_use.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M553_check.json")
CACHE = os.path.join(ROOT, "window_cache")
GAP_S = 5.0
CAPS = (1.5, 2.1, 3.0)                 # assumed windows (kWh), CAP_KWH = 2.1 verified:false and unchanged
CAP_MAIN = 2.1
AH_LEAD = 5.0                          # OEM Article-10 rated 5 Ah: an Ah twin, a lead, not adopted
SHARES = (0.25, 0.5, 1.0)
MIN_ELIG_S = (600.0, 1800.0)
PCTS = (50, 90, 95, 99)
R_THRESHOLD, WINDOW_USED_MAX = 2.0, 0.05
TOL_CLOSURE_KWH, TOL_GROSS_KWH = 1e-4, 1e-4


# ---------------------------------------------------------------- kernel (pure, unit-tested)
def excursion(ts, y):
    """ts seconds (non-decreasing), y signal piecewise linear between samples (A or kW). Returns the per-drive excursion of Q = integral of y dt / 3600 (Ah or kWh) over the supported segments."""
    ts = np.asarray(ts, float); y = np.asarray(y, float)
    dt = np.diff(ts)
    brk = np.flatnonzero(dt > GAP_S)
    edges = [0] + [int(b) + 1 for b in brk] + [len(ts)]
    ranges, nets = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        t, v = ts[a:b], y[a:b]
        if len(t) < 2:
            ranges.append(0.0); nets.append(0.0); continue
        d = np.diff(t)
        q = np.concatenate([[0.0], np.cumsum((v[:-1] + v[1:]) / 2.0 * d / 3600.0)])
        cand = [q]
        cross = np.flatnonzero((d > 0) & (v[:-1] * v[1:] < 0))
        if len(cross):
            tau = d[cross] * v[cross] / (v[cross] - v[cross + 1])
            cand.append(q[cross] + (v[cross] * tau + (v[cross + 1] - v[cross]) * tau * tau / (2.0 * d[cross])) / 3600.0)
        allq = np.concatenate(cand)
        ranges.append(float(allq.max() - allq.min())); nets.append(float(q[-1]))
    span = float(ts[-1] - ts[0]) if len(ts) > 1 else 0.0
    gap = float(dt[dt > GAP_S].sum()) if len(dt) else 0.0
    return {"upper": float(sum(ranges)), "lower": float(max(ranges)) if ranges else 0.0, "netSegSum": float(sum(nets)), "nSeg": len(ranges),
            "supportedS": float(dt[dt <= GAP_S].sum()) if len(dt) else 0.0, "gapS": gap, "gapShare": (gap / span) if span > 0 else 0.0}


def pairs(df, t):
    """the master's own pairing (identical to energy_packets.pair_stream) with the signed discharge current: (ts, Id A, V) or None."""
    import compute_drive_summary_v6 as D
    I = D._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    V = D._series(df, t, "V", lo=200, hi=450)
    if I is None or V is None or len(I) <= 2:
        return None
    e = D._asof(I.copy(), V, "V", D.V_ALIGN_TOL).dropna(subset=["V"])
    if len(e) < 2:
        return None
    Id = -e["v"].to_numpy(dtype=float)
    tn = e["t"].values.astype("datetime64[ns]").astype("int64")
    return (tn - tn[0]) / 1e9, Id, e["V"].to_numpy(dtype=float)


def drive_record(ts, Id, V, off=0.0, off2=0.0):
    rec = {"ah": excursion(ts, Id), "kwh": excursion(ts, Id * V / 1000.0)}
    rec["ahOff"] = excursion(ts, Id - off)["upper"]; rec["kwhOff"] = excursion(ts, (Id - off) * V / 1000.0)["upper"]
    rec["ahOff2p"] = excursion(ts, Id - off2)["upper"]; rec["kwhOff2p"] = excursion(ts, (Id - off2) * V / 1000.0)["upper"]
    return rec


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (excursion, pairs, drive_record)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- aggregation
def _boot(vals, days, fn, seed=42, draws=4000):
    """day-clustered percentile bootstrap of fn(values): days resampled, drives kept inside their day."""
    v = np.asarray(vals, float)
    ud = sorted(set(days)); by = {u: v[[i for i, d in enumerate(days) if d == u]] for u in ud}
    rng = np.random.default_rng(seed); idx = rng.integers(0, len(ud), size=(draws, len(ud)))
    bs = [fn(np.concatenate([by[ud[j]] for j in row])) for row in idx]
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return [float(lo), float(hi)]


def _pct(vals, days, q):
    import power_duration as PD
    return PD._pct_boot(vals, days, q)


def _partial_spearman(x, y, z):
    rx, ry, rz = (pd.Series(a).rank().to_numpy() for a in (x, y, z))
    def res(a, b):
        A = np.vstack([np.ones_like(b), b]).T
        return a - A @ np.linalg.lstsq(A, a, rcond=None)[0]
    return float(np.corrcoef(res(rx, rz), res(ry, rz))[0, 1])


def stratum_block(recs, soc_range):
    res = {"nDrives": len(recs), "nDays": len({r["day"] for r in recs})}
    days = [r["day"] for r in recs]
    up = np.array([r["rec"]["ah"]["upper"] for r in recs]); lo = np.array([r["rec"]["ah"]["lower"] for r in recs])
    ku = np.array([r["rec"]["kwh"]["upper"] for r in recs]); kl = np.array([r["rec"]["kwh"]["lower"] for r in recs])
    pts = np.array([r["socMax"] - r["socMin"] for r in recs]); dur = np.array([r["durationS"] for r in recs])
    gross = np.array([r["gross"] for r in recs])
    res["populationNote"] = "canonical-clean drives without energy_null_reason or sign ANOMALY with reported SoC and a pair stream"
    res["referenceFree"] = {
        "netChargeExcursionAhUpper": {f"p{q}": _pct(up, days, q) for q in PCTS}, "netChargeExcursionAhLower": {f"p{q}": round(float(np.percentile(lo, q)), 4) for q in (50, 95)},
        "reportedSocExcursionPoints": {f"p{q}": _pct(pts, days, q) for q in PCTS},
        "socExcursionShareOfObservedRange": {f"p{q}": round(float(np.percentile(pts / soc_range["widthPoints"], q)), 4) for q in (50, 90, 95)},
        "observedSocRange": soc_range,
        "ahTwinOverRatedLead": {"leadAh": AH_LEAD, "label": "lead, not adopted", **{f"p{q}": round(float(np.percentile(up / AH_LEAD, q)), 4) for q in (50, 95)}},
        "upperOverLowerBracket": {"p50": round(float(np.percentile(up[lo > 0] / lo[lo > 0], 50)), 3), "p95": round(float(np.percentile(up[lo > 0] / lo[lo > 0], 95)), 3)} if (lo > 0).any() else None,
        "gapShare": {"p50": round(float(np.percentile([r["rec"]["ah"]["gapShare"] for r in recs], 50)), 4), "p95": round(float(np.percentile([r["rec"]["ah"]["gapShare"] for r in recs], 95)), 4),
                     "drivesOver10Pct": int(sum(1 for r in recs if r["rec"]["ah"]["gapShare"] > 0.10))}}
    res["assumedWindow"] = {}
    for cap in CAPS:
        sh = ku / cap
        row = {"capKwh": cap, "verified": False, "shareUpper": {f"p{q}": _pct(sh, days, q) for q in PCTS}}
        for th in SHARES:
            f = (sh >= th).astype(float)
            row[f"drivesWithShareAtLeast{th}"] = {"share": round(float(f.mean()), 4), "n": int(f.sum()),
                                                  "ci95": [round(c, 4) for c in _boot(f, days, np.mean)] if len(set(days)) >= 5 else None}
        row["shareLowerBracket"] = {f"p{q}": round(float(np.percentile(kl / cap, q)), 4) for q in (50, 95)}
        res["assumedWindow"][str(cap)] = row
    ok = ku > 0
    R = gross[ok] / ku[ok]; rd = [d for d, o in zip(days, ok) if o]
    medci = _boot(R, rd, np.median) if len(set(rd)) >= 5 else None
    rl = gross[ku > 0] / np.maximum(kl[ku > 0], 1e-12)
    used = {c: res["assumedWindow"][str(c)]["drivesWithShareAtLeast1.0"]["share"] for c in (1.5, 2.1)}
    res["throughputOverExcursion"] = {"definition": "R = gross_throughput_kwh / terminal-energy excursion (upper bracket); CAP-free", "median": round(float(np.median(R)), 3), "ci95": [round(c, 3) for c in medci] if medci else None,
                                      "p5": round(float(np.percentile(R, 5)), 3), "nDrives": int(ok.sum()), "nDays": len(set(rd)), "excludedZeroExcursion": int((~ok).sum()), "medianLowerBracket": round(float(np.median(rl)), 3)}
    for c in (1.5, 2.1):
        res["throughputOverExcursion"][f"verdictAtCap{c}"] = ("consistent with buffer use" if (medci and medci[0] > R_THRESHOLD and used[c] <= WINDOW_USED_MAX) else "not supported")
    res["throughputOverExcursion"]["rule"] = f"consistent with buffer use iff lower 95 % bound of median R > {R_THRESHOLD} AND share of drives with share >= 1.0 <= {WINDOW_USED_MAX}; otherwise not supported"
    if len(recs) > 2:
        res["socVersusCharge"] = {"spearman": round(float(pd.Series(pts).corr(pd.Series(up), method="spearman")), 3), "partialOnDuration": round(_partial_spearman(pts, up, dur), 3),
                                  "spearmanWithDuration": {"ah": round(float(pd.Series(up).corr(pd.Series(dur), method="spearman")), 3)}}
    res["durationSubsets"] = {}
    for m in MIN_ELIG_S:
        s = dur >= m
        res["durationSubsets"][f"atLeast{int(m)}s"] = {"nDrives": int(s.sum()), "medianR": round(float(np.median(gross[s & ok] / ku[s & ok])), 3) if (s & ok).any() else None,
                                                       "shareAtLeast1At2p1": round(float((ku[s] / CAP_MAIN >= 1).mean()), 4) if s.any() else None}
    off = np.array([r["rec"]["kwhOff"] for r in recs]); off2 = np.array([r["rec"]["kwhOff2p"] for r in recs])
    res["offsetSensitivity"] = {"removedOffset": {"p95KwhExcursion": round(float(np.percentile(off, 95)), 4), "classificationFlips": int(((off / CAP_MAIN >= 1) != (ku / CAP_MAIN >= 1)).sum()),
                                                  "shareAtLeast1At2p1": round(float((off / CAP_MAIN >= 1).mean()), 4)},
                                "removedOffset2p": {"p95KwhExcursion": round(float(np.percentile(off2, 95)), 4), "classificationFlips": int(((off2 / CAP_MAIN >= 1) != (ku / CAP_MAIN >= 1)).sum()),
                                                    "shareAtLeast1At2p1": round(float((off2 / CAP_MAIN >= 1).mean()), 4)},
                                "primaryP95KwhExcursion": round(float(np.percentile(ku, 95)), 4)}
    for k, arr in (("removedOffset", off), ("removedOffset2p", off2)):
        res["offsetSensitivity"][k]["shareAtLeast1At1p5"] = round(float((arr / 1.5 >= 1).mean()), 4)
    flips = []
    for i, r in enumerate(recs):
        if (off[i] / CAP_MAIN >= 1) != (ku[i] / CAP_MAIN >= 1):
            exp = abs(r["iOff"]) * r["durationS"] * r["vMed"] / 3.6e6 if r["vMed"] else None
            flips.append({"file": r["file"], "durationS": r["durationS"], "upperKwh": round(float(ku[i]), 4), "lowerKwh": round(float(kl[i]), 4), "upperKwhOffsetRemoved": round(float(off[i]), 4),
                          "deltaKwh": round(float(ku[i] - off[i]), 4), "expectedDeltaKwhFromOffset": round(exp, 4) if exp is not None else None, "gapShare": round(float(r["rec"]["ah"]["gapShare"]), 4)})
    res["offsetSensitivity"]["classificationFlipDrives"] = flips
    return res


# ---------------------------------------------------------------- driver
def load_records(only=None):
    import ah_throughput as AH
    import compute_summary_arrays as C
    import energy_packets as EP
    import compute_drive_summary_v6 as D
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    bad = C._canonical_bad(dm)
    loader = AH.raw_loader()
    os.makedirs(CACHE, exist_ok=True)
    sh = hashlib.sha256((_src_hash() + EP._src_hash()).encode()).hexdigest()[:16]
    recs, stats = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "notOk": 0}
    for i, r in dm.iterrows():
        fn = r["file"]
        if only and fn not in only:
            continue
        b = loader(fn)
        if b is None:
            stats["noRaw"] += 1; continue
        off = float(r["I_offset_A_applied"]) if pd.notna(r.get("I_offset_A_applied")) else 0.0
        off2 = float(r["I_offset_2p_A_applied"]) if pd.notna(r.get("I_offset_2p_A_applied")) else 0.0
        digest = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE, f"{digest}_{sh}_{off:.4f}_{off2:.4f}.json")
        if os.path.exists(cp):
            rec = json.load(open(cp, encoding="utf-8")); stats["cacheHits"] += 1
        else:
            df, t = D._prep_bytes(b)
            ps = pairs(df, t)
            if ps is None:
                rec = {"ok": False}
            else:
                ts, Id, V = ps
                rec = {"ok": True, "rec": drive_record(ts, Id, V, off, off2)}
                st = EP.stream_runs(ts, Id * V / 1000.0)
                rec["rec"]["gapNetKwh"] = float(st["gapDisc"] - st["gapChg"])
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            stats["extracted"] += 1
        if not rec.get("ok"):
            stats["notOk"] += 1
        rec = dict(rec)
        rec.update(file=fn, rawSha256=digest, cadence=cad.get(fn) if isinstance(cad.get(fn), str) else "unknown", canonClean=bool(not bad.iloc[i]),
                   day=(lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}")("".join(c for c in fn if c.isdigit())),
                   excluded=bool(pd.notna(r.get("energy_null_reason")) or r.get("sign_check") == "ANOMALY"),
                   socMin=float(r["soc_min"]) if pd.notna(r.get("soc_min")) else None, socMax=float(r["soc_max"]) if pd.notna(r.get("soc_max")) else None,
                   gross=float(r["gross_throughput_kwh"]) if pd.notna(r.get("gross_throughput_kwh")) else None, durationS=float(r["duration_s"]), iOff=off, vMed=float(r["V_pack_median"]) if pd.notna(r.get("V_pack_median")) else None, netDraw=float(r["net_draw_kwh"]) if pd.notna(r.get("net_draw_kwh")) else None)
        recs[fn] = rec
    return dm, recs, stats


def known_answers(recs):
    n = {"closure": 0, "bounds": 0}
    bad = {"closure": [], "bounds": []}
    for fn, a in recs.items():
        if not a.get("ok") or a["excluded"] or a["netDraw"] is None or a["gross"] is None:
            continue
        x = a["rec"]
        n["closure"] += 1
        tot = x["kwh"]["netSegSum"] + x["gapNetKwh"]
        if abs(tot - a["netDraw"]) > TOL_CLOSURE_KWH:
            bad["closure"].append((fn, round(tot, 6), a["netDraw"]))
        n["bounds"] += 1
        if not (abs(x["kwh"]["netSegSum"]) <= x["kwh"]["upper"] + 1e-9 and x["kwh"]["upper"] <= a["gross"] + TOL_GROSS_KWH and x["kwh"]["lower"] <= x["kwh"]["upper"] + 1e-12):
            bad["bounds"].append((fn, round(abs(x["kwh"]["netSegSum"]), 6), round(x["kwh"]["upper"], 6), a["gross"]))
    return {"n": n, "misses": {k: len(v) for k, v in bad.items()}, "examples": {k: v[:5] for k, v in bad.items()}}


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = set(json.load(open(os.path.join(ROOT, "analyses", "M553_audit_sample.json"), encoding="utf-8"))["files"])
    dm, recs, stats = load_records(only)
    ka = known_answers(recs)
    res = {"milestone": "M553", "mode": mode, "stats": stats, "knownAnswer": ka, "extractorSourceHash": _src_hash()}
    if any(ka["misses"].values()):
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "known-answer miss", **ka}, default=float)); sys.exit(2)
    base = [r for r in recs.values() if r.get("ok") and not r["excluded"] and r["canonClean"]]
    el = [r for r in base if r["socMin"] is not None and r["socMax"] is not None and r["gross"] is not None]
    res["populations"] = {"withPairs": int(sum(1 for r in recs.values() if r.get("ok"))), "excludedNullOrAnomaly": int(sum(1 for r in recs.values() if r.get("ok") and r["excluded"])),
                          "notCanonicalClean": int(sum(1 for r in recs.values() if r.get("ok") and not r["excluded"] and not r["canonClean"])), "noReportedSocOrThroughput": len(base) - len(el),
                          "eligible": len(el), "notOk": stats["notOk"]}
    soc_range = {"widthPoints": round(float(np.percentile([r["socMax"] for r in el], 99.5) - np.percentile([r["socMin"] for r in el], 0.5)), 3),
                 "lowP0_5": round(float(np.percentile([r["socMin"] for r in el], 0.5)), 3), "highP99_5": round(float(np.percentile([r["socMax"] for r in el], 99.5)), 3), "label": "observed range, not a BMS limit"}
    res["strata"] = {c: stratum_block([r for r in el if r["cadence"] == c], soc_range) for c in ("fast", "slow", "unknown") if sum(1 for r in el if r["cadence"] == c) > 2}
    res["unknownCadenceDriveSharePct"] = round(100.0 * sum(1 for r in el if r["cadence"] == "unknown") / len(el), 2) if el else None
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((r["file"], r["rawSha256"]) for r in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    json.dump({f: r for f, r in recs.items()}, open(os.path.join(CACHE, "_all.json" if not only else "_sample.json"), "w", encoding="utf-8"), default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka, "populations": res["populations"], "unknownShare": res["unknownCadenceDriveSharePct"]}, default=float))
    if mode == "--splice" and not only:
        splice(res)


def splice(res):
    """additive write of S.windowUse (+ stamp); no existing key changes."""
    flags = {}
    for c, st in res["strata"].items():
        t = st["throughputOverExcursion"]; a15 = st["assumedWindow"]["1.5"]["drivesWithShareAtLeast1.0"]["share"]; a21 = st["assumedWindow"]["2.1"]["drivesWithShareAtLeast1.0"]["share"]
        ub = st["referenceFree"]["upperOverLowerBracket"]; gs = st["referenceFree"]["gapShare"]; so = st.get("socVersusCharge")
        flags[c] = {"windowUsedOver5PctAt2p1": a21 > WINDOW_USED_MAX, "windowUsedOver5PctAt1p5": a15 > WINDOW_USED_MAX,
                    "partialCorrelationBelow0p5": bool(so and st["nDays"] >= 20 and so["partialOnDuration"] < 0.5),
                    "medianRIntervalContainsThreshold": bool(t["ci95"] and t["ci95"][0] <= R_THRESHOLD <= t["ci95"][1]),
                    "verdictDiffersBetweenCaps": t["verdictAtCap1.5"] != t["verdictAtCap2.1"],
                    "upperOverLowerP95Over2": bool(ub and ub["p95"] > 2), "gapShareOver10PctInOver10PctOfDrives": bool(gs["drivesOver10Pct"] > 0.10 * st["nDrives"]),
                    "offsetFlipsClassification": bool(st["offsetSensitivity"]["removedOffset"]["classificationFlips"] or st["offsetSensitivity"]["removedOffset2p"]["classificationFlips"])}
    flags["unknownCadenceDriveSharePct"] = res["unknownCadenceDriveSharePct"]
    block = {"_provenance": "GENERATED by tools/window_use.py (M553). Do not hand-edit.", "schemaVersion": 1,
             "basis": "raw bytes through the master's own current / voltage pairing (nearest voltage within 1.5 s), signal piecewise linear between pair samples, support step <= 5 s; raw/ = sha256-verified originals (M366); app-reported BMS channels (logged, not measured); the energy is a reconstructed terminal I x V integral",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]},
             "rule": {"primary": "upper bracket = sum over supported segments of (max - min) of the integrated net charge (Ah) or terminal energy (kWh), exact including the interior extremum at a zero crossing", "lowerBracket": "the largest single segment",
                      "assumedWindow": "CAP_KWH 2.1 kWh (verified:false, unchanged) with the sensitivity grid 1.5 / 2.1 / 3.0 kWh; the OEM rated 5 Ah enters only as an Ah twin (lead, not adopted)",
                      "referenceFree": "net charge excursion in Ah, reported SoC excursion in points, and the SoC excursion over the corpus-observed range", "R": "gross_throughput_kwh / terminal-energy excursion, CAP-free",
                      "verdict": f"consistent with buffer use iff lower 95 % bound of median R > {R_THRESHOLD} AND share of drives with share >= 1.0 at the cap <= {WINDOW_USED_MAX}; otherwise not supported",
                      "strata": "logger cadence regime (fast / slow / unknown); no pooled headline, no contrast between strata", "intervals": "day-clustered percentile bootstrap, seed 42, 4000 draws; per-drive-weighted; same support rules as M552"},
             "populations": res["populations"], "knownAnswer": res["knownAnswer"], "strata": res["strata"], "flags": flags,
             "limits": ["Ah is the primary quantity; kWh is terminal energy (includes I^2R), not stored energy; the reported SoC is a BMS display value in 0.5-point steps, not an energy meter",
                        "reported SoC confinement is a controller policy, not proof of capacity", "SoC and the integrated charge extremes are not time-aligned", "CAP_KWH = 2.1 is verified:false and unchanged; the OEM rated 5 Ah is a lead only",
                        "the upper bracket adds segment excursions (no bridging of gaps); the lower bracket is the largest single segment", "the strata are not comparable (cadence invariance fails); no pooled value is given",
                        "a verdict of not supported is not evidence against buffer use and consistent with buffer use is not a proof; no capacity, depth-of-discharge or state-of-health quantity is estimated here"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("windowUse", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "windowUse"}
    A2["windowUse"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M553: computed by tools/window_use.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["windowUse"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "windowUse"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"windowUse": "written"}))


if __name__ == "__main__":
    main()
