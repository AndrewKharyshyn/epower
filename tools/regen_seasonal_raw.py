#!/usr/bin/env python3
"""M341 (spec analyses/M341_spec.md rev 2): regenerate the 37 RAW-class seasonal contracts (seasonalCharts.charts[ID].data.{all,warm,shoulder}) on the live corpus.
Same released builders as the top-level blocks, called per thermal cohort (thermal_regime of seasonal_drive_master.csv). PARITY GUARD per chart: the all-rows result must equal the fresh
top-level block byte-for-byte (canonical JSON; composed blocks: crawlStopGo + two-part, highSocRegen + covariates, thermalFuelPenalty + continuous); a chart that fails is NOT spliced.
Loaders: raw_only/ (staged master-key view of raw/; F03 provenance-sensitive) and drive_raw_cache.make_frame_loader() exactly as the pipeline. Never writes drive_master.csv or raw files.
Modes: --check (parity, conservation, cutpoint scan, timings; writes analyses/M341_check.json, no payload write) | --splice (check + additive splice + m295_payload.py).
Usage: python tools/regen_seasonal_raw.py --check|--splice [--only ID,ID] [--no-cache]"""
import copy, hashlib, inspect, json, os, pickle, re, subprocess, sys, time, datetime
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import compute_summary_arrays as C
import drive_raw_cache as drc

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M341_check.json")
CACHE = os.path.join(os.environ.get("TEMP", ROOT), "m341_cache")
RAW_DIR = os.path.abspath("raw_only")
LC = lambda s: s[0].lower() + s[1:]
COUNT_KEYS = {"nDrives", "n_drives", "drives", "hours", "nStops", "seconds", "km", "totalKm", "nEvents", "events", "nFiles", "nStarts", "starts", "totalHours", "pooledHours", "n"}


def canon(o):
    return json.dumps(json.loads(json.dumps(o, default=float)), sort_keys=True)


def raw_loader(fn):
    with open(os.path.join(RAW_DIR, fn), "rb") as f:
        return f.read()


class Counting:
    """wraps a loader to count successful loads (category_B skips files silently on exceptions)."""
    def __init__(self, f):
        self.f, self.ok, self.none, self.err = f, 0, 0, 0

    def __call__(self, fn):
        try:
            r = self.f(fn)
        except Exception:
            self.err += 1; raise
        if r is None:
            self.none += 1
        else:
            self.ok += 1
        return r


def builders(fl, rl, rd):
    """chart id -> callable(sub dm) returning that chart's TOP-LEVEL-composed block, exactly as build_summary_arrays composes it."""
    def csg(sub):
        b = C._crawl_stop_go(sub, rl, frame_loader=fl)
        if b:
            t = C._crawl_stop_go_two_part(sub, rl, frame_loader=fl)
            if t is not None:
                b.update(t)
            t3 = C._crawl_stop_go_phases(sub, rl, frame_loader=fl)      # M356
            if t3 is not None:
                b.update(t3)
        return b

    def hsr(sub):
        b = C._high_soc_regen(sub, frame_loader=fl)
        if b:
            t = C._high_soc_regen_covariates(sub, frame_loader=fl)
            if t is not None:
                b.update(t)
        return b

    def tfp(sub):
        b = C._thermal_fuel_penalty(sub, raw_loader=rl, raw_dir=rd)
        if b:
            t = C._thermal_fuel_penalty_continuous(sub, raw_loader=rl, raw_dir=rd)
            if t is not None:
                b.update(t)
        return b
    return {
        "ThermalWarmupLag": lambda s: C._thermal_warmup_lag(s, frame_loader=fl), "ThermalFuelPenalty": tfp, "HighSocRegen": hsr,
        "BufferDebtRecovery": lambda s: C._buffer_debt_recovery(s, frame_loader=fl), "HandoffSequence": lambda s: C._handoff_sequence(s, frame_loader=fl),
        "EngineStartContext": lambda s: C._engine_start_context(s, frame_loader=fl), "CellSpreadRelaxation": lambda s: C._cell_spread_relaxation(s, frame_loader=fl),
        "DepartureArrival": lambda s: C._departure_arrival(s, frame_loader=fl), "RpmSpeedSync": lambda s: C._rpm_speed_sync(s, rl, frame_loader=fl),
        "EnergyShifting": lambda s: C._energy_shifting(s, rl, frame_loader=fl), "VgtAirPath": lambda s: C._vgt_airpath(s, raw_loader=rl, raw_dir=rd),
        "EngineStateMachine": lambda s: C._engine_state_machine(s, rl, frame_loader=fl), "AccelDecelEnvelopes": lambda s: C._accel_decel_envelopes(s, rl, frame_loader=fl),
        "CrawlStopGo": csg}


