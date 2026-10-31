#!/usr/bin/env python3
"""M545 (analyses/M545_spec.md Rev 2): wave 3 of the engine-on migration: additive top-level payload blocks engineOnDurationRule, engineOnBySpeedRule, turboByRpmRule, turboBySpeedCtxRule, hvcTurboActivityRule (+ stamps): the
engine-on blocks of _RawAccum under the project rule (rpm > 400, strict) next to the stored rpm > 300 blocks, all drives and the three season cohorts, with day-clustered intervals. The stored blocks are not touched.

Per-drive sidecar engine_on_blocks_sidecar.json (tracked, deterministic JSON, LF): the sufficient statistics of ONE drive from _RawAccum(eng_on_rpm=400).add(...) (run lengths, on / valid / segment counts, per-zone native counts,
per-band and per-zone turbo counts, per-drive hvc counts). It stores NO drive class, cohort, cadence stratum, date or rendered label: these are joined from the master at aggregation, so a refit cannot leave the cache stale. Cache key per
drive: raw-file SHA-256; global key (meta): sha of the entry function + tools/engine_on_blocks.py + grid-convention version + loader code key + threshold. Aggregation never rereads raw CSVs. Run lengths merge by CONCATENATION (exact medians),
counts by summation.
Gates (STOP, nothing written): E1 the per-drive rule seconds equal engine_on_rule_sidecar.csv gt400 on every drive; drive set = the stored blocks' set (engineOnDrives equal); with --g300 also G1: the aggregator on entries built at threshold 300 reproduces the
stored five blocks and the cohort charts byte for byte. Usage: python tools/engine_on_blocks_stage.py [--dry-run] [--check] [--rebuild] [--g300]"""
import copy, datetime, hashlib, inspect, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import engine_on_blocks as EOB

KEYS = ("engineOnDurationRule", "engineOnBySpeedRule", "turboByRpmRule", "turboBySpeedCtxRule", "hvcTurboActivityRule")
STORED = {"engineOnDurationRule": "engineOnDuration", "engineOnBySpeedRule": "engineOnBySpeed", "turboByRpmRule": "turboByRpm", "turboBySpeedCtxRule": "turboBySpeedCtx", "hvcTurboActivityRule": "hvcTurboActivity"}
CHART = {"engineOnDuration": "EngineOnDuration", "engineOnBySpeed": "EngineOnBySpeed", "turboByRpm": "TurboByRpm"}
SIDECAR = os.path.join(ROOT, "engine_on_blocks_sidecar.json")
SPEC = "analyses/M545_spec.md"
THR = 400
NB, SEED, MIN_DAYS = 4000, 42, 5
COHORTS = ("all", "warm", "shoulder", "cold")
DUMMY_CLASS = "urban"         # gates the class-keyed accumulators of add(); the class itself is joined from the master at aggregation
SPD_COL = ["#3b82f6", "#60a5fa", "#4ade80", "#eab308", "#f97316", "#ef4444", "#dc2626"]
EOD_COL = {"urban": "#ef4444", "mixed": "#eab308", "mixed_highway": "#3b82f6", "highway": "#22c55e"}


def canon(o):
    return json.dumps(json.loads(json.dumps(o, default=float)), sort_keys=True)


def _ints(a):
    return [int(x) if float(x) == int(x) else float(x) for x in a]


def build_entry(acc):
    """one drive's sufficient statistics from a single-drive _RawAccum (class key DUMMY_CLASS)"""
    e = {"runs": _ints(acc.eod.get(DUMMY_CLASS, [])), "eod": [float(x) for x in acc.eod_on[DUMMY_CLASS]] if DUMMY_CLASS in acc.eod_on else None,
         "spdTot": [float(x) for x in acc.eng_tot], "spdOn": [float(x) for x in acc.eng_on], "spdAny": bool(acc.eng_on_files),
         "tr": {l: [int(d["n"]), int(d["act"]), float(d["sumAct"]), float(d["max"])] for l, d in acc.turbo_rpm.items() if d["n"]},
         "ts": {l: [int(d["n"]), int(d["act"]), float(d["max"])] for l, d in acc.turbo_spd.items() if d["n"]},
         "hvc": [int(acc.hvc_turbo[DUMMY_CLASS]["n"]), int(acc.hvc_turbo[DUMMY_CLASS]["act"]), float(acc.hvc_turbo[DUMMY_CLASS]["max"])] if acc.hvc_turbo[DUMMY_CLASS]["n"] else None}
    return e


