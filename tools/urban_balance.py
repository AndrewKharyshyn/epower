#!/usr/bin/env python3
"""M504 (spec analyses/M504_spec.md Rev 2): covariate balance and design-dependence of the Warm-vs-Shoulder urban energy-intensity contrast (audit ST-09).
Reporting only: the released contrast (comparisonCube.urbanContrast, M491) and the M494 block verdict are read, never changed. D0 is computed with the cube's own joint-day function and generator
stream (seed 20260925, stream SEED+2, band after band) and HARD-STOPS unless its estimate, counts and interval bounds equal the cube's. D1-D3 use separate fixed streams (seed 42 + design index).
Reads only drive_master.csv, seasonal_drive_master.csv and summary_arrays.json (no raw files). Default: write analyses/M504_result.json.
--splice: write the additive payload block urbanContrastBalance + stamp (ingestion stage); escalates (exit 3) if the overall verdict changed unless --ack-verdict-change.
Usage: python tools/urban_balance.py [--out analyses/M504_result.json] [--splice] [--ack-verdict-change]"""
import copy, datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import urban_week_block as UW
import joint_day_bootstrap as JB

CUBE_SEED, CUBE_DRAWS = 20260925, 4000       # m297_comparison_cube: B = 2000, draws = B * 2 = 4000, rngJ = default_rng(SEED + 2)
N_DRAWS, SEED = 4000, 42
MIN_DRIVES, MIN_DAYS, LOW_DAYS, DROP_CAP, WIDTH_MAX = 10, 5, 10, 0.005, 1.5
MC_NEAR_ZERO = 0.25      # Director (M504 decision): an interval endpoint within this distance of zero is flagged as Monte Carlo-sensitive (reporting only; the frozen verdict is unchanged)
D3_NOTE = ("D3 = the rows of D1 that are also rows of D2, with the common-support ranges computed on the full band population; other definitions of common support inside the same-date set give different "
           "row counts and estimates, so the combined-restriction reading depends on the design and on this definition")
BANDS = UW.BANDS
COVS = [("dayOfYear", "day of year"), ("startHour", "start hour"), ("socStart", "start SoC"), ("tPackStart", "pack temperature at start"),
        ("tPackMean", "mean pack temperature (measured during the drive; description only)"), ("speedMoving", "moving speed"), ("distance", "distance"), ("weekend", "weekend share")]
CS_COVS = ["startHour", "socStart", "tPackStart"]           # common-support covariates of D2 (none is measured during the drive)


def add_covariates(g, seas):
    g = g.copy().merge(seas, on="file", how="left")
    d = pd.to_datetime(g["date"].astype(str))
    g["dayOfYear"] = d.dt.dayofyear.astype(float)
    t = pd.to_datetime(g["time_start"].astype(str), format="%H:%M:%S.%f", errors="coerce").fillna(pd.to_datetime(g["time_start"].astype(str), errors="coerce"))
    g["startHour"] = t.dt.hour + t.dt.minute / 60.0 + t.dt.second / 3600.0
    g["socStart"] = pd.to_numeric(g["soc_start"], errors="coerce")
    g["tPackStart"] = pd.to_numeric(g["pack_temp_start_c"], errors="coerce")
    g["tPackMean"] = pd.to_numeric(g["T_pack_mean_avg"], errors="coerce")
    g["speedMoving"] = pd.to_numeric(g["speed_mean_moving"], errors="coerce")
    g["distance"] = pd.to_numeric(g["distance_km"], errors="coerce")
    g["weekend"] = (d.dt.dayofweek >= 5).astype(float)
    return g


def smd(a, b, proportion=False):
    """(mean_b - mean_a) / pooled SD with a = Warm, b = Shoulder; the SD of a proportion is sqrt(p(1-p)). None when undefined."""
    a, b = a.dropna(), b.dropna()
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = (a.mean() * (1 - a.mean()), b.mean() * (1 - b.mean())) if proportion else (a.var(ddof=1), b.var(ddof=1))
    sp = np.sqrt((va + vb) / 2.0)
    return None if sp == 0 else float((b.mean() - a.mean()) / sp)


def inside_share(x, ref):
    ref = ref.dropna()
    x = x.dropna()
    if len(ref) == 0 or len(x) == 0:
        return None
    lo, hi = np.percentile(ref, [5, 95])
    return round(float(((x >= lo) & (x <= hi)).sum() / len(x)), 3)


