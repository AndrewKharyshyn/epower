#!/usr/bin/env python3
"""M418 (analyses/M418_spec.md, audit F19): thermal support ledger. Additive: writes ONLY the payload block summary_arrays.json['thermalSupportLedger'] (+ its artifact stamp). Reporting-only: no estimator, no survival model.

For the thermal estimates that SELECT drives or fits (warm-up lag to 60/70/80 C for coolant and oil, hvcEngine80C, warmupCurve, thermalFuelPenalty) every drive is classified with the estimator's OWN rules (the helpers and constants are
imported from compute_summary_arrays) into candidates / excluded (by reason) / accepted / reached / censored; a drive that never reaches a threshold is a right-censored observation (its observation ended before the threshold),
not a "failure to warm up". Risk-set counts at fixed times are counts, not a survival function. The ledger's `accepted` must equal the estimator's published n (reconciliation, written into the block and gated).
thermalStepResponse, shortTripWarmup, the suppressed cold cohort and the intake-air support are copied through with their own n.
Usage: python tools/thermal_support_ledger.py [--dry-run]   (needs raw_only/ staged by tools/stage_raw.py and the frame cache)"""
import copy, datetime, hashlib, json, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
METHOD_VERSION = 1
RISK_TIMES_S = [60, 120, 300, 600, 900, 1800]
ALLOWED = ["/thermalSupportLedger", "/_artifactStamps/thermalSupportLedger"]


def _csa():
    import compute_summary_arrays as C
    return C


# ------------------------------------------------------------------------------------------------ warm-up lag (coolant and oil time to threshold)
def lag_record(fr, C):
    """One drive, classified exactly as _thermal_warmup_lag does."""
    g = C._twl_grid(fr)
    if g is None or "cool" not in g.columns:
        return {"status": "noFrameOrCoolantChannel"}
    c = g["cool"].dropna()
    if len(c) < 30:
        return {"status": "fewerThan30ValidCoolantSeconds"}
    cstart = float(c.iloc[0])
    if cstart >= C._TWL_COLD_MAX:
        return {"status": "warmStart", "coolantStartC": cstart}
    tsec = (g.index - g.index[0]).total_seconds().values
    rec = {"status": "cold", "spanS": float(tsec[-1]), "coolantStartC": cstart, "cool": {}, "oil": None}
    for t in C._TWL_THR:
        rec["cool"][t] = C._twl_time_to(g["cool"].values, tsec, t, cstart)
    if "oil" in g.columns and g["oil"].notna().sum() >= 30:
        ostart = float(g["oil"].dropna().iloc[0])
        rec["oil"] = {"startC": ostart, "t": {t: C._twl_time_to(g["oil"].values, tsec, t, ostart) for t in C._TWL_THR}}
    return rec


def _q(v):
    v = np.asarray(v, float)
    if v.size == 0:
        return None
    return {"p25": round(float(np.percentile(v, 25)), 1), "median": round(float(np.median(v)), 1), "p75": round(float(np.percentile(v, 75)), 1), "max": round(float(v.max()), 1), "n": int(v.size)}


def _risk(times, spans):
    """times: time to threshold (NaN = never), spans: observation span (s). Counts at fixed times (not a survival function)."""
    t = np.asarray(times, float)
    s = np.asarray(spans, float)
    reached = np.isfinite(t)
    exit_t = np.where(reached, t, s)                       # time at which the drive leaves the risk set
    out = []
    for tt in RISK_TIMES_S:
        out.append({"t": tt, "atRisk": int((exit_t >= tt).sum()), "reachedByT": int((reached & (t <= tt)).sum()), "censoredBeforeT": int((~reached & (s < tt)).sum())})
    return out


def _days(recs):
    """Distinct calendar days of the records that carry a date ('_d', set by build)."""
    return len({r["_d"] for r in recs if r.get("_d")})