def _meta(thr):
    import compute_summary_arrays as cs
    import drive_raw_cache as drc
    src = inspect.getsource(build_entry) + open(os.path.join(ROOT, "tools", "engine_on_blocks.py"), encoding="utf-8").read()
    return {"rowFnSha256": hashlib.sha256(src.encode("utf-8")).hexdigest(), "gridVersion": EOB.GRID_VERSION, "loaderCodeKey": str(drc.code_key()), "thresholdRpm": thr, "boundary": "gt",
            "note": "raw/ = sha256-verified originals (M366); no class, cohort, cadence, date or label is stored"}


def compute_entries(dm, thr, sidecar_path=None, rebuild=False):
    """{file: entry} at threshold thr; with sidecar_path the file is the cache (only new or changed drives are parsed); without it nothing is read or written (gate use)"""
    import compute_summary_arrays as cs
    import drive_raw_cache as drc
    import ah_throughput as AH
    load = AH.raw_loader(); fl = drc.make_frame_loader(raw_dir=os.path.abspath(os.path.join(ROOT, "raw_only")))
    meta = _meta(thr); old = {}
    if sidecar_path and not rebuild and os.path.exists(sidecar_path):
        J = json.load(open(sidecar_path, encoding="utf-8"))
        if J.get("meta") == meta:
            old = J["drives"]
    dist = dict(zip(dm["file"], dm["distance_km"]))
    out, rep = {}, 0
    for i, fn in enumerate(dm["file"]):
        raw = load(fn)
        if raw is None:
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if fn in old and old[fn]["sha256"] == sha:
            out[fn] = old[fn]; continue
        try:
            df = fl(fn)
        except Exception:
            df = None
        if df is None:
            continue
        acc = cs._RawAccum(eng_on_rpm=thr)
        acc.add(df.copy(), dist.get(fn), DUMMY_CLASS, cs._day_label(dm, i), fn)
        e = build_entry(acc); e["sha256"] = sha
        out[fn] = e; rep += 1
    if sidecar_path:
        with open(sidecar_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"meta": meta, "drives": {k: out[k] for k in sorted(out)}}, sort_keys=True, separators=(",", ":")) + "\n")
    return out, rep


def _pct_ci(rng_seed, num_by_day, den_by_day):
    days = sorted(num_by_day)
    if len(days) < 2 or sum(den_by_day[d] for d in days) == 0:
        return None
    n = np.array([num_by_day[d] for d in days], float); m = np.array([den_by_day[d] for d in days], float)
    idx = np.random.default_rng(rng_seed).integers(0, len(days), (NB, len(days)))
    dn, dm_ = n[idx].sum(1), m[idx].sum(1)
    ok = dm_ > 0
    r = 100.0 * dn[ok] / dm_[ok]
    return [round(float(np.percentile(r, 2.5)), 2), round(float(np.percentile(r, 97.5)), 2)]


def _median_ci(rng_seed, runs_by_day):
    days = [d for d in sorted(runs_by_day) if len(runs_by_day[d])]
    if len(days) < 2:
        return None
    vec = [np.asarray(runs_by_day[d], float) for d in days]
    idx = np.random.default_rng(rng_seed).integers(0, len(days), (NB, len(days)))
    meds = [float(np.median(np.concatenate([vec[i] for i in ix]))) for ix in idx]
    return [round(float(np.percentile(meds, 2.5)), 1), round(float(np.percentile(meds, 97.5)), 1)]