def walk_counts(a, parts, path=""):
    """conservation: count-type numeric leaves must satisfy sum(cohort parts) == all, where the parts are warm, shoulder and the below-minimum-support cold drives."""
    out = []
    if isinstance(a, dict) and all(isinstance(x, dict) or x is None for x in parts):
        for k in a:
            out += walk_counts(a[k], [(x or {}).get(k) if x else None for x in parts], path + "/" + str(k))
    elif isinstance(a, list) and a and all(isinstance(x, dict) and "label" in x for x in a) and all(isinstance(p, list) and all(isinstance(x, dict) and "label" in x for x in p) for p in parts if p):
        for x in a:        # lists of labelled items (sorted by count in some builders) are aligned BY LABEL, never by index
            lab = x["label"]
            out += walk_counts(x, [next((y for y in p if y.get("label") == lab), None) if p else None for p in parts], path + f"[label={lab}]")
    elif isinstance(a, list) and all(isinstance(x, list) and len(x) == len(a) for x in parts):
        for i, x in enumerate(a):
            out += walk_counts(x, [p[i] for p in parts], path + f"[{i}]")
    elif isinstance(a, (int, float)) and not isinstance(a, bool) and path.split("/")[-1].split("[")[0] in COUNT_KEYS:
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in parts):
            dec = len(repr(float(a)).split(".")[1].rstrip("0")) if isinstance(a, float) and "e" not in repr(a) else 0
            tol = (1.5 * 10 ** -min(dec, 3)) if dec else 1e-9           # parts are rounded to <= 3 decimals before summing; counts must be exact
            out.append((path, abs(sum(parts) - a) <= tol, a, parts))
        else:
            out.append((path, None, a, parts))
    return out


def cutpoints(fn):
    try:
        src = inspect.getsource(fn)
    except Exception:
        return []
    return [l.strip()[:150] for l in src.split("\n") if re.search(r"(np\.)?(percentile|quantile|nanpercentile|nanquantile)\(|sample_n\s*=|\.quantile\(|tertile", l)][:12]


