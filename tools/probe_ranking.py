#!/usr/bin/env python3
"""M549 (spec analyses/M549_spec.md Rev 2): hottest / coldest temperature-probe ranking with an explicit tie policy (audit 2026-10-29 F01).
The released accumulator (_RawAccum.add, 'sensorSummary') ranks T1..T4 with np.argmax / np.argmin, so the first index wins every tie, and it counts native rows (after ffill(limit=15)), not elapsed time.
This tool reads the same pipeline frames (frame loader, F03 originals) and reports, per probe: unique (alone at the extreme), tied (at the extreme together with at least one other probe), the any-tie total,
the fractional share (1/k) and the tie time; the legacy first-index rule is kept only as a labelled diagnostic. Three steps are reported separately (D2): legacy row first-index (G0), grid first-index, grid unique / tied.
Primary population: the pipeline 1 Hz grid with the `last` aggregator (D1; native quantisation kept, exact equality is a valid tie test), one grid second = one second; S1 = MEAN aggregator; S2 = seconds in which every
probe has a native reading within the preceding 5 s (per probe, before any fill; D4). Ratio of sums, day-clustered percentile bootstrap (seed 42, 4000 draws). Per-drive sufficient statistics are cached by the raw file
sha256 and the extractor source hash (probe_cache/, git-ignored); aggregation never rereads raw.
Modes: --check (writes analyses/M549_check.json) | --splice (check + additive write of S.temperatureProbeRanking). Usage: python tools/probe_ranking.py --check|--splice"""
import copy, datetime, hashlib, inspect, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
from drive_raw_cache import fast_time as _ft
import compute_summary_arrays as C
import drive_raw_cache as drc

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M549_check.json")
CACHE = os.path.join(ROOT, "probe_cache")
PROBES = ["T1", "T2", "T3", "T4"]
FILL_LIMIT = 15
FRESH_S = 5
SEED, DRAWS = 42, 4000
MIN_DAYS_INTERVAL = 5
FRESH_MIN_SUPPORT = 0.5


# ---------------------------------------------------------------- extraction (pure kernels, unit-tested)
def rank_counts(V):
    """V: (n, 4) float array of fully valid rows. Returns, for the maximum (hot) and the minimum (cold) rule:
    m[p][k-1] = number of rows in which probe p is at the extreme in a set of k probes; first[p] = legacy argmax / argmin count (lowest index wins); ties = rows with k >= 2."""
    out = {}
    for name, ext, arg in (("hot", np.max, np.argmax), ("cold", np.min, np.argmin)):
        if V.shape[0] == 0:
            out[name] = {"m": [[0] * 4 for _ in range(4)], "first": [0] * 4, "ties": 0}
            continue
        K = V == ext(V, axis=1)[:, None]
        k = K.sum(axis=1)
        m = [[int((K[:, p] & (k == kk)).sum()) for kk in (1, 2, 3, 4)] for p in range(4)]
        first = np.bincount(arg(V, axis=1), minlength=4).astype(int).tolist()
        out[name] = {"m": m, "first": first, "ties": int((k >= 2).sum())}
    return out


def _step(vals):
    u = np.unique(vals[np.isfinite(vals)])
    if u.size < 2:
        return None, None
    d = np.diff(u)
    d = d[d > 1e-9]
    return (float(u[0]), float(d.min())) if d.size else (None, None)