def aggregate(entries, rows, with_ci=True, stored_wording=False):
    """rows: list of dict(file, cls (master drive_type), day, label (day label), idx) in master order. Returns the five stored-shaped blocks plus the detail leaves (counts, n drives, n days, intervals)."""
    import compute_summary_arrays as cs
    eod, eod_on = {}, {}
    tot, on, files = np.zeros(len(cs.Z_ENGINE_LBL)), np.zeros(len(cs.Z_ENGINE_LBL)), 0
    tr = {lbl: {"n": 0, "act": 0, "sumAct": 0., "max": 0.} for _, _, lbl in cs.RPM_BANDS}
    ts = {lbl: {"n": 0, "act": 0, "max": 0.} for _, _, lbl in cs.Z_TURBO_SPD}
    hv = {k: {"n": 0, "act": 0, "max": 0.0, "label": None} for k in cs.CLASS_ORDER}
    day = {"eod": {}, "spd": {}, "hvc": {}}
    drives = set(); days = set(); cls_drives, cls_days = {}, {}; hvc_drives = {}
    for r in rows:
        e = entries.get(r["file"])
        if e is None:
            continue
        drives.add(r["file"]); days.add(r["day"])
        k = str(r["cls"])
        if e["eod"] is not None:
            eod.setdefault(k, []).extend(float(x) for x in e["runs"])
            a = eod_on.setdefault(k, [0.0, 0.0, 0.0])
            a[0] += e["eod"][0]; a[1] += e["eod"][1]; a[2] += e["eod"][2]
            dd = day["eod"].setdefault(k, {}).setdefault(r["day"], [])
            dd.extend(float(x) for x in e["runs"])
            cls_drives.setdefault(k, set()).add(r["file"]); cls_days.setdefault(k, set()).add(r["day"])
        tot += np.array(e["spdTot"]); on += np.array(e["spdOn"]); files += int(e["spdAny"])
        dsp = day["spd"].setdefault(r["day"], [np.zeros(len(tot)), np.zeros(len(tot))])
        dsp[0] += np.array(e["spdTot"]); dsp[1] += np.array(e["spdOn"])
        for l, v in e["tr"].items():
            d = tr[l]; d["n"] += v[0]; d["act"] += v[1]; d["sumAct"] += v[2]; d["max"] = max(d["max"], v[3])
        for l, v in e["ts"].items():
            d = ts[l]; d["n"] += v[0]; d["act"] += v[1]; d["max"] = max(d["max"], v[2])
        c2 = cs._cond_class(r["cls"])
        if c2 and e["hvc"]:
            d = hv[c2]; d["n"] += e["hvc"][0]; d["act"] += e["hvc"][1]
            if e["hvc"][2] > d["max"]:
                d["max"] = e["hvc"][2]; d["label"] = r["label"]
            hvc_drives.setdefault(c2, set()).add(r["file"])
            h = day["hvc"].setdefault(c2, {}).setdefault(r["day"], [0, 0, r["file"]])
            h[0] += e["hvc"][0]; h[1] += e["hvc"][1]
    out, det = {}, {}
    pct = np.where(tot > 0, on / tot * 100, 0)
    out["engineOnBySpeed"] = [{"zone": z, "pct": round(float(p)), "color": c} for z, p, c in zip(cs.Z_ENGINE_LBL, pct, SPD_COL)]
    det["engineOnBySpeed"] = {"nDrives": int(files), "nDays": len(days), "exploratory": bool(len(days) < MIN_DAYS), "zones": []}
    for i, z in enumerate(cs.Z_ENGINE_LBL):
        nd = {d: v[1][i] for d, v in day["spd"].items()}; dd = {d: v[0][i] for d, v in day["spd"].items()}
        det["engineOnBySpeed"]["zones"].append({"zone": z, "onRows": int(on[i]), "totRows": int(tot[i]), "pctExact": round(float(pct[i]), 3),
                                                "ci95": _pct_ci(SEED + i, nd, dd) if with_ci and len(days) >= 2 else None})
    eo = []
    det["engineOnDuration"] = {}
    for k in cs.CLASS_ORDER:
        L = eod.get(k)
        if not L or len(L) < 5:
            continue
        a = np.asarray(L, float); o, t_, ns = eod_on[k]
        eo.append({"label": k.replace("_", " ").title(), "min": round(float(a.min()), 1), "max": round(float(a.max()), 1), "median": round(float(np.median(a)), 1),
                   "p10": round(float(np.percentile(a, 10)), 1), "p90": round(float(np.percentile(a, 90)), 1), "onFraction": round(o / t_ * 100, 1) if t_ else None,
                   "segsPer10min": round(ns / (t_ / 600.0), 1) if t_ else None, "nSegments": int(len(a)), "color": EOD_COL.get(k, "#94a3b8")})
        nday = len(cls_days[k])
        det["engineOnDuration"][k] = {"nDrives": len(cls_drives[k]), "nDays": nday, "nSegments": int(len(a)), "medianCi95": _median_ci(SEED, day["eod"][k]) if with_ci and nday >= 2 else None,
                                      "exploratory": bool(nday < MIN_DAYS)}
    out["engineOnDuration"] = eo
    out["turboByRpm"] = [{"rpm": lbl, "n": tr[lbl]["n"], "activePct": round(tr[lbl]["act"] / tr[lbl]["n"] * 100),
                          "meanActive": round(tr[lbl]["sumAct"] / tr[lbl]["act"], 3) if tr[lbl]["act"] else 0.0, "maxBoost": round(tr[lbl]["max"], 2)}
                         for _, _, lbl in cs.RPM_BANDS if tr[lbl]["n"]]
    out["turboBySpeedCtx"] = [{"zone": lbl, "activePct": round(ts[lbl]["act"] / ts[lbl]["n"] * 100), "maxBoost": round(ts[lbl]["max"], 2)} for _, _, lbl in cs.Z_TURBO_SPD if ts[lbl]["n"]]
    det["turboByRpm"] = {"nDrives": len(drives), "nDays": len(days), "exploratory": bool(len(days) < MIN_DAYS)}
    det["turboBySpeedCtx"] = dict(det["turboByRpm"])
    hvs, hdet = {}, {}
    for k in cs.CLASS_ORDER:
        d = hv[k]
        if d["n"] == 0:
            hvs[k] = None; continue
        share = d["act"] / d["n"] * 100
        hdays = day["hvc"].get(k, {})
        hdet[k] = {"n": d["n"], "act": d["act"], "sharePct": round(share, 3), "maxBoost": round(d["max"], 3), "maxLabel": d["label"], "nDrives": len(hvc_drives.get(k, ())), "nDrivesInClass": len(cls_drives.get(k, ())), "nDays": len(hdays),
                   "exploratory": bool(len(hdays) < MIN_DAYS), "ci95": _pct_ci(SEED, {x: v[1] for x, v in hdays.items()}, {x: v[0] for x, v in hdays.items()}) if with_ci and len(hdays) >= 2 else None}
        if stored_wording:        # the former wording, used only by the G1 identity gate against the stored string
            s = "%.1f%% of engine-on time (n=%s, >0.1 bar)" % (share, format(d["n"], ","))
        else:
            s = "%.1f%% of engine-on native rows (rpm > 400, logged samples; n=%s, >0.1 bar)" % (share, format(d["n"], ","))
        if d["max"] > 0:
            s += "; peak %.2f bar" % d["max"] + (" — %s" % d["label"] if d["label"] else "")
        hvs[k] = s
    out["hvcTurboActivity"] = hvs
    det["hvcTurboActivity"] = hdet
    return out, det


