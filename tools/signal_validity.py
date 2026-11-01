#!/usr/bin/env python3
"""M556 (spec analyses/M556_spec.md Rev 2): signal-validity registry (audit 2026-10-29 N05). The hand-curated declarations live in signal_validity_registry.json (this tool never edits them); the tool verifies each declaration against
the raw corpus and writes the additive payload block `signalValidity`: per channel the instrument location, the rule, the period and extent over which it holds in the corpus, the sampling freshness, the resolution (null when fewer than
5 distinct values) and the permissible analyses, plus an inventory of the channels that are all zero in at least one file (zero can be a physical state: the inventory never classifies a channel as invalid).
Raw zeros are preserved: nothing is suppressed, repaired or written back. `status(entry_id, values)` is the reader contract for future consumers.
Per-file records are cached by the raw sha256, the extractor hash and the registry hash (validity_cache/, git-ignored). Modes: --check (writes analyses/M556_check.json) | --splice (check + additive write of S.signalValidity).
Usage: python tools/signal_validity.py --check|--splice [--sample]"""
import copy, datetime, hashlib, inspect, io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M556_check.json")
REG = os.path.join(ROOT, "signal_validity_registry.json")
CACHE = os.path.join(ROOT, "validity_cache")
INVENTORY_MIN_N = 5
AIR_BOUNDS = (-40.0, 90.0)
MIN_DISTINCT = 5
REQUIRED = ("id", "column", "instrumentLocation", "rule", "physicalJustification", "status", "permissibleAnalyses", "impermissibleAnalyses", "consumers", "references")


# ---------------------------------------------------------------- reader contract (pure, unit-tested)
def load_registry(path=REG):
    return json.load(open(path, encoding="utf-8"))


def _rule_eval(rule, values):
    """('holds' | 'not_holding' | 'not_testable') for a vector under a rule of kind all_non_missing_equal; NaN, None and non-numeric are missing."""
    v = pd.to_numeric(pd.Series(list(values) if values is not None else []), errors="coerce").dropna()
    if len(v) == 0:
        return "not_testable"
    return "holds" if bool((v == float(rule["value"])).all()) else "not_holding"


def status(entry_id, values, registry=None):
    """{status, values, escalate}: `rule_holds_unavailable` (values withheld: None), `rule_not_holding` (values returned unchanged; a mixed file of an all_non_missing_equal channel raises `escalate`), or `not_testable`
    (empty or all missing; never unavailable by default). The input is never modified."""
    reg = registry or load_registry()
    e = next(x for x in reg["entries"] if x["id"] == entry_id)
    if e["rule"]["kind"] != "all_non_missing_equal":
        return {"status": "not_testable", "values": values, "escalate": False, "reason": "rule kind %s has no per-file unavailable verdict" % e["rule"]["kind"]}
    r = _rule_eval(e["rule"], values)
    if r == "holds":
        return {"status": "rule_holds_unavailable", "values": None, "escalate": False}
    if r == "not_holding":
        return {"status": "rule_not_holding", "values": values, "escalate": True}
    return {"status": "not_testable", "values": values, "escalate": False}


