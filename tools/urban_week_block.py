#!/usr/bin/env python3
"""M494 (spec analyses/M494_spec.md Rev 2): the additive payload block `urbanContrastBlocks` (+ artifact stamp): block-bootstrap sensitivities of the Warm-vs-Shoulder urban energy-intensity contrast (Shoulder minus Warm, ratio of sums,
four trip-length bands): ISO-calendar-week blocks (W), date-type stratified weeks (WS), 7- and 14-day CIRCULAR moving blocks (M7, M14) and a block-length-1 reference (M1), both cohorts resampled together (tools/block_bootstrap.py).
Reporting only: the released contrast (comparisonCube.urbanContrast, M491 joint-day interval) is read, never changed. The tool reproduces the cube's eligibility from drive_master.csv and seasonal_drive_master.csv and HARD-STOPS unless its
point estimates, drive counts and day counts equal the cube's. Nothing is typed: every number comes from the master and the cube. Seed 42, 4,000 draws (project default); the cube keeps its registered seed 20260925.
Usage: python tools/urban_week_block.py [--dry-run] [--check]   (writes ONLY /urbanContrastBlocks and /_artifactStamps/urbanContrastBlocks of summary_arrays.json; --check recomputes and compares with the payload, read-only)"""
import copy, datetime, hashlib, json, os, sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import block_bootstrap as BB

METHOD_VERSION = 1
N_DRAWS, SEED = 4000, 42
STREAMS = {"W": 42, "WS": 43, "M7": 44, "M14": 45, "M1": 46}      # one generator per procedure, consumed band after band
MIN_UNITS, MIN_COHORT_WEEKS = 10, 5
N_REPEATS = 8                  # Director ruling (Rev 2 result review): endpoint Monte Carlo error from repeats of each procedure on separate streams; diagnostic, the stored intervals use the main streams
ALLOWED = ["/urbanContrastBlocks", "/_artifactStamps/urbanContrastBlocks"]
BANDS = [("all urban trips", 0, 1e9), ("< 3 km", 0, 3), ("3–10 km", 3, 10), ("≥ 10 km", 10, 1e9)]


def population(dm, reg):
    """The cube's urban Warm / Shoulder population (m297_comparison_cube.py: canonical-clean, city read as urban, gross energy integral, distance > 0)."""
    d = dm.merge(reg, on="file", how="left")
    flag = lambda c: d[c].astype(str).str.strip().str.lower().eq("true")
    d = d[~(flag("ens_invalid") | flag("ens_outlier_v2"))].copy()
    d["day"] = d["date"].astype(str)
    ck = d["drive_type"].astype(str).str.strip().str.lower().replace({"city": "urban"})
    return d[ck.eq("urban") & d["thermal_regime"].isin(["warm", "shoulder"]) & d["gross_throughput_kwh"].notna() & d["distance_km"].gt(0)].copy()


def day_sums(g):
    return g.groupby("day")[["gross_throughput_kwh", "distance_km"]].sum().rename(columns={"gross_throughput_kwh": "num", "distance_km": "den"})


def includes_zero(ci):
    return None if ci is None else bool(ci[0] <= 0 <= ci[1])


