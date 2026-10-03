#!/usr/bin/env python3
"""M343 (spec analyses/M343_spec.md rev 2): engine-start (RPM-onset) rate per 100 km from the RELEASED detector, pooled as a ratio of sums with day-clustered CIs.
Detector, reproduced verbatim from compute_summary_arrays._RawAccum.add: 1 Hz grid hz = frame.resample('1s').mean().ffill(limit=15) after the pipeline's per-column ffill(limit=15),
rpm > 300 (NaN = off), run-length encoded, only runs >= MIN_ENGINE_START_S (2 s) are starts. Known answer: the per-drive starts/100 km equals the value the released _RawAccum.add appends
(exact float equality, per drive and per class n); a mismatch STOPS. Reads the pipeline frame cache (basis raw/, F03 provenance-sensitive); never writes drive_master.csv.
Modes: --check (known answer + estimates -> analyses/M343_check.json, no payload write) | --splice (check + additive write of S.engineStartRate).
Usage: python tools/engine_start_rate.py --check|--splice"""
import copy, datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import compute_summary_arrays as C
import drive_raw_cache as drc
import fuel_analytics as fa

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M343_check.json")
BANDS = ["<40C", "40-60C", ">=60C", "unknown"]
MOTORED_LOAD = 12.0          # M82 motored proxy: calculated engine load < 12% (stated recall/contamination in compute_summary_arrays)


def build_hz(df, lim=15):
    """identical to _RawAccum.add up to hz (only the columns used here)."""
    df, _ = C._apply_speed_priority(df)
    df = df.rename(columns={k: v for k, v in C.RAW_MAP.items() if k in df.columns})
    if "time" not in df:
        return None

    def col(name, lo=None, hi=None):
        if name not in df:
            return None
        s = pd.to_numeric(df[name], errors="coerce").ffill(limit=lim)
        if lo is not None:
            s = s.where(s >= lo)
        if hi is not None:
            s = s.where(s <= hi)
        return s
    t = pd.to_datetime(df["time"], format="mixed", errors="coerce")
    g1 = pd.DataFrame({"t": t})
    for cN, cS in [("eng_rpm", col("eng_rpm", 0)), ("T_coolant", col("T_coolant", -40, 150)), ("eng_load_calc", col("eng_load_calc"))]:
        g1[cN] = cS.values if cS is not None else np.nan
    g1 = g1.dropna(subset=["t"]).set_index("t")
    return g1.resample("1s").mean().ffill(limit=lim)


def onsets(hz):
    er = hz["eng_rpm"].values
    on = np.nan_to_num(er, nan=0.0) > 300
    edges = np.diff(np.concatenate([[0], on.astype(int), [0]]))
    s_idx = np.where(edges == 1)[0]
    seg_len = np.where(edges == -1)[0] - s_idx
    q = seg_len >= C.MIN_ENGINE_START_S
    return s_idx[q], seg_len[q], bool(on.size and on[0] and q.size and (s_idx.size and s_idx[0] == 0 and q[0]))


def band(v):
    return "unknown" if not np.isfinite(v) else ("<40C" if v < 40 else ("40-60C" if v < 60 else ">=60C"))