def _src_hash():
    return hashlib.sha256("".join(inspect.getsource(f) for f in (_rule_eval, status, file_record)).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- per-file extraction
def file_record(b, entry_cols):
    """one read of the raw file: per column n non-missing numeric, zero count, min / max, distinct count (capped); for the declared columns also the second independent text-route count, the -100 count and the out-of-bound count."""
    df = pd.read_csv(io.BytesIO(b), low_memory=False)
    rec = {"nRows": int(len(df)), "columns": {}, "declared": {}}
    for c in df.columns[1:]:
        s = df[c]
        v = pd.to_numeric(s, errors="coerce").dropna()
        n = int(len(v))
        rec["columns"][c] = [n, int((v == 0).sum()), float(v.min()) if n else None, float(v.max()) if n else None, int(min(v.nunique(), 6)) if n else 0]
    for c in entry_cols:
        dups = [x for x in df.columns if x == c or x.startswith(c + ".")]
        if not dups:
            continue
        txt = pd.read_csv(io.BytesIO(b), usecols=[c], dtype=str, keep_default_na=False)[c].str.strip()
        v = pd.to_numeric(df[c], errors="coerce").dropna()
        rec["declared"][c] = {"nHeaderMatches": len(dups), "nText": int((txt != "").sum()), "nNumeric": int(len(v)), "nZero": int((v == 0).sum()), "nMinus100": int((v == -100).sum()),
                              "nOutOfBoundNotMinus100": int((((v < AIR_BOUNDS[0]) | (v > AIR_BOUNDS[1])) & (v != -100)).sum()), "nDistinct": int(min(v.nunique(), 6)) if len(v) else 0,
                              "min": float(v.min()) if len(v) else None, "max": float(v.max()) if len(v) else None}
    return rec


# ---------------------------------------------------------------- aggregation
def _day(fn):
    d = "".join(c for c in fn if c.isdigit())
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


dgt = lambda s_: "".join(ch for ch in s_ if ch.isdigit())[:14]


def _sr_lookup():
    p = os.path.join(ROOT, "signal_representation.json")
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))["files"]
    return {dgt(f): {c: v.get("grid_step") for c, v in x.get("channels", {}).items()} for f, x in d.items()}


def entry_block(e, recs, sr):
    c = e["column"]
    have = [(fn, r["rec"]["declared"][c]) for fn, r in recs.items() if c in r["rec"]["declared"]]
    withs = [(fn, d) for fn, d in have if d["nNumeric"] > 0]
    blk = {"id": e["id"], "column": c, "instrumentLocation": e["instrumentLocation"], "status": e["status"], "rule": e["rule"], "physicalJustification": e["physicalJustification"],
           "permissibleAnalyses": e["permissibleAnalyses"], "impermissibleAnalyses": e["impermissibleAnalyses"], "consumers": e["consumers"],
           "filesWithHeader": len(have), "filesWithSamples": len(withs), "headerOnlyEmptyFiles": len(have) - len(withs), "samples": int(sum(d["nNumeric"] for _, d in withs)),
           "headerMatchesOverOne": int(sum(1 for _, d in have if d["nHeaderMatches"] > 1))}
    if withs:
        blk["valueRange"] = [min(d["min"] for _, d in withs), max(d["max"] for _, d in withs)]
        fr = [d["nNumeric"] / recs[fn]["durationS"] for fn, d in withs if recs[fn]["durationS"] > 0]
        blk["freshnessSamplesPerSecondMedian"] = round(float(np.median(fr)), 4) if fr else None
        dist = max(d["nDistinct"] for _, d in withs)
        steps = [sr[dgt(recs[fn]["rawName"])][c] for fn, _ in withs if dgt(recs[fn]["rawName"]) in sr and sr[dgt(recs[fn]["rawName"])].get(c)]
        if dist < MIN_DISTINCT:
            blk["resolution"] = {"value": None, "reason": "fewer than %d distinct values in every file" % MIN_DISTINCT}
        elif steps:
            blk["resolution"] = {"value": float(np.median(steps)), "reason": None, "source": "signal_representation.json grid step (median over %d files)" % len(steps)}
        else:
            blk["resolution"] = {"value": None, "reason": "no signal_representation record for the files carrying the channel"}
        blk["textRouteAgrees"] = bool(all(d["nText"] == d["nNumeric"] for _, d in have))
    k = e["rule"]["kind"]
    if k == "all_non_missing_equal":
        v0 = float(e["rule"]["value"])
        holds = [(fn, d) for fn, d in withs if d["nZero"] == d["nNumeric"]] if v0 == 0.0 else []
        mixed = [fn for fn, d in withs if (d["nZero"] != d["nNumeric"])]
        blk.update({"filesRuleHolds": len(holds), "filesRuleNotHolding": len(mixed), "daysRuleHolds": len({_day(fn) for fn, _ in holds}), "samplesRuleHolds": int(sum(d["nNumeric"] for _, d in holds)),
                    "nonZeroValuesInDeclaredChannel": int(sum(d["nNumeric"] - d["nZero"] for _, d in withs)), "shareOfChannelFilesWhereRuleHolds": round(len(holds) / len(withs), 4) if withs else None,
                    "activePeriod": [min(_day(fn) for fn, _ in holds), max(_day(fn) for fn, _ in holds)] if holds else None,
                    "verdict": "unavailable in the files where the rule holds (all logged values equal 0); raw zeros preserved"})
    elif k == "value_equals":
        sent = [(fn, d) for fn, d in withs if d["nMinus100"] > 0]
        blk.update({"filesWithSentinel": len(sent), "daysWithSentinel": len({_day(fn) for fn, _ in sent}), "sentinelSamples": int(sum(d["nMinus100"] for _, d in sent)),
                    "otherOutOfBoundSamples": int(sum(d["nOutOfBoundNotMinus100"] for _, d in withs)), "bounds": list(AIR_BOUNDS),
                    "otherOutOfBoundFiles": [{"file": fn, "day": _day(fn), "samples": d["nOutOfBoundNotMinus100"], "maxValue": d["max"]} for fn, d in withs if d["nOutOfBoundNotMinus100"] > 0],
                    "activePeriod": [min(_day(fn) for fn, _ in sent), max(_day(fn) for fn, _ in sent)] if sent else None, "verdict": "handled upstream (the master removes the sentinel by its bound); counted here only"})
    else:
        blk.update({"daysWithSamples": len({_day(fn) for fn, _ in withs}), "activePeriod": [min(_day(fn) for fn, _ in withs), max(_day(fn) for fn, _ in withs)] if withs else None,
                    "verdict": "sparse, location-specific observations: descriptive only"})
    return blk


