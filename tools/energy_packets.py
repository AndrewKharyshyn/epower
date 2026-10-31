#!/usr/bin/env python3
"""M551 (spec analyses/M551_spec.md Rev 2): energy packets (N01) = observed same-sign electrical exchange runs of the HV battery, with boundary censoring, per logger-cadence stratum (audit 2026-10-29 N01).
Substrate: the master's own current / voltage pairing (D._prep_bytes, D._series, D._asof, V_ALIGN_TOL; |I| < 900, V 200..450; Id = -I, P = Id * V / 1000, discharge positive); power is piecewise linear between pair
samples and each interval is split exactly like the released ledger (F01 / M229 zero-crossing-aware directional integration, step capped at DT_CAP_S = 5 s). An interval with raw step > 5 s is a GAP: it breaks the segment and its capped
energy is carried by direction (gapBridged*). A run = maximal same-sign chain of directional portions inside one segment; idle intervals (both endpoints zero) and a sign change across a duplicate timestamp break a run; a mid-segment break is an
OBSERVED end; a run is censored only at a segment edge (first / last portion of the segment with no break before / after it). Reconciliation to the master ledger is a known answer (STOP on a miss). Per-drive records are cached by the raw
sha256 and the extractor source hash (packet_cache/, git-ignored); aggregation never rereads raw.
Modes: --check (writes analyses/M551_check.json) | --splice (check + additive write of S.energyPackets). Usage: python tools/energy_packets.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M551_check.json")
CACHE = os.path.join(ROOT, "packet_cache")
DT_CAP_S = 5.0
DEADBANDS_A = (1.0, 2.0, 5.0)
THRESH_WH = (0.5, 1.0, 2.0)
SEED, DRAWS = 42, 4000
MIN_DAYS_INTERVAL, MIN_DAYS_P99 = 5, 20
BIN_DEC = 0.02                                  # histogram resolution: 0.02 decade of Wh and of s
EDGES = np.arange(-4.0, 4.0 + BIN_DEC / 2, BIN_DEC)     # log10 bin edges (Wh: 1e-4 .. 1e4; s: 1e-4 .. 1e4)
TOL_TOTAL_KWH, TOL_SIDE_KWH = 1e-4, 5e-5


# ---------------------------------------------------------------- kernel (pure, unit-tested)
def stream_runs(ts, P):
    """ts: float seconds (monotonic non-decreasing expected), P: kW (discharge positive), aligned. Returns the runs and the ledger totals of the stream.
    Run table keys: sign (+1 discharge / -1 charge), wh, dur_s, cens_start, cens_end, seg. Totals in kWh: disc, chg (all intervals incl. gaps), gapDisc, gapChg."""
    ts = np.asarray(ts, float); P = np.asarray(P, float)
    n = len(ts)
    out = {"sign": [], "wh": [], "dur_s": [], "cens_start": [], "cens_end": [], "seg": [], "disc": 0.0, "chg": 0.0, "gapDisc": 0.0, "gapChg": 0.0,
           "nIntervals": max(n - 1, 0), "nGaps": 0, "nZeroDt": 0, "nIdle": 0, "nSegments": 0}
    if n < 2:
        return out
    raw = np.diff(ts)
    d = np.clip(raw, 0.0, DT_CAP_S)
    dh = d / 3600.0
    p0, p1 = P[:-1], P[1:]
    absum = np.abs(p0) + np.abs(p1)
    den = np.where(absum > 0, 2.0 * absum, 1.0)
    cross = (p0 * p1) < 0
    disc_c = dh * ((p0 > 0) * p0 ** 2 + (p1 > 0) * p1 ** 2) / den
    chg_c = dh * ((p0 < 0) * p0 ** 2 + (p1 < 0) * p1 ** 2) / den
    signed = dh * (p0 + p1) / 2.0
    disc = np.where(cross, disc_c, np.where(signed > 0, signed, 0.0))
    chg = np.where(cross, chg_c, np.where(signed < 0, -signed, 0.0))
    gap = raw > DT_CAP_S
    zero = raw <= 0
    out["disc"], out["chg"] = float(disc.sum()), float(chg.sum())
    out["gapDisc"], out["gapChg"] = float(disc[gap].sum()), float(chg[gap].sum())
    out["nGaps"], out["nZeroDt"] = int(gap.sum()), int(zero.sum())
    idle = (~gap) & (~zero) & (disc <= 0) & (chg <= 0)
    zbreak = zero & cross
    out["nIdle"] = int(idle.sum())
    brk = gap | idle | zbreak                                   # break markers (a run cannot continue across them)
    seg = np.cumsum(np.concatenate([[0], gap[:-1].astype(int)]))     # segment id of each interval: the number of gap intervals before it (a gap interval closes the segment it ends)
    out["nSegments"] = int(len(np.unique(seg[~gap]))) if (~gap).any() else 0
    live = (~gap) & (~zero)
    # portions in time order
    idx_l, sg_l, en_l, du_l = [], [], [], []
    ii = np.flatnonzero(live)
    c = cross[ii]
    ncr = ii[~c]
    for_pos = ncr[(disc[ncr] > 0)]; for_neg = ncr[(chg[ncr] > 0)]
    # non-crossing portions
    idx_l += [for_pos, for_neg]; sg_l += [np.ones(len(for_pos)), -np.ones(len(for_neg))]
    en_l += [disc[for_pos], chg[for_neg]]; du_l += [d[for_pos], d[for_neg]]
    # crossing: two portions, order by the sign of p0
    cr = ii[c]
    f = np.abs(p0[cr]) / absum[cr]
    first_sign = np.where(p0[cr] > 0, 1.0, -1.0)
    e_first = np.where(p0[cr] > 0, disc[cr], chg[cr]); e_second = np.where(p0[cr] > 0, chg[cr], disc[cr])
    idx_l += [cr, cr]; sg_l += [first_sign, -first_sign]; en_l += [e_first, e_second]; du_l += [f * d[cr], (1 - f) * d[cr]]
    ordr = np.array([0] * len(for_pos) + [0] * len(for_neg) + [0] * len(cr) + [1] * len(cr))      # 0 = first portion of an interval, 1 = second
    pidx = np.concatenate(idx_l) if idx_l else np.array([], int)
    psg = np.concatenate(sg_l); pen = np.concatenate(en_l); pdu = np.concatenate(du_l)
    if len(pidx) == 0:
        return out
    o = np.lexsort((ordr, pidx))
    pidx, psg, pen, pdu, pord = pidx[o], psg[o], pen[o], pdu[o], ordr[o]
    B = np.cumsum(brk.astype(int))                               # B[i] = number of break markers at intervals <= i
    # a portion continues the previous run iff same sign and no break marker strictly between their intervals
    same = np.zeros(len(pidx), bool)
    if len(pidx) > 1:
        same[1:] = (psg[1:] == psg[:-1]) & ((B[pidx[1:]] - B[pidx[:-1]]) == 0) & (seg[pidx[1:]] == seg[pidx[:-1]])
    run = np.cumsum(~same) - 1
    nr = int(run[-1]) + 1
    wh = np.bincount(run, weights=pen, minlength=nr) * 1000.0
    dur = np.bincount(run, weights=pdu, minlength=nr)
    sign = np.zeros(nr); sign[run] = psg
    first_p = np.flatnonzero(~same); last_p = np.concatenate([first_p[1:] - 1, [len(pidx) - 1]])
    # segment edges: first / last portion of each segment, with no break marker before / after it inside the segment
    intervals_idx = np.arange(len(raw))
    seg_lo = {s: int(intervals_idx[seg == s][0]) for s in np.unique(seg)}
    seg_hi = {s: int(intervals_idx[(seg == s) & (~gap)][-1]) if ((seg == s) & (~gap)).any() else -1 for s in np.unique(seg)}
    cs = np.zeros(nr, bool); ce = np.zeros(nr, bool)
    segp = seg[pidx]
    for s in np.unique(segp):
        pm = np.flatnonzero(segp == s)
        lo, hi = seg_lo[s], seg_hi[s]
        p_first, p_last = pm[0], pm[-1]
        before = B[pidx[p_first]] - (B[lo - 1] if lo > 0 else 0)
        after = B[hi] - B[pidx[p_last]]
        # the break marker AT the portion's own interval does not exist (live intervals are not breaks)
        if before == 0 and pord[p_first] == 0:
            cs[run[p_first]] = True
        if after == 0:
            ce[run[p_last]] = True
    out.update(sign=sign.astype(int).tolist(), wh=wh.tolist(), dur_s=dur.tolist(), cens_start=cs.tolist(), cens_end=ce.tolist(),
               seg=[int(x) for x in np.bincount(run, weights=segp, minlength=nr) / np.maximum(np.bincount(run, minlength=nr), 1)])
    return out


def pair_stream(df, t):
    """the master's own pairing: returns (ts seconds from the first sample, P kW, |I| A) or None."""
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
    P = Id * e["V"].to_numpy(dtype=float) / 1000.0
    ts = (e["t"].values.astype("datetime64[ns]").astype("int64") - e["t"].values.astype("datetime64[ns]").astype("int64")[0]) / 1e9
    return ts, P, np.abs(e["v"].to_numpy(dtype=float))


