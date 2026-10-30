#!/usr/bin/env python3
"""M544 (analyses/M544_spec.md Rev 2): wave 3-0 EVIDENCE for the _RawAccum engine-on blocks (engineOnDuration, engineOnBySpeed, turboByRpm / turboBySpeedCtx, hvcTurboActivity) under the engine-on rule (rpm > 400) next to the stored
rpm > 300 gate. Read-only: no payload key, no JSX, no dashboard change. Output analyses/M544_evidence.json (first output kept).

Method: the class compute_summary_arrays._RawAccum is re-created from its own source with the threshold literals replaced ONLY at the registry anchors (engineOnDuration `eon = (rr > 300)`, engineOnBySpeed and turbo `eng = rp > 300` (2), per-class turbo
`m = (rp > 300)`); the regeneration proxy (rp <= 300) and the onset detector (> 300) are untouched (the onset sensitivity is a third copy). One observer line (`self._eon_hook = eon.copy()`) is added after the engineOnDuration threshold line to read the
run structure. Frames come from the pipeline loader (drive_raw_cache.make_frame_loader over raw_only/, master order, silent skip of missing frames, as category_B).
Gates (STOP, nothing written): G0a the substituted copy at 300 equals the imported class per drive (accumulator state of the targeted blocks); G0b the 300 copy reproduces the STORED blocks (primary and the cohort charts) exactly; G0c every finalize key
outside the targeted keys is byte-identical between the 300 and 400 copies; the substitution counts equal the registry anchors.
Usage: python tools/engine_on_wave3_evidence.py [--synthetic-only]"""
import copy, hashlib, inspect, io, json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

OUT = os.path.join(ROOT, "analyses", "M544_evidence.json")
ADD_OUT = os.path.join(ROOT, "analyses", "M544_evidence_addendum.json")        # Director addendum: E3 / E1 identity gates and the full flip list (first output kept)
NB, SEED = 4000, 42
TARGET_KEYS = ("engineOnDuration", "engineOnBySpeed", "turboByRpm", "turboBySpeedCtx", "hvcTurboActivity")
ANCHORS = [("eon = (rr > 300) & valid", "eon = (rr > 400) & valid", 1),
           ("eng = rp > 300", "eng = rp > 400", 2),
           ("m = (rp > 300) & ~np.isnan(bo)", "m = (rp > 400) & ~np.isnan(bo)", 1)]
ONSET = ("on = np.nan_to_num(er, nan=0.0) > 300     # NaN -> off boundary", "on = np.nan_to_num(er, nan=0.0) > 400     # NaN -> off boundary", 1)
HOOK_AFTER = "eon = (rr > {t}) & valid\n"
CHART = {"engineOnDuration": "EngineOnDuration", "engineOnBySpeed": "EngineOnBySpeed", "turboByRpm": "TurboByRpm"}


def canon(o):
    return json.dumps(json.loads(json.dumps(o, default=float)), sort_keys=True)


def classify_runs(eon_lo, eon_hi):
    """run-boundary taxonomy between the lower-threshold on-set and the higher-threshold on-set (a subset): each lower run is UNCHANGED, SHORTENED (one sub-run with other bounds), SPLIT (>= 2 sub-runs) or DROPPED (none); runs cannot merge."""
    a = np.asarray(eon_lo, dtype=bool); b = np.asarray(eon_hi, dtype=bool)
    assert not (b & ~a).any(), "the higher-threshold on-set must be a subset"
    ea = np.diff(np.concatenate([[0], a.astype(int), [0]]))
    sa, ee = np.where(ea == 1)[0], np.where(ea == -1)[0]
    eb = np.diff(np.concatenate([[0], b.astype(int), [0]]))
    sb, eeb = np.where(eb == 1)[0], np.where(eb == -1)[0]
    out = {"unchanged": 0, "shortened": 0, "split": 0, "dropped": 0, "subRuns": int(len(sb))}
    for s, e in zip(sa, ee):
        inside = [(x, y) for x, y in zip(sb, eeb) if x >= s and y <= e]
        if not inside:
            out["dropped"] += 1
        elif len(inside) >= 2:
            out["split"] += 1
        elif inside[0] == (s, e):
            out["unchanged"] += 1
        else:
            out["shortened"] += 1
    out["runsLow"] = int(len(sa))
    return out


