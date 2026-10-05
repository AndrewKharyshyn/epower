#!/usr/bin/env python3
"""M373 point runner (analyses/M373_spec.md Rev 2, frozen; spec sha256 recorded in the output). Runs the three PUBLISHED producers' own functions (sensitivity_gtr, simultaneity_gtr,
speed_split; no producer is modified) on one basis and writes analyses/M373_<point>_blocks.json (never the root *_out.json files, never anything published).
  --point O : current set on the originals (XT_RAW_DIR = raw_only/, sha256-verified originals)
  --point R : current set on the FORMER per-sample raw (333 archived re-exports staged outside the repo by tools/m373_stage_former.py; current master)
Gates (frozen): drive_master MD5 before/after; sensitivity BASE == target (O: live payload headline; R: the pre-M366 headline from git 3845725, recorded); speedSplit validation
n_matched == n_checked against the point's fuel_recon_master (O: repo file; R: git 3845725 version); simultaneity identity < 1e-6 kWh and partition 100 % +-0.2;
ONE frozen drive-ID list (written by O, asserted equal by R). Also: deadband grid (analysis only), R_cut (sensitivity on the date-cutoff set 2026-09-16, basis R only).
Usage: python tools/m373_point.py --point O|R"""
import argparse, hashlib, json, os, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
ap = argparse.ArgumentParser()
ap.add_argument("--point", required=True, choices=["O", "R"])
ap.add_argument("--tag", default="M373", help="output / spec prefix (M375 re-runs the blocks on the canonical-clean set)")
a = ap.parse_args()
P = a.point
TAG = a.tag
STAGE = json.load(open("analyses/M373_stage_former.json", encoding="utf-8"))["dest"] if P == "R" else None     # M377b: point O needs no staged former basis
RAWDIR = os.path.join(ROOT, "raw_only") if P == "O" else STAGE
os.environ["XT_RAW_DIR"] = RAWDIR.replace("\\", "/")          # BEFORE the imports below (recon_engine.BASE is read at import)
sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import recon_engine as RE, fuel_recon as FR
import sensitivity_gtr as SG, simultaneity_gtr as SM, speed_split as SS

sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
git = lambda *c: subprocess.run(["git", *c], capture_output=True, text=True, cwd=ROOT).stdout
import m377_pin
MASTER_MD5 = m377_pin.master_pin(TAG, os.path.join(ROOT, "drive_master.csv"))     # M377b: frozen hash for the historical tags M373 / M375; later tags pin the live master at start (asserted unchanged at the end)
EPS = (0.25, 0.5, 1.0)
CUT = "2026-09-16"
PRE_M366 = "3845725"
t0 = time.time()
assert md5(os.path.join(ROOT, "drive_master.csv")) == MASTER_MD5 and md5(RE.BASE + "drive_master.csv") == MASTER_MD5, "drive_master.csv MD5"
dm = pd.read_csv(RE.BASE + "drive_master.csv")
date_of = dict(zip(dm["file"], dm["date"].astype(str)))
meta = {"point": P, "rawDir": RAWDIR, "specSha256": sha(f"analyses/{TAG}_spec.md"), "tag": TAG, "gitHead": git("rev-parse", "--short", "HEAD").strip(),
        "scriptSha256": {f: sha(f)[:16] for f in ("tools/m373_point.py", "sensitivity_gtr.py", "simultaneity_gtr.py", "speed_split.py", "recon_engine.py", "fuel_recon.py", "model_constants.py")},
        "driveMasterMd5Before": MASTER_MD5, "stage": json.load(open("analyses/M373_stage_former.json", encoding="utf-8")) if P == "R" else None}

# ---- targets for the gates ----
if P == "O":
    target = dict(SG.SHIPPED)
    target_src = "live payload corpus (summary_arrays.json generatorTractionRecon.corpus)"
    fr_master = pd.read_csv("fuel_recon_master.csv")
    fr_src = "repo fuel_recon_master.csv sha256 " + sha("fuel_recon_master.csv")[:16]
else:
    c = json.loads(git("show", f"{PRE_M366}:summary_arrays.json"))["generatorTractionRecon"]["corpus"]
    target = dict(gen100=c["generator"], trac100=c["tractionGross"], fgen=c["fGen"], etaBus=c["etaBus"])
    target_src = f"pre-M366 headline from git {PRE_M366}:summary_arrays.json"
    txt = git("show", f"{PRE_M366}:fuel_recon_master.csv")
    fp = os.path.join(os.path.dirname(STAGE), "xtrail-m373-former", "fuel_recon_master_pre_M366.csv")
    open(fp, "w", encoding="utf-8", newline="").write(txt)
    fr_master = pd.read_csv(fp)
    if TAG != "M373":      # M375 Rev 4: the R target is the pre-M366 headline under the SAME canonical-clean definition (same aggregation, pre-M366 fuel_recon_master rows)
        import wire_gtr_seasonal as W
        _c = W.aggregate(W.load_merged(fuel_path=fp), "All", 489)["corpus"]
        target = dict(gen100=_c["generator"], trac100=_c["tractionGross"], fgen=_c["fGen"], etaBus=_c["etaBus"])
        target_src += " recomputed under the canonical-clean definition (wire_gtr_seasonal.aggregate on the pre-M366 fuel_recon_master rows; M375 Rev 4)"
    fr_src = f"git {PRE_M366}:fuel_recon_master.csv sha256 " + sha(fp)[:16]
