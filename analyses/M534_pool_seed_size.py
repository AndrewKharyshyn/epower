#!/usr/bin/env python3
"""M534 (analyses/M534_spec.md Rev 2): which Monte Carlo choice produces the spread of the M393 / M529 / M532 emulated-sampling result: the slow-pool draw (arm P), the emulation seeds (arm S) or the pool size (arm N).
Same data, helpers (tools/cadence_emulate.py build_pools / emulate, compute_drive_summary_v6.analyze_bytes, unchanged) and statistics as analyses/M532_emulation_seed_sensitivity.py (untouched).
Output: analyses/M534_pool_seed_size.json (first output kept; run-once lock). Usage: python analyses/M534_pool_seed_size.py [--workers 4] [--only P_R7_k0,S_R7_k6]"""
import argparse, concurrent.futures as cf, hashlib, json, os, sys, time
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
OUT = os.path.join("analyses", "M534_pool_seed_size.json")
STAGE = os.path.join(ROOT, "raw_only")
SEED_STEP = 7919
SEEDS_PER_DRIVE = 3
FAST2_FROM = "2026-10-01"
rcol, icol = "vreg_R_pack_mohm", "vreg_I_p95_A"
P_SEEDS = [11, 13, 17, 19, 23, 29, 31, 37, 41, 43]              # arm P: pool seeds, offset k = 0, size 40
S_KS = list(range(1, 11))                                         # arm S: pool seed 7, offsets 7919*k
N_SIZES = (20, 80); N_SEEDS = [7, 11, 13, 17, 19]                 # arm N: sizes 20 / 80, offset k = 0
N40_SEEDS = [11, 13, 17, 19]                                      # determinism check: size 40 equals arm P for the same R
_CTX = {}


def specs():
    """replicate id -> (arm, pool seed R, offset index k, pool size)"""
    d = {"P_R7_k0": ("P", 7, 0, 40)}                              # control = the M529 draw
    for R in P_SEEDS:
        d["P_R%d_k0" % R] = ("P", R, 0, 40)
    for k in S_KS:
        d["S_R7_k%d" % k] = ("S", 7, k, 40)
    for R in N_SEEDS:
        for sz in N_SIZES:
            d["N%d_R%d_k0" % (sz, R)] = ("N", R, 0, sz)
    for R in N40_SEEDS:
        d["N40_R%d_k0" % R] = ("N", R, 0, 40)
    return d


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


def pool_for(slow_files, R, size):
    rs = np.random.default_rng(R)
    return [slow_files[i] for i in sorted(rs.choice(len(slow_files), size=min(size, len(slow_files)), replace=False))]


def run_replicate(rid):
    """checkpointed (infrastructure only, added after two interrupted runs): a finished replicate is stored in analyses/M534_replicates/<id>.json and reused on a restart"""
    cp = os.path.join(ROOT, "analyses", "M534_replicates", rid + ".json")
    if os.path.exists(cp):
        return json.load(open(cp, encoding="utf-8"))
    res = _run_replicate(rid)
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    json.dump(res, open(cp, "w", encoding="utf-8", newline=chr(10)))
    return res