def balance(g):
    w, s = g[g.thermal_regime.eq("warm")], g[g.thermal_regime.eq("shoulder")]
    out = {}
    for key, label in COVS:
        a, b = w[key], s[key]
        sv = smd(a, b, proportion=(key == "weekend"))
        out[key] = {"label": label, "nWarm": int(a.notna().sum()), "nShoulder": int(b.notna().sum()), "nMissingWarm": int(a.isna().sum()), "nMissingShoulder": int(b.isna().sum()),
                    "meanWarm": None if a.notna().sum() == 0 else round(float(a.mean()), 3), "sdWarm": None if a.notna().sum() < 2 else round(float(a.std(ddof=1)), 3),
                    "meanShoulder": None if b.notna().sum() == 0 else round(float(b.mean()), 3), "sdShoulder": None if b.notna().sum() < 2 else round(float(b.std(ddof=1)), 3),
                    "smd": None if sv is None else round(sv, 3), "shoulderInsideWarmP5P95": inside_share(b, a), "warmInsideShoulderP5P95": inside_share(a, b)}
    return out


def day_frame(c):
    return c.groupby("day")[["gross_throughput_kwh", "distance_km"]].sum().rename(columns={"gross_throughput_kwh": "num", "distance_km": "den"})


def design_result(g, rng, n_draws, exact_cube=None):
    """Point estimate and joint calendar-day percentile interval (dates of the design resampled together, both cohorts) through joint_day_bootstrap.joint_difference."""
    w, s = g[g.thermal_regime.eq("warm")], g[g.thermal_regime.eq("shoulder")]
    out = {"warm": {"nDrives": int(len(w)), "nDays": int(w["day"].nunique())}, "shoulder": {"nDrives": int(len(s)), "nDays": int(s["day"].nunique())}}
    if len(w) < MIN_DRIVES or len(s) < MIN_DRIVES or out["warm"]["nDays"] < MIN_DAYS or out["shoulder"]["nDays"] < MIN_DAYS:
        out.update(estimable=False, reason="fewer than %d drives or %d days in a cohort" % (MIN_DRIVES, MIN_DAYS))
        return out
    ew = 100 * w.gross_throughput_kwh.sum() / w.distance_km.sum()
    es = 100 * s.gross_throughput_kwh.sum() / s.distance_km.sum()
    dw, ds = day_frame(w), day_frame(s)
    draws, _, _, dropped, nunion, nshared = JB.joint_difference(dw, ds, rng, n_draws)
    ci = JB.interval(draws)
    out.update(estimable=True, warmEstimate=round(float(ew), 2), shoulderEstimate=round(float(es), 2), estimate=round(float(es - ew), 2), ci95=ci, includesZero=bool(ci[0] <= 0 <= ci[1]),
               nDraws=int(n_draws), nDrawsDropped=int(dropped), nUnionDates=int(nunion), nSharedDates=int(nshared),
               nonDecisive=bool(dropped > DROP_CAP * n_draws), lowPrecision=bool(min(out["warm"]["nDays"], out["shoulder"]["nDays"]) < LOW_DAYS),
               endpointMcSensitive=bool(min(abs(ci[0]), abs(ci[1])) < MC_NEAR_ZERO))
    return out