def aggregate_lag(recs, C):
    cold = [r for r in recs if r["status"] == "cold"]
    ex = {}
    for r in recs:
        if r["status"] != "cold" and r["status"] != "warmStart":
            ex[r["status"]] = ex.get(r["status"], 0) + 1
    n_warm = sum(1 for r in recs if r["status"] == "warmStart")
    spans = [r["spanS"] for r in cold]
    out = {"candidates": len(recs), "excluded": [{"reason": k, "n": v} for k, v in sorted(ex.items())], "warmStartExcluded": n_warm, "nValidCoolant": len(cold) + n_warm,
           "coldStarts": len(cold), "coldStartDays": _days(cold), "candidateDays": _days(recs), "coldStartRule": "first valid coolant < %g C (and >= 30 valid coolant seconds)" % C._TWL_COLD_MAX, "observedSpanSeconds": _q(spans), "coolant": {}, "oil": {}}
    for t in C._TWL_THR:
        tt = [r["cool"][t] for r in cold]
        reached = int(np.isfinite(tt).sum())
        cens = [s for x, s in zip(tt, spans) if not np.isfinite(x)]
        out["coolant"][str(t)] = {"reached": reached, "censored": len(tt) - reached, "shareReached": round(reached / len(tt), 4) if tt else None, "censoredObservedSeconds": _q(cens), "riskSet": _risk(tt, spans),
                                  "pooledMedianOver": "reachers only", "reachedTimeSeconds": _q([x for x in tt if np.isfinite(x)])}
    oil = [r for r in cold if r["oil"] is not None]
    out["oilCandidates"] = len(cold)
    out["oilExcludedNoOilChannel"] = len(cold) - len(oil)
    out["nWithOil"] = len(oil)
    ospan = [r["spanS"] for r in oil]
    for t in C._TWL_THR:
        tt = [r["oil"]["t"][t] for r in oil]
        fin = np.isfinite(tt)
        at_start = sum(1 for r in oil if r["oil"]["startC"] >= t)
        cens = [s for x, s in zip(tt, ospan) if not np.isfinite(x)]
        out["oil"][str(t)] = {"reached": int(fin.sum()), "atOrAboveAtStart": int(at_start), "reachedAfterStart": int(fin.sum()) - int(at_start), "censored": len(tt) - int(fin.sum()),
                              "shareReached": round(float(fin.sum()) / len(tt), 4) if tt else None, "censoredObservedSeconds": _q(cens), "riskSet": _risk(tt, ospan),
                              "pooledMedianOver": "reachers only; includes the drives whose oil started at or above the threshold (time 0)"}
    out["riskSetTimesSeconds"] = RISK_TIMES_S
    return out


# ------------------------------------------------------------------------------------------------ hvcEngine80C and warmupCurve (1 Hz grid as _RawAccum.add builds it)
def hz_grid(df, C):
    df, _ = C._apply_speed_priority(df)
    df = df.rename(columns={k: v for k, v in C.RAW_MAP.items() if k in df.columns})
    if "time" not in df:
        return None
    t = C._ft(df["time"], mixed=True)

    def col(name, lo=None, hi=None):
        if name not in df:
            return None
        s = pd.to_numeric(df[name], errors="coerce").ffill(limit=15)
        if lo is not None:
            s = s.where(s >= lo)
        if hi is not None:
            s = s.where(s <= hi)
        return s
    spd, tcool = col("speed", 0, 260), col("T_coolant", -40, 150)
    g1 = pd.DataFrame({"t": t})
    g1["speed"] = spd.values if spd is not None else np.nan
    g1["T_coolant"] = tcool.values if tcool is not None else np.nan
    g1 = g1.dropna(subset=["t"]).set_index("t")
    return g1.resample("1s").mean().ffill(limit=15)