def inventory(recs, declared_cols):
    agg = {}
    for fn, r in recs.items():
        for c, (n, nz, mn, mx, nd) in r["rec"]["columns"].items():
            if n >= INVENTORY_MIN_N and nz == n:
                a = agg.setdefault(c, {"files": 0, "days": set(), "samples": 0}); a["files"] += 1; a["days"].add(_day(fn)); a["samples"] += n
    rows = [{"column": c, "files": a["files"], "days": len(a["days"]), "samples": a["samples"], "declaredInRegistry": c in declared_cols} for c, a in sorted(agg.items(), key=lambda x: (-x[1]["files"], x[0]))]
    return {"label": "channels that are all zero in at least one file (n >= %d): zero can be a physical state (for example an engine that never ran); this list is not a validity declaration unless the channel has a registry entry" % INVENTORY_MIN_N,
            "nChannels": len(rows), "top": rows[:20]}


def load_records(only=None):
    import compute_summary_arrays as C
    reg = load_registry()
    reg_hash = hashlib.sha256(open(REG, "rb").read()).hexdigest()
    cols = [e["column"] for e in reg["entries"]]
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
    dig = lambda s: "".join(ch for ch in s if ch.isdigit())[:14]
    rawmap = {}
    for f in os.listdir(raw_dir):
        if f.endswith(".csv"):
            rawmap.setdefault(dig(f), []).append(f)
    os.makedirs(CACHE, exist_ok=True)
    sh = _src_hash()
    recs, stats, unparsed = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "unparsed": 0}, []
    for i, r in dm.iterrows():
        fn = r["file"]
        if only and fn not in only:
            continue
        cand = rawmap.get(dig(fn))
        if not cand:
            stats["noRaw"] += 1; continue
        b = open(os.path.join(raw_dir, cand[0]), "rb").read()
        digest = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE, f"{digest}_{sh}_{reg_hash[:8]}.json")
        if os.path.exists(cp):
            rec = json.load(open(cp, encoding="utf-8")); stats["cacheHits"] += 1
        else:
            try:
                rec = file_record(b, cols)
            except Exception as ex:
                rec = {"error": repr(ex), "columns": {}, "declared": {}}
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            stats["extracted"] += 1
        if rec.get("error"):
            stats["unparsed"] += 1; unparsed.append(fn); continue
        recs[fn] = {"rec": rec, "rawName": cand[0], "rawSha256": digest, "durationS": float(r["duration_s"])}
    return dm, recs, stats, unparsed, rawmap, reg, reg_hash