def extract_core(t, raw_T):
    """t: Series of timestamps (native rows); raw_T: dict probe -> numeric Series of the native values BEFORE any fill (aligned with t). Mirrors _RawAccum.add: native ffill(limit=15), plausibility -40..90,
    then the grid frame.resample('1s').{mean,last}().ffill(limit=15)."""
    filled = {p: raw_T[p].ffill(limit=FILL_LIMIT).where(lambda s: (s >= -40) & (s <= 90)) for p in PROBES}
    F = pd.DataFrame({"t": t.values, **{p: filled[p].values for p in PROBES}}).dropna(subset=["t"])
    G = pd.DataFrame({"t": t.values, **{p: filled[p].values for p in PROBES}}).dropna(subset=["t"]).set_index("t")
    rec = {}
    # legacy: native rows with all four probes valid (the released rule and population)
    Vn = F[PROBES].dropna().values
    rl = rank_counts(Vn)
    rec["legacy"] = {"rows": int(Vn.shape[0]), "hot": rl["hot"]["first"], "cold": rl["cold"]["first"]}
    if G.empty:
        rec["nGridSeconds"] = 0
        return rec
    g_last = G.resample("1s").last().ffill(limit=FILL_LIMIT)
    g_mean = G.resample("1s").mean().ffill(limit=FILL_LIMIT)
    ok_l = g_last[PROBES].notna().all(axis=1).values
    ok_m = g_mean[PROBES].notna().all(axis=1).values
    rec["last"] = {"valid": int(ok_l.sum()), **rank_counts(g_last[PROBES].values[ok_l])}
    rec["mean"] = {"valid": int(ok_m.sum()), **rank_counts(g_mean[PROBES].values[ok_m])}
    # S2: every probe has a native reading (before any fill) within the preceding FRESH_S seconds of the end of the grid second
    ends = (g_last.index.values.astype("datetime64[ns]").astype("int64") + 1_000_000_000)
    fresh = np.ones(len(g_last), dtype=bool)
    for p in PROBES:
        tt = np.sort(t.values[raw_T[p].notna().values].astype("datetime64[ns]").astype("int64"))
        if tt.size == 0:
            fresh[:] = False
            continue
        j = np.searchsorted(tt, ends, side="left") - 1
        has = j >= 0
        age = np.where(has, ends - tt[np.clip(j, 0, None)], np.iinfo(np.int64).max)
        fresh &= has & (age <= FRESH_S * 1_000_000_000)
    ok_f = ok_l & fresh
    rec["fresh"] = {"valid": int(ok_f.sum()), **rank_counts(g_last[PROBES].values[ok_f])}
    # G-Q: share of MEAN grid values that fall off the probe's observed native value step
    gq = {}
    for p in PROBES:
        base, st = _step(filled[p].values)
        v = g_mean[p].values[ok_m]
        if st is None or not v.size:
            gq[p] = {"n": int(v.size), "off": 0, "step": st}
            continue
        r = (v - base) / st
        off = int((np.abs(r - np.round(r)) > 1e-6).sum())
        gq[p] = {"n": int(v.size), "off": off, "step": st}
    rec["gq"] = gq
    rec["nGridSeconds"] = int(len(g_last))
    return rec


def extract(df):
    """df as returned by the frame loader; the same preprocessing as _RawAccum.add up to the probe columns."""
    df, _ = C._apply_speed_priority(df)
    df = df.rename(columns={k: v for k, v in C.RAW_MAP.items() if k in df.columns})
    if "time" not in df or not all(p in df for p in PROBES):
        return None
    t = _ft(df["time"], mixed=True)
    raw_T = {p: pd.to_numeric(df[p], errors="coerce") for p in PROBES}
    return extract_core(t, raw_T)


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (rank_counts, _step, extract_core, extract)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- aggregation
def _boot(num, den, days):
    """ratio of sums over calendar-day clusters; percentile bootstrap seed 42, 4000 draws; interval only with >= 5 days."""
    ud = sorted(set(days))
    n = np.array([sum(a for a, d in zip(num, days) if d == u) for u in ud], float)
    d = np.array([sum(a for a, dd in zip(den, days) if dd == u) for u in ud], float)
    if d.sum() <= 0:
        return {"pct": None, "ci95Pct": None, "nDays": len(ud)}
    pt = 100.0 * n.sum() / d.sum()
    if len(ud) < MIN_DAYS_INTERVAL:
        return {"pct": round(pt, 3), "ci95Pct": None, "nDays": len(ud)}
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(ud), size=(DRAWS, len(ud)))
    den_b = d[idx].sum(1)
    ok = den_b > 0
    bs = 100.0 * n[idx].sum(1)[ok] / den_b[ok]
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return {"pct": round(pt, 3), "ci95Pct": [round(float(lo), 3), round(float(hi), 3)], "nDays": len(ud)}