def designs(g, rngs, cube_diff):
    w, s = g[g.thermal_regime.eq("warm")], g[g.thermal_regime.eq("shoulder")]
    shared = set(w["day"]) & set(s["day"])
    d1 = g[g["day"].isin(shared)]
    keep = pd.Series(True, index=g.index)
    cs = {}
    for k in CS_COVS:
        lo = max(np.percentile(w[k].dropna(), 5), np.percentile(s[k].dropna(), 5))
        hi = min(np.percentile(w[k].dropna(), 95), np.percentile(s[k].dropna(), 95))
        cs[k] = [round(float(lo), 3), round(float(hi), 3)]
        keep &= g[k].between(lo, hi)
    n_missing = int(g[CS_COVS].isna().any(axis=1).sum())
    d2 = g[keep]
    d3 = d1[d1.index.isin(d2.index)]
    res = {"D0": design_result(g, rngs["D0"], CUBE_DRAWS), "D1": design_result(d1, rngs["D1"], N_DRAWS), "D2": design_result(d2, rngs["D2"], N_DRAWS), "D3": design_result(d3, rngs["D3"], N_DRAWS)}
    # R7: D0 must equal the released contrast exactly
    if (res["D0"]["estimate"] != cube_diff["estimate"] or res["D0"]["ci95"] != cube_diff["ci95"]):
        raise SystemExit("M504 STOP: D0 differs from comparisonCube (estimate %r vs %r, ci %r vs %r)" % (res["D0"]["estimate"], cube_diff["estimate"], res["D0"]["ci95"], cube_diff["ci95"]))
    base_w = res["D0"]["ci95"][1] - res["D0"]["ci95"][0]
    for k in ("D1", "D2", "D3"):
        r = res[k]
        if r.get("estimable"):
            r["widthRatioToD0"] = round((r["ci95"][1] - r["ci95"][0]) / base_w, 3)
            if r["widthRatioToD0"] > WIDTH_MAX:
                r["lowPrecision"] = True
    res["fidelityD0"] = {"estimateEqualsCube": True, "ci95EqualsCube": True, "cubeEstimate": cube_diff["estimate"], "cubeCi95": cube_diff["ci95"], "note": "hard stop otherwise"}
    res["commonSupportRanges"] = cs
    res["nSharedDates"] = int(len(shared))
    res["nExcludedMissingCovariate"] = n_missing
    return res


def verdict(dres):
    base = dres["D0"]
    est = {k: dres[k] for k in ("D1", "D2", "D3") if dres[k].get("estimable") and not dres[k].get("nonDecisive")}
    if not base.get("estimable") or not est:
        return {"verdict": "not assessable", "differing": []}
    diff = [{"design": k, "flip": ("excludes zero -> includes zero" if base["includesZero"] is False else "includes zero -> excludes zero"), "widthRatioToD0": v.get("widthRatioToD0"), "lowPrecision": bool(v.get("lowPrecision")), "endpointMcSensitive": bool(v.get("endpointMcSensitive"))}
            for k, v in est.items() if v["includesZero"] != base["includesZero"]]
    if not diff:
        return {"verdict": "reading unchanged", "differing": []}
    lab = "reading depends on the design; restricted design has lower precision" if all(d["lowPrecision"] for d in diff) else "reading depends on the design"
    return {"verdict": lab, "differing": diff}


def build(dm, reg, seas, cube):
    pop = add_covariates(UW.population(dm, reg), seas)
    rngs = {"D0": np.random.default_rng(CUBE_SEED + 2)}
    for i, k in enumerate(("D1", "D2", "D3")):
        rngs[k] = np.random.default_rng(SEED + i + 1)
    bands = []
    for (label, lo, hi), cb in zip(BANDS, cube["urbanContrast"]["bands"]):
        assert cb["band"] == label, (cb["band"], label)
        g = pop[(pop.distance_km >= lo) & (pop.distance_km < hi)]
        w, s = g[g.thermal_regime.eq("warm")], g[g.thermal_regime.eq("shoulder")]
        if (len(w) != cb["warm"]["nDrives"] or len(s) != cb["shoulder"]["nDrives"] or w["day"].nunique() != cb["warm"]["nDays"] or s["day"].nunique() != cb["shoulder"]["nDays"]):
            raise SystemExit("M504 STOP: band %r drive/day counts differ from comparisonCube" % label)
        dres = designs(g, rngs, cb["difference"])
        v = verdict(dres)
        bands.append({"band": label, "balance": balance(g), "designs": dres, "verdict": v["verdict"], "differing": v["differing"]})
    order = ["reading depends on the design", "reading depends on the design; restricted design has lower precision", "not assessable", "reading unchanged"]
    overall = next(v for v in order if any(b["verdict"] == v for b in bands))
    cand = [(k, abs(x["smd"])) for k, x in bands[0]["balance"].items() if x["smd"] is not None and k != "tPackMean"]
    big = max(cand, key=lambda t: t[1]) if cand else None
    return {"bands": bands, "overallVerdict": overall, "largestAbsSmdAllUrban": None if big is None else {"covariate": big[0], "absSmd": round(big[1], 3)}}