def build_classes():
    import compute_summary_arrays as C
    src = inspect.getsource(C._RawAccum)
    diff = []

    def mk(onset):
        s = src
        for old, new, cnt in ANCHORS:
            assert s.count(old) == cnt, ("anchor count", old, s.count(old))
            s = s.replace(old, new)
        if onset:
            assert s.count(ONSET[0]) == ONSET[2], ("onset anchor", s.count(ONSET[0]))
            s = s.replace(ONSET[0], ONSET[1])
        return s

    def hook(s, t):
        o = "eon = (rr > %d) & valid\n" % t
        assert s.count(o) == 1
        s = s.replace(o, o + "            self._eon_hook = eon.copy()\n")
        o2 = "ok = ~np.isnan(sp) & ~np.isnan(rp)\n"
        assert s.count(o2) == 1
        # independent observer of the rows with 300 < rpm <= 400 per speed zone (E3 identity gate); not part of the pipeline result
        return s.replace(o2, o2 + "            self._band_rows = np.bincount(z[(rp > 300) & (rp <= 400) & ok], minlength=len(Z_ENGINE_LBL)).astype(float)\n")
    base = src
    base300 = hook(base, 300)
    s400 = hook(mk(False), 400)
    s400s = hook(mk(True), 400)
    cls = {}
    for name, text in (("t300", base300), ("t400", s400), ("t400onset", s400s)):
        ns = dict(vars(C))
        exec(compile(text, "<_RawAccum %s>" % name, "exec"), ns)
        cls[name] = ns["_RawAccum"]
    sub = {"sourceSha256": hashlib.sha256(src.encode("utf-8")).hexdigest(), "anchors": [{"from": o, "to": n, "count": c} for o, n, c in ANCHORS], "onsetAnchor": {"from": ONSET[0], "to": ONSET[1]}, "observerLine": "self._eon_hook = eon.copy() after the engineOnDuration threshold line; self._band_rows = per-zone count of native rows with 300 < rpm <= 400 after the engineOnBySpeed ok line (both read-only observers)"}
    return C, cls, sub


def state(acc):
    return canon({"eod": acc.eod, "eod_on": acc.eod_on, "eng_on": acc.eng_on.tolist(), "eng_tot": acc.eng_tot.tolist(), "turbo_rpm": acc.turbo_rpm, "turbo_spd": acc.turbo_spd, "hvc_turbo": acc.hvc_turbo})