meta["sensitivityTarget"] = {"value": target, "source": target_src}
meta["fuelReconMasterForValidation"] = fr_src

# ---- simultaneity (also yields the clean-ID list and the deadband grid) ----
cache = SM.build_cache()
clean = sorted(e["file"] for e in cache if e["fgen"] == e["fgen"])
ids_all = sorted(e["file"] for e in cache)
idf = f"analyses/{TAG}_driveids.json"
if P == "O":
    json.dump({"all": ids_all, "clean": clean}, open(idf, "w", encoding="utf-8", newline="\n"), indent=1)
else:
    fz = json.load(open(idf, encoding="utf-8"))
    nanR = sorted(set(fz["clean"]) - set(clean)); nanO = sorted(set(clean) - set(fz["clean"]))
    assert ids_all == fz["all"], "drive-ID list differs from the frozen O list"
    meta["nanOnOneBasisOnly"] = {"cleanOnOnly": sorted(nanO), "cleanOnROnly": nanR}
meta["eligibility"] = {"rule": "canonical-clean (ens_outlier_v2 / ens_invalid explicit True excluded; eligibility.py)", "nCacheDrives": len(ids_all)}
meta["driveIds"] = {"nAll": len(ids_all), "nClean": len(clean), "nDaysClean": len({date_of[f] for f in clean}), "idsSha256": hashlib.sha256(",".join(clean).encode()).hexdigest()[:16]}
rows = SM.classify(cache)
for r in rows:
    assert abs(r["genPlusBattDischarge"] + r["chargesAndDrives"] + r["genAloneNeutral"] + r["fullyBanked"] - 100.0) < 0.2, "partition"
dead = {}
for et in EPS:
    for eb in EPS:
        rr = SM.classify(cache, et, eb)
        acc = {}
        for e in cache:
            if not (e["fgen"] == e["fgen"]) or e["drive_type"] not in SM.CLASS_ORDER:
                continue
            eon = e["Pgen_t"] > 0
            if not eon.any():
                continue
            d = acc.setdefault(e["drive_type"], {"eon": 0.0, "band_ptrac": 0.0, "band_pbatt": 0.0})
            d["eon"] += float(e["dt"][eon].sum()); d["band_ptrac"] += float(e["dt"][eon & (np.abs(e["Ptrac"]) <= et)].sum()); d["band_pbatt"] += float(e["dt"][eon & (np.abs(e["Pbatt"]) <= eb)].sum())
        dead[f"{et}_{eb}"] = {"rows": rr, "bandShareEngineOn": {k: {"absPtracLEeps": round(v["band_ptrac"] / v["eon"], 4), "absPbattLEeps": round(v["band_pbatt"] / v["eon"], 4)} for k, v in acc.items()}}
simult = {"rows": rows, "params": {"epsTracKw": SM.EPS_TRAC, "epsBattKw": SM.EPS_BATT}, "nDrives": meta["driveIds"]["nClean"], "nDays": meta["driveIds"]["nDaysClean"]}
print("simultaneity done", round(time.time() - t0), "s", flush=True)

# ---- sensitivity (the published script's own loop; BASE gate against the point's target) ----
scache = SG.build_cache()
sens, rcut = [], None
for label, mutate, scen in SG.AXES:
    rs = mutate()
    try:
        r = SG.run_axis(scache, scen)
    finally:
        for fn in rs:
            fn()
    sens.append({"axis": label, "gen100": r["gen100"], "trac100": r["trac100"], "fgen": r["fgen"], "etaBus": r["etaBus"], "nClean": r["nClean"]})
base = sens[0]
mism = [k for k, v in target.items() if not (base[k] == base[k]) or abs(base[k] - v) > 1e-9]
meta["sensitivityBaseGate"] = {"target": target, "base": {k: base[k] for k in target}, "passed": not mism, "nClean": base["nClean"], "equalsSimultaneityCleanN": base["nClean"] == len(clean)}
if mism:
    json.dump({"meta": meta, "failed": "sensitivity BASE gate", "mismatch": mism}, open(f"analyses/{TAG}_{P}_blocks.json", "w"), indent=1)
    sys.exit("sensitivity BASE does not reproduce its target: %s" % mism)