def raw_record(fr, dist_km, drive_type, C):
    """One drive for hvcEngine80C and warmupCurve; the two decisions are independent (as in _RawAccum.add)."""
    out = {"hvc": None, "curve": None}
    if fr is None:
        return {"status": "noFrame"}
    hz = hz_grid(fr, C)
    if hz is None:
        return {"status": "noTimeColumn"}
    cls = drive_type if drive_type in C.CLASS_ORDER else None
    # hvcEngine80C
    if not (dist_km and dist_km > 0):
        out["hvc"] = {"status": "distanceNotPositive"}
    else:
        tc = hz["T_coolant"].values
        valid = ~np.isnan(tc)
        if not valid.any():
            out["hvc"] = {"status": "noValidCoolant"}
        elif cls is None:
            out["hvc"] = {"status": "classOutsideTaxonomy"}
        else:
            first = float(tc[valid][0])
            reached = bool((tc[valid] >= C.WARM_ENGINE_C).any())
            out["hvc"] = {"status": "accepted", "class": cls, "reached": reached, "startedAtOrAbove80": first >= C.WARM_ENGINE_C, "firstValidCoolantC": first,
                          "coldStart": first <= C.WARMUP_COLD_C, "minutes": (int(np.argmax(tc >= C.WARM_ENGINE_C)) / 60.0) if reached else None}
    # warmupCurve
    wgrp = C._cond_class(drive_type)
    if wgrp is None:
        out["curve"] = {"status": "classOutsideTaxonomy"}
    else:
        tcv, spv = hz["T_coolant"].values, hz["speed"].values
        vc = ~np.isnan(tcv)
        if not vc.any():
            out["curve"] = {"status": "noValidCoolant"}
        else:
            i0 = int(np.argmax(vc))
            if tcv[i0] > C.WARMUP_COLD_C:
                out["curve"] = {"status": "warmStart", "firstValidCoolantC": float(tcv[i0])}
            else:
                dcum = np.cumsum(np.nan_to_num(spv[i0:])) / 3600.0
                m = ~np.isnan(tcv[i0:])
                if m.sum() < 3:
                    out["curve"] = {"status": "fewerThan3ValidCoolantSamples"}
                else:
                    out["curve"] = {"status": "accepted", "class": wgrp, "spanKm": float(dcum[m][-1])}
    return out


def aggregate_raw(recs, C):
    hv = {"candidates": len(recs), "excluded": {}, "accepted": {k: {"n": 0, "reached": 0, "notReached": 0, "startedAtOrAbove80": 0, "coldStartAndReached": 0, "coldStartNotReached": 0} for k in C.CLASS_ORDER}}
    cu = {"candidates": len(recs), "excluded": {}, "accepted": {k: 0 for k in C.CLASS_ORDER}}
    spans = {k: [] for k in C.CLASS_ORDER}
    hv_days = {k: set() for k in C.CLASS_ORDER}
    cu_days = {k: set() for k in C.CLASS_ORDER}
    for r in recs:
        if "status" in r:                                          # no frame / no time column: not a candidate of either
            for d in (hv, cu):
                d["excluded"][r["status"]] = d["excluded"].get(r["status"], 0) + 1
            continue
        h = r["hvc"]
        if h["status"] != "accepted":
            hv["excluded"][h["status"]] = hv["excluded"].get(h["status"], 0) + 1
        else:
            a = hv["accepted"][h["class"]]
            a["n"] += 1
            if r.get("_d"):
                hv_days[h["class"]].add(r["_d"])
            a["reached" if h["reached"] else "notReached"] += 1
            a["startedAtOrAbove80"] += int(h["startedAtOrAbove80"])
            if h["coldStart"]:
                a["coldStartAndReached" if h["reached"] else "coldStartNotReached"] += 1
        c = r["curve"]
        if c["status"] != "accepted":
            cu["excluded"][c["status"]] = cu["excluded"].get(c["status"], 0) + 1
        else:
            cu["accepted"][c["class"]] += 1
            if r.get("_d"):
                cu_days[c["class"]].add(r["_d"])
            spans[c["class"]].append(c["spanKm"])
    hv["excluded"] = [{"reason": k, "n": v} for k, v in sorted(hv["excluded"].items())]
    cu["excluded"] = [{"reason": k, "n": v} for k, v in sorted(cu["excluded"].items())]
    for k, a in hv["accepted"].items():
        a["shareReached"] = round(a["reached"] / a["n"], 4) if a["n"] else None
        a["nDays"] = len(hv_days[k])
    cu["acceptedDays"] = {k: len(v) for k, v in cu_days.items()}
    hv["rule"] = "distance_km > 0, >= 1 valid coolant sample, class in CLASS_ORDER; no cold-start gate: a warm restart counts as reached at about 0 min; minutes counted from the file start"
    cu["rule"] = "class in CLASS_ORDER; first valid coolant <= %g C; >= 3 valid coolant samples after the anchor" % C.WARMUP_COLD_C
    grid = {}
    for k in C.CLASS_ORDER:
        s = np.asarray(spans[k], float)
        grid[k] = [{"km": g, "nDrivesReachingThisDistance": int((s >= g).sum()), "emitted": bool((s >= g).sum() >= C.WARMUP_MIN_N)} for g in C.WARMUP_GRID]
    cu["gridAttrition"] = grid
    cu["minNPerPoint"] = C.WARMUP_MIN_N
    return hv, cu


