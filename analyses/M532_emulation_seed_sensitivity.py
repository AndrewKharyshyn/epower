#!/usr/bin/env python3
"""M532 (analyses/M532_spec.md Rev 2): sensitivity of the M393 / M529 emulated-sampling result (Part C of analyses/M393_resistance_cadence.py) to the slow-pool draw and the emulation seeds.
1 control replicate (pool seed 7, seed offset 0: reproduces M529 exactly) + 10 replicates (pool seeds 11, 13, 17, 19, 23, 29, 31, 37, 41, 43; seed offset 7919*k, k = 1..10). Same data, helpers and statistics as M393 Part C
(tools/cadence_emulate.py build_pools / emulate and compute_drive_summary_v6.analyze_bytes used as libraries, unchanged). Output: analyses/M532_emulation_seed_sensitivity.json (first output kept; run-once lock).
Usage: python analyses/M532_emulation_seed_sensitivity.py [--workers 4] [--only 0,4]"""
import argparse, concurrent.futures as cf, hashlib, json, os, sys, time
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
OUT = os.path.join("analyses", "M532_emulation_seed_sensitivity.json")
STAGE = os.path.join(ROOT, "raw_only")
POOL_SEEDS = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43]      # k = 0 is the control (the M393 / M529 value)
SEED_STEP = 7919
SEEDS_PER_DRIVE = 3
FAST2_FROM = "2026-10-01"
rcol, icol = "vreg_R_pack_mohm", "vreg_I_p95_A"
_CTX = {}


def setup():
    if _CTX:
        return _CTX
    import compute_drive_summary_v6 as V
    import cadence_emulate as CE
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    reg = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
    keep = ~dm["ens_outlier_v2"].fillna(False).astype(bool)
    cc = dm[keep].dropna(subset=[rcol, "T_pack_mean_avg", icol, "date"]).copy()
    cc["regime"] = cc["file"].map(reg)
    cc["era"] = np.where(cc["regime"] == "fast", np.where(cc["date"].astype(str) >= FAST2_FROM, "fast2", "fast1"), np.where(cc["regime"] == "slow", "slow", "unknown"))
    _CTX.update(V=V, CE=CE, cc=cc, NB=V.N_BOOT)
    return _CTX


def run_replicate(k):
    C = setup(); V, CE, cc, NB = C["V"], C["CE"], C["cc"], C["NB"]
    R = POOL_SEEDS[k]
    t0 = time.time()
    fast = cc[cc["era"].isin(["fast1", "fast2"])]
    slow_files = cc[cc["era"] == "slow"]["file"].tolist()
    rs = np.random.default_rng(R)
    pool_files = [slow_files[i] for i in sorted(rs.choice(len(slow_files), size=min(40, len(slow_files)), replace=False))]
    pools = CE.build_pools([os.path.join(STAGE, f) for f in pool_files])
    emu = {}
    for n, f in enumerate(fast["file"].tolist()):
        vals = []
        data = open(os.path.join(STAGE, f), "rb").read()
        for s in range(SEEDS_PER_DRIVE):
            rng = np.random.default_rng(s * 100003 + n + SEED_STEP * k)
            b, rep = CE.emulate(data, pools, rng)
            row = V.analyze_bytes(b, f)
            vals.append(row.get(rcol))
        v = [x for x in vals if x is not None and x == x]
        emu[f] = float(np.mean(v)) if v else float("nan")
    fast = fast.assign(R_emu=fast["file"].map(emu))
    fast_all = fast.copy()
    fast = fast[np.isfinite(fast["R_emu"])]
    fast = fast.assign(diff=fast["R_emu"] - fast[rcol])
    res = {"k": k, "poolSeed": R, "seedOffset": SEED_STEP * k, "nFastClean": int(len(fast_all)), "nKept": int(len(fast)), "nLose": int(len(fast_all) - len(fast)),
           "loseByEra": {e: int((g["R_emu"].isna()).sum()) for e, g in fast_all.groupby("era")}, "poolFiles": pool_files,
           "loseSet": sorted(fast_all[fast_all["R_emu"].isna()]["file"].tolist()), "perDriveDiff": {f: float(d) for f, d in zip(fast["file"], fast["diff"])}, "paired": {}}
    for era, g in fast.groupby("era"):
        dd = g.groupby(g["date"].astype(str))["diff"].mean(); rng = np.random.default_rng(42)
        bs = [dd.values[rng.integers(0, len(dd), len(dd))].mean() for _ in range(NB)]
        res["paired"][era] = {"n": int(len(g)), "nDays": int(len(dd)), "mean": round(float(g["diff"].mean()), 3), "median": round(float(g["diff"].median()), 3),
                              "ci95": [round(float(x), 3) for x in np.percentile(bs, [2.5, 97.5])], "originalMean": round(float(g[rcol].mean()), 2), "meanUnrounded": float(g["diff"].mean())}
    res["seconds"] = round(time.time() - t0)
    return res