def _shares(recs, basis, which):
    """per-probe estimands for one basis ('last' | 'mean' | 'fresh') and one rule ('hot' | 'cold')."""
    days = [r["day"] for r in recs]
    den = [r[basis]["valid"] for r in recs]
    M = [np.array(r[basis][which]["m"]) for r in recs]
    out = {"seconds": int(sum(den)), "nDrives": len(recs), "nDays": len(set(days)), "hours": round(sum(den) / 3600.0, 2)}
    for pi, p in enumerate(PROBES):
        uniq = [int(m[pi][0]) for m in M]
        tied = [int(m[pi][1:].sum()) for m in M]
        frac = [float(sum(m[pi][k] / (k + 1) for k in range(4))) for m in M]
        first = [r[basis][which]["first"][pi] for r in recs]
        out[p] = {"unique": _boot(uniq, den, days), "tied": _boot(tied, den, days), "anyTie": _boot([a + b for a, b in zip(uniq, tied)], den, days),
                  "fractional": _boot(frac, den, days), "firstIndexGrid": _boot(first, den, days)}
    out["tieTime"] = _boot([r[basis][which]["ties"] for r in recs], den, days)
    return out


def load_records(only=None):
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sd = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "thermal_regime"]]
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    coh, cad = dict(zip(sd.file, sd.thermal_regime)), dict(zip(cr.file, cr.regime))
    bad = C._canonical_bad(dm)
    os.makedirs(CACHE, exist_ok=True)
    fl = drc.make_frame_loader()
    sh = _src_hash()
    rawdir = next((d for d in (os.environ.get("XT_RAW_DIR"), os.path.join(ROOT, "raw")) if d and os.path.isdir(d)), None)
    rawmap = {"".join(ch for ch in f if ch.isdigit()): os.path.join(rawdir, f) for f in os.listdir(rawdir) if f.lower().endswith(".csv")} if rawdir else {}   # the raw file matches the master key by the digits of its name
    recs, stats = [], {"cacheHits": 0, "extracted": 0, "noProbeColumns": 0, "noRawFile": 0}
    for i, r in dm.iterrows():
        fn = r["file"]
        if only and fn not in only:
            continue
        p = rawmap.get("".join(ch for ch in str(fn) if ch.isdigit()))
        if p is None:
            stats["noRawFile"] += 1
        digest = hashlib.sha256(open(p, "rb").read()).hexdigest() if p and os.path.exists(p) else None
        cp = os.path.join(CACHE, f"{digest}_{sh}.json") if digest else None
        if cp and os.path.exists(cp):
            rec = json.load(open(cp, encoding="utf-8")); stats["cacheHits"] += 1
        else:
            df = fl(fn)
            rec = extract(df) if df is not None else None
            if rec is None:
                stats["noProbeColumns"] += 1; continue
            if cp:
                json.dump(rec, open(cp, "w", encoding="utf-8"))
            stats["extracted"] += 1
        d = str(fn)[:10] if "-" in str(fn)[:5] else f"{str(fn)[:4]}-{str(fn)[4:6]}-{str(fn)[6:8]}"
        rec.update(file=fn, day=d, canonClean=bool(not bad.iloc[i]), cohort=coh.get(fn, "unknown"), cadence=cad.get(fn) if isinstance(cad.get(fn), str) else "unknown", rawSha256=digest)
        recs.append(rec)
    return recs, stats


