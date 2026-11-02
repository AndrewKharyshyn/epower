#!/usr/bin/env python3
"""M561 (spec analyses/M561_spec.md Rev 2): uninterrupted-direction variant of the M552 power-duration profile (audit 2026-10-29 N02 follow-up).
Highest mean power observed over a window W in {5, 10, 30, 60, 120} s during which the power did not change direction: the window lies inside one run of P >= 0 (discharge) or P <= 0 (charge, on -P).
Runs: the M552 supported segment (raw step > 5 s is a gap), piecewise-linear P, a knot with P = 0 is added at every strict sign change on an interval of positive length (on a zero-duration step the run simply ends at that timestamp);
runs are closed (P = 0 allowed at the window ends). Inside a run the exact continuous-start extremum is the M552 kernel (`power_duration.window_extremes`). Brackets: 1 s start grid anchored at the run start, 0.5 s shift,
and the pre-registered near-zero sensitivities (R5): no interpolated tail (run ends at the last same-sign sample), deadband (|I| at or below the current quantum counts as zero), current offset (+/- I_offset_A_applied).
Per-drive records are cached by raw sha256 and the extractor source hash (duration_cache/, git-ignored, key prefix u561_). Aggregation never rereads raw.
Usage: python tools/power_duration_uninterrupted.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import power_duration as PD

ARR = PD.ARR
OUT = os.path.join(ROOT, "analyses", "M561_check.json")
CACHE = PD.CACHE
WINDOWS, GAP_S, SEED, DRAWS, PCTS = PD.WINDOWS, PD.GAP_S, PD.SEED, PD.DRAWS, PD.PCTS
TOL = 1e-9
VARIANTS = ("noInterp", "deadband", "offPlus", "offMinus")


# ---------------------------------------------------------------- kernel (pure, unit-tested)
def runs_of(t, q, interp=True):
    """maximal chains of knots with q >= 0 (closed runs). With interp, a knot q = 0 is inserted at every strict sign change on an interval of positive length. Returns [(t, q)] (times shifted to start at 0) and drops runs with fewer than 2 knots."""
    t = np.asarray(t, float); q = np.asarray(q, float) + 0.0   # -0.0 -> 0.0
    tt, qq = [t[0]], [q[0]]
    for i in range(1, len(t)):
        d = t[i] - t[i - 1]
        if interp and d > 0 and ((q[i - 1] > 0 and q[i] < 0) or (q[i - 1] < 0 and q[i] > 0)):
            tt.append(t[i - 1] + d * q[i - 1] / (q[i - 1] - q[i])); qq.append(0.0)
        tt.append(t[i]); qq.append(q[i])
    tt = np.array(tt); qq = np.array(qq)
    ok = qq >= 0
    out, i, n = [], 0, len(tt)
    while i < n:
        if not ok[i]:
            i += 1; continue
        j = i
        while j + 1 < n and ok[j + 1]:
            j += 1
        if j > i:
            out.append((tt[i:j + 1] - tt[i], qq[i:j + 1]))
        i = j + 1
    return out


def run_best(runs, W, end_budget=None):
    """best exact / grid / shifted value over runs of length >= W; end_budget limits eligible run time (exposure-standardised). Returns dict or None when no run is eligible."""
    best = None; elig = 0.0; rem = end_budget
    per = []
    for t, q in runs:
        L = float(t[-1])
        if L < W:
            per.append(None); continue
        if rem is not None:
            if rem <= 0:
                per.append(None); continue
            take = min(L, rem)
            if take < W:
                rem -= L; per.append(None); continue
            r = PD.window_extremes(t, q, W, end=take); rem -= L
        else:
            r = PD.window_extremes(t, q, W)
        if r is None:
            per.append(None); continue
        elig += r["len"]; per.append(max(0.0, r["max"]))
        g, s = r.get("gridMax"), r.get("shiftMax")
        if best is None:
            best = {"exact": -1e18, "grid": None, "shift": None, "nGrid": 0}
        best["exact"] = max(best["exact"], r["max"])
        best["nGrid"] += r["gridN"]
        if g is not None:
            best["grid"] = g if best["grid"] is None else max(best["grid"], g)
        if s is not None:
            best["shift"] = s if best["shift"] is None else max(best["shift"], s)
    if best is None:
        return None
    best["exact"] = max(0.0, best["exact"]); best["eligRunS"] = elig; best["perRun"] = per
    return best


def _quantum(Ia):
    u = np.unique(np.round(np.abs(np.asarray(Ia, float)), 4)); d = np.diff(u)
    d = d[d > 1e-6]
    return float(d.min()) if len(d) else 0.0


def drive_record(ts, P, Ia, i_off=0.0, m552=None):
    """per-drive record. P in kW (discharge positive), Ia = |I| in A (same stream)."""
    ts = np.asarray(ts, float); P = np.asarray(P, float); Ia = np.asarray(Ia, float)
    segs = PD.segments(ts, P)
    cut = np.flatnonzero(np.diff(ts) > GAP_S) + 1
    idx = [(a, b) for a, b in zip(np.concatenate([[0], cut]), np.concatenate([cut, [len(ts)]])) if b - a >= 2]
    quant = _quantum(Ia)
    with np.errstate(divide="ignore", invalid="ignore"):
        Id = np.where(P >= 0, Ia, -Ia)
        V = np.where(np.abs(Id) >= 1.0, P / np.where(Id == 0, 1, Id) * 1000.0, np.nan)
    V = pd.Series(V).ffill().bfill().fillna(0.0).to_numpy()
    rec = {"nSegments": len(segs), "quantumA": quant, "iOffA": float(i_off), "byW": {}, "ka5Violations": 0}
    rec["nSignChangesP"] = int(sum(int(((np.sign(P[a:b])[1:] * np.sign(P[a:b])[:-1]) < 0).sum()) for a, b in idx))
    variants = {"primary": lambda P_, Ia_, V_: P_, "deadband": lambda P_, Ia_, V_: np.where(Ia_ <= quant, 0.0, P_),
                "offPlus": lambda P_, Ia_, V_: P_ + i_off * V_ / 1000.0, "offMinus": lambda P_, Ia_, V_: P_ - i_off * V_ / 1000.0}
    runs = {}   # (variant, direction) -> list of runs over all segments
    for name, fn in variants.items():
        Pv = fn(P, Ia, V)
        for dirn, sgn in (("dis", 1.0), ("chg", -1.0)):
            lst = []
            for a, b in idx:
                lst += runs_of(ts[a:b] - ts[a], sgn * Pv[a:b], True)
            runs[(name, dirn)] = lst
    for dirn, sgn in (("dis", 1.0), ("chg", -1.0)):
        lst = []
        for a, b in idx:
            lst += runs_of(ts[a:b] - ts[a], sgn * P[a:b], False)
        runs[("noInterp", dirn)] = lst
    rec["runSeconds"] = {d: [round(float(t[-1]), 3) for t, _ in runs[("primary", d)]] for d in ("dis", "chg")}
    rec["ka6Violations"] = 0
    prim = {}
    for W in WINDOWS:
        row = {}
        for dirn in ("dis", "chg"):
            b = run_best(runs[("primary", dirn)], W)
            prim[(W, dirn)] = b
            ex = run_best(runs[("primary", dirn)], W, PD.EXPO_S)
            row[dirn] = {"exact": b["exact"] if b else None, "grid": (max(0.0, b["grid"]) if b and b["grid"] is not None else None),
                         "shift": (max(0.0, b["shift"]) if b and b["shift"] is not None else None), "eligRunS": b["eligRunS"] if b else 0.0,
                         "nRunsEligible": int(sum(1 for x in b["perRun"] if x is not None)) if b else 0, "exp": ex["exact"] if ex else None,
                         "noGridStart": bool(b and b["grid"] is None)}
            for v in ("noInterp", "deadband", "offPlus", "offMinus"):
                bv = run_best(runs[(v, dirn)], W)
                row[dirn][v] = bv["exact"] if bv else None
        rec["byW"][str(W)] = row
    # KB5 monotone in W over runs eligible for both windows (integer multiples), per direction
    for dirn in ("dis", "chg"):
        for a in WINDOWS:
            for b in WINDOWS:
                if b > a and b % a == 0 and prim[(a, dirn)] and prim[(b, dirn)]:
                    for x, y in zip(prim[(a, dirn)]["perRun"], prim[(b, dirn)]["perRun"]):
                        if x is not None and y is not None and y > x + TOL:
                            rec["ka6Violations"] += 1
    # M552 comparison (exact, same stream)
    m = m552 if m552 is not None else PD.drive_record(ts, P)
    rec["m552"] = {W: {"dis": m["byW"][str(W)]["dis"], "chg": m["byW"][str(W)]["chg"], "eligS": m["byW"][str(W)]["eligS"], "segEligible": m["byW"][str(W)]["nSegEligible"]} for W in map(str, WINDOWS)}
    rec["ka5Violations"] = 0
    for W in WINDOWS:
        for dirn in ("dis", "chg"):
            u = rec["byW"][str(W)][dirn]; n = rec["m552"][str(W)][dirn]
            if u["exact"] is not None and u["exact"] > n + TOL:
                rec["ka5Violations"] += 1
            if u["grid"] is not None and (u["grid"] > u["exact"] + TOL or u["grid"] > n + TOL):
                rec["ka5Violations"] += 1
    return rec


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (runs_of, run_best, _quantum, drive_record)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- aggregation
def _summ(vals, days):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    dd = [d for x, d in zip(vals, days) if x is not None]
    return {f"p{q}": PD._pct_boot(v, dd, q) for q in PCTS} | {"max": round(float(max(v)), 3)}


def _shift(a, b):
    d = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    return {"p50": round(float(np.percentile(np.abs(d), 50)), 4), "p95": round(float(np.percentile(np.abs(d), 95)), 4), "n": len(d)} if d else None


def stratum_block(recs):
    res = {"nDrives": len(recs), "nDays": len({r["day"] for r in recs}), "byW": {}}
    allrun = {d: [x for r in recs for x in r["rec"]["runSeconds"][d]] for d in ("dis", "chg")}
    res["runSeconds"] = {d: ({"median": round(float(np.median(v)), 2), "p95": round(float(np.percentile(v, 95)), 2), "n": len(v)} if v else None) for d, v in allrun.items()}
    for W in WINDOWS:
        w = str(W)
        withseg = [r for r in recs if r["rec"]["m552"][w]["segEligible"] > 0]   # a segment >= W exists (M552 population)
        row = {"nDrivesWithSegment": len(withseg), "nDaysWithSegment": len({r["day"] for r in withseg})}
        for dirn, name in (("dis", "discharge"), ("chg", "charge")):
            ok = [r for r in withseg if r["rec"]["byW"][w][dirn]["exact"] is not None]
            days_ok = [r["day"] for r in ok]; days_all = [r["day"] for r in withseg]
            u = lambda k, rs=ok: [r["rec"]["byW"][w][dirn][k] for r in rs]
            n552 = [r["rec"]["m552"][w][dirn] for r in ok]
            zero_inc = [r["rec"]["byW"][w][dirn]["exact"] if r["rec"]["byW"][w][dirn]["exact"] is not None else 0.0 for r in withseg]
            gap = np.array(n552) - np.array(u("exact")) if ok else np.array([])
            blk = {"eligibleRunShare": round(len(ok) / len(withseg), 4) if withseg else None, "nDrivesWithRun": len(ok), "nDaysWithRun": len(set(days_ok)),
                   "uninterrupted": _summ(u("exact"), days_ok),                                                       # PRIMARY: conditional on an eligible run
                   "uninterruptedZeroIncluded": _summ(zero_inc, days_all),                                            # secondary: drives with a segment but no run count as 0
                   "net552OnSameDrives": {f"p{q}": round(float(np.percentile(n552, q)), 3) for q in (50, 90, 95)} if ok else None,
                   "net552MinusUninterrupted": {"p50": round(float(np.percentile(gap, 50)), 4), "p95": round(float(np.percentile(gap, 95)), 4)} if len(gap) else None,
                   "shareUninterruptedEqualsNet": round(float(np.mean(gap <= 1e-9)), 4) if len(gap) else None,
                   "gridLowerBracket": {f"p{q}": round(float(np.percentile([x for x in u("grid") if x is not None], q)), 3) for q in (50, 95)} if any(x is not None for x in u("grid")) else None,
                   "shifted0p5": {f"p{q}": round(float(np.percentile([x for x in u("shift") if x is not None], q)), 3) for q in (50, 95)} if any(x is not None for x in u("shift")) else None,
                   "runsWithExactButNoGridStart": int(sum(1 for r in ok if r["rec"]["byW"][w][dirn]["noGridStart"])),
                   "exposure600s": {f"p{q}": round(float(np.percentile([x for x in u("exp") if x is not None], q)), 3) for q in (50, 95)} if any(x is not None for x in u("exp")) else None,
                   "nearZeroSensitivity": {v: _shift(u(v), u("exact")) for v in VARIANTS}}
            # Director ruling (A3, M561): display support rule and bracket triggers, script-written
            nE, nD = len(ok), len(set(days_ok)); share = blk["eligibleRunShare"] or 0.0
            blk["eligibleShareByBracket"] = {"primary": blk["eligibleRunShare"], **{v: (round(sum(1 for r in withseg if r["rec"]["byW"][w][dirn][v] is not None) / len(withseg), 4) if withseg else None) for v in ("noInterp", "deadband")}}
            blk["displayRule"] = {"showCell": bool(nE >= 20 and nD >= 5), "showP50": bool(nE >= 20 and nD >= 5), "showP90": bool(nE >= 20 and nD >= 5), "showP95": bool(nE >= 40 and nD >= 5), "showP99AndMax": bool(nE >= 200 and nD >= 5),
                                  "lowSupport": bool(share < 0.5), "nEligible": nE, "nDaysEligible": nD}
            p95v = blk["uninterrupted"]["p95"]["value"] if blk["uninterrupted"] else None
            ci = blk["uninterrupted"]["p95"]["ci95"] if blk["uninterrupted"] else None
            trig = [v for v, sv in blk["nearZeroSensitivity"].items() if sv and p95v and (sv["p95"] > 0.05 * p95v or (ci and sv["p95"] > (ci[1] - ci[0]) / 2.0))]
            nz = [x for x in u("noInterp") if x is not None]
            blk["bracketTriggered"] = {"triggered": bool(trig), "brackets": trig, "noInterpP95": round(float(np.percentile(nz, 95)), 3) if nz else None,
                                       "noInterpP95ShiftKw": blk["nearZeroSensitivity"]["noInterp"]["p95"] if blk["nearZeroSensitivity"]["noInterp"] else None}
            row[name] = blk
        res["byW"][w] = row
    return res


# ---------------------------------------------------------------- driver
def load_records(only=None):
    import energy_packets as EP
    import ah_throughput as AH
    import compute_summary_arrays as C
    import compute_drive_summary_v6 as D
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    bad = C._canonical_bad(dm)
    loader = AH.raw_loader()
    os.makedirs(CACHE, exist_ok=True)
    sh = hashlib.sha256((_src_hash() + PD._src_hash() + EP._src_hash()).encode()).hexdigest()[:16]
    recs, stats = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "notOk": 0}
    for i, r in dm.iterrows():
        fn = r["file"]
        if only and fn not in only:
            continue
        b = loader(fn)
        if b is None:
            stats["noRaw"] += 1; continue
        digest = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE, f"u561_{digest}_{sh}.json")
        if os.path.exists(cp):
            with open(cp, encoding="utf-8") as f:
                rec = json.load(f)
            stats["cacheHits"] += 1
        else:
            df, t = D._prep_bytes(b)
            ps = EP.pair_stream(df, t)
            if ps is None:
                rec = {"ok": False}
            else:
                ts, P, Ia = ps
                off = r.get("I_offset_A_applied")
                rec = {"ok": True, "rec": drive_record(ts, P, Ia, abs(float(off)) if pd.notna(off) else 0.0)}
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            stats["extracted"] += 1
        if not rec.get("ok"):
            stats["notOk"] += 1
        rec = dict(rec)
        rec.update(file=fn, rawSha256=digest, cadence=cad.get(fn) if isinstance(cad.get(fn), str) else "unknown", canonClean=bool(not bad.iloc[i]),
                   day=(lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}")("".join(c for c in fn if c.isdigit())),
                   excluded=bool(pd.notna(r.get("energy_null_reason")) or r.get("sign_check") == "ANOMALY"), nSignCrossingsMaster=(None if pd.isna(r.get("n_sign_crossings")) else float(r["n_sign_crossings"])))
        recs[fn] = rec
    return dm, recs, stats


def known_answers(recs):
    n, bad = 0, {"kb5LeqNet": [], "kb5Monotone": []}
    for fn, a in recs.items():
        if not a.get("ok") or a["excluded"]:
            continue
        n += 1
        if a["rec"]["ka5Violations"]:
            bad["kb5LeqNet"].append((fn, a["rec"]["ka5Violations"]))
        if a["rec"]["ka6Violations"]:
            bad["kb5Monotone"].append((fn, a["rec"]["ka6Violations"]))
    return {"nDrives": n, "misses": {k: len(v) for k, v in bad.items()}, "examples": {k: v[:5] for k, v in bad.items()}}


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = set(f["file"] for f in json.load(open(os.path.join(ROOT, "analyses", "M561_audit_sample.json"), encoding="utf-8"))["files"]) if "--sample" in sys.argv else None
    dm, recs, stats = load_records(only)
    ka = known_answers(recs)
    res = {"milestone": "M561", "mode": mode, "stats": stats, "knownAnswer": ka, "extractorSourceHash": _src_hash()}
    if any(ka["misses"].values()):
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "known-answer miss", **ka}, default=float)); sys.exit(2)
    el = [r for r in recs.values() if r.get("ok") and not r["excluded"] and r["canonClean"]]
    res["populations"] = {"withPairs": int(sum(1 for r in recs.values() if r.get("ok"))), "excludedNullOrAnomaly": int(sum(1 for r in recs.values() if r.get("ok") and r["excluded"])), "eligibleCanonicalClean": len(el), "notOk": stats["notOk"]}
    res["strata"] = {c: stratum_block([r for r in el if r["cadence"] == c]) for c in ("fast", "slow", "unknown") if any(r["cadence"] == c for r in el)}
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((r["file"], r["rawSha256"]) for r in recs.values())).encode()).hexdigest()
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    with open(os.path.join(CACHE, "_u561_all.json" if not only else "_u561_sample.json"), "w", encoding="utf-8") as f:
        json.dump(recs, f, default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka, "populations": res["populations"]}, default=float))
    if mode == "--splice" and not only:
        splice(res)


def splice(res):
    """additive write of S.powerDurationUninterrupted (+ stamp); no existing key changes."""
    flags = {}
    for c, st in res["strata"].items():
        f = {"noRunShareOver25PctAt120": False, "gapP95Over5PctAtW5": False, "nearZeroP95Over5PctOrHalfWidth": False}
        for W, row in st["byW"].items():
            for dirn in ("discharge", "charge"):
                b = row[dirn]
                p95 = (b["uninterrupted"] or {}).get("p95", {}).get("value") if b["uninterrupted"] else None
                if W == "120" and b["eligibleRunShare"] is not None and b["eligibleRunShare"] < 0.75:
                    f["noRunShareOver25PctAt120"] = True
                if W == "5" and p95 and b["net552MinusUninterrupted"] and b["net552MinusUninterrupted"]["p95"] > 0.05 * p95:
                    f["gapP95Over5PctAtW5"] = True
                ci = (b["uninterrupted"] or {}).get("p95", {}).get("ci95") if b["uninterrupted"] else None
                for v, sv in b["nearZeroSensitivity"].items():
                    if sv and p95 and (sv["p95"] > 0.05 * p95 or (ci and sv["p95"] > (ci[1] - ci[0]) / 2.0)):
                        f["nearZeroP95Over5PctOrHalfWidth"] = True
        flags[c] = f
    block = {"_provenance": "GENERATED by tools/power_duration_uninterrupted.py (M561). Do not hand-edit.", "schemaVersion": 1,
             "basis": "as powerDuration (M552): the master's own current / voltage pairing, power piecewise linear, support step <= 5 s, app-reported BMS channels (logged, not measured); the power is a reconstructed I x V product; the sign is set by an offset-sensitive reconstructed current",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]},
             "rule": {"windowsS": list(WINDOWS), "primary": "exact continuous-start extremum of the window mean inside one run of P >= 0 (discharge) or P <= 0 (charge, magnitude); runs are closed, a zero knot is inserted at every strict sign change on an interval of positive length, a zero-duration step ends the run at its timestamp",
                      "lowerBracket": "1 s start grid anchored at the run start (not a subset of the M552 grid)", "sensitivity": "0.5 s shifted grid; first 600 s of eligible run time; near-zero brackets: no interpolated tail, deadband at the current quantum, current offset +/- I_offset_A_applied",
                      "population": "primary percentile base is conditional on an eligible run (eligible share beside it); the zero-included version is secondary; a drive with no segment of length W is absent",
                      "strata": "logger cadence regime (fast / slow / unknown); no pooled headline, no contrast between strata",
                      "intervals": f"day-clustered percentile bootstrap, seed {SEED}, {DRAWS} draws, as powerDuration"},
             "populations": res["populations"], "knownAnswer": res["knownAnswer"], "strata": res["strata"], "flags": flags,
             "limits": ["observed one-direction window extrema of a logged, reconstructed I x V power: not ratings, capabilities, limits or operating percentiles",
                        "the difference of the pooled percentiles of the net and the uninterrupted values is not the percentile of the per-drive differences; the per-drive difference is given separately",
                        "runs are cut at the first sign change, so the result depends on the current offset and on noise near P = 0; the near-zero brackets quantify this and are not gates",
                        "cadence limits the resolution of a crossing; strata are not comparable and no pooled value is given",
                        "the M552 values (powerDuration) are unchanged and remain the net-mean estimand"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("powerDurationUninterrupted", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "powerDurationUninterrupted"}
    A2["powerDurationUninterrupted"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M561: computed by tools/power_duration_uninterrupted.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["powerDurationUninterrupted"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "powerDurationUninterrupted"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"powerDurationUninterrupted": "written"}))


if __name__ == "__main__":
    main()