def raw_listing_md5():
    h = hashlib.md5()
    for f in sorted(os.listdir(STAGE)):
        h.update((f + ":" + str(os.path.getsize(os.path.join(STAGE, f)))).encode())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--only", default=""); a = ap.parse_args()
    if os.path.exists(OUT) and not a.only:
        print("run-once lock: " + OUT + " exists"); return 1
    master0 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(); raw0 = raw_listing_md5()
    ks = [int(x) for x in a.only.split(",")] if a.only else list(range(len(POOL_SEEDS)))
    out = {"spec": "analyses/M532_spec.md", "specSha256": hashlib.sha256(open("analyses/M532_spec.md", "rb").read()).hexdigest(), "numpy": np.__version__, "pandas": pd.__version__,
           "masterMd5Before": master0, "stagedRawListingMd5Before": raw0, "poolSeeds": POOL_SEEDS, "seedStep": SEED_STEP, "seedsPerDrive": SEEDS_PER_DRIVE}
    t0 = time.time(); reps = {}
    with cf.ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_replicate, k): k for k in ks}
        for f in cf.as_completed(futs):
            k = futs[f]
            try:
                reps[k] = f.result(); print("replicate", k, "done in", reps[k]["seconds"], "s", flush=True)
            except Exception as e:                                   # a replicate that errors is reported, not dropped
                reps[k] = {"k": k, "error": repr(e)[:300]}; print("replicate", k, "ERROR", repr(e)[:200], flush=True)
    out["replicates"] = [reps[k] for k in sorted(reps)]
    out["wallSeconds"] = round(time.time() - t0)
    out["masterMd5After"] = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(); out["stagedRawListingMd5After"] = raw_listing_md5()
    out["unchangedInputs"] = bool(master0 == out["masterMd5After"] and raw0 == out["stagedRawListingMd5After"])
    ok = [r for r in out["replicates"] if "error" not in r]
    if a.only:
        json.dump(out, open(os.path.join("analyses", "M532_partial_%s.json" % a.only.replace(",", "_")), "w", encoding="utf-8", newline="\n"), indent=1); return 0
    # A1: control equality with the stored M529 result (stored precision) - STOP on mismatch
    S = json.load(open(os.path.join("analyses", "M529_resistance_cadence.json"), encoding="utf-8"))["C_emulation"]
    c0 = next((r for r in ok if r["k"] == 0), None)
    ctrl = {"present": c0 is not None}
    if c0:
        ctrl.update(nFastClean=c0["nFastClean"] == S["n_fast_clean"], nKept=c0["nKept"] == S["n_fast_clean_emulated"], loseByEra=c0["loseByEra"] == S["lose_proxy_by_era"],
                    eras={e: {k2: (c0["paired"][e][k2] == S["paired_diff_" + e][k1]) for k1, k2 in (("n", "n"), ("n_days", "nDays"), ("mean_emulated_minus_original_mohm", "mean"), ("median", "median"), ("ci95_day_clustered", "ci95"), ("original_mean", "originalMean"))} for e in ("fast1", "fast2")})
        ctrl["passed"] = bool(ctrl["nFastClean"] and ctrl["nKept"] and ctrl["loseByEra"] and all(all(v.values()) for v in ctrl["eras"].values()))
    out["control"] = ctrl
    out["controlPassed"] = bool(ctrl.get("passed"))
    # summary (descriptive; the range is not an interval)
    summ = {}
    for e in ("fast1", "fast2"):
        m = [r["paired"][e]["meanUnrounded"] for r in ok]; lo = [r["paired"][e]["ci95"][0] for r in ok]; hi = [r["paired"][e]["ci95"][1] for r in ok]
        ref = S["paired_diff_" + e]; hw = (ref["ci95_day_clustered"][1] - ref["ci95_day_clustered"][0]) / 2
        summ[e] = {"meanRange": [round(min(m), 3), round(max(m), 3)], "meanRangeWidth": round(max(m) - min(m), 3), "meanSdDescriptive": round(float(np.std(m, ddof=1)), 3), "ciLoRange": [min(lo), max(lo)], "ciHiRange": [min(hi), max(hi)],
                   "m529Interval": ref["ci95_day_clustered"], "m529HalfWidth": round(hw, 3), "nRange": [min(r["paired"][e]["n"] for r in ok), max(r["paired"][e]["n"] for r in ok)],
                   "loseRange": [min(r["loseByEra"][e] for r in ok), max(r["loseByEra"][e] for r in ok)]}
    # common support: the drives that keep the proxy in EVERY replicate
    common = set.intersection(*[set(r["perDriveDiff"]) for r in ok]) if ok else set()
    era_of = setup()["cc"].set_index("file")["era"].to_dict()
    cs_means = {e: [round(float(np.mean([r["perDriveDiff"][f] for f in common if era_of[f] == e])), 3) for r in ok] for e in ("fast1", "fast2")}
    summ["commonSupport"] = {"nDrives": len(common), "nByEra": {e: sum(1 for f in common if era_of[f] == e) for e in ("fast1", "fast2")}, "meanByReplicate": cs_means,
                             "meanRangeByEra": {e: [min(v), max(v)] for e, v in cs_means.items()}}
    ctl = set(c0["loseSet"]) if c0 else set()
    summ["loseSetJaccardVsControl"] = {str(r["k"]): round(len(set(r["loseSet"]) & ctl) / max(1, len(set(r["loseSet"]) | ctl)), 3) for r in ok}
    tw = {"eraMeanOutsideM529Interval": {}, "eraIntervalIncludesZero": {}, "eraMeanSignChange": {}, "totalLoseDiffersFrom29By>5": [], "eraLoseDiffersBy>3": {}, "meanRangeOverHalfM529HalfWidth": {}}
    for e in ("fast1", "fast2"):
        ref = S["paired_diff_" + e]; lo0, hi0 = ref["ci95_day_clustered"]
        tw["eraMeanOutsideM529Interval"][e] = [r["k"] for r in ok if not (lo0 <= r["paired"][e]["meanUnrounded"] <= hi0)]
        tw["eraIntervalIncludesZero"][e] = [r["k"] for r in ok if r["paired"][e]["ci95"][0] <= 0 <= r["paired"][e]["ci95"][1]]
        tw["eraMeanSignChange"][e] = [r["k"] for r in ok if (r["paired"][e]["meanUnrounded"] > 0) != (ref["mean_emulated_minus_original_mohm"] > 0)]
        tw["eraLoseDiffersBy>3"][e] = [r["k"] for r in ok if abs(r["loseByEra"][e] - S["lose_proxy_by_era"][e]) > 3]
        tw["meanRangeOverHalfM529HalfWidth"][e] = bool(summ[e]["meanRangeWidth"] > 0.5 * summ[e]["m529HalfWidth"])
    tw["totalLoseDiffersFrom29By>5"] = [r["k"] for r in ok if abs(r["nLose"] - S["n_fast_lose_proxy_at_slow_sampling"]) > 5]
    out["summary"] = summ; out["tripwires"] = tw
    out["errors"] = [r for r in out["replicates"] if "error" in r]
    json.dump(out, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1)
    print(json.dumps({"controlPassed": out["controlPassed"], "unchangedInputs": out["unchangedInputs"], "summary": {e: summ[e] for e in ("fast1", "fast2")}, "tripwires": tw}, default=float)[:3000])
    return 0 if out["controlPassed"] and out["unchangedInputs"] and not out["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