def known_answers(recs, reg):
    n = {"textRoute": 0, "partition": 0}
    bad = {"textRoute": [], "partition": [], "bms12NonZero": [], "headerMatches": []}
    for e in reg["entries"]:
        c = e["column"]
        for fn, r in recs.items():
            d = r["rec"]["declared"].get(c)
            if not d:
                continue
            n["textRoute"] += 1
            if d["nText"] != d["nNumeric"]:
                bad["textRoute"].append((fn, e["id"], d["nText"], d["nNumeric"]))
            if d["nHeaderMatches"] > 1:
                bad["headerMatches"].append((fn, e["id"]))
        if e["rule"]["kind"] == "all_non_missing_equal":
            ws = [(fn, r["rec"]["declared"][c]) for fn, r in recs.items() if c in r["rec"]["declared"] and r["rec"]["declared"][c]["nNumeric"] > 0]
            holds = sum(1 for _, d in ws if d["nZero"] == d["nNumeric"]); mixed = sum(1 for _, d in ws if d["nZero"] != d["nNumeric"])
            n["partition"] += 1
            if holds + mixed != len(ws):
                bad["partition"].append(e["id"])
            if e["id"] == "bms_12v_supply" and mixed:
                bad["bms12NonZero"].append(mixed)
    return {"n": n, "misses": {k: len(v) for k, v in bad.items()}, "examples": {k: v[:5] for k, v in bad.items()}}


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = None
    if "--sample" in sys.argv:
        only = set(json.load(open(os.path.join(ROOT, "analyses", "M556_audit_sample.json"), encoding="utf-8"))["files"])
    dm, recs, stats, unparsed, rawmap, reg, reg_hash = load_records(only)
    for e in reg["entries"]:
        miss = [k for k in REQUIRED if not e.get(k) and k != "consumers"]
        assert not miss, (e.get("id"), miss)
    ka = known_answers(recs, reg)
    res = {"milestone": "M556", "mode": mode, "stats": stats, "knownAnswer": ka, "extractorSourceHash": _src_hash(), "registrySha256": reg_hash}
    if any(ka["misses"][k] for k in ("textRoute", "partition", "bms12NonZero")):
        json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, default=float)
        print(json.dumps({"STOP": "known-answer miss", **ka}, default=float)); sys.exit(2)
    raw_all = sorted({f for v in rawmap.values() for f in v}); matched = {a["rawName"] for a in recs.values()}
    mf = json.load(open("raw_manifest.json", encoding="utf-8"))
    dg = lambda s_: "".join(ch for ch in s_ if ch.isdigit())[:14]
    excl = {dg(x["raw_name"]) for x in mf.get("typedExclusions", [])}
    notin = sorted(set(raw_all) - matched)
    res["reconciliation"] = {"rawFilesInRaw": len(raw_all), "masterRows": int(len(dm)), "masterRowsParsed": len(recs), "unparsedMasterRows": unparsed,
                             "rawNotInMaster": len(notin), "rawNotInMasterByRole": {"auxiliary (e4ORCE exports)": sum(1 for f in notin if f.startswith("e4ORCE")), "comparison_only (typedExclusions)": sum(1 for f in notin if not f.startswith("e4ORCE") and dg(f) in excl),
                                                                                       "unexplained": sum(1 for f in notin if not f.startswith("e4ORCE") and dg(f) not in excl)}}
    sr = _sr_lookup()
    res["entries"] = [entry_block(e, recs, sr) for e in reg["entries"]]
    air = [e for e in reg["entries"] if e["rule"]["kind"] == "value_equals"]
    if air and "T_intake" in dm.columns:
        ti = pd.to_numeric(dm["T_intake"], errors="coerce").dropna()
        res["masterIntakeCheck"] = {"column": "T_intake", "nNonMissing": int(len(ti)), "min": float(ti.min()), "max": float(ti.max()), "rowsOutsideBound": int(((ti < AIR_BOUNDS[0]) | (ti > AIR_BOUNDS[1])).sum()), "bounds": list(AIR_BOUNDS)}
    res["inventory"] = inventory(recs, {e["column"] for e in reg["entries"]})
    res["inventory"]["coverage"] = "full read of every parsed master-mapped raw file (signal_representation.json covers only a subset of recent files and is used for resolution cross-checks, not for the inventory)"
    json.dump(res, open(OUT if not only else OUT.replace(".json", "_sample.json"), "w", encoding="utf-8"), indent=1, default=float)
    json.dump({f: {"declared": a["rec"]["declared"]} for f, a in recs.items()}, open(os.path.join(CACHE, "_all.json" if not only else "_sample.json"), "w", encoding="utf-8"), default=float)
    print(json.dumps({"ok": True, "stats": stats, "knownAnswer": ka, "reconciliation": res["reconciliation"], "entries": [{k: b.get(k) for k in ("id", "filesWithHeader", "filesWithSamples", "headerOnlyEmptyFiles", "filesRuleHolds", "filesRuleNotHolding", "samples")} for b in res["entries"]]}, default=float))
    if mode == "--splice" and not only:
        splice(res)


