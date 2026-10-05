#!/usr/bin/env python3
"""Emulated sampling-sensitivity study of the pipeline keys to the logger PID-cadence regime (M379b; analyses/M379_spec.md Rev 2 + Rev 3; library tools/cadence_emulate.py).
Studies: (A) fast-regime drives with an energy block, emulated at the slow-regime interval distribution ("slow") and at twice its intervals ("slower"), 20 seeds per drive;
(B) control: 100 random slow-regime drives (seed 42) thinned to twice the slow intervals ("slower"), 20 seeds; (C) emulator-robustness: nearest-sample selection (no dithering) on
30 random fast drives (seed 42), seeds 1..5. Observational strata and the +-7 day transition windows come from the master columns and are labelled confounded.
Per key: ratio of sums (emulated / original) or mean per-drive difference with a day-clustered percentile bootstrap CI (seed 42, 4000 draws), seed spread, and the
classification under the frozen margins. Nothing is written to the master. Output: analyses/M379_cadence_sensitivity.json (script-written; provenance recorded).
Usage: python tools/cadence_sensitivity.py [--workers 10] [--seeds 20] [--limit N] [--out PATH]    (resumable through audit/m379_runs.jsonl)"""
import argparse, concurrent.futures as cf, glob, hashlib, json, os, re, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cadence_emulate as E

NB, BOOT_SEED = 4000, 42
dig = lambda s: re.sub(r"\D", "", str(s).rsplit(".", 1)[0])[:14]
RATIO_MARGIN = (0.99, 1.01)
MARGINS = {"ratio": {k: RATIO_MARGIN for k in ("gross_throughput_kwh", "gross_discharge_kwh", "gross_charge_kwh", "distance_km", "rf_efc", "fce")},
           "abs": {**{k: 0.003 for k in ("net_draw_kwh_corr", "energy_residual_kwh", "offset_kwh_removed", "soc_delta_kwh", "net_draw_per100km_corr", "ev_kwh_per100km")},
                   **{k: 0.5 for k in ("engine_on_pct", "regen_share_of_charge", "ev_dist_pct")}}}
UNITS = {"net_draw_per100km_corr": "kWh/100km", "ev_kwh_per100km": "kWh/100km", "engine_on_pct": "pp", "regen_share_of_charge": "pp", "ev_dist_pct": "pp"}
HEADLINE = {"net_draw_per100km_corr": "EnergyIntensity.all (kWh/100km, canonical-clean)"}


def setup():
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    dm["k"] = dm["file"].map(dig)
    cr = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv"))
    cr["k"] = cr["file"].map(dig)
    raw = {dig(os.path.basename(p)): p for p in glob.glob(os.path.join(ROOT, "raw", "*.csv"))}
    m = dm.merge(cr[["k", "regime"]], on="k", how="left").set_index("k")
    ok = m["gross_throughput_kwh"].notna() & (m["distance_km"] > 0) & (m["ens_outlier_v2"].astype(str) != "True") & m.index.isin(list(raw))
    return dm, m, raw, ok


def _init(pools):
    global POOLS
    POOLS = pools


def _task(a):
    kind, key, path, idx, seed, factor, dither, ioff = a
    try:
        import compute_drive_summary_v6 as C
        if kind == "orig":
            return dict(kind=kind, key=key, seed=0, keys=E.keys_of(C.analyze_bytes(open(path, "rb").read(), os.path.basename(path)), ioff), rep={})
        if kind == "identity":
            k, rep = E.run_drive(path, POOLS, 1, idx, 1.0, ioff, keep_all=True)
            return dict(kind=kind, key=key, seed=1, keys=k, rep=rep)
        k, rep = E.run_drive(path, POOLS, seed, idx, factor, ioff, dither=dither)
        return dict(kind=kind, key=key, seed=seed, keys=k, rep=rep)
    except Exception as e:     # a failing drive is recorded, never silently dropped
        return dict(kind=kind, key=key, seed=seed, keys=None, rep={}, error="%s: %s" % (type(e).__name__, str(e)[:200]))