# ------------------------------------------------------------------------------------------------ thermalFuelPenalty selection
def fuel_record(fn, C, raw_loader, raw_dir):
    g = C._of_grid(fn, raw_loader, raw_dir)
    if g is None:
        return {"status": "noReadableGrid"}
    c = g["cool"].dropna()
    if len(c) < 60:
        return {"status": "fewerThan60ValidCoolantSeconds"}
    if float(c.iloc[0]) >= C._OF_COLD_MAX:
        return {"status": "warmStart"}
    if float(c.max()) < C._OF_WARM_THR:
        return {"status": "coldStartNeverReached70C", "maxC": float(c.max()), "spanS": float(len(g))}
    a = g["acc"].dropna()
    if len(a) < 30 or (a.iloc[-1] - a.iloc[0]) <= 0.02:
        return {"status": "rejectedFuelGate"}
    return {"status": "accepted"}


def aggregate_fuel(recs, C):
    order = ["noReadableGrid", "fewerThan60ValidCoolantSeconds", "warmStart", "coldStartNeverReached70C", "rejectedFuelGate", "accepted"]
    cnt = {k: sum(1 for r in recs if r["status"] == k) for k in order}
    cens = [r["spanS"] for r in recs if r["status"] == "coldStartNeverReached70C"]
    return {"candidates": len(recs), "excluded": [{"reason": k, "n": cnt[k]} for k in order[:-1]], "accepted": cnt["accepted"], "acceptedDays": _days([r for r in recs if r["status"] == "accepted"]), "coldStarts": cnt["coldStartNeverReached70C"] + cnt["rejectedFuelGate"] + cnt["accepted"],
            "censoredNeverReached70C": cnt["coldStartNeverReached70C"], "censoredObservedSeconds": _q(cens),
            "rule": "readable raw grid with the fuel accumulator and a speed channel; >= 60 valid coolant seconds; first coolant < %g C; MAX coolant >= %g C (selection on reaching the threshold); >= 30 accumulator samples with an increase > 0.02 L" % (C._OF_COLD_MAX, C._OF_WARM_THR),
            "note": "the estimator conditions on the coolant reaching 70 C: cold starts that never reached it are censored and absent from every estimate of this block"}


# ------------------------------------------------------------------------------------------------ build, reconcile, splice
def _n_from_string(s):
    m = re.search(r"\(n=(\d+)\)", s or "")
    return int(m.group(1)) if m else None