def _compact(r):
    """round and keep only what the aggregation needs"""
    return {k: ([round(x, 6) for x in v] if k in ("wh", "dur_s") else v) for k, v in r.items()}


def extract(csv_bytes):
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(csv_bytes)
    ps = pair_stream(df, t)
    if ps is None:
        return {"ok": False}
    ts, P, Ia = ps
    base = stream_runs(ts, P)
    rec = {"ok": True, "base": _compact(base), "nPairs": int(len(ts))}
    for k in DEADBANDS_A:
        v = stream_runs(ts, np.where(Ia <= k, 0.0, P))
        c = np.array(v["cens_start"], bool) | np.array(v["cens_end"], bool)
        wh = np.array(v["wh"]); sg = np.array(v["sign"])
        comp = ~c
        rec[f"db{int(k)}"] = {"nComplete": int(comp.sum()), "nBelow1": int((comp & (wh < 1.0)).sum()), "whComplete": float(wh[comp].sum()), "whBelow1": float(wh[comp & (wh < 1.0)].sum()),
                              "residualDisc": base["disc"] - v["disc"], "residualChg": base["chg"] - v["chg"]}
    return rec


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (stream_runs, pair_stream, _compact, extract)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- aggregation
def _hist(x):
    h, _ = np.histogram(np.log10(np.clip(x, 1e-4, 1e4)), bins=EDGES)
    return h