def splice(res):
    """additive write of S.signalValidity (+ stamp); no existing key changes."""
    flags = {}
    for b in res["entries"]:
        f = {"headerOnlyEmptyOver5Pct": bool(b["filesWithHeader"] and b["headerOnlyEmptyFiles"] > 0.05 * b["filesWithHeader"]), "headerMatchesOverOne": b["headerMatchesOverOne"] > 0,
             "consumersListedNonEmpty": bool(b["consumers"])}
        if b["rule"]["kind"] == "all_non_missing_equal":
            f["nonZeroValuesInDeclaredChannel"] = b["nonZeroValuesInDeclaredChannel"] > 0
        if b["rule"]["kind"] == "value_equals":
            f["otherOutOfBoundValues"] = b["otherOutOfBoundSamples"] > 0
        flags[b["id"]] = f
    flags["masterIntakeRowsOutsideBound"] = int((res.get("masterIntakeCheck") or {}).get("rowsOutsideBound", 0))
    flags["rawNotInMasterUnexplained"] = res["reconciliation"]["rawNotInMasterByRole"]["unexplained"]
    flags["unparsedMasterRows"] = len(res["reconciliation"]["unparsedMasterRows"])
    block = {"_provenance": "GENERATED by tools/signal_validity.py (M556). Do not hand-edit; the declarations are in signal_validity_registry.json.", "schemaVersion": 1,
             "basis": "raw bytes of the master-mapped files; raw zeros are preserved and nothing is suppressed; raw/ = sha256-verified originals (M366)",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "registrySha256": res["registrySha256"]},
             "rule": {"declaration": "per-channel declarations with a physical justification; no generic all-zero rule", "equality": "values parsed as numbers (0, 0.0, -0 equal 0 exactly); empty and non-numeric are missing; the rule is per file and needs at least one non-missing value",
                      "reader": "status(entry, values) returns {status, values, escalate}; unavailable withholds the values, not-holding returns them unchanged, empty is not testable", "inventory": "channels all zero in at least one file (n >= %d); not a validity declaration" % INVENTORY_MIN_N},
             "reconciliation": res["reconciliation"], "knownAnswer": res["knownAnswer"], "masterIntakeCheck": res.get("masterIntakeCheck"), "entries": res["entries"], "inventory": res["inventory"], "flags": flags,
             "limits": ["a validity rule holds in the corpus files listed, not always; the cause of the all-zero response of the BMS 12 V channel is unknown", "no physical statement about a 12 V supply, battery or DC/DC converter is made from any of these channels",
                        "the all-zero inventory contains channels whose zeros are physical (for example an engine that never ran); it is not a validity declaration", "the intake-air sentinel is handled upstream in the master; this block only counts it",
                        "the adapter and ECU supply channels are sparse, location-specific observations"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("signalValidity", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "signalValidity"}
    A2["signalValidity"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M556: computed by tools/signal_validity.py from the raw bytes; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["signalValidity"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "signalValidity"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"signalValidity": "written"}))


if __name__ == "__main__":
    main()