if P == "R":
    sub = [e for e in scache if date_of[e["file"]] <= CUT]
    rc = []
    for label, mutate, scen in SG.AXES:
        rs = mutate()
        try:
            r = SG.run_axis(sub, scen)
        finally:
            for fn in rs:
                fn()
        rc.append({"axis": label, "gen100": r["gen100"], "trac100": r["trac100"], "fgen": r["fgen"], "etaBus": r["etaBus"], "nClean": r["nClean"]})
    rcut = {"cutoff": CUT, "nFuel": len(sub), "nClean": rc[0]["nClean"], "partialStepA": "date-cutoff reconstruction; published M279 basis was 181 fuel / 180 clean; matches only if nClean == 180 (fuel n differs by design)", "axes": rc}


def _axis_unrounded(cache_, scen):     # same aggregation as sensitivity_gtr.run_axis WITHOUT the final rounding (analysis only; the Director asked for unrounded O-minus-R deltas)
    recs = []
    for e in cache_:
        ce = RE.central_estimate_v2(RE.precompute(SG._slim_g(e)), e["mrow"], scen)
        if ce is None:
            continue
        dist = e["dist"]
        recs.append(dict(distance_km=dist, generator_kWh_100=ce["E_gen"] / dist * 100.0, traction_gross_kWh_100=ce["E_trac_gross"] / dist * 100.0, gen_to_traction_kWh_100=ce["E_gen_to_trac"] / dist * 100.0, eta_fuel_bus=ce["eta_fuel_bus"], f_gen=ce["f_gen"]))
    cl = pd.DataFrame(recs)
    cl = cl[cl["f_gen"].notna()]
    return dict(gen100=float(SG._wavg(cl, "generator_kWh_100")), trac100=float(SG._wavg(cl, "traction_gross_kWh_100")), fgen=float((cl["gen_to_traction_kWh_100"] * cl["distance_km"]).sum() / (cl["traction_gross_kWh_100"] * cl["distance_km"]).sum()), etaBus=float(SG._wavg(cl, "eta_fuel_bus")))


sens_unr = []
for label, mutate, scen in SG.AXES:
    rs = mutate()
    try:
        sens_unr.append({"axis": label, **_axis_unrounded(scache, scen)})
    finally:
        for fn in rs:
            fn()
print("sensitivity done", round(time.time() - t0), "s", flush=True)

# ---- speedSplit (the published script's validation + builder, on this point's fuel_recon_master) ----
const = FR.corpus_offset(dm)[0]
offsets = {f: FR.resolve_offset({"I_offset_A_applied": v}, const)[0] for f, v in zip(dm["file"], dm["I_offset_A_applied"])}
targets = [f for f in dm["file"] if os.path.exists(RE.BASE + f) and FR._has_fuel(RE.BASE + f)]
meta["nFuelInstrumentedRows"] = len(targets)
targets = SS.canonical_targets(dm, targets, fr_master)       # M375: the speed-split mask is the canonical-clean reconstructed set (pinned in speed_split.py)
n_checked, n_matched, max_diff = SS.validate_against_master(dm, fr_master, targets, offsets)
meta["speedSplitValidation"] = {"nChecked": n_checked, "nMatched": n_matched, "maxAbsDiffKwh100km": max_diff, "passed": n_matched == n_checked}
if n_matched != n_checked:
    json.dump({"meta": meta, "failed": "speedSplit validation"}, open(f"analyses/{TAG}_{P}_blocks.json", "w"), indent=1)
    sys.exit("speedSplit validation failed")
split = SS.build_speed_split(dm, fr_master, targets, offsets)
in_master = [f for f in targets if f in set(fr_master["file"])]
speed = {"bins": split, "nDrives": len(in_master), "nDays": len({date_of[f] for f in in_master})}
print("speedSplit done", round(time.time() - t0), "s", flush=True)

meta["driveMasterMd5After"] = md5(os.path.join(ROOT, "drive_master.csv"))
assert meta["driveMasterMd5After"] == MASTER_MD5
meta["runtimeS"] = round(time.time() - t0)
out = {"meta": meta, "sensitivity": {"axesUnrounded": sens_unr, "axes": sens, "nDrives": meta["driveIds"]["nClean"], "nDays": meta["driveIds"]["nDaysClean"]}, "simultaneity": simult, "speedSplit": speed, "deadband": dead}
if rcut:
    out["sensitivityRcut"] = rcut
with open(f"analyses/{TAG}_{P}_blocks.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(out, f, indent=1, ensure_ascii=False, default=float)
    f.write("\n")
print("wrote analyses/%s_%s_blocks.json" % (TAG, P))