def _rec_one(est, tl, hvc, curve_classes, fuel_n, pre):
    """Ledger accepted counts of one cohort against the published estimator n of that cohort."""
    out = {}
    if tl:
        L = est["warmupLag"]
        out[pre + "warmupLag.nColdStart"] = [L["coldStarts"], tl["nColdStart"]]
        out[pre + "warmupLag.nDrivesTotal"] = [L["nValidCoolant"], tl["nDrivesTotal"]]
        out[pre + "warmupLag.nWithOil"] = [L["nWithOil"], tl["nWithOil"]]
        for t in ("60", "70", "80"):
            out[pre + "warmupLag.coolant%s.n" % t] = [L["coolant"][t]["reached"], (tl["coolantTimeToThresholdS"][t] or {}).get("n", 0)]
            out[pre + "warmupLag.oil%s.n" % t] = [L["oil"][t]["reached"], (tl["oilTimeToThresholdS"][t] or {}).get("n", 0)]
    hv = est["hvcEngine80C"]
    for k in ("urban", "mixed", "mixed_highway", "highway"):
        s_ = (hvc or {}).get(k)
        out[pre + "hvcEngine80C.%s.n" % k] = [hv["accepted"][k]["n"], _n_from_string(s_) or 0]
        m = re.match(r"(\d+)%", s_ or "")
        out[pre + "hvcEngine80C.%s.pctReached" % k] = [round(100 * hv["accepted"][k]["shareReached"]) if hv["accepted"][k]["n"] else None, int(m.group(1)) if m else None]
    for k in ("urban", "mixed", "mixed_highway", "highway"):
        out[pre + "warmupCurve.%s.nDrives" % k] = [est["warmupCurve"]["accepted"][k], ((curve_classes or {}).get(k) or {}).get("nDrives", 0)]
    out[pre + "thermalFuelPenalty.nColdStartDrives"] = [est["fuelPenalty"]["accepted"], fuel_n or 0]
    # partitions: every candidate is in exactly one excluded / accepted bucket (ledger against itself)
    L, F, W = est["warmupLag"], est["fuelPenalty"], est["warmupCurve"]
    out[pre + "partition.warmupLag"] = [L["candidates"], sum(e["n"] for e in L["excluded"]) + L["warmStartExcluded"] + L["coldStarts"]]
    out[pre + "partition.hvcEngine80C"] = [hv["candidates"], sum(e["n"] for e in hv["excluded"]) + sum(a["n"] for a in hv["accepted"].values())]
    out[pre + "partition.warmupCurve"] = [W["candidates"], sum(e["n"] for e in W["excluded"]) + sum(W["accepted"].values())]
    out[pre + "partition.fuelPenalty"] = [F["candidates"], sum(e["n"] for e in F["excluded"]) + F["accepted"]]
    return {k: {"ledger": v[0], "published": v[1], "equal": v[0] == v[1]} for k, v in out.items()}


def reconcile(blk, A):
    """The ledger's accepted counts against the estimators' published n: the all-corpus blocks, and the warm / shoulder cohort variants in seasonalCharts."""
    ch = A["seasonalCharts"]["charts"]
    checks = _rec_one(blk["estimators"], A["thermalWarmupLag"], A["hvcEngine80C"], A["warmupCurve"]["classes"], (A.get("thermalFuelPenalty") or {}).get("nColdStartDrives"), "")
    for c in ("warm", "shoulder"):
        d = lambda cid: (ch[cid]["data"].get(c) or {})
        checks.update(_rec_one(blk["byCohort"][c], d("ThermalWarmupLag") or None, d("HvcEngine80C"), d("WarmupCurve").get("classes"), d("ThermalFuelPenalty").get("nColdStartDrives"), c + "."))
    return {"checks": checks, "allEqual": all(v["equal"] for v in checks.values())}