def build(recs):
    el = [r for r in recs if r["canonClean"] and r.get("last", {}).get("valid", 0) > 0]
    res = {"populations": {"eligibleCanonicalClean": len(el), "withProbeColumns": len(recs)}}
    res["pooled"] = {w: _shares(el, "last", w) for w in ("hot", "cold")}
    res["byCohort"] = {c: {w: _shares([r for r in el if r["cohort"] == c], "last", w) for w in ("hot", "cold")} for c in ("warm", "shoulder", "cold") if any(r["cohort"] == c for r in el)}
    res["byCadence"] = {c: {w: _shares([r for r in el if r["cadence"] == c], "last", w) for w in ("hot", "cold")} for c in sorted({r["cadence"] for r in el})}
    res["sensitivityMean"] = {w: _shares(el, "mean", w) for w in ("hot", "cold")}
    fr = {}
    for c in ["all"] + sorted({r["cadence"] for r in el}):
        sub = el if c == "all" else [r for r in el if r["cadence"] == c]
        tot = sum(r["last"]["valid"] for r in sub); kept = sum(r["fresh"]["valid"] for r in sub)
        sup = kept / tot if tot else None
        fr[c] = {"supportShare": None if sup is None else round(sup, 4), "interpretable": bool(sup is not None and sup >= FRESH_MIN_SUPPORT),
                 **({w: _shares([r for r in sub if r["fresh"]["valid"] > 0], "fresh", w) for w in ("hot", "cold")} if sub and kept else {})}
    res["sensitivityFresh5s"] = fr
    gq = {}
    for p in PROBES:
        n = sum(r["gq"][p]["n"] for r in el if "gq" in r); off = sum(r["gq"][p]["off"] for r in el if "gq" in r)
        gq[p] = {"seconds": int(n), "offStepShare": round(off / n, 4) if n else None, "steps": sorted({r["gq"][p]["step"] for r in el if "gq" in r and r["gq"][p]["step"]})[:4]}
    res["meanAveragingArtefact"] = gq
    # three steps (D2)
    lg_rows = sum(r["legacy"]["rows"] for r in recs)
    res["legacy"] = {"nRows": int(lg_rows), "nDrives": len(recs),
                     "hotFirstIndexRowSharePct": {p: round(100.0 * sum(r["legacy"]["hot"][i] for r in recs) / lg_rows, 3) for i, p in enumerate(PROBES)} if lg_rows else None,
                     "coldFirstIndexRowSharePct": {p: round(100.0 * sum(r["legacy"]["cold"][i] for r in recs) / lg_rows, 3) for i, p in enumerate(PROBES)} if lg_rows else None}
    # D3 identities on the same seconds (any failure is a code bug)
    bad = []
    for r in el:
        for b in ("last", "mean", "fresh"):
            h, c = r[b]["hot"], r[b]["cold"]
            if h["first"][0] != sum(h["m"][0]): bad.append((r["file"], b, "hot"))
            if c["first"][3] != c["m"][3][0]: bad.append((r["file"], b, "cold"))
            if abs(sum(sum(h["m"][p][k] / (k + 1) for k in range(4)) for p in range(4)) - r[b]["valid"]) > 1e-6: bad.append((r["file"], b, "partition"))
    res["identities"] = {"nViolations": len(bad), "examples": bad[:5]}
    return res


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = set(json.load(open(os.path.join(ROOT, "analyses", "M549_audit_sample.json"), encoding="utf-8"))["files"])
    recs, stats = load_records(only)
    res = build(recs)
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((r["file"], r["rawSha256"]) for r in recs)).encode()).hexdigest()
    res.update(milestone="M549", mode=mode, stats=stats, extractorSourceHash=_src_hash(), rule={"fillLimit": FILL_LIMIT, "freshS": FRESH_S, "seed": SEED, "draws": DRAWS, "primaryAggregator": "last", "minDaysInterval": MIN_DAYS_INTERVAL})
    if res["identities"]["nViolations"]:
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "identity violation", **res["identities"]}, default=float)); sys.exit(2)
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    print(json.dumps({"ok": True, "stats": stats, "identities": res["identities"], "legacy": res["legacy"]}, default=float))
    if mode == "--splice" and not only:
        splice(res)