def master_rows(dm):
    import compute_summary_arrays as cs
    sdm = pd.read_csv(os.path.join(ROOT, "seasonal_drive_master.csv"), low_memory=False, usecols=["file", "thermal_regime"]).set_index("file")["thermal_regime"]
    return [{"file": fn, "cls": dm["drive_type"].iloc[i], "day": str(dm["date"].iloc[i]), "label": cs._day_label(dm, i), "cohort": sdm.get(fn)} for i, fn in enumerate(dm["file"])]


def by_cohort(entries, rows, **kw):
    return {c: aggregate(entries, [r for r in rows if c == "all" or r["cohort"] == c], **kw) for c in COHORTS}


def g300(dm, rows, A):
    """G1: the aggregator on entries built at threshold 300 reproduces the stored blocks and the cohort charts byte for byte (nothing is read from or written to the sidecar)"""
    ent, _ = compute_entries(dm, 300, None)
    res = by_cohort(ent, rows, with_ci=False, stored_wording=True)
    res["all"][0]["hvcTurboActivity"]["city"] = res["all"][0]["hvcTurboActivity"]["urban"]       # the stored block carries the M86 alias
    sc = A["seasonalCharts"]["charts"]
    g = {"primary": {k: canon(res["all"][0][k]) == canon(A[k]) for k in ("engineOnDuration", "engineOnBySpeed", "turboByRpm", "turboBySpeedCtx", "hvcTurboActivity")},
         "cohortCharts": {c: {k: canon(res[c][0][k]) == canon(sc[CHART[k]]["data"][c]) for k in CHART} for c in COHORTS}}
    g["engineOnDrives"] = bool(res["all"][1]["engineOnBySpeed"]["nDrives"] == A["engineOnDrives"])
    g["passed"] = bool(all(g["primary"].values()) and all(all(v.values()) for v in g["cohortCharts"].values()) and g["engineOnDrives"])
    return g