def main():
    global T0
    T0 = time.time()
    mode = "--splice" if "--splice" in sys.argv else "--check"
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    os.makedirs(CACHE, exist_ok=True)
    A = json.load(open(ARR, encoding="utf-8"))
    cfg = json.load(open("summary_config.json", encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    reg = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "thermal_regime"]]
    dm_r = dm.merge(reg, on="file", how="left")
    assert len(dm_r) == len(dm) and dm_r.thermal_regime.notna().all(), "cohort label join incomplete"
    subsets = {"all": dm, "warm": dm_r[dm_r.thermal_regime == "warm"].drop(columns=["thermal_regime"]).reset_index(drop=True),
               "shoulder": dm_r[dm_r.thermal_regime == "shoulder"].drop(columns=["thermal_regime"]).reset_index(drop=True),
               "cold_ins": dm_r[~dm_r.thermal_regime.isin(["warm", "shoulder"])].drop(columns=["thermal_regime"]).reset_index(drop=True)}   # below-minimum-support cold drives: conservation only, never spliced
    ch = A["seasonalCharts"]["charts"]
    raw_ids = [k for k, v in ch.items() if v.get("pipelineClass") == "raw" and (only is None or k in only)]
    fl = drc.make_frame_loader(raw_dir=RAW_DIR)   # M369: a frame whose recorded raw md5 differs from the file on disk is treated as missing
    cache_idx = None
    try:
        cache_idx = json.load(open(os.path.join(drc.CACHE_DIR, "manifest.json"), encoding="utf-8"))
    except Exception:
        pass
    frames = sorted(f for f in os.listdir(drc.CACHE_DIR) if f.endswith(".pkl.gz")) if os.path.isdir(drc.CACHE_DIR) else []
    res_cache = {"frameEntries": len(frames), "nonFrameEntries": sorted(f for f in os.listdir(drc.CACHE_DIR) if not f.endswith(".pkl.gz")),
                 "framesEqualMasterFiles": sorted(f[:-len(".pkl.gz")] for f in frames) == sorted(dm.file), "explanation": "entries = one frame per master drive plus manifest.json"}
    res = {"milestone": "M341", "mode": mode, "cacheIndex": res_cache, "nLive": int(len(dm)), "cohortSizes": {k: int(len(v)) for k, v in subsets.items()}, "cacheSchemaVersion": drc.SCHEMA_VERSION,
           "cacheEntries": len(os.listdir(drc.CACHE_DIR)) if os.path.isdir(drc.CACHE_DIR) else None, "charts": {}, "timings": {}, "rawDir": "raw_only/ (staged raw/; F03 provenance-sensitive)"}
    # ---- compute: category_B (23 core charts) and the 14 builders, for all/warm/shoulder ----
    core_ids = [k for k in raw_ids if LC(k) in A and k not in builders(None, None, None)]
    out = {c: {} for c in subsets}
    loaded = {}
    for c, sub in subsets.items():
        cf, cr = Counting(fl), Counting(raw_loader)
        t = time.time()
        pk = os.path.join(CACHE, f"catB_{c}_{len(sub)}_{drc.content_key(sub.file, code_paths=[C.__file__, drc.__file__])}.pkl")
        if os.path.exists(pk) and "--no-cache" not in sys.argv:
            B = pickle.load(open(pk, "rb")); ld = None
        else:
            B = C.category_B(sub, cr, frame_loader=cf); pickle.dump(B, open(pk, "wb")); ld = (cf.ok, cf.none, cf.err)
        res["timings"][f"category_B_{c}_s"] = round(time.time() - t, 1)
        loaded[c] = ld
        for k in core_ids:
            out[c][k] = B.get(LC(k))
        res.setdefault("filesLoaded", {})[c] = {"subset": int(len(sub)), "framesLoaded": (ld[0] if ld else "cached"), "none": (ld[1] if ld else "cached")}
        if ld and ld[0] != len(sub):
            res["filesLoaded"][c]["MISMATCH"] = True
        print("category_B", c, res["timings"][f"category_B_{c}_s"], "s", flush=True)
    for c, sub in subsets.items():
        cf, cr = Counting(fl), Counting(raw_loader)
        bl = builders(cf, cr, RAW_DIR)
        for k in raw_ids:
            if k not in bl:
                continue
            t = time.time()
            pk = os.path.join(CACHE, f"b_{k}_{c}_{len(sub)}_{drc.content_key(sub.file, code_paths=[C.__file__, drc.__file__])}.pkl")
            try:
                if os.path.exists(pk) and "--no-cache" not in sys.argv:
                    v = pickle.load(open(pk, "rb"))
                else:
                    v = bl[k](sub); pickle.dump(v, open(pk, "wb"))
                out[c][k] = v
            except Exception as e:
                out[c][k] = None; res["charts"].setdefault(k, {})["error_" + c] = repr(e)[:200]
            res["timings"][f"{k}_{c}_s"] = round(time.time() - t, 1)
        res.setdefault("builderLoads", {})[c] = {"framesLoaded": cf.ok, "none": cf.none, "errors": cf.err, "rawFilesLoaded": cr.ok, "note": "cumulative over all builder calls of this cohort (each builder loads the files it needs)"}
        print("builders", c, flush=True)
    # ---- guard, conservation, cutpoints ----
    funcs = {"ThermalWarmupLag": C._thermal_warmup_lag, "ThermalFuelPenalty": C._thermal_fuel_penalty, "HighSocRegen": C._high_soc_regen, "BufferDebtRecovery": C._buffer_debt_recovery,
             "HandoffSequence": C._handoff_sequence, "EngineStartContext": C._engine_start_context, "CellSpreadRelaxation": C._cell_spread_relaxation, "DepartureArrival": C._departure_arrival,
             "RpmSpeedSync": C._rpm_speed_sync, "EnergyShifting": C._energy_shifting, "VgtAirPath": C._vgt_airpath, "EngineStateMachine": C._engine_state_machine,
             "AccelDecelEnvelopes": C._accel_decel_envelopes, "CrawlStopGo": C._crawl_stop_go}
    passed = []
    for k in raw_ids:
        e = res["charts"].setdefault(k, {})
        top = A.get(LC(k))
        e["class"] = "core(category_B)" if k in core_ids else "builder"
        e["topLevelStatus"] = (A["_artifactStamps"].get(LC(k)) or {}).get("computationStatus")
        e["parity"] = bool(out["all"].get(k) is not None and top is not None and canon(out["all"][k]) == canon(top))
        if not e["parity"]:
            e["parityNote"] = "all-rows result differs from the fresh top-level block" if out["all"].get(k) is not None else "builder returned None / errored"
        cons = walk_counts(out["all"].get(k), [out["warm"].get(k), out["shoulder"].get(k), out["cold_ins"].get(k)]) if e["parity"] else []
        e["conservation"] = {"nCountLeaves": len(cons), "violations": [{"path": p, "all": a, "parts[warm,shoulder,coldBelowSupport]": parts} for p, ok, a, parts in cons if ok is False][:8],
                             "notComparable": sum(1 for x in cons if x[1] is None), "nViolations": sum(1 for x in cons if x[1] is False)}
        e["conservation"]["nConserved"] = sum(1 for x in cons if x[1] is True)
        extra = {"CrawlStopGo": [C._crawl_stop_go_two_part], "HighSocRegen": [C._high_soc_regen_covariates], "ThermalFuelPenalty": [C._thermal_fuel_penalty_continuous]}.get(k, [])
        e["corpusDerivedCutpointLines"] = sum((cutpoints(f_) for f_ in [funcs.get(k, C.category_B)] + extra), [])
        e["cohortRelativeCutpoints"] = [l_ for l_ in e["corpusDerivedCutpointLines"] if re.search(r"33\.3|66\.7|tertile|terc", l_)]
        e["cohortNone"] = {c: out[c].get(k) is None for c in ("warm", "shoulder")}
        e["coldBelowSupportNone"] = out["cold_ins"].get(k) is None
        if e["parity"] and not any(e["cohortNone"].values()):
            passed.append(k)
    res["parityPassed"] = sorted(passed); res["parityFailed"] = sorted(set(raw_ids) - set(passed))
    res["totalSeconds"] = round(time.time() - T0, 1)
    json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"passed": len(passed), "failed": res["parityFailed"], "filesLoaded": res["filesLoaded"], "timings": {k: v for k, v in res["timings"].items() if k.startswith("category")}}, indent=1))
    if mode == "--check":
        return
    # ---- splice (additive; same pattern as M296) ----
    old = copy.deepcopy(A)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in passed:
        d = ch[k].setdefault("data", {})
        for c in ("all", "warm", "shoulder"):
            d[c] = copy.deepcopy(json.loads(json.dumps(out[c][k], default=float)))
        d["cold"] = None
        cov = ch[k].get("coverage") if isinstance(ch[k].get("coverage"), dict) else {}
        for c, sub in subsets.items():
            ent = {"n_drives": int(len(sub)), "km": round(float(sub.distance_km.sum()), 2)}
            if isinstance(cov.get(c), dict) and "independent_days" in cov[c]:
                ent["independent_days"] = int(sub.date.nunique())
            cov[c] = ent
        ch[k]["coverage"] = cov
        ch[k]["basisNDrives"] = int(len(dm)); ch[k]["refreshedBy"] = "M341 (tools/regen_seasonal_raw.py)"
        ck = res["charts"][k]
        if ck["cohortRelativeCutpoints"]:
            ch[k]["cohortNote"] = ("cohort-relative cutpoints: the tertile cutpoints of this chart are computed within each cohort subset (not held at the all-rows values), so strata are not comparable "
                                   "across cohorts by value; lines: " + " | ".join(ck["cohortRelativeCutpoints"][:4]))
        if ck["conservation"]["nViolations"]:
            ch[k]["conservationNote"] = ("%d count leaves do not satisfy warm + shoulder + cold-below-support = all (builder pairs events within the drives it is given, so cohort subsets differ from the all-rows run by a few events); "
                                         "see analyses/M341_check.json" % ck["conservation"]["nViolations"])
    st = A["seasonalCharts"]["_staleness"]
    st["stillStale"] = sorted(res["parityFailed"] + [x for x in st.get("stillStale", []) if x not in passed and x not in raw_ids])
    st["refreshedRawCharts"] = {"keys": sorted(passed), "milestone": "M341", "basisNDrives": int(len(dm)), "generatedAt": now,
                                "method": "same released builders as the top-level blocks, called per thermal cohort on the live corpus (raw_only/, frame cache schema %d); parity-guarded (f(all rows) == top-level block byte-for-byte); cohort-derived cutpoints are cohort-relative (see analyses/M341_check.json)" % drc.SCHEMA_VERSION}
    st["perChartStatus"] = {k: ("refreshed" if k in passed else "carried forward: " + (res["charts"][k].get("parityNote") or "cohort call returned None")) for k in raw_ids}
    st["liveNDrives"] = int(len(dm))
    st["reason"] = ("M341: %d of %d RAW-class seasonal charts are regenerated on the live %d-drive corpus (per-chart status in perChartStatus); the %d that failed the parity guard stay carried forward "
                    "at the 410-drive basis and are listed in stillStale. The TOP-LEVEL blocks are fresh at the live basis." % (len(passed), len(raw_ids), len(dm), len(res["parityFailed"])))
    A["seasonalCharts"]["_meta"]["generatedAt"] = now
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
    subprocess.run([sys.executable, os.path.join(ROOT, "m295_payload.py")], check=True)
    print(json.dumps({"spliced": sorted(passed), "stillStale": st["stillStale"]}))


if __name__ == "__main__":
    main()
