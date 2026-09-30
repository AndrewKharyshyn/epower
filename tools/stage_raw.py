#!/usr/bin/env python3
"""Stage a raw directory named by the drive_master 'file' keys (the code base loads raw files by those keys; this checkout stores
'YYYY-MM-DD HH-MM-SS.csv' with a space). Creates raw_only/ (git-ignored) with symlinks: one per master row, the e-4ORCE captures and comparison
files under their own names, raw_manifest.json, and drive_master.csv (fuel_recon.py / speed_split.py read the master from the raw directory).
Usage: python tools/stage_raw.py [--raw-dir DIR]. Idempotent (rebuilds the directory). Exit 1 if a master row has no raw file."""
import argparse, os, re, shutil, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
import pandas as pd

def _link(src, dst, copy_fallback=False):
    """Symlink raw_only/<key> -> raw file; on Windows without the symlink privilege (WinError 1314) fall back to a hardlink
    (same volume, read-only share of the same bytes), then to a copy. raw_only/ is git-ignored and rebuilt each run."""
    try:
        os.symlink(src, dst)
    except OSError:
        try:
            if copy_fallback:          # corpus anchor files: never share an inode with the master
                raise OSError
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)


ap = argparse.ArgumentParser()
ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
a = ap.parse_args()
raw = os.path.abspath(a.raw_dir)
stage = os.path.join(ROOT, "raw_only")
if os.path.isdir(stage):
    shutil.rmtree(stage)
os.makedirs(stage)
dig = lambda n: re.sub(r"\D", "", n.rsplit(".", 1)[0])
idx = {dig(f): f for f in os.listdir(raw) if f.lower().endswith(".csv")}
dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file"])
missing = []
for f in dm["file"].astype(str):
    real = idx.get(dig(f))
    if real is None:
        missing.append(f); continue
    _link(os.path.join(raw, real), os.path.join(stage, f))
for f in os.listdir(raw):
    if (f.lower().startswith("e4orce_") or "_comparison" in f.lower()) and f.lower().endswith(".csv") and f not in ("e4orce_master.csv", "e4orce_ambient.csv"):
        _link(os.path.join(raw, f), os.path.join(stage, f))
_link(os.path.join(ROOT, "raw_manifest.json"), os.path.join(stage, "raw_manifest.json"), True)
_link(os.path.join(ROOT, "drive_master.csv"), os.path.join(stage, "drive_master.csv"), True)
print({"staged": len(os.listdir(stage)), "missing": missing})
sys.exit(1 if missing else 0)