_HV = __import__("re").compile(r"([\d.]+)% of engine-on (?:time|native rows) \((?:rpm > 400, logged samples; )?n=([\d,]+)")


def ka_m544(res):
    """pre-registered known answers: every numeric field of the Rule lists equals the 'at400' value recorded by the M544 evidence tool (all-drives view and the three cohorts); hvc counts and shares equal the digits of the M544 strings"""
    p = os.path.join(ROOT, "analyses", "M544_evidence.json")
    if not os.path.exists(p):
        return {"skipped": "analyses/M544_evidence.json absent", "passed": True}
    E = json.load(open(p, encoding="utf-8"))["whatIf"]
    bad = []
    for c in COHORTS:
        for blk in ("engineOnDuration", "engineOnBySpeed", "turboByRpm", "turboBySpeedCtx"):
            for row_e, row_r in zip(E[c][blk], res[c][0][blk]):
                for fld, v in row_e.items():
                    if isinstance(v, dict) and "at400" in v and v["at400"] != row_r.get(fld):
                        bad.append([c, blk, row_e["key"], fld, v["at400"], row_r.get(fld)])
            if len(E[c][blk]) != len(res[c][0][blk]):
                bad.append([c, blk, "rowCount", len(E[c][blk]), len(res[c][0][blk])])
        h4, hr = E[c]["hvcTurboActivity"]["at400"], res[c][0]["hvcTurboActivity"]
        for k in h4:
            if k == "city":
                continue
            a, b = (_HV.match(h4[k]) if h4[k] else None), (_HV.match(hr.get(k)) if hr.get(k) else None)
            if (a and a.groups()) != (b and b.groups()):
                bad.append([c, "hvcTurboActivity", k, a and a.groups(), b and b.groups()])
    return {"nMismatches": len(bad), "mismatches": bad[:20], "passed": not bad}


BASIS = {"engineOnDurationRule": "engine-on run lengths (rpm > 400, 1 Hz grid, strict; NaN breaks a run): run-boundary re-definition (rpm > 400, 1 Hz grid; deterministic, same data)",
         "engineOnBySpeedRule": "share of native rows with logged rpm > 400 per speed zone (rpm > 400, native rows)",
         "turboByRpmRule": "boost > 0.1 bar share of engine-on native rows (rpm > 400, native rows) per rpm band",
         "turboBySpeedCtxRule": "boost > 0.1 bar share of engine-on native rows (rpm > 400, native rows) per speed zone",
         "hvcTurboActivityRule": "boost > 0.1 bar share of engine-on native rows (rpm > 400, logged samples) per drive type"}