def _q_from_hist(h, q):
    c = np.cumsum(h)
    if c[-1] == 0:
        return None
    k = int(np.searchsorted(c, q * c[-1]))
    return float(10 ** (EDGES[min(k, len(EDGES) - 2)] + BIN_DEC / 2))


def _qint(vals_by_day, q, mindays):
    """pooled-run quantile from per-day histograms; interval by resampling days. vals_by_day: {day: hist}"""
    days = sorted(vals_by_day)
    H = np.array([vals_by_day[d] for d in days])
    pt = _q_from_hist(H.sum(0), q)
    if pt is None:
        return None
    if len(days) < mindays:
        return {"value": round(pt, 4), "ci95": None, "nDays": len(days)}
    rng = np.random.default_rng(SEED); idx = rng.integers(0, len(days), size=(DRAWS, len(days)))
    bs = [_q_from_hist(H[row].sum(0), q) for row in idx]
    lo, hi = np.quantile([b for b in bs if b is not None], [0.025, 0.975])
    return {"value": round(pt, 4), "ci95": [round(float(lo), 4), round(float(hi), 4)], "nDays": len(days)}


def _ratio(num_by_day, den_by_day):
    days = sorted(den_by_day)
    n = np.array([num_by_day.get(d, 0.0) for d in days], float); dn = np.array([den_by_day[d] for d in days], float)
    if dn.sum() <= 0:
        return {"pct": None, "ci95Pct": None, "nDays": len(days)}
    pt = 100.0 * n.sum() / dn.sum()
    if len(days) < MIN_DAYS_INTERVAL:
        return {"pct": round(pt, 3), "ci95Pct": None, "nDays": len(days)}
    rng = np.random.default_rng(SEED); idx = rng.integers(0, len(days), size=(DRAWS, len(days)))
    db = dn[idx].sum(1); ok = db > 0
    bs = 100.0 * n[idx].sum(1)[ok] / db[ok]
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return {"pct": round(pt, 3), "ci95Pct": [round(float(lo), 3), round(float(hi), 3)], "nDays": len(days)}


