#!/usr/bin/env python3
"""M458 splice (spec analyses/M458_spec.md Rev 1.1-1.2): single-key update of summary_arrays.json (key carOffStandby) with the block recomputed by the PRODUCER function compute_summary_arrays._car_off_standby (gate G3: the splice IS the producer output).
Gate G1: the point fields are bit-identical to the current block. Gate G2: only the leaves of the isolation list may change or appear; every other key of the payload is identical. Idempotent. Usage: python tools/m458_standby_splice.py [--dry-run]"""
import copy
import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import pandas as pd
import compute_summary_arrays as C

POINT = ["n_gaps", "watts", "kwh_per_day", "jump_pp_per_keycycle", "corr_gap_vs_draw", "estimator", "n_boot"]
CHANGED = ["ci95_watts", "ci95_kwh_per_day", "p_draw_gt0"]
NEW = ["slope_pp_per_h", "ci95_slope_pp_per_h", "ciMethod", "nClusters", "kishClusters", "nUndefinedDraws", "ci95WattsIid", "ci95KwhPerDayIid", "pDrawGt0Iid", "ciIidNote", "sensitivities", "methodDisagreement",
       "nPairsTotal", "nPairsDropped", "nDrivesDroppedMissingSoc", "pairCountNote", "gapsSpanningMidnight", "gapsWithOdoJump", "capacityAssumption", "limits"]

raw = open("summary_arrays.json", "rb").read().decode("utf-8")
A = json.loads(raw)
if json.dumps(A, ensure_ascii=False, indent=1) != raw and json.dumps(A, ensure_ascii=False, indent=1) + "\n" != raw:
    raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
dm = pd.read_csv("drive_master.csv", low_memory=False)
md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
blk = C._car_off_standby(dm)
if "error" in blk:
    raise SystemExit("producer error: %s" % blk["error"])
old = A["carOffStandby"]
bad = [k for k in POINT if old.get(k) != blk.get(k)]
if bad:
    raise SystemExit("G1 failed: point fields differ: %r" % bad)
unexpected = sorted(set(blk) - set(POINT) - set(CHANGED) - set(NEW))
if unexpected:
    raise SystemExit("G2 failed: leaves outside the isolation list: %r" % unexpected)
missing = sorted(set(old) - set(blk))
if missing:
    raise SystemExit("G2 failed: leaves would disappear: %r" % missing)
N = copy.deepcopy(A)
N["carOffStandby"] = blk
import datetime
st = N["_artifactStamps"]["carOffStandby"]
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
st["generatedAt"] = st["includedInReleaseAt"] = now
st["computationStatusNote"] = "M458: interval recomputed by compute_summary_arrays._car_off_standby (tools/standby_ci.py, arrival-day cluster bootstrap); point fields unchanged; spliced by tools/m458_standby_splice.py"
changed = [k for k in blk if old.get(k) != blk[k]]
print(json.dumps({"changed": changed, "masterMd5": md5}))
if "--dry-run" in sys.argv or (N["carOffStandby"] == A["carOffStandby"]):
    sys.exit(0)
with open("summary_arrays.json", "w", encoding="utf-8", newline=chr(10)) as f:
    f.write(json.dumps(N, ensure_ascii=False, indent=1) + (chr(10) if raw.endswith(chr(10)) else ""))
print("wrote summary_arrays.json")