def build(dm, frame_loader, raw_dir, A):
    C = _csa()
    files = list(dm["file"])
    dist = dict(zip(dm["file"], dm["distance_km"]))
    dtype = dict(zip(dm["file"], dm["drive_type"]))
    day = dict(zip(dm["file"], dm["date"].astype(str).str[:10]))
    lag, raw, fuel = [], [], []
    for fn in files:
        fr = frame_loader(fn)
        lag.append({**lag_record(fr, C), "_d": day.get(fn)})
        raw.append({**raw_record(fr, dist.get(fn), dtype.get(fn), C), "_d": day.get(fn)})
        fuel.append({**fuel_record(fn, C, None, raw_dir), "_d": day.get(fn)})
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")["thermal_regime"]
    regime = [sdm.get(fn) for fn in files]

    def est_for(idx):
        hv_, cu_ = aggregate_raw([raw[i] for i in idx], C)
        return {"warmupLag": aggregate_lag([lag[i] for i in idx], C), "hvcEngine80C": hv_, "warmupCurve": cu_, "fuelPenalty": aggregate_fuel([fuel[i] for i in idx], C)}
    est = est_for(range(len(files)))
    by_cohort = {c: est_for([i for i, r in enumerate(regime) if r == c]) for c in ("warm", "shoulder")}
    cm = (A.get("cohortMeta") or {}).get("cold")
    ia = (A.get("meta") or {}).get("intakeAir") or {}
    blk = {"_provenance": "GENERATED by tools/thermal_support_ledger.py (M418, spec analyses/M418_spec.md); do not hand-edit. Additive block: candidate / accepted / excluded / censored counts of the thermal estimates that select drives; no estimator and no time-to-event model.",
           "methodVersion": METHOD_VERSION,
           "population": {"nMasterDrives": int(len(dm)), "nDays": int(dm["date"].astype(str).str[:10].nunique()), "note": "the estimators do not filter on ens_outlier_v2; each ledger states its own rule"},
           "estimators": {**est,
                          "thermalStepResponse": {k: A["thermalStepResponse"].get(k) for k in ("nCandidates", "nFits", "gateRejections")},
                          "shortTripWarmup": {k: A["shortTripWarmup"].get(k) for k in ("n", "nCrossed80", "pctCrossed80")}},
           "byCohort": by_cohort,
           "cohortNote": "warm and shoulder reproduce the cohort variants of the thermal charts (seasonal_drive_master thermal_regime); the cold cohort (7 drives, 3 days) is below the minimum support and is not computed",
           "coldCohort": {k: (cm or {}).get(k) for k in ("nObserved", "nDaysObserved", "suppressed", "eligibleForCohortView", "inferenceAvailable")},
           "intakeAir": {k: ia.get(k) for k in ("nDrives", "nDrivesValid", "nDrivesNoValue", "lastValidDate", "nDrivesAfterLastValid")},
           "censoringReading": ["a drive that does not reach a threshold is a right-censored observation: its observation ended (key-off) before the threshold",
                                "the pooled time-to-threshold medians of thermalWarmupLag are medians of the reachers only; censored drives are excluded, so the median understates the time for all cold starts; where fewer than half of the cold starts reached the threshold the cohort median is not identifiable from these data",
                                "risk-set rows are counts at fixed times, not a time-to-event estimate; censoring by key-off is not independent of the trip choices and is not modelled",
                                "winter stays suppressed: the cold cohort has too few drives and days for any estimate; this ledger reports its support only"],
           "limits": ["single vehicle, one driver, May-October; ambient 3-38 C", "the cold-start definitions differ by estimator on purpose (coolant <= 50 C, none, < 60 C): each ledger states its own",
                      "the ledger classifies drives with the estimator's own rules and checks its accepted counts against the published n; a changed estimator rule makes the reconciliation fail until the ledger is updated"]}
    blk["reconciliation"] = reconcile(blk, A)
    return blk


def splice(A, blk, master_md5="", now=None):
    import dependence_sensitivity as DS
    new = copy.deepcopy(A)
    new["thermalSupportLedger"] = blk
    old = (A.get("_artifactStamps") or {}).get("thermalSupportLedger")
    if old and A.get("thermalSupportLedger") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["thermalSupportLedger"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M418: derived by tools/thermal_support_ledger.py from the frame cache and the raw files; additive thermal support ledger", upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        new["_artifactStamps"]["thermalSupportLedger"] = st
    ch = DS._paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    import drive_raw_cache as drc
    import dependence_sensitivity as DS
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    raw_dir = os.environ.get("XT_RAW_DIR_STAGED") or os.path.join(ROOT, "raw_only")
    fl = drc.make_frame_loader(raw_dir=raw_dir)
    blk = DS._round(build(dm, fl, raw_dir, A0), 4)
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, changed, bad = splice(A0, blk, md5)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad, "reconciliationAllEqual": blk["reconciliation"]["allEqual"],
                      "notEqual": {k: v for k, v in blk["reconciliation"]["checks"].items() if not v["equal"]}}, indent=1))
    if bad or not blk["reconciliation"]["allEqual"]:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