def stratum_block(recs):
    """recs: eligible drive records of ONE stratum (with day)."""
    days = sorted({r["day"] for r in recs})
    res = {"nDrives": len(recs), "nDays": len(days)}
    runs = []
    for r in recs:
        b = r["base"]
        for i in range(len(b["wh"])):
            runs.append((r["day"], b["sign"][i], b["wh"][i], b["dur_s"][i], bool(b["cens_start"][i] or b["cens_end"][i])))
    A = pd.DataFrame(runs, columns=["day", "sign", "wh", "dur", "cens"]) if runs else pd.DataFrame(columns=["day", "sign", "wh", "dur", "cens"])
    res["nRunsAll"] = int(len(A)); res["nRunsComplete"] = int((~A.cens).sum()) if len(A) else 0
    res["censoredRunSharePct"] = round(100.0 * A.cens.mean(), 3) if len(A) else None
    res["censoredEnergySharePct"] = round(100.0 * A.wh[A.cens].sum() / A.wh.sum(), 3) if len(A) and A.wh.sum() > 0 else None
    res["hours"] = None
    def side(sub, label):
        out = {"label": label}
        comp = sub[~sub.cens]
        out["nComplete"] = int(len(comp)); out["nAll"] = int(len(sub))
        if not len(comp):
            return out
        byday = lambda s, col: {d: _hist(g[col].values) for d, g in s.groupby("day")}
        for col, nm in (("wh", "energyWh"), ("dur", "durationS")):
            hc = byday(comp, col); ha = byday(sub, col)
            out[nm] = {"completeOnly": {"median": _qint(hc, 0.5, MIN_DAYS_INTERVAL), "p90": _qint(hc, 0.9, MIN_DAYS_INTERVAL), "p99": _qint(hc, 0.99, MIN_DAYS_P99)},
                       "allRunsCensoredAsLowerBounds": {"median": _qint(ha, 0.5, MIN_DAYS_INTERVAL), "p90": _qint(ha, 0.9, MIN_DAYS_INTERVAL), "p99": _qint(ha, 0.99, MIN_DAYS_P99)}}
        for th in THRESH_WH:
            cnt_b = {d: float(((g.wh < th)).sum()) for d, g in comp.groupby("day")}; cnt_d = {d: float(len(g)) for d, g in comp.groupby("day")}
            en_b = {d: float(g.wh[g.wh < th].sum()) for d, g in comp.groupby("day")}; en_d = {d: float(g.wh.sum()) for d, g in comp.groupby("day")}
            out[f"below{th:g}Wh"] = {"countSharePct": _ratio(cnt_b, cnt_d), "energySharePct": _ratio(en_b, en_d)}
        out["bin"] = f"{BIN_DEC:g} decade (log10 Wh and log10 s)"
        return out
    res["overall"] = side(A, "all runs")
    res["discharge"] = side(A[A.sign > 0], "discharge runs")
    res["charge"] = side(A[A.sign < 0], "charge runs")
    # deadband sensitivity (run definition only; the removed energy is an explicit residual by direction)
    db = {}
    for k in DEADBANDS_A:
        key = f"db{int(k)}"
        nc = sum(r[key]["nComplete"] for r in recs); nb = sum(r[key]["nBelow1"] for r in recs)
        wc = sum(r[key]["whComplete"] for r in recs); wb = sum(r[key]["whBelow1"] for r in recs)
        db[f"{int(k)}A"] = {"nComplete": int(nc), "below1WhCountSharePct": round(100.0 * nb / nc, 3) if nc else None, "below1WhEnergySharePct": round(100.0 * wb / wc, 3) if wc else None,
                            "residualDischargeKwh": round(sum(r[key]["residualDisc"] for r in recs), 4), "residualChargeKwh": round(sum(r[key]["residualChg"] for r in recs), 4)}
    res["deadbandSensitivity"] = db
    return res


# ---------------------------------------------------------------- driver
def load_records(only=None):
    import ah_throughput as AH
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    import compute_summary_arrays as C
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
            rec = extract(b)
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


