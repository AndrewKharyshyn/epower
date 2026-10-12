#!/usr/bin/env python3
"""M414/M415 control build (analyses/M413_spec.md gate (e)): the arrays build of tools/ingest_core.step4_arrays with its unchanged arguments, run on the CURRENT master and raw set,
written to a file that is NOT summary_arrays.json. Used as build A (default exposure basis) and, after the flip (M415), as build B (XT_EXPOSURE_BASIS=rated5Ah); the diff B vs A (never a fresh
build vs the published file) is tools/exposure_control_diff.py. Nothing in the repository is modified.
Usage (after tools/stage_raw.py): python tools/exposure_control_build.py --out FILE [--basis legacy2p1kWh|rated5Ah]"""
import hashlib, json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
if "--basis" in sys.argv:
    os.environ["XT_EXPOSURE_BASIS"] = sys.argv[sys.argv.index("--basis") + 1]
import pandas as pd
import compute_summary_arrays as csa
import drive_raw_cache as drc

t0 = time.time()
OUT = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "control_arrays.json"
dm = pd.read_csv("drive_master.csv", low_memory=False)
cfg = json.load(open("summary_config.json", encoding="utf-8"))
prev = json.load(open("summary_arrays.json", encoding="utf-8"))
raw_stage = os.path.join(ROOT, "raw_only")


def loader(fn):
    with open(os.path.join(raw_stage, fn), "rb") as f:
        return f.read()


drc.add_missing(list(dm["file"].astype(str)), raw_stage, verbose=False)
arrays = csa.build_summary_arrays(
    dm, loader, with_raw=True, odometer_km=cfg.get("vehicle", {}).get("odometerKm"),
    seasonal_cfg=cfg.get("seasonalAssumptions"), ambient_by_drive=cfg.get("ambientByDrive"),
    frame_loader=drc.make_frame_loader(raw_dir=raw_stage), session_cfg=cfg, raw_dir=raw_stage,
    recompute_m119v2=False, prev_arrays=prev, recompute_energy_mc=True)
json.dump(arrays, open(OUT, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1, default=float)
side = os.path.join(ROOT, "ah_throughput.csv")
print(json.dumps({"out": OUT, "seconds": round(time.time() - t0, 1), "topLevelKeys": len(arrays), "basis": os.environ.get("XT_EXPOSURE_BASIS", "legacy2p1kWh"),
                  "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "sidecarMd5": hashlib.md5(open(side, "rb").read()).hexdigest() if os.path.exists(side) else None}))
