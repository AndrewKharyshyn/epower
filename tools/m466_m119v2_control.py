#!/usr/bin/env python3
"""M466 stage C: no-new-drive CONTROL refit of M119-v2 on the first N rows of the live drive_master.csv (the 489-drive basis of the carried block), with today's code, on a chosen raw directory.
Read-only for the repo (writes only --out). Three-way split of the 606-vs-published difference (Director condition of M463):
  published (carried 489 block, git ref) -> control on the FORMER re-exports (today's code)   = code effect
  control(former) -> control(originals)                                                      = provenance effect (M366 raw swap)
  control(originals, 489) -> shipped 606 refit                                               = new-data effect
Usage: python tools/m466_m119v2_control.py --n 489 --raw-dir raw_only --out PATH     |   --raw-dir ../../xtrail-m373-former for the former basis"""
import argparse, json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import pandas as pd
import m119v2_model

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=489)
ap.add_argument("--raw-dir", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
dm = pd.read_csv("drive_master.csv", low_memory=False).iloc[:a.n].copy()
t0 = time.time()
blk = m119v2_model.build_m119v2(dm, raw_loader=None, raw_dir=os.path.abspath(a.raw_dir))
blk["_control"] = {"nRows": int(len(dm)), "rawDir": os.path.basename(os.path.abspath(a.raw_dir)), "seconds": round(time.time() - t0), "firstFile": dm["file"].iloc[0], "lastFile": dm["file"].iloc[-1]}
with open(a.out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(blk, f, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
print(json.dumps({"nDrivesCovered": blk.get("nDrivesCovered"), "seconds": blk["_control"]["seconds"]}))