def reconcile(dm, recs):
    n, bad = 0, []
    for _, r in dm.iterrows():
        a = recs.get(r["file"])
        if a is None or not a.get("ok") or a["excluded"] or pd.isna(r.get("gross_throughput_kwh")):
            continue
        b = a["base"]
        sd = sum(w for w, s in zip(b["wh"], b["sign"]) if s > 0) / 1000.0 + b["gapDisc"]
        sc = sum(w for w, s in zip(b["wh"], b["sign"]) if s < 0) / 1000.0 + b["gapChg"]
        n += 1
        e_t = abs((sd + sc) - float(r["gross_throughput_kwh"])); e_d = abs(sd - float(r["gross_discharge_kwh"])); e_c = abs(sc - float(r["gross_charge_kwh"]))
        if e_t > TOL_TOTAL_KWH or e_d > TOL_SIDE_KWH or e_c > TOL_SIDE_KWH:
            bad.append((r["file"], round(e_t, 6), round(e_d, 6), round(e_c, 6)))
    return {"nCompared": n, "nMisses": len(bad), "examples": bad[:5], "tolerance": {"totalKwh": TOL_TOTAL_KWH, "sideKwh": TOL_SIDE_KWH}}


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = set(json.load(open(os.path.join(ROOT, "analyses", "M551_audit_sample.json"), encoding="utf-8"))["files"])
    dm, recs, stats = load_records(only)
    ka = reconcile(dm, recs)
    res = {"milestone": "M551", "mode": mode, "stats": stats, "reconciliation": ka, "extractorSourceHash": _src_hash()}
    if ka["nMisses"]:
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "reconciliation miss", **ka}, default=float)); sys.exit(2)
    el = [r for r in recs.values() if r.get("ok") and not r["excluded"] and r["canonClean"]]
    res["populations"] = {"withPairs": int(sum(1 for r in recs.values() if r.get("ok"))), "excludedNullOrAnomaly": int(sum(1 for r in recs.values() if r.get("ok") and r["excluded"])),
                          "eligibleCanonicalClean": len(el), "notOk": stats["notOk"]}
    res["strata"] = {c: stratum_block([r for r in el if r["cadence"] == c]) for c in ("fast", "slow", "unknown") if any(r["cadence"] == c for r in el)}
    res["unknownCadenceDriveSharePct"] = round(100.0 * sum(1 for r in el if r["cadence"] == "unknown") / len(el), 2) if el else None
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((r["file"], r["rawSha256"]) for r in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    print(json.dumps({"ok": True, "stats": stats, "reconciliation": ka, "populations": res["populations"], "unknownShare": res["unknownCadenceDriveSharePct"]}, default=float))
    if mode == "--splice" and not only:
        splice(res)


def splice(res):
    """additive write of S.energyPackets (+ stamp); no existing key changes."""
    flags = {}
    for c, st in res["strata"].items():
        base = st["overall"]["below1Wh"]["countSharePct"]["pct"]
        flags[c] = {"censoredRunSharePct": st["censoredRunSharePct"], "censoredEnergySharePct": st["censoredEnergySharePct"],
                    "deadbandRelativeChangeOfBelow1WhCountShare": {k: (None if not base else round((v["below1WhCountSharePct"] - base) / base, 4)) for k, v in st["deadbandSensitivity"].items()},
                    "escalation": {"censoredRunShareOver5Pct": bool((st["censoredRunSharePct"] or 0) > 5), "censoredEnergyShareOver10Pct": bool((st["censoredEnergySharePct"] or 0) > 10),
                                   "deadbandChangeOver50PctRelative": bool(any(v is not None and abs(v) > 0.5 for v in {k: (None if not base else (vv["below1WhCountSharePct"] - base) / base) for k, vv in st["deadbandSensitivity"].items()}.values()))}}
    flags["unknownCadenceDriveSharePct"] = res["unknownCadenceDriveSharePct"]
    block = {"_provenance": "GENERATED by tools/energy_packets.py (M551). Do not hand-edit.", "schemaVersion": 1,
             "basis": "raw bytes through the master's own current / voltage pairing (nearest voltage within 1.5 s), power piecewise linear between pair samples, released-ledger directional split, support step <= 5 s; raw/ = sha256-verified originals (M366); app-reported BMS channels (logged, not measured); the power is a reconstructed I x V product",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]},
             "rule": {"run": "maximal same-sign chain of directional portions inside one supported segment", "gap": "raw step > 5 s (capped energy carried by direction as gapBridged*)", "idle": "both interval endpoints zero (breaks a run; observed end)",
                      "duplicateTimestamp": "no energy; a strict sign change across it breaks the run", "censored": "first / last portion of a segment with no break marker before / after it",
                      "complete": "uncensored runs; quantiles also given for all runs with censored runs as lower bounds", "strata": "logger cadence regime (fast / slow / unknown); no pooled headline, no contrast between strata",
                      "intervals": f"day-clustered percentile bootstrap, seed {SEED}, {DRAWS} draws; median and p90 from {MIN_DAYS_INTERVAL} days, p99 from {MIN_DAYS_P99} days; histogram bin {BIN_DEC:g} decade",
                      "thresholdsWh": list(THRESH_WH), "deadbandsA": list(DEADBANDS_A)},
             "populations": res["populations"], "reconciliation": res["reconciliation"], "strata": res["strata"], "flags": flags,
             "limits": ["a run is an observed electrical exchange, not an electrochemical ageing cycle; the count share of tiny runs is not a share of battery stress",
                        "the run count depends on the logger cadence (more samples, more and shorter runs): the strata are not comparable and no pooled value is given",
                        "censoring is length-biased (long runs meet gaps more often): complete-only quantiles are biased low; the all-runs bracket treats censored runs as lower bounds",
                        "the deadband variants change the run definition only; the energy inside the band is an explicit residual by direction",
                        "the substrate is the master's nearest-voltage pairing (the audit's analytic union-of-knots integration differs by about -0.106 % in total energy; a known deviation, not a target)",
                        "the continuous energy ledger and the reversal / rainflow counts are unchanged and answer other questions"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("energyPackets", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "energyPackets"}
    A2["energyPackets"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M551: computed by tools/energy_packets.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["energyPackets"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "energyPackets"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"energyPackets": "written"}))


if __name__ == "__main__":
    main()