def provenance():
    return {"masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "seasonalMasterMd5": hashlib.md5(open("seasonal_drive_master.csv", "rb").read()).hexdigest(),
            "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "specSha256": hashlib.sha256(open("analyses/M504_spec.md", "rb").read()).hexdigest(),
            "seeds": {"D0": "cube stream 20260925 + 2, %d draws, band after band" % CUBE_DRAWS, "D1-D3": "42 + design index, %d draws" % N_DRAWS}}


def main():
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M504_result.json"
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    reg = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "thermal_regime"]]
    seas = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "pack_temp_start_c"]]
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    res = build(dm, reg, seas, A["comparisonCube"])
    prov = provenance()
    if "--splice" in sys.argv:
        splice(A, res, prov)
        return
    out = {"spec": "analyses/M504_spec.md", "provenance": {**prov, "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}, **res}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
    brief = {"overall": res["overallVerdict"], "largestAbsSmd": res["largestAbsSmdAllUrban"]}
    brief["bands"] = [{"band": b["band"], "verdict": b["verdict"], "differing": b["differing"],
                       "designs": {k: {kk: v.get(kk) for kk in ("estimate", "ci95", "includesZero", "warm", "shoulder", "estimable", "widthRatioToD0", "lowPrecision")} for k, v in b["designs"].items() if isinstance(v, dict) and "warm" in v}} for b in res["bands"]]
    print(json.dumps(brief, indent=1)[:7000])


def splice(A, res, prov):
    P = "summary_arrays.json"
    raw = open(P, encoding="utf-8", newline="").read()
    blk = {"label": "covariate balance and design-dependence of the Warm-vs-Shoulder urban energy-intensity contrast (reporting only; the displayed interval stays the M491 joint-day interval; the designs are restrictions, not adjustments; thermal cohorts are ambient-threshold classes confounded with date and season)",
           "spec": "analyses/M504_spec.md", "specSha256": prov["specSha256"], "scriptSha256": prov["scriptSha256"], "masterMd5": prov["masterMd5"], "seasonalMasterMd5": prov["seasonalMasterMd5"], "seeds": prov["seeds"],
           "designRule": "D0 released (reproduced exactly); D1 same-date restriction; D2 common-support restriction (start hour, start SoC and pack temperature at start inside the intersection of the cohorts' P5-P95); D3 = D1 and D2; not estimable below 10 drives or 5 days in a cohort; non-decisive when more than 0.5 percent of draws are dropped",
           "designDefinitionNote": D3_NOTE, "endpointFlagRule": "endpointMcSensitive: the interval endpoint nearest to zero lies within %.2f of zero (reporting only; the verdict rule is unchanged)" % MC_NEAR_ZERO,
           "multiplicity": "12 non-D0 intervals across 4 overlapping bands; no adjustment; the any-estimable-design-differs rule leans conservative",
           "bands": res["bands"], "overallVerdict": res["overallVerdict"], "largestAbsSmdAllUrban": res["largestAbsSmdAllUrban"]}
    blk = json.loads(json.dumps(blk))
    old_blk = A.get("urbanContrastBalance")
    old = (A.get("_artifactStamps") or {}).get("urbanContrastBalance")
    coherent = old and old.get("includedInReleaseAt") == old.get("computedAt") == old.get("generatedAt")
    if old_blk == blk and coherent and old.get("corpusHash") == prov["masterMd5"]:
        print(json.dumps({"changed": False}))
        return
    if old_blk and old_blk.get("overallVerdict") != blk["overallVerdict"] and "--ack-verdict-change" not in sys.argv:
        print("ESCALATE (M504 spec, Escalation): the overall verdict changed from %r to %r; Director review required, rerun with --ack-verdict-change after it" % (old_blk.get("overallVerdict"), blk["overallVerdict"]))
        sys.exit(3)
    A["urbanContrastBalance"] = blk
    st = copy.deepcopy(A["_artifactStamps"]["urbanContrastBlocks"])
    n = res["bands"][0]["designs"]["D0"]
    st.update(corpusHash=prov["masterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M504: derived by tools/urban_balance.py from drive_master.csv, seasonal_drive_master.csv and comparisonCube (spec analyses/M504_spec.md Rev 2); all-urban D0: %d Warm and %d Shoulder drives" % (n["warm"]["nDrives"], n["shoulder"]["nDrives"]),
              upstreamHashes={"driveMasterMd5": prov["masterMd5"]})
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["urbanContrastBalance"] = st
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True, "overall": blk["overallVerdict"]}))


if __name__ == "__main__":
    main()
