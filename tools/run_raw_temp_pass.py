#!/usr/bin/env python3
"""Stage wrapper for raw_temp_pass.py (M310): regenerate raw_temperature_triplets.csv over the staged raw_only/ directory (master-key
file names; raw_temp_pass.py itself hardcodes RAW_DIR=/mnt/project). Without this stage new drives enter the seasonal master with
temp_start_coverage='unavailable' (found at M293 and again at M310). Requires tools/stage_raw.py to have run.
Fails (exit 1) if any pre-existing row of the previous triplets file changes (determinism check) or a master drive has no row."""
import csv, io, os, subprocess, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import raw_temp_pass as r

stage = os.path.join(ROOT, "raw_only")
if not os.path.isdir(stage):
    sys.exit("raw_only/ missing: run tools/stage_raw.py first")
r.RAW_DIR = stage
rows = [r.process_file(p) for p in r.canonical_files()]
cols = list(rows[0].keys())
out = "raw_temperature_triplets.csv"
try:
    prev = pd.read_csv(io.BytesIO(subprocess.check_output(["git", "show", "HEAD:" + out], cwd=ROOT)), dtype=str, keep_default_na=False)
except Exception:
    prev = None
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    for x in rows:
        w.writerow({k: ("" if v is None else v) for k, v in x.items()})
new = pd.read_csv(out, dtype=str, keep_default_na=False)
dm = pd.read_csv("drive_master.csv", usecols=["file"])
missing = sorted(set(dm["file"]) - set(new["file"]))
bad = 0
if prev is not None:
    common = prev[prev["file"].isin(new["file"])]
    m = new.set_index("file").loc[common["file"]].reset_index()
    bad = int((m.values != common.values).any(axis=1).sum())
print({"rows": len(new), "missing_vs_master": missing, "preexisting_rows_changed": bad})
sys.exit(1 if (missing or bad) else 0)