ROLE_SPLIT = " — reads "


def _role_paths(A):
    """the text leaves 'Hottest probe — reads highest in N% of samples' / 'Coldest probe ...': pooled list and the four cohort views of the seasonal chart."""
    out = [A["sensorSummary"]]
    sc = A.get("seasonalCharts", {}).get("charts", {}).get("SensorSummary", {}).get("data", {})
    out += [sc[k] for k in ("all", "warm", "shoulder", "cold") if k in sc]
    return out


def splice(res):
    """additive write of S.temperatureProbeRanking and the text-only strip of the legacy percentages from the role leaves (keys never renamed; the shares are read from the block by the dashboard)."""
    primary = res["pooled"]["hot"]["tieTime"]
    flags = {"freshNotInterpretable": [c for c, v in res["sensitivityFresh5s"].items() if c != "all" and not v["interpretable"]]}
    for w in ("hot", "cold"):
        a, b = res["pooled"][w]["tieTime"], res["sensitivityMean"][w]["tieTime"]
        half = (a["ci95Pct"][1] - a["ci95Pct"][0]) / 2.0 if a["ci95Pct"] else None
        flags[f"meanTieShareDiffPct_{w}"] = round(abs(a["pct"] - b["pct"]), 3)
        flags[f"meanTieShareWithinPrimaryHalfWidth_{w}"] = None if half is None else bool(abs(a["pct"] - b["pct"]) <= half)
    block = {"_provenance": "GENERATED by tools/probe_ranking.py (M549). Do not hand-edit.", "schemaVersion": 1,
             "basis": "pipeline 1 Hz grid (last aggregator, one grid second = one second of elapsed time), canonical-clean drives, raw/ = sha256-verified originals (M366); app-reported BMS probe channels (logged, not measured)",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawListSha256": res["rawListSha256"]}, "rule": res["rule"], "populations": res["populations"],
             "pooled": res["pooled"], "byCohort": res["byCohort"],
             "detail": {"byCadence": res["byCadence"], "sensitivityMean": res["sensitivityMean"], "sensitivityFresh5s": res["sensitivityFresh5s"], "meanAveragingArtefact": res["meanAveragingArtefact"]},
             "legacy": {**res["legacy"], "label": "first-index row share on native rows (G0): a tie-biased diagnostic, not a physical share"},
             "identities": res["identities"], "flags": flags, "extractorSourceHash": res["extractorSourceHash"],
             "limits": ["unique + tied = the share of seconds at the extreme; fractional shares sum to 100 % and live in this detail only", "ties are exact equality of the aggregated per-second value; probes are logged on a 1 degC step",
                        "no cohort or cadence contrast is drawn; cold has fewer than 5 days (no interval)", "S2 (every probe read within 5 s) is not interpretable in a cadence stratum that keeps under 50 % of its seconds",
                        "the 1 Hz grid carries values forward by up to 15 native rows and 15 grid seconds, so a valid second may rest on a stale reading (primary has no freshness filter)"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("temperatureProbeRanking", "_artifactStamps", "sensorSummary", "seasonalCharts")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "temperatureProbeRanking"}
    A2["temperatureProbeRanking"] = block
    n_leaves = 0
    for lst in _role_paths(A2):
        for e in lst:
            if ROLE_SPLIT in e["role"]:
                e["role"] = e["role"].split(ROLE_SPLIT)[0]; n_leaves += 1
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M549: computed by tools/probe_ranking.py from the pipeline frame cache; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["temperatureProbeRanking"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "temperatureProbeRanking"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"temperatureProbeRanking": "written", "roleLeavesStripped": n_leaves}))


if __name__ == "__main__":
    main()