def day_boot(dates, cols, nb=NB, seed=BOOT_SEED):
    """Per-day sums of the columns (dict name -> per-drive array) and the day-resampling count matrix."""
    df = pd.DataFrame({"_day": dates, **cols}).groupby("_day").sum()
    n = len(df)
    rng = np.random.default_rng(seed)
    cnt = np.stack([np.bincount(rng.integers(0, n, n), minlength=n) for _ in range(nb)])
    return {c: df[c].values for c in cols}, cnt, n


def stat_key(kind, key, orig, emu_by_seed, dates):
    """orig: array over drives; emu_by_seed: array (seeds x drives); NaN where missing. Returns the corpus statistic with CI, seed spread, classification."""
    emu_mean = np.nanmean(emu_by_seed, axis=0)
    ok = ~(np.isnan(orig) | np.isnan(emu_mean))
    if ok.sum() < 3:
        return {"n": int(ok.sum()), "note": "too few paired drives"}
    o, e, d = orig[ok], emu_mean[ok], np.asarray(dates)[ok]
    out = {"nDrives": int(ok.sum()), "nDays": int(len(set(d)))}
    if kind in ("ratio", "count"):
        sums, cnt, _ = day_boot(d, {"e": e, "o": o})
        r = (cnt @ sums["e"]) / (cnt @ sums["o"])
        out["statistic"] = "ratio of sums (emulated / original)"
        out["estimate"] = float(e.sum() / o.sum())
        per = [float(np.nansum(np.where(ok, emu_by_seed[s], np.nan)) / o.sum()) for s in range(emu_by_seed.shape[0])]
    else:
        sums, cnt, _ = day_boot(d, {"d": e - o, "n": np.ones(len(o))})
        r = (cnt @ sums["d"]) / (cnt @ sums["n"])
        out["statistic"] = "mean per-drive difference (emulated - original)" + (" [%s]" % UNITS[key] if key in UNITS else "")
        out["estimate"] = float((e - o).mean())
        per = [float(np.nanmean(np.where(ok, emu_by_seed[s] - orig, np.nan))) for s in range(emu_by_seed.shape[0])]
    out["ci95"] = [float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))]
    out["seedSd"] = float(np.std(per, ddof=1)) if len(per) > 1 else None
    if kind == "peak":
        out["class"] = "reported (one-sided bias; negative control)"
        out["movementDetected"] = bool(out["ci95"][0] > 0 or out["ci95"][1] < 0)
    elif kind == "count":
        out["class"] = "reported (scaling factor)"
    elif key in MARGINS["ratio"]:
        lo, hi = MARGINS["ratio"][key]
        out["margin"] = [lo, hi]
        out["class"] = "cadence-insensitive within the pre-registered margin" if (out["ci95"][0] >= lo and out["ci95"][1] <= hi) else "cadence-sensitive (outside the pre-registered margin)"
    elif key in MARGINS["abs"]:
        m = MARGINS["abs"][key]
        out["margin"] = [-m, m]
        out["class"] = "cadence-insensitive within the pre-registered margin" if (out["ci95"][0] >= -m and out["ci95"][1] <= m) else "cadence-sensitive (outside the pre-registered margin)"
    else:
        out["class"] = "reported (no pre-registered margin)"
    return out


def aggregate(runs, origs, study_keys, dates_of, kinds=E.KEYS):
    """runs: {key: {seed: keys}}, origs: {key: keys}; returns {keyname: stat}."""
    res = {}
    seeds = sorted({s for k in runs for s in runs[k]})
    for name, kind in kinds.items():
        orig = np.array([np.nan if origs[k].get(name) is None else float(origs[k][name]) for k in study_keys])
        emu = np.array([[np.nan if runs[k].get(s, {}).get(name) is None else float(runs[k][s][name]) for k in study_keys] for s in seeds])
        res[name] = stat_key(kind, name, orig, emu, [dates_of[k] for k in study_keys])
    return res


