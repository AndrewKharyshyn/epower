#!/usr/bin/env python3
"""F03 control build (no new drives): the arrays build of tools/ingest_core.step4_arrays, unchanged arguments, run on a checkout whose raw/ holds the sha256-verified originals
(all 489 canonical files match raw_manifest.json). Writes the result to control_arrays.json (NOT summary_arrays.json); the diff against the published arrays is tools/f03_control_diff.py.
Usage (after tools/stage_raw.py): python tools/f03_control_build.py [--out FILE]  (default control_arrays.json; run once on the swapped checkout and once, as the baseline, on the unswapped one)"""
import json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import pandas as pd
import compute_summary_arrays as csa
import drive_raw_cache as drc

t0 = time.time()
dm = pd.read_csv("drive_master.csv", low_memory=False)
cfg = json.load(open("summary_config.json"))
prev = json.load(open("summary_arrays.json"))
raw_stage = os.path.join(ROOT, "raw_only")


def loader(fn):
    with open(os.path.join(raw_stage, fn), "rb") as f:
        return f.read()


# verify_md5=True: without it add_missing keeps any existing cache entry by name and the swapped files would be read from stale frames
n_added, n_pending = drc.add_missing(list(dm["file"].astype(str)), raw_stage, verify_md5=True, verbose=False)
print("frames rebuilt:", n_added, "pending:", n_pending, flush=True)
print("frame cache ready", round(time.time() - t0, 1), flush=True)
arrays = csa.build_summary_arrays(
    dm, loader, with_raw=True, odometer_km=cfg.get("vehicle", {}).get("odometerKm"),
    seasonal_cfg=cfg.get("seasonalAssumptions"), ambient_by_drive=cfg.get("ambientByDrive"),
    frame_loader=drc.make_frame_loader(), session_cfg=cfg, raw_dir=raw_stage,
    recompute_m119v2=False, prev_arrays=prev, recompute_energy_mc=True)
OUT = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "control_arrays.json"
json.dump(arrays, open(OUT, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1, default=float)
print("control build done", round(time.time() - t0, 1), "s;", len(arrays), "top-level keys", flush=True)
