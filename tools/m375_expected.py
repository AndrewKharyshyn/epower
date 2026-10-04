#!/usr/bin/env python3
"""M375 (analyses/M375_spec.md Rev 2): EXACT expected effect of removing the two canonical-outlier drives from the three P2 blocks, computed BEFORE any producer is changed.
Runs the CURRENT, unmodified producers' own functions (sensitivity_gtr, simultaneity_gtr, speed_split) on the O basis (raw_only/, sha256-verified originals) over the full set and over the set
without the excluded drives; writes analyses/M375_expected.json (full, without, delta; sensitivity also unrounded). The build's final run must reproduce the 'without' values.
Usage: python tools/m375_expected.py   (writes nothing else; run it on an UNMODIFIED tree)"""
import hashlib, json, os, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
os.environ["XT_RAW_DIR"] = os.path.join(ROOT, "raw_only").replace("\\", "/")
sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import recon_engine as RE, fuel_recon as FR
import sensitivity_gtr as SG, simultaneity_gtr as SM, speed_split as SS

EXCL = ["20260513_182950.csv", "20260813_144601.csv"]
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
t0 = time.time()
tree = subprocess.run(["git", "status", "--porcelain", "--", "sensitivity_gtr.py", "simultaneity_gtr.py", "speed_split.py", "wire_gtr_seasonal.py", "refresh_gtr_headline.py"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
assert tree == "", "producers must be UNMODIFIED when the expected deltas are computed: " + tree
dm = pd.read_csv(RE.BASE + "drive_master.csv")
out = {"excluded": EXCL, "specSha256": sha("analyses/M375_spec.md"), "producerSha256": {f: sha(f)[:16] for f in ("sensitivity_gtr.py", "simultaneity_gtr.py", "speed_split.py")}, "gitHead": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()}

# ---- simultaneity ----
cache = SM.build_cache()
wo = [e for e in cache if e["file"] not in EXCL]
out["simultaneity"] = {"full": SM.classify(cache), "without": SM.classify(wo), "excludedInCache": [e["file"] for e in cache if e["file"] in EXCL]}
secs = {}
for e in cache:
    if e["file"] in EXCL:
        eon = e["Pgen_t"] > 0
        secs[e["file"]] = {"drive_type": e["drive_type"], "fgenIsNaN": bool(e["fgen"] != e["fgen"]), "engineOnSeconds": round(float(e["dt"][eon].sum()), 1)}
out["simultaneity"]["excludedDrives"] = secs
print("simultaneity done", round(time.time() - t0), "s", flush=True)

# ---- sensitivity (rounded via the published run_axis; unrounded by the same aggregation without the final rounding) ----
scache = SG.build_cache()
swo = [e for e in scache if e["file"] not in EXCL]


def unrounded(c, scen):
    recs = []
    for e in c:
        ce = RE.central_estimate_v2(RE.precompute(SG._slim_g(e)), e["mrow"], scen)
        if ce is None:
            continue
        d = e["dist"]
        recs.append(dict(distance_km=d, generator_kWh_100=ce["E_gen"] / d * 100.0, traction_gross_kWh_100=ce["E_trac_gross"] / d * 100.0, gen_to_traction_kWh_100=ce["E_gen_to_trac"] / d * 100.0, eta_fuel_bus=ce["eta_fuel_bus"], f_gen=ce["f_gen"]))
    cl = pd.DataFrame(recs)
    cl = cl[cl["f_gen"].notna()]
    return dict(gen100=float(SG._wavg(cl, "generator_kWh_100")), trac100=float(SG._wavg(cl, "traction_gross_kWh_100")), fgen=float((cl["gen_to_traction_kWh_100"] * cl["distance_km"]).sum() / (cl["traction_gross_kWh_100"] * cl["distance_km"]).sum()), etaBus=float(SG._wavg(cl, "eta_fuel_bus")))


sens = []
for label, mutate, scen in SG.AXES:
    rs = mutate()
    try:
        rf, rw = SG.run_axis(scache, scen), SG.run_axis(swo, scen)
        uf, uw = unrounded(scache, scen), unrounded(swo, scen)
    finally:
        for fn in rs:
            fn()
    sens.append({"axis": label, "full": rf, "without": rw, "fullUnrounded": uf, "withoutUnrounded": uw, "deltaUnrounded": {k: uw[k] - uf[k] for k in uf}})
out["sensitivity"] = sens
print("sensitivity done", round(time.time() - t0), "s", flush=True)

# ---- speedSplit ----
const = FR.corpus_offset(dm)[0]
offsets = {f: FR.resolve_offset({"I_offset_A_applied": v}, const)[0] for f, v in zip(dm["file"], dm["I_offset_A_applied"])}
targets = [f for f in dm["file"] if os.path.exists(RE.BASE + f) and FR._has_fuel(RE.BASE + f)]
fr_master = pd.read_csv("fuel_recon_master.csv")
full = SS.build_speed_split(dm, fr_master, targets, offsets)
without = SS.build_speed_split(dm, fr_master, [f for f in targets if f not in EXCL], offsets)
out["speedSplit"] = {"full": full, "without": without, "nTargets": len(targets), "nTargetsWithout": len([f for f in targets if f not in EXCL])}
print("speedSplit done", round(time.time() - t0), "s", flush=True)
assert hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest() == "bd9d10726bb064d857cf9ff98d2b7338"
with open("analyses/M375_expected.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(out, f, indent=1, ensure_ascii=False, default=float)
    f.write("\n")
print("wrote analyses/M375_expected.json", round(time.time() - t0), "s")