def observational(m, ok, windows):
    """Per-regime strata and +-7 day transition windows from the master columns (descriptive; confounded by season, ambient and drive mix)."""
    keys = [k for k in E.KEYS if k in m.columns and E.KEYS[k] != "count"]
    sub = m[ok & m["regime"].notna()].copy()
    sub["dd"] = sub["date"].astype(str).str[:10]

    def block(frame):
        out = {}
        for k in keys:
            v = pd.to_numeric(frame[k], errors="coerce")
            f = frame[v.notna()]
            if len(f) < 3:
                continue
            sums, cnt, n = day_boot(f["dd"].values, {"s": v[v.notna()].values, "n": np.ones(len(f))})
            r = (cnt @ sums["s"]) / (cnt @ sums["n"])
            out[k] = {"mean": float(v[v.notna()].mean()), "ci95": [float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))], "nDrives": int(len(f)), "nDays": int(f["dd"].nunique())}
        return out
    res = {"label": "descriptive; confounded by season, ambient and drive mix (the first fast run is summer)", "byRegime": {g: block(sub[sub["regime"] == g]) for g in ("fast", "slow")}, "windows": []}
    for name, t in windows:
        t0 = pd.Timestamp(t)
        w = sub[(pd.to_datetime(sub["dd"]) >= t0 - pd.Timedelta(days=7)) & (pd.to_datetime(sub["dd"]) <= t0 + pd.Timedelta(days=7))]
        res["windows"].append({"transition": name, "from": str((t0 - pd.Timedelta(days=7)).date()), "to": str((t0 + pd.Timedelta(days=7)).date()),
                               "nFast": int((w["regime"] == "fast").sum()), "nSlow": int((w["regime"] == "slow").sum()),
                               "byRegime": {g: block(w[w["regime"] == g]) for g in ("fast", "slow")}})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0, help="limit the number of study drives (smoke test)")
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M379_cadence_sensitivity.json"))
    a = ap.parse_args()
    t0 = time.time()
    os.chdir(ROOT)
    import m377_pin
    dm, m, raw, ok = setup()
    fast = m[ok & (m["regime"] == "fast")]
    slow_all = m[(m["regime"] == "slow") & m.index.isin(list(raw))]
    slow_ok = m[ok & (m["regime"] == "slow")]
    rng = np.random.default_rng(42)
    pool_keys = list(rng.choice(slow_all.index.values, 40, replace=False))
    pools = E.build_pools([raw[k] for k in pool_keys])
    icol = next(c for c in pools if "HV Battery Current (A)" in c)
    slow_pm = pools[icol][pools[icol] < 5.0]
    study = list(fast.index)
    ctrl = list(rng.choice(slow_ok.index.values, 100, replace=False)) if len(slow_ok) >= 100 else list(slow_ok.index)
    robust = list(rng.choice(study, min(30, len(study)), replace=False))
    if a.limit:
        study, ctrl, robust = study[:a.limit], ctrl[:a.limit], robust[:a.limit]
    seeds = list(range(1, a.seeds + 1))
    ioff = m["I_offset_A_applied"].to_dict()
    dates_of = m["date"].astype(str).str[:10].to_dict()
    idx_of = {k: i for i, k in enumerate(m.index)}
    tasks = []
    for k in sorted(set(study) | set(ctrl)):
        tasks.append(("orig", k, raw[k], idx_of[k], 0, 1.0, True, ioff[k]))
    ident = list(study[:5]) + list(ctrl[:5])
    for k in ident:
        tasks.append(("identity", k, raw[k], idx_of[k], 1, 1.0, True, ioff[k]))
    for k in study:
        for s in seeds:
            tasks.append(("fast_to_slow", k, raw[k], idx_of[k], s, 1.0, True, ioff[k]))
            tasks.append(("fast_to_slower", k, raw[k], idx_of[k], s, 2.0, True, ioff[k]))
    for k in ctrl:
        for s in seeds:
            tasks.append(("slow_to_slower", k, raw[k], idx_of[k], s, 2.0, True, ioff[k]))
    for k in robust:
        for s in range(1, 6):
            tasks.append(("fast_to_slow_nearest", k, raw[k], idx_of[k], s, 1.0, False, ioff[k]))
    os.makedirs(os.path.join(ROOT, "audit"), exist_ok=True)
    cache_p = os.path.join(ROOT, "audit", "m379_runs.jsonl")
    done = {}
    if os.path.exists(cache_p):
        for line in open(cache_p, encoding="utf-8"):
            r = json.loads(line)
            if r.get("keys") is not None:
                done[(r["kind"], r["key"], r["seed"])] = r
    todo = [t for t in tasks if (t[0], t[1], t[4] if t[0] not in ("orig",) else 0) not in done]
    print("tasks", len(tasks), "cached", len(tasks) - len(todo), flush=True)
    with open(cache_p, "a", encoding="utf-8", newline="\n") as fh, cf.ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(pools,)) as ex:
        for n, r in enumerate(ex.map(_task, todo, chunksize=4), 1):
            fh.write(json.dumps(r, default=float) + "\n")
            if r.get("keys") is not None:
                done[(r["kind"], r["key"], r["seed"])] = r
            if n % 250 == 0:
                print(n, "of", len(todo), round(time.time() - t0), "s", flush=True)
    errors = [r for r in (json.loads(l) for l in open(cache_p, encoding="utf-8")) if r.get("keys") is None and (r["kind"], r["key"], r["seed"]) not in done]
    get = lambda kind, key, seed=0: done.get((kind, key, seed))
    origs = {k: get("orig", k)["keys"] for k in set(study) | set(ctrl) if get("orig", k)}
    # ---- validation ----
    val = {"identityKeepAll": {"nDrives": len(ident), "maxAbsDiffAllKeys": max((abs((get("identity", k, 1)["keys"].get(n) or 0) - (origs[k].get(n) or 0)) for k in ident if get("identity", k, 1) and k in origs for n in E.KEYS), default=None)}}
    mk = m
    d_thr = [abs(float(origs[k]["gross_throughput_kwh"]) - float(mk.loc[k, "gross_throughput_kwh"])) for k in origs if origs[k].get("gross_throughput_kwh") is not None]
    d_dist = [abs(float(origs[k]["distance_km"]) - float(mk.loc[k, "distance_km"])) for k in origs if origs[k].get("distance_km") is not None]
    val["masterReproduction"] = {"nDrives": len(d_thr), "maxAbsDiffGrossThroughput": max(d_thr), "maxAbsDiffDistance": max(d_dist), "nDistanceDiffering": int(sum(1 for x in d_dist if x > 1e-6)),
                                 "note": "distance_km as emitted by analyze_bytes differs from the master post-processed distance on these drives; the paired differences use the same analyze_bytes distance for original and emulated"}
    reps = [r["rep"]["I_interval_lt5"] for (kd, _k, _s), r in done.items() if kd == "fast_to_slow" and r["rep"].get("I_interval_lt5")]
    if reps:
        w = np.array([x["n"] for x in reps], float)
        em = float(np.average([x["mean"] for x in reps], weights=w))
        val["intervalMatch"] = {"basis": "I-PID intervals below 5 s (pipeline integration cap)", "slowPoolMean": float(slow_pm.mean()), "emulatedMeanWeighted": em, "relDiffMean": em / float(slow_pm.mean()) - 1.0,
                                "withinFivePercent": bool(abs(em / float(slow_pm.mean()) - 1.0) <= 0.05),
                                "slowPoolMedian": float(np.median(slow_pm)), "emulatedMedianOfMedians": float(np.median([x["median"] for x in reps])),
                                "slowPoolQuantiles_p10_p25_p75_p90": [float(x) for x in np.percentile(slow_pm, [10, 25, 75, 90])],
                                "emulatedQuantilesMean_p10_p25_p75_p90": [float(np.average([x["q"][i] for x in reps], weights=w)) for i in range(4)],
                                "limit": "thinning keeps native samples (grid about 0.8 s): the median is quantized and the spread wider than the slow regime"}
    ivs = [done[("fast_to_slow", k, s)]["keys"].get("iv_alignment_gap_s") for k in study for s in seeds if ("fast_to_slow", k, s) in done]
    ivs = [x for x in ivs if x is not None]
    slow_iv = pd.to_numeric(m[m["regime"] == "slow"]["iv_alignment_gap_s"], errors="coerce").dropna()
    if ivs and len(slow_iv):
        val["ivGap"] = {"emulatedMedian": float(np.median(ivs)), "slowRegimeMasterMedian": float(slow_iv.median()), "relDiff": float(np.median(ivs) / slow_iv.median() - 1.0), "flagOutsidePlusMinus25pct": bool(abs(np.median(ivs) / slow_iv.median() - 1.0) > 0.25)}
    # ---- results ----
    def runs_of(kind, keys):
        return {k: {s: done[(kind, k, s)]["keys"] for s in sorted({s for (kd, kk, s) in done if kd == kind and kk == k})} for k in keys if any((kind, k, s) in done for s in seeds)}
    results = {}
    for kind, keys in (("fast_to_slow", study), ("fast_to_slower", study), ("slow_to_slower", ctrl), ("fast_to_slow_nearest", robust)):
        rr = runs_of(kind, keys)
        ks = [k for k in keys if k in rr and k in origs]
        results[kind] = {"nDriveSeedRuns": int(sum(len(v) for v in rr.values())), "keys": aggregate(rr, origs, ks, dates_of)}
    flips = {n: {"fast_to_slow": results["fast_to_slow"]["keys"][n].get("class"), "nearest": results["fast_to_slow_nearest"]["keys"][n].get("class")} for n in E.KEYS
             if results["fast_to_slow"]["keys"][n].get("class") != results["fast_to_slow_nearest"]["keys"][n].get("class")}
    # ---- quarter-half-width rule for the headline KPI ----
    try:
        A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
        kp = next(k for k in json.load(open(os.path.join(ROOT, "tools", "kpi_paths.json")))["kpis"] if k["name"] == HEADLINE["net_draw_per100km_corr"])
        lo, hi = [__import__("functools").reduce(lambda d, k: d[k], path, A) for path in kp["ci"]]
        hw = (hi - lo) / 2
        sh = results["fast_to_slow"]["keys"]["net_draw_per100km_corr"].get("estimate")
        quarter = {"headlineKpi": kp["name"], "ciHalfWidth": hw, "quarter": hw / 4, "shift": sh, "shiftBelowQuarter": bool(sh is not None and abs(sh) < hw / 4)}
    except Exception as e:
        quarter = {"note": "not computed: %s" % e}
    out = {"meta": {"milestone": "M379b", "specSha256Frozen": m377_pin.spec_sha(os.path.join(ROOT, "analyses", "M379_spec.md")),
                    "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "seeds": seeds, "bootstrap": {"draws": NB, "seed": BOOT_SEED, "unit": "calendar day"},
                    "poolDrives": len(pool_keys), "poolSeed": 42, "nStudyDrives": len(study), "nStudyDays": len({dates_of[k] for k in study}), "nControlDrives": len(ctrl), "nRobustnessDrives": len(robust),
                    "scriptSha256": {f: hashlib.sha256(open(os.path.join(ROOT, "tools", f), "rb").read()).hexdigest()[:16] for f in ("cadence_sensitivity.py", "cadence_emulate.py")},
                    "runtimeS": round(time.time() - t0), "nTaskErrors": len(errors), "errors": [{"kind": e["kind"], "key": e["key"], "seed": e["seed"], "error": e.get("error")} for e in errors[:10]],
                    "limits": ["thinning emulation, not a causal cadence effect (PID-set / polling-order change, I-V co-timing, jitter and app-internal calculations are not emulated)", "fast -> slow direction only, on Aug / Oct conditions",
                               "keys of analyze_bytes only (+ the three offset keys recomputed with the frozen formula); the generator / traction reconstruction (f_gen, eta_bus) is not covered", "fuel rate / counter keys excluded (app-calculated)"]},
           "validation": val, "emulation": results, "robustnessClassFlips": flips, "headlineQuarterRule": quarter,
           "observational": observational(m, ok, [("2026-08-14 slow -> fast", "2026-08-14"), ("2026-09-06 fast -> slow", "2026-09-06"), ("2026-10-01 slow -> fast", "2026-10-01")])}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=1, ensure_ascii=False, default=float) + "\n")
    print("wrote", a.out, "in", round(time.time() - t0), "s; task errors:", len(errors))


if __name__ == "__main__":
    main()