def band_block(g, rngs):
    w, s = g[g.thermal_regime.eq("warm")], g[g.thermal_regime.eq("shoulder")]
    dw, ds = day_sums(w), day_sums(s)
    ew = 100 * w.gross_throughput_kwh.sum() / w.distance_km.sum()
    es = 100 * s.gross_throughput_kwh.sum() / s.distance_km.sum()
    out = {"estimate": round(float(es - ew), 2), "warm": {"nDrives": int(len(w)), "nDays": int(dw.shape[0])}, "shoulder": {"nDrives": int(len(s)), "nDays": int(ds.shape[0])}}
    # unit counts (ISO weeks of the union of dates; calendar span)
    u = dw.index.union(ds.index)
    wk = BB.iso_week(u)
    wk_w, wk_s = BB.iso_week(dw.index), BB.iso_week(ds.index)
    out["weeks"] = {"union": int(len(set(wk))), "warm": int(len(set(wk_w))), "shoulder": int(len(set(wk_s))), "mixed": int(len(set(wk_w) & set(wk_s)))}
    span = int((pd.to_datetime(u.max()) - pd.to_datetime(u.min())).days) + 1
    out["calendarSpanDays"] = span
    procs = {}

    def mc_se(fn):
        """Monte Carlo SD of the two interval endpoints over N_REPEATS repeats on separate streams (fn(rng) -> draws)."""
        ends = np.array([[np.percentile(fn(np.random.default_rng(100000 + 1000 * r + k)), q) for q in (2.5, 97.5)] for k, r in enumerate(range(N_REPEATS))])
        return [round(float(x), 3) for x in ends.std(axis=0, ddof=1)]

    def near_zero(ci, se):
        return bool(min(abs(ci[0]), abs(ci[1])) <= 2 * max(se))

    def rec(name, draws, drop, extra=None, few=False, fn=None):
        if few or draws is None:
            procs[name] = {"fewBlocks": True, "ci95": None, "nDraws": 0, "nDrawsDropped": 0, "includesZero": None, **(extra or {})}
            return
        if drop > BB.DROP_CAP * N_DRAWS:
            raise SystemExit("M494 STOP: %d of %d %s draws discarded (cap %.1f %%): Director decision needed" % (drop, N_DRAWS, name, BB.DROP_CAP * 100))
        ci = BB.interval(draws)
        se = mc_se(fn)
        procs[name] = {"fewBlocks": False, "ci95": ci, "nDraws": int(len(draws)), "nDrawsDropped": int(drop), "includesZero": includes_zero(ci),
                       "endpointMcSd": se, "endpointWithinMcErrorOfZero": near_zero(ci, se), **(extra or {})}

    few_w = out["weeks"]["union"] < MIN_UNITS or out["weeks"]["warm"] < MIN_COHORT_WEEKS or out["weeks"]["shoulder"] < MIN_COHORT_WEEKS
    if few_w:
        rec("W", None, 0, few=True)
        rec("WS", None, 0, few=True)
    else:
        d, ra, rb, drop, nb, *_ = BB.week_difference(dw, ds, rngs["W"], N_DRAWS)
        rec("W", d, drop, {"nBlocks": nb}, fn=lambda r: BB.week_difference(dw, ds, r, N_DRAWS)[0])
        d2, drop2, strata = BB.stratified_weeks(dw, ds, rngs["WS"], N_DRAWS)
        rec("WS", d2, drop2, {"strata": strata}, fn=lambda r: BB.stratified_weeks(dw, ds, r, N_DRAWS)[0])
    for L, key in ((7, "M7"), (14, "M14")):
        # spec A2: the span must cover at least 10 blocks and each cohort must occupy at least 5 blocks' worth (5 L) of days
        few = span < MIN_UNITS * L or int(dw.shape[0]) < MIN_COHORT_WEEKS * L or int(ds.shape[0]) < MIN_COHORT_WEEKS * L
        if few:
            rec(key, None, 0, few=True)
        else:
            d, ra, rb, drop, D, nbk = BB.circular_moving_block(dw, ds, L, rngs[key], N_DRAWS)
            rec(key, d, drop, {"L": L, "D": int(D), "blocksPerDraw": int(nbk)}, fn=lambda r, L=L: BB.circular_moving_block(dw, ds, L, r, N_DRAWS)[0])
    d1, ra1, rb1, drop1, D1, _ = BB.circular_moving_block(dw, ds, 1, rngs["M1"], N_DRAWS)
    out["referenceL1"] = {"ci95": BB.interval(d1), "nDrawsDropped": int(drop1), "note": "diagnostic only: circular blocks of length 1 over the calendar axis (empty days included), same stream construction"}
    out["procedures"] = procs
    return out