def synthetic():
    """known-answer test of the run taxonomy: a dip to 350 rpm splits a run; a run entirely at 350 drops; a run ending exactly at 400 shortens (strict >); a run with a 350 edge shortens"""
    r = np.array([0, 500, 600, 350, 600, 500, 0, 350, 350, 0, 900, 400, 0, 350, 800, 800, 0, 1000, 700, 380, 0], dtype=float)
    lo, hi = r > 300, r > 400
    c = classify_runs(lo, hi)
    assert c == {"unchanged": 0, "shortened": 3, "split": 1, "dropped": 1, "subRuns": 5, "runsLow": 5}, c
    r2 = np.array([0, 500, 600, 500, 0, 700, 700, 0], dtype=float)
    assert classify_runs(r2 > 300, r2 > 400) == {"unchanged": 2, "shortened": 0, "split": 0, "dropped": 0, "subRuns": 2, "runsLow": 2}
    return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    synthetic()
    if "--synthetic-only" in argv:
        print("synthetic ok"); return 0
    import drive_raw_cache as drc
    C, cls, sub = build_classes()
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False, usecols=["file", "thermal_regime"]).set_index("file")["thermal_regime"]
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    fl = drc.make_frame_loader(raw_dir=os.path.abspath("raw_only"))
    dist, cond, date = dict(zip(dm["file"], dm["distance_km"])), dict(zip(dm["file"], dm["drive_type"])), dict(zip(dm["file"], dm["date"]))
    label = {}
    for fn in dm["file"]:
        idx = dm.index[dm["file"] == fn]
        label[fn] = C._day_label(dm, idx[0]) if len(idx) else None
    cohorts = ["all", "warm", "shoulder", "cold"]
    pools = {c: {t: cls[t]() for t in cls} for c in cohorts}
    g0a, tax, segs, n_used = [], {}, {}, 0
    e3_rows, e3_drop, e1 = np.zeros(7), np.zeros(7), {}
    t0 = time.time()
    for fn in dm["file"]:
        try:
            df = fl(fn)
        except Exception:
            continue
        if df is None:
            continue
        n_used += 1
        d3 = cls["t300"](); d3.add(df.copy(), dist.get(fn), cond.get(fn), label.get(fn), fn)
        d0 = C._RawAccum(); d0.add(df.copy(), dist.get(fn), cond.get(fn), label.get(fn), fn)
        g0a.append(state(d0) == state(d3))
        d4 = cls["t400"](); d4.add(df.copy(), dist.get(fn), cond.get(fn), label.get(fn), fn)
        k = str(cond.get(fn))
        if hasattr(d4, "_band_rows"):
            e3_rows += d4._band_rows
        e3_drop += (d3.eng_on - d4.eng_on)
        e1[fn] = float(d4.eod_on.get(k, [0.0])[0]) if k in d4.eod_on else 0.0
        if hasattr(d3, "_eon_hook") and hasattr(d4, "_eon_hook"):
            tx = classify_runs(d3._eon_hook, d4._eon_hook)
            a = tax.setdefault(k, {"unchanged": 0, "shortened": 0, "split": 0, "dropped": 0, "subRuns": 0, "runsLow": 0})
            for kk in a:
                a[kk] += tx[kk]
        for t in ("t300", "t400"):
            dd = d3 if t == "t300" else d4
            segs.setdefault(t, {}).setdefault(k, []).append((str(date.get(fn)), list(dd.eod.get(k, []))))
        for c in cohorts:
            if c == "all" or sdm.get(fn) == c:
                for t in cls:
                    pools[c][t].add(df.copy(), dist.get(fn), cond.get(fn), label.get(fn), fn)
    fin = {c: {t: pools[c][t].finalize() for t in cls} for c in cohorts}
    res = {"spec": "analyses/M544_spec.md Rev 2", "nDrivesUsed": n_used, "nDrivesMaster": int(len(dm)), "substitution": sub,
           "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "runSeconds": round(time.time() - t0, 1)}
    # G0a / G0b / G0c
    g = {"G0a_perDriveStateEqual": bool(all(g0a)), "G0a_nDrives": len(g0a)}
    f3, f4 = fin["all"]["t300"], fin["all"]["t400"]
    g["G0b_primary"] = {k: canon(f3[k]) == canon(A[k]) for k in ("engineOnDuration", "engineOnBySpeed", "turboByRpm", "turboBySpeedCtx")}
    sc = A["seasonalCharts"]["charts"]
    g["G0b_cohortCharts"] = {c: {k: canon(fin[c]["t300"][k]) == canon(sc[CHART[k]]["data"][c]) for k in CHART} for c in cohorts}
    diffk = sorted(k for k in set(f3) | set(f4) if canon(f3.get(k)) != canon(f4.get(k)))
    g["G0c_differingFinalizeKeys"] = diffk
    g["G0c_onlyTargeted"] = bool(set(diffk) <= set(TARGET_KEYS))
    g["passed"] = bool(g["G0a_perDriveStateEqual"] and all(g["G0b_primary"].values()) and all(all(v.values()) for v in g["G0b_cohortCharts"].values()) and g["G0c_onlyTargeted"])
    res["gates"] = g
    if not g["passed"]:
        print(json.dumps({"STOP": "G0 failed", "gates": g}, indent=1)[:3000]); return 1
    # what-if: field-level shifts, 5 % materiality
    def shifts(a, b, key):
        out = []
        for x, y in zip(a, b):
            row = {"key": x.get("label") or x.get("zone") or x.get("rpm") or key}
            for kk, vx in x.items():
                vy = y.get(kk)
                if isinstance(vx, (int, float)) and isinstance(vy, (int, float)) and not isinstance(vx, bool):
                    rel = None if vx == 0 else round(100 * (vy - vx) / abs(vx), 3)
                    row[kk] = {"at300": vx, "at400": vy, "relPct": rel, "material5pct": bool(rel is not None and abs(rel) >= 5)}
            out.append(row)
        return out
    for cname in cohorts:
        a3, a4 = fin[cname]["t300"], fin[cname]["t400"]
        res.setdefault("whatIf", {})[cname] = {k: shifts(a3[k], a4[k], k) for k in ("engineOnDuration", "engineOnBySpeed", "turboByRpm", "turboBySpeedCtx") if isinstance(a3.get(k), list)}
        hv3, hv4 = a3.get("hvcTurboActivity"), a4.get("hvcTurboActivity")
        res["whatIf"][cname]["hvcTurboActivity"] = {"at300": hv3, "at400": hv4, "equal": canon(hv3) == canon(hv4)}
    res["runBoundaryTaxonomy"] = tax
    # identity gates E3 / E4 (counts)
    res["identity"] = {"E4_turboByRpmBandsAt1500AndAboveEqual": bool(all(canon(x) == canon(y) for x, y in zip(f3["turboByRpm"], f4["turboByRpm"]) if x["rpm"] != "<1500"))}
    # day-clustered interval of the pooled median segment length at 300 and 400 (calendar day, seed 42, 4000 draws)
    rng = np.random.default_rng(SEED)
    med = {}
    for k in sorted(segs["t300"]):
        row = {}
        for t in ("t300", "t400"):
            byday = {}
            for dday, v in segs[t][k]:
                byday.setdefault(dday, []).extend(v)
            days = sorted(byday)
            vec = [np.array(byday[dd]) for dd in days]
            allv = np.concatenate(vec) if vec else np.array([])
            row[t] = {"median": float(np.median(allv)) if len(allv) else None, "nSegments": int(len(allv)), "nDays": len(days)}
            if len(days) >= 2 and len(allv):
                r = np.random.default_rng(SEED)
                idx = r.integers(0, len(days), (NB, len(days)))
                meds = [float(np.median(np.concatenate([vec[i] for i in ix if len(vec[i])]))) for ix in idx if any(len(vec[i]) for i in ix)]
                row[t]["ci95"] = [float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))]
            row[t]["exploratory"] = bool(len(days) < 10)
        row["shiftOutsideCi300"] = bool(row["t300"].get("ci95") and row["t400"]["median"] is not None and not (row["t300"]["ci95"][0] <= row["t400"]["median"] <= row["t300"]["ci95"][1]))
        med[k] = row
    res["pooledMedianSegmentSeconds"] = med
    # onset sensitivity (counts only; the name RPM onset is kept)
    o3, o4 = fin["all"]["t300"], fin["all"]["t400onset"]
    res["onsetSensitivity"] = {"name": "RPM onset (> 300 rpm, run >= 2 s); the > 400 version is a sensitivity only", "differingKeys": sorted(k for k in set(o3) | set(o4) if canon(o3.get(k)) != canon(o4.get(k))),
                               "engineStartsByType": {"at300": o3.get("engineStartsByType"), "at400": o4.get("engineStartsByType")}}
    # rule seconds cross-check (E1): the engineOnDuration on-sample count under the rule against engineOnRule per drive class is reported, not forced
    res["ruleSecondsNote"] = "engineOnRule.pooled.engineOnSeconds (grid_rpm, dropna) vs the hz-grid on-sample count of this copy: reported in whatIf onFraction; any difference is explained, never forced"
    # Director addendum: E3 identity (per speed zone, the drop in on-rows equals the count of rows with rpm in (300, 400]), E1 exact (rule seconds per drive equal engineOnRule), full flip / materiality list
    rs = pd.read_csv("engine_on_rule_sidecar.csv").set_index("file")["gt400"]
    e1_diff = {fn: [e1[fn], float(rs.get(fn, np.nan))] for fn in e1 if fn in rs.index and e1[fn] != float(rs[fn])}
    flips, material = [], []
    for cname in cohorts:
        for blk, rows in res["whatIf"][cname].items():
            if not isinstance(rows, list):
                continue
            for r in rows:
                for fld, v in r.items():
                    if isinstance(v, dict) and "at300" in v and v["at300"] != v["at400"]:
                        rec = {"cohort": cname, "block": blk, "key": r["key"], "field": fld, "at300": v["at300"], "at400": v["at400"], "relPct": v["relPct"]}
                        (material if v["material5pct"] else flips).append(rec)
        hv = res["whatIf"][cname]["hvcTurboActivity"]
        if not hv["equal"]:
            for kk in hv["at300"]:
                if hv["at300"][kk] != hv["at400"][kk]:
                    flips.append({"cohort": cname, "block": "hvcTurboActivity", "key": kk, "field": "string", "at300": hv["at300"][kk], "at400": hv["at400"][kk]})
    add = {"spec": "analyses/M544_spec.md Rev 2 + Director addendum", "E3_engineOnBySpeed_identity": {"dropInOnRowsPerZone": e3_drop.tolist(), "rowsWithRpm300to400PerZone": e3_rows.tolist(), "equal": bool(np.array_equal(e3_drop, e3_rows))},
           "E1_ruleSecondsExact": {"nDrivesCompared": len(e1), "nDifferent": len(e1_diff), "differences": dict(list(e1_diff.items())[:20]), "equal": bool(not e1_diff)},
           "changedFieldsMaterial5pct": material, "changedFieldsOther": flips}
    if not os.path.exists(ADD_OUT):
        json.dump(add, open(ADD_OUT, "w", encoding="utf-8", newline=chr(10)), indent=1, ensure_ascii=False, default=float)
    if not (add["E3_engineOnBySpeed_identity"]["equal"] and add["E1_ruleSecondsExact"]["equal"]):
        print(json.dumps({"STOP": "E3 or E1 failed", "addendum": {k: add[k] for k in ("E3_engineOnBySpeed_identity", "E1_ruleSecondsExact")}}, default=float)[:2500])
        return 1
    if not os.path.exists(OUT):
        json.dump(res, open(OUT, "w", encoding="utf-8", newline=chr(10)), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"gates": g, "runBoundaryTaxonomy": tax, "pooledMedianSegmentSeconds": med}, default=float)[:3500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