def _run_replicate(rid):
    C = setup(); V, CE, cc, NB = C["V"], C["CE"], C["cc"], C["NB"]
    arm, R, k, size = specs()[rid]
    t0 = time.time()
    fast = cc[cc["era"].isin(["fast1", "fast2"])]
    slow_files = cc[cc["era"] == "slow"]["file"].tolist()
    pool_files = pool_for(slow_files, R, size)
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
    res = {"id": rid, "arm": arm, "poolSeed": R, "k": k, "seedOffset": SEED_STEP * k, "poolSize": size, "nSlowEligible": len(slow_files), "nFastClean": int(len(fast_all)), "nKept": int(len(fast)),
           "nLose": int(len(fast_all) - len(fast)), "loseByEra": {e: int((g["R_emu"].isna()).sum()) for e, g in fast_all.groupby("era")}, "poolFiles": pool_files,
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


def nesting():
    """whether the size 20 / 40 / 80 pools for the same R are nested (recorded, not assumed)"""
    cc = setup()["cc"]; slow = cc[cc["era"] == "slow"]["file"].tolist(); out = {}
    for R in N_SEEDS:
        p = {sz: set(pool_for(slow, R, sz)) for sz in (20, 40, 80)}
        out[str(R)] = {"20in40": p[20] <= p[40], "40in80": p[40] <= p[80], "20in80": p[20] <= p[80]}
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--only", default=""); a = ap.parse_args()
    if os.path.exists(OUT) and not a.only:
        print("run-once lock: " + OUT + " exists"); return 1
    master0 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(); raw0 = raw_listing_md5()
    ids = a.only.split(",") if a.only else list(specs())
    out = {"spec": "analyses/M534_spec.md", "specSha256": hashlib.sha256(open("analyses/M534_spec.md", "rb").read()).hexdigest(), "numpy": np.__version__, "pandas": pd.__version__,
           "masterMd5Before": master0, "stagedRawListingMd5Before": raw0, "seedStep": SEED_STEP, "seedsPerDrive": SEEDS_PER_DRIVE, "specs": {k: list(v) for k, v in specs().items() if k in ids}}
    t0 = time.time(); reps = {}
    with cf.ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_replicate, i): i for i in ids}
        for f in cf.as_completed(futs):
            i = futs[f]
            try:
                reps[i] = f.result(); print("replicate", i, "done in", reps[i]["seconds"], "s", flush=True)
            except Exception as e:                                   # a replicate that errors is reported, not dropped
                reps[i] = {"id": i, "error": repr(e)[:300]}; print("replicate", i, "ERROR", repr(e)[:200], flush=True)
    out["replicates"] = [reps[i] for i in ids]
    out["wallSeconds"] = round(time.time() - t0)
    out["masterMd5After"] = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(); out["stagedRawListingMd5After"] = raw_listing_md5()
    out["unchangedInputs"] = bool(master0 == out["masterMd5After"] and raw0 == out["stagedRawListingMd5After"])
    ok = [r for r in out["replicates"] if "error" not in r]
    if a.only:
        json.dump(out, open(os.path.join("analyses", "M534_partial_%s.json" % a.only.replace(",", "_")), "w", encoding="utf-8", newline="\n"), indent=1); return 0
    # A1: control equality with the stored M529 result (stored precision) - STOP on mismatch
    S = json.load(open(os.path.join("analyses", "M529_resistance_cadence.json"), encoding="utf-8"))["C_emulation"]
    M32 = json.load(open(os.path.join("analyses", "M532_emulation_seed_sensitivity.json"), encoding="utf-8"))
    c0 = next((r for r in ok if r["id"] == "P_R7_k0"), None)
    ctrl = {"present": c0 is not None}
    if c0:
        ctrl.update(nFastClean=c0["nFastClean"] == S["n_fast_clean"], nKept=c0["nKept"] == S["n_fast_clean_emulated"], loseByEra=c0["loseByEra"] == S["lose_proxy_by_era"],
                    loseSetEqualsM532Control=c0["loseSet"] == M32["replicates"][0]["loseSet"],
                    eras={e: {k2: (c0["paired"][e][k2] == S["paired_diff_" + e][k1]) for k1, k2 in (("n", "n"), ("n_days", "nDays"), ("mean_emulated_minus_original_mohm", "mean"), ("median", "median"), ("ci95_day_clustered", "ci95"), ("original_mean", "originalMean"))} for e in ("fast1", "fast2")})
        ctrl["passed"] = bool(ctrl["nFastClean"] and ctrl["nKept"] and ctrl["loseByEra"] and ctrl["loseSetEqualsM532Control"] and all(all(v.values()) for v in ctrl["eras"].values()))
    out["control"] = ctrl
    out["controlPassed"] = bool(ctrl.get("passed"))
    # arm summaries (descriptive; ranges are not intervals). Arms P and S include the control (11 replicates each, as in M532).
    by = {r["id"]: r for r in ok}
    arms = {"P": [r for r in ok if r["arm"] == "P"], "S": [r for r in ok if r["arm"] == "S"] + ([c0] if c0 else []),
            "N20": [r for r in ok if r["arm"] == "N" and r["poolSize"] == 20], "N40": [by[i] for i in sorted(by) if i.startswith("N40_")], "N80": [r for r in ok if r["arm"] == "N" and r["poolSize"] == 80]}
    summ = {}
    for name, rs in arms.items():
        summ[name] = {"nReplicates": len(rs)}
        for e in ("fast1", "fast2"):
            m = [r["paired"][e]["meanUnrounded"] for r in rs]
            summ[name][e] = {"meanRange": [round(min(m), 3), round(max(m), 3)], "meanSd": round(float(np.std(m, ddof=1)), 3) if len(m) > 1 else None, "nRange": [min(r["paired"][e]["n"] for r in rs), max(r["paired"][e]["n"] for r in rs)],
                             "loseRange": [min(r["loseByEra"][e] for r in rs), max(r["loseByEra"][e] for r in rs)], "intervalIncludesZero": [r["id"] for r in rs if r["paired"][e]["ci95"][0] <= 0 <= r["paired"][e]["ci95"][1]]}
    att = {}
    for e in ("fast1", "fast2"):
        sp, ss = summ["P"][e]["meanSd"], summ["S"][e]["meanSd"]
        att[e] = {"sdP": sp, "sdS": ss, "ratioPS": round(sp / ss, 3) if ss else None, "sqrtSumSquares": round(float(np.hypot(sp, ss)), 3), "m532CoupledSd": M32["summary"][e]["meanSdDescriptive"],
                  "notAttributable": bool(ss and 0.5 <= sp / ss <= 2.0)}
    summ["attribution"] = att
    # determinism check: arm N size 40 equals arm P for the same R
    det = {}
    for R in N40_SEEDS:
        a_, b_ = by.get("N40_R%d_k0" % R), by.get("P_R%d_k0" % R)
        det[str(R)] = bool(a_ and b_ and a_["perDriveDiff"] == b_["perDriveDiff"] and a_["loseSet"] == b_["loseSet"] and a_["poolFiles"] == b_["poolFiles"])
    summ["determinismN40EqualsP"] = det
    summ["nesting"] = nesting()
    summ["nSlowEligible"] = ok[0]["nSlowEligible"] if ok else None
    # tripwires
    lo32 = {e: M32["summary"][e]["meanRange"] for e in ("fast1", "fast2")}
    tw = {"eraMeanOutsideM532Range": {}, "eraMeanSignChange": {}, "armNloseMoreThan3FromM529": [], "eraIntervalIncludesZeroByArm": {}, "ratioPSwithin0.5to2": {e: att[e]["notAttributable"] for e in att}}
    for e in ("fast1", "fast2"):
        ref = S["paired_diff_" + e]
        tw["eraMeanOutsideM532Range"][e] = [r["id"] for r in ok if not (lo32[e][0] <= r["paired"][e]["meanUnrounded"] <= lo32[e][1])]
        tw["eraMeanSignChange"][e] = [r["id"] for r in ok if (r["paired"][e]["meanUnrounded"] > 0) != (ref["mean_emulated_minus_original_mohm"] > 0)]
        tw["armNloseMoreThan3FromM529"] += [r["id"] for r in ok if r["arm"] == "N" and abs(r["loseByEra"][e] - S["lose_proxy_by_era"][e]) > 3]
        tw["eraIntervalIncludesZeroByArm"][e] = {n: summ[n][e]["intervalIncludesZero"] for n in arms}
    out["summary"] = summ; out["tripwires"] = tw
    out["errors"] = [r for r in out["replicates"] if "error" in r]
    json.dump(out, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1)
    print(json.dumps({"controlPassed": out["controlPassed"], "unchangedInputs": out["unchangedInputs"], "attribution": att, "tripwires": tw}, default=float)[:3000])
    return 0 if out["controlPassed"] and out["unchangedInputs"] and not out["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