def published_note(pub):
    """M363: the note about the published per-drive MEAN; the per-drive maximum and its distance are bound to the payload row, never typed."""
    u = pub.get("Urban") or {}
    mx = (f"the per-drive maximum is {u.get('hi')} per 100 km on a {u.get('maxKm')} km drive"
          if u.get("hi") is not None and u.get("maxKm") is not None else "the per-drive extremes are driven by very short drives")
    return f"unweighted MEAN of per-drive rates (short trips dominate: {mx}); not comparable with the pooled ratio of sums"


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    A = json.load(open(ARR, encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    reg = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "thermal_regime"]]
    coh = dict(zip(reg.file, reg.thermal_regime))
    bad = C._canonical_bad(dm)
    fl = drc.make_frame_loader()
    acc = C._RawAccum()
    rows, known = [], {"nCompared": 0, "mismatches": [], "classN": {}}
    for i, r in dm.iterrows():
        fn, km, cls = r["file"], r["distance_km"], C._cond_class(r["drive_type"])
        df = fl(fn)
        if df is None:
            continue
        before = {k: len(v) for k, v in acc.starts.items()}
        acc.add(df, km, r["drive_type"], None, fn)                       # released accumulator (known answer)
        rel = None
        if km and km > 0 and cls and len(acc.starts[cls]) > before.get(cls, 0):
            rel = acc.starts[cls][-1]
        hz = build_hz(df)
        if hz is None or "eng_rpm" not in hz.columns:
            continue
        s_idx, seg, lc = onsets(hz)
        n = int(len(s_idx))
        mine = (n / km * 100) if (km and km > 0 and cls) else None
        if rel is not None or mine is not None:
            known["nCompared"] += 1
            known["classN"][cls] = known["classN"].get(cls, 0) + 1
            if (rel is None) != (mine is None) or (rel is not None and rel != mine):
                known["mismatches"].append({"file": fn, "released": rel, "mine": mine})
        tc = hz["T_coolant"].values if "T_coolant" in hz.columns else np.full(len(hz), np.nan)
        load = hz["eng_load_calc"].values if "eng_load_calc" in hz.columns else np.full(len(hz), np.nan)
        bnd = [band(float(tc[j])) for j in s_idx]
        mot = [bool(np.isfinite(np.nanmean(load[j:j + 3])) and np.nanmean(load[j:j + 3]) < MOTORED_LOAD) if np.isfinite(load[j:j + 3]).any() else False for j in s_idx]
        rows.append({"file": fn, "day": str(fn)[:10] if "-" in str(fn)[:5] else f"{str(fn)[:4]}-{str(fn)[4:6]}-{str(fn)[6:8]}", "km": float(km) if km else 0.0, "cls": cls or "unknown",
                     "cohort": coh.get(fn, "unknown"), "n": n, "first": 1 if n else 0, "restarts": max(n - 1, 0), "leftCensored": bool(lc), "canonClean": bool(not bad.iloc[i]),
                     "motoredFlag": int(sum(mot)), **{f"b_{b}": int(sum(1 for x in bnd if x == b)) for b in BANDS}})
    d = pd.DataFrame(rows)
    d["day"] = d["day"].str.replace(r"^(\d{4})-(\d{2})-(\d{2}).*$", r"\1-\2-\3", regex=True)
    res = {"milestone": "M343", "mode": mode, "nDrivesProcessed": int(len(d)), "knownAnswer": {"nCompared": known["nCompared"], "nMismatches": len(known["mismatches"]), "mismatchExamples": known["mismatches"][:5],
                                                                                         "perClassN": known["classN"], "rule": "exact per-drive float equality with the released _RawAccum.add append"},
           "detector": {"gridS": 1, "ffillLimitS": 15, "rpmThreshold": 300, "minRunS": int(C.MIN_ENGINE_START_S), "nanIsOff": True, "coolantChannel": "T_coolant (engine coolant, clip -40..150), 1 s grid value at the onset sample (ffill limit 15 s)",
                        "motoredProxy": f"calculated load < {MOTORED_LOAD}% in the first 3 s of a run (M82 proxy; flag only)"}}
    if res["knownAnswer"]["nMismatches"]:
        json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
        print(json.dumps({"STOP": "known-answer mismatch", **res["knownAnswer"]}, indent=1, default=float)); sys.exit(2)
    # ---- estimates ----
    def est(sub):
        sub = sub.assign(starts=sub.n.astype(float))
        r_ = fa.ratio_ci(sub, "starts", "km", 100.0)
        r_["support"] = fa.support(int(sub.day.nunique())) if len(sub) else "none"
        if r_.get("ci95") is not None and int(sub.day.nunique()) < fa.MIN_DAYS_CI:
            r_["ci95"] = None if int(sub.day.nunique()) < fa.MIN_DAYS_LOWCLUSTER else r_["ci95"]
        r_["nStarts"] = int(sub.n.sum()); r_["km"] = round(float(sub.km.sum()), 1)
        return r_
    prim = d[d.canonClean & (d.km > 0) & (d.cls != "unknown")].copy()
    def block(sub):
        out = {"all": est(sub) if len(sub) else None}
        for c in ("warm", "shoulder"):
            out[c] = est(sub[sub.cohort == c]) if (sub.cohort == c).any() else None
        below = sub[~sub.cohort.isin(["warm", "shoulder"])]
        out["coldBelowSupport"] = {"nDrives": int(len(below)), "nStarts": int(below.n.sum()), "km": round(float(below.km.sum()), 1), "note": "below minimum support: not estimated, in the All view only"}
        return out
    res["primary"] = block(prim)
    res["byClass"] = {c: est(prim[prim.cls == c]) for c in ("urban", "mixed", "mixed_highway", "highway") if (prim.cls == c).any()}
    def comp(sub, name):
        x = sub.assign(first_s=sub["first"].astype(float), rest_s=sub["restarts"].astype(float))
        return {"firstPer100km": fa.ratio_ci(x, "first_s", "km", 100.0), "restartsPer100km": fa.ratio_ci(x, "rest_s", "km", 100.0)}
    res["decomposition"] = {"all": comp(prim, "all"), "warm": comp(prim[prim.cohort == "warm"], "warm"), "shoulder": comp(prim[prim.cohort == "shoulder"], "shoulder"),
                            "sumCheck": bool(((prim["first"] + prim["restarts"]) == prim["n"]).all()),
                            "note": "a trip is one master file; the first run of the file is the trip-first start, later runs are restarts within the file; a restart across a file boundary is a first start by construction"}
    bandt = {}
    for c, sub in (("all", prim), ("warm", prim[prim.cohort == "warm"]), ("shoulder", prim[prim.cohort == "shoulder"])):
        tot = float(sub.n.sum()); bandt[c] = {}
        for b in BANDS:
            x = sub.assign(bs=sub[f"b_{b}"].astype(float)); e = fa.ratio_ci(x, "bs", "km", 100.0)
            bandt[c][b] = {"nStarts": int(sub[f"b_{b}"].sum()), "shareOfStarts": round(float(sub[f"b_{b}"].sum() / tot), 4) if tot else None, "per100km": e["est"], "ci95": e["ci95"] if int(sub.day.nunique()) >= fa.MIN_DAYS_CI else None}
    res["byCoolantBand"] = {"definition": "band starts / TOTAL km (bands sum to the pooled rate); coolant at the onset sample", **bandt}
    res["flags"] = {"leftCensoredDrives": int(prim.leftCensored.sum()), "leftCensoredShareOfDrives": round(float(prim.leftCensored.mean()), 4), "motoredFlagStarts": int(prim.motoredFlag.sum()),
                    "motoredFlagShareOfStarts": round(float(prim.motoredFlag.sum() / max(prim.n.sum(), 1)), 4)}
    sens = {}
    for name, sub in (("distGe0p5km", prim[prim.km >= 0.5]), ("allRowsIncludingInvalid", d[(d.km > 0) & (d.cls != "unknown")]), ("excludingLeftCensored", prim[~prim.leftCensored])):
        sens[name] = {"all": est(sub), "nDrives": int(len(sub)), "differenceVsPrimary": {"drives": int(len(sub) - len(prim)), "starts": int(sub.n.sum() - prim.n.sum()), "km": round(float(sub.km.sum() - prim.km.sum()), 1), "note": "signed: sensitivity set minus primary set (negative = removed, positive = added)"}}
    # fill-design sensitivity (audit finding): limit 3 on BOTH fills instead of 15 (the count depends on the fill design; the second fill is load-bearing)
    n3 = {}
    for fn_ in prim.file:
        df_ = fl(fn_)
        h3 = build_hz(df_, 3) if df_ is not None else None
        n3[fn_] = int(len(onsets(h3)[0])) if h3 is not None and "eng_rpm" in h3.columns else 0
    p3 = prim.assign(n3=prim.file.map(n3).astype(float))
    e3 = fa.ratio_ci(p3, "n3", "km", 100.0)
    sens["fillLimit3BothFills"] = {"all": {"est": e3["est"], "ci95": e3["ci95"], "nTrips": e3["nTrips"], "nDays": e3["nDays"], "nStarts": int(p3.n3.sum())},
                                   "changeInTotalStartsPct": round(100.0 * (p3.n3.sum() / prim.n.sum() - 1.0), 2),
                                   "note": "the 1 s grid is NaN between raw rows (raw sampling interval > 1 s); grid NaN reads as engine-off, so the second fill is load-bearing; no-second-fill variants are not meaningful (runs split into many short runs)"}
    # file-gap context: a trip is one master file; consecutive files that start shortly after the previous one ended make 'trip-first' a file-boundary artefact
    def key_start(f):
        import re
        m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})[_ ](\d{2})-?(\d{2})-?(\d{2})", str(f))
        return pd.Timestamp(*[int(x) for x in m.groups()]) if m else pd.NaT
    g = prim.merge(dm[["file", "duration_s"]], on="file", how="left")
    g["t0"] = g.file.map(key_start)
    g = g.dropna(subset=["t0"]).sort_values("t0")
    g["t1"] = g.t0 + pd.to_timedelta(g.duration_s.fillna(0), unit="s")
    gap = (g.t0.values[1:] - g.t1.values[:-1]) / np.timedelta64(1, "m")
    gap = gap[np.isfinite(gap) & (gap >= 0)]
    res["fileGapContext"] = {"nConsecutivePairs": int(len(gap)), "startWithin5min": int((gap <= 5).sum()), "startWithin30min": int((gap <= 30).sum()), "startWithin60min": int((gap <= 60).sum()),
                             "shareWithin30min": round(float((gap <= 30).mean()), 3),
                             "note": "file start from the file key, end = start + duration_s; a restart across a file boundary is counted as a trip-first start, so the first/restart split is a file-boundary artefact, not a cold-start measure"}
    res["sensitivity"] = sens
    pub = {x["label"]: x for x in (A.get("engineStartsByType") or [])}
    res["publishedEngineStartsByType"] = {"avgPerDriveRates": {k: v.get("avg") for k, v in pub.items()}, "note": published_note(pub),
                                          "seasonalContractCoverageAll": (A["seasonalCharts"]["charts"]["EngineStartsByType"].get("coverage") or {}).get("all")}
    res["stops"] = {"knownAnswerMismatch": False, "coldRenderedAsZero": False, "decompositionNotSumming": not res["decomposition"]["sumCheck"], "estimateWithoutN": any(v is not None and v.get("nDays") is None for v in res["primary"].values() if isinstance(v, dict) and "est" in v)}
    json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"known": res["knownAnswer"], "primary": {k: (v if k == "coldBelowSupport" else {x: v[x] for x in ("est", "ci95", "nTrips", "nDays", "nStarts", "km")}) for k, v in res["primary"].items() if v}, "flags": res["flags"],
                      "decomp": {k: {x: y["est"] for x, y in v.items()} for k, v in res["decomposition"].items() if k in ("all", "warm", "shoulder")}}, indent=1, default=float))
    if mode == "--check":
        return
    # ---- additive splice of S.engineStartRate (seasonal contract deferred to the dashboard step) ----
    block_out = {"_provenance": "GENERATED by tools/engine_start_rate.py (M343). Do not hand-edit.", "schemaVersion": 1,
                 "basis": "RPM onsets from the released detector on the pipeline frame cache (raw/ basis, F03 provenance-sensitive); not M299-reproducible; RPM onsets are not current-direction reversals and not fuel-on starts",
                 "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()}, "method": "ratio of sums, day-clustered percentile bootstrap (seed 42, 4000 draws); interval only with >= 7 distinct days (5-6 low-cluster, < 5 points only)",
                 "detector": res["detector"], "primary": res["primary"], "byClass": res["byClass"], "decomposition": res["decomposition"], "byCoolantBand": res["byCoolantBand"], "flags": res["flags"],
                 "sensitivity": res["sensitivity"], "fileGapContext": res["fileGapContext"], "knownAnswer": res["knownAnswer"], "publishedEngineStartsByType": res["publishedEngineStartsByType"],
                 "limits": ["a trip is one master file: restarts across a file boundary are first starts", "ffill(limit=15) is applied twice (raw columns and the 1 s grid) and can bridge gaps of ~15-30 s, merging runs", "the 1 s mean can cross the 300 rpm threshold", "rpm > 300 also counts generator-motored spin-ups: named RPM onsets, not fuel-on starts",
                            "coolant band is the start context at onset, not a cold-start or thermal-penalty claim", "F10.r1 stays partly open: cold thermal starts and fuel-on starts are not separated"]}
    block_out = json.loads(json.dumps(block_out, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("engineStartRate", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "engineStartRate"}
    A2["engineStartRate"] = block_out
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block_out["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M343: computed by tools/engine_start_rate.py from the pipeline frame cache; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(block_out["inputs"]))
    st.pop("carriedForward", None)
    A2["_artifactStamps"]["engineStartRate"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "engineStartRate"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"engineStartRate": "written"}))


if __name__ == "__main__":
    main()