def build_blocks(dm, A, rebuild=False):
    import re
    rows = master_rows(dm)
    ent, rep = compute_entries(dm, THR, SIDECAR, rebuild)
    rs = pd.read_csv(os.path.join(ROOT, "engine_on_rule_sidecar.csv")).set_index("file")["gt400"]
    e1 = [fn for fn, e in ent.items() if fn in rs.index and (e["eod"][0] if e["eod"] else 0.0) != float(rs[fn])]
    gates = {"E1RuleSecondsExact": {"nCompared": int(sum(1 for fn in ent if fn in rs.index)), "nDifferent": len(e1), "passed": not e1}}
    res = by_cohort(ent, rows)
    gates["driveSetEqualsStoredBlock"] = bool(res["all"][1]["engineOnBySpeed"]["nDrives"] == A["engineOnDrives"])
    gates["M544KnownAnswers"] = ka_m544(res)
    gates["passed"] = bool(gates["E1RuleSecondsExact"]["passed"] and gates["driveSetEqualsStoredBlock"] and gates["M544KnownAnswers"]["passed"])
    sha = lambda q: hashlib.sha256(open(os.path.join(ROOT, q), "rb").read()).hexdigest()
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    prov = {"spec": SPEC, "specSha256": sha(SPEC), "toolSha256": sha("tools/engine_on_blocks_stage.py"), "kernelsSha256": sha("tools/engine_on_blocks.py"), "masterMd5": md5, "reparsedDrives": rep, "gates": gates,
            "method": {"cluster": "calendar day", "draws": NB, "seed": SEED, "interval": "percentile; ratio of sums (shares) or pooled median of run lengths", "minDaysForIntervalReading": MIN_DAYS},
            "cohortSource": "thermal_regime of seasonal_drive_master.csv"}
    out = {}
    for key in KEYS:
        st = STORED[key]
        blk = {"estimand": BASIS[key], "basis": "rpm > 400 (strict) on the pipeline convention of the stored block; a deterministic re-definition on the same data, not a correction; the stored rpm > 300 block is unchanged (key %s)" % st,
               "rule": {"thresholdRpm": THR, "boundary": "gt", "name": "engine-on (rpm > 400)", "storedKey": st}, "descriptive": True, "displayed": False, "pooled": res["all"][0][st], "byCohort": {c: res[c][0][st] for c in COHORTS[1:]},
               "detail": {"pooled": res["all"][1].get(st), "byCohort": {c: res[c][1].get(st) for c in COHORTS[1:]}},
               "limits": ["logged rpm and boost are app-reported, not measured", "native-row blocks are shares of logged samples at the native cadence, not time-weighted (M521)", "no 300-versus-400 contrast or difference interval is drawn",
                          "fewer than %d calendar days: exploratory, no interval reading" % MIN_DAYS, "the day bootstrap does not capture serial day correlation; convenience sample"],
               "provenance": prov}
        if key == "hvcTurboActivityRule":
            sb = {}
            for k, v in (A.get(st) or {}).items():
                m = re.match(r"([\d.]+)% of engine-on time \(n=([\d,]+)", v or "")
                if m and k != "city":
                    sb[k] = {"sharePct": float(m.group(1)), "n": int(m.group(2).replace(",", "")), "label": "stored basis (rpm > 300, native rows)"}
            blk["storedBasis"] = sb
            blk["pooled"]["city"] = blk["pooled"]["urban"]
        out[key] = blk
    return out, gates


def splice(A, blocks, master_md5="", now=None):
    new = copy.deepcopy(A)
    for key, blk in blocks.items():
        new[key] = blk
        old = (A.get("_artifactStamps") or {}).get(key)
        if old and A.get(key) == blk and old.get("corpusHash") == master_md5:
            new["_artifactStamps"][key] = old
        else:
            st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
            st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                      computationStatusNote="M545: derived by tools/engine_on_blocks_stage.py from drive_master.csv and the raw drive files through engine_on_blocks_sidecar.json (keyed by raw sha256); gates E1 and the M544 known answers",
                      upstreamHashes={"driveMasterMd5": master_md5})
            st.pop("carriedForward", None)
            st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
            import stamp_common as _sc
            new["_artifactStamps"][key] = _sc.carry_declared(old, st)
    ch = [k for k in set(A) | set(new) if A.get(k) != new.get(k)]
    bad = [k for k in ch if k not in KEYS and k != "_artifactStamps"]
    st_bad = [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k) and k not in KEYS]
    return new, ch, bad + st_bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw_txt = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw_txt)
    if "--g300" in argv:
        g = g300(dm, master_rows(dm), A)
        json.dump({"spec": SPEC, "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "gates": g}, open(os.path.join("analyses", "M545_g300.json"), "w", encoding="utf-8", newline=chr(10)), indent=1)
        print(json.dumps(g))
        return 0 if g["passed"] else 1
    blocks, gates = build_blocks(dm, A, rebuild="--rebuild" in argv)
    if not gates["passed"]:
        print(json.dumps({"STOP": "E1 / drive set / M544 known answers failed", "gates": gates}, default=float)[:3000])
        return 1
    if "--check" in argv:
        keep = lambda b: {k: v for k, v in (b or {}).items() if k != "provenance"}
        ok = all(keep(A.get(k)) == keep(blocks[k]) for k in KEYS)
        print(json.dumps({"check": list(KEYS), "matchesPayload": ok}))
        return 0 if ok else 1
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, ch, bad = splice(A, blocks, md5)
    print(json.dumps({"gates": gates, "nChanged": len(ch), "outsideAllowList": bad}, default=float)[:2500])
    if bad:
        return 1
    if "--dry-run" not in argv and ch:
        with open("summary_arrays.json", "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw_txt.endswith(chr(10)) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