def build(dm, reg, cube):
    pop = population(dm, reg)
    rngs = {k: np.random.default_rng(v) for k, v in STREAMS.items()}
    bands = []
    cube_bands = cube["urbanContrast"]["bands"]
    for (label, lo, hi), cb in zip(BANDS, cube_bands):
        assert cb["band"] == label, (cb["band"], label)
        g = pop[(pop.distance_km >= lo) & (pop.distance_km < hi)]
        b = band_block(g, rngs)
        # hard stop: the tool's population is the cube's
        dif = cb["difference"]
        if (b["estimate"] != dif["estimate"] or b["warm"]["nDrives"] != cb["warm"]["nDrives"] or b["shoulder"]["nDrives"] != cb["shoulder"]["nDrives"]
                or b["warm"]["nDays"] != cb["warm"]["nDays"] or b["shoulder"]["nDays"] != cb["shoulder"]["nDays"]):
            raise SystemExit("M494 STOP: band %r differs from comparisonCube (estimate %r vs %r, drives %r/%r vs %r/%r)" % (label, b["estimate"], dif["estimate"], b["warm"]["nDrives"], b["shoulder"]["nDrives"], cb["warm"]["nDrives"], cb["shoulder"]["nDrives"]))
        jd = dif["ci95"]
        b["band"] = label
        b["jointDay"] = {"ci95": jd, "includesZero": includes_zero(jd), "source": "comparisonCube.urbanContrast (M491)"}
        wj = jd[1] - jd[0]
        for name, p in b["procedures"].items():
            if p["ci95"] is not None:
                p["widthRatioToJointDay"] = round((p["ci95"][1] - p["ci95"][0]) / wj, 3)
                p["widthRatioToL1"] = round((p["ci95"][1] - p["ci95"][0]) / (b["referenceL1"]["ci95"][1] - b["referenceL1"]["ci95"][0]), 3)
        have = [p for p in b["procedures"].values() if p["ci95"] is not None]
        if not have:
            b["verdict"] = "not assessable"
        elif all(p["includesZero"] == b["jointDay"]["includesZero"] for p in have):
            b["verdict"] = "unchanged"
        else:
            b["verdict"] = "depends on the resampling unit"
        bands.append(b)
    order = ["depends on the resampling unit", "not assessable", "unchanged"]
    overall = next(v for v in order if any(b["verdict"] == v for b in bands))
    return {"_provenance": "GENERATED by tools/urban_week_block.py (M494, spec analyses/M494_spec.md Rev 2); do not hand-edit. Additive block, regenerated at every ingestion after the comparison cube.",
            "methodVersion": METHOD_VERSION, "seed": SEED, "nDraws": N_DRAWS, "streams": STREAMS,
            "procedures": {"W": "ISO calendar-week blocks of the union of dates, both cohorts resampled together (multinomial weights)",
                           "WS": "weeks stratified by cohort occupancy (warm-only / shoulder-only / mixed), resampled within each stratum",
                           "M7": "overlapping moving blocks of 7 consecutive calendar days, circular", "M14": "overlapping moving blocks of 14 consecutive calendar days, circular",
                           "M1": "circular blocks of length 1 over the calendar axis (diagnostic reference)"},
            "fewBlocksRule": "interval withheld when the union has fewer than %d week units, or either cohort occupies fewer than %d weeks (moving blocks: span below 10 L, or either cohort below 5 L days)" % (MIN_UNITS, MIN_COHORT_WEEKS),
            "dropCap": "%.1f %% of the draws per band and procedure (above it the run stops)" % (BB.DROP_CAP * 100),
            "mcRule": "endpointWithinMcErrorOfZero: the interval endpoint nearest to zero lies within 2 x the larger Monte Carlo SD of the two endpoints (%d repeats on separate streams); such a reading is seed-sensitive" % N_REPEATS,
            "verdictRule": "unchanged iff every procedure with an interval has the same includes-zero reading as the joint-day interval; depends on the resampling unit if any differs; not assessable if every procedure is fewBlocks",
            "bands": bands, "overallVerdict": overall,
            "reading": ["block sensitivity across neighbouring dates; uncertainty analysis, not a change of the point estimate",
                        "thermal cohorts are ambient-threshold classes, confounded with season, date and drift; week blocks also absorb season and composition variance, not only serial dependence",
                        "the displayed interval stays the M491 joint calendar-day interval"]}


def splice(A, blk, master_md5, now=None):
    import dependence_sensitivity as DS
    new = copy.deepcopy(A)
    new["urbanContrastBlocks"] = blk
    old = (A.get("_artifactStamps") or {}).get("urbanContrastBlocks")
    if old and A.get("urbanContrastBlocks") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["urbanContrastBlocks"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["cohortSupport"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M494: derived by tools/urban_week_block.py from drive_master.csv, seasonal_drive_master.csv and the comparison cube; additive block-bootstrap sensitivity of the urban contrast", upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        st["inputBasis"] = {"nDrives": A["meta"]["totalDrives"], "masterMd5": master_md5, "source": "stamping pass: meta.totalDrives, corpusHash"}
        new["_artifactStamps"]["urbanContrastBlocks"] = st
    ch = DS._paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    reg = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "thermal_regime"]]
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw)
    blk = build(dm, reg, A["comparisonCube"])
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    if "--check" in argv:
        ok = A.get("urbanContrastBlocks") == blk
        print(json.dumps({"check": "urbanContrastBlocks", "matchesPayload": ok, "overallVerdict": blk["overallVerdict"]}))
        return 0 if ok else 1
    new, changed, bad = splice(A, blk, md5)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad, "overallVerdict": blk["overallVerdict"],
                      "bands": [{"band": b["band"], "verdict": b["verdict"], "jointDay": b["jointDay"]["ci95"], **{k: p["ci95"] for k, p in b["procedures"].items()}} for b in blk["bands"]]}, ensure_ascii=False))
    if bad:
        return 1
    if blk["overallVerdict"] == "depends on the resampling unit":
        print("M494 STOP before the splice: verdict 'depends on the resampling unit' goes to the Director")
        return 3
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
