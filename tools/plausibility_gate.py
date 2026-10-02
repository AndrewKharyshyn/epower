#!/usr/bin/env python3
"""M308 input-plausibility gate for NEW raw drive files (spec: analyses/M308_plausibility_gate_spec.md, approved by Andrii 2026-09-30,
incl. the Amendment 1 refinements below). Flags, never repairs; a flagged file is quarantined by tools/ingest_core.py (fail closed).

Rules (thresholds fixed before any new data; applied to NEW files only, never retroactively to the published master):
  R1 cell-voltage range: any non-null value of '[BMS] Max Cell Voltage (V)' / '[BMS] Min Cell Voltage (V)' outside [2.5, 4.3] V.
  R2 quantisation: min positive difference between sorted distinct values >= 0.05 V (needs >= 5 distinct values), tested PER CHANNEL
     (GateA2, M324: each of the Max/Min columns on its own; one flag lists the channels that trip; the pooled M308 statistic missed mixed-grid files).
Amendment 1 (2026-09-30, from the corpus scan on existing files, before any new drive is ingested):
  * R1/R2 apply to the single-cell Max/Min columns only. 'G01..Gnn Cell Voltage' are cell-GROUP voltages (G01 ~ 7.4-8.2 V, two cells in
    series) and would flag every file from mid-August (incl. all 113 hash-verified files); they are out of scope of the approved thresholds.
  * R3 (current values all multiples of 0.5 A) is NOT implemented: 415/446 corpus files, including 105/113 hash-verified ones, have every
    current value at a 0.5 A multiple, i.e. 0.5 A is the normal resolution, not a damage signature. No discriminating precision rule exists
    in the available data; recorded, not silently dropped.
Files with no Max/Min cell-voltage columns (7 early files) produce no flags (nothing to check).
Usage: python tools/plausibility_gate.py FILE [FILE ...]   |   python tools/plausibility_gate.py --scan RAW_DIR OUT.json"""
import hashlib, io, json, os, re, sys
import numpy as np
import pandas as pd

V_MIN, V_MAX = 2.5, 4.3
STEP_MAX_OK = 0.05          # a min positive step >= this flags
MIN_DISTINCT = 5
COLS = ("Max Cell Voltage", "Min Cell Voltage")


GATE_VERSION = "M308+GateA2"


def _channel_r2(series):
    """One cell-voltage column on its own. Returns (status, nDistinct, minStep). status: tested / untested_nan / untested_few_distinct."""
    v = pd.to_numeric(series, errors="coerce").dropna()
    if not len(v):
        return "untested_nan", 0, None
    dist = np.sort(v.unique())
    if len(dist) < MIN_DISTINCT:
        return "untested_few_distinct", int(len(dist)), None
    return "tested", int(len(dist)), float(np.diff(dist).min())


def check_bytes(csv_bytes, name="<bytes>"):
    d = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    cols = [c for c in d.columns if any(k in c for k in COLS)]
    flags, stats = [], {"cellVoltageColumns": cols}
    sha = hashlib.sha256(csv_bytes).hexdigest()
    if not cols:
        return {"file": name, "flags": flags, "stats": stats, "checked": False, "partial": False, "sha256": sha}
    v = pd.concat([pd.to_numeric(d[c], errors="coerce") for c in cols]).dropna()
    stats["nValues"] = int(len(v))
    if not len(v):                                   # NaN-only / non-numeric cell-voltage columns: nothing was actually checked
        return {"file": name, "flags": flags, "stats": stats, "checked": False, "partial": False, "sha256": sha}
    stats["min"], stats["max"] = float(v.min()), float(v.max())
    out = v[(v < V_MIN) | (v > V_MAX)]
    if len(out):                                      # R1 stays pooled (a range violation anywhere is a violation)
        flags.append({"rule": "R1_cell_voltage_range", "nOutOfRange": int(len(out)), "min": float(v.min()), "max": float(v.max()),
                      "range": [V_MIN, V_MAX]})
    # R2 (GateA2, amendment 2): each matched column on its own; ONE flag listing the channels that trip.
    chan = {}
    for c in cols:
        st, nd, step = _channel_r2(d[c])
        chan[c] = {"status": st, "nDistinct": nd, "minStepV": None if step is None else round(step, 6)}
    stats["channels"] = chan
    pooled = np.sort(v.unique())                      # pooled statistic kept for comparison with the M308 scan (informational)
    stats["nDistinct"] = int(len(pooled))
    if len(pooled) >= MIN_DISTINCT:
        stats["minStepV"] = round(float(np.diff(pooled).min()), 6)
    tripped = {c: x["minStepV"] for c, x in chan.items() if x["status"] == "tested" and x["minStepV"] >= STEP_MAX_OK - 1e-12}
    if tripped:
        flags.append({"rule": "R2_quantisation", "channels": sorted(tripped), "minStepV": tripped and min(tripped.values()),
                      "perChannelMinStepV": tripped, "threshold": STEP_MAX_OK})
    untested = sorted(c for c, x in chan.items() if x["status"] != "tested")
    return {"file": name, "flags": flags, "stats": stats, "checked": True, "partial": bool(untested), "untestedChannels": untested,
            "gateVersion": GATE_VERSION, "sha256": sha}


def check_path(path):
    with open(path, "rb") as f:
        return check_bytes(f.read(), os.path.basename(path))


def main():
    a = sys.argv[1:]
    if a and a[0] == "--scan":
        raw_dir, out = a[1], a[2]
        res = [check_path(os.path.join(raw_dir, f)) for f in sorted(os.listdir(raw_dir))
               if f.endswith(".csv") and re.match(r"^(\d{4}-\d{2}-\d{2}|\d{8})[ _]\d", f)]
        summ = {"nFiles": len(res), "nChecked": sum(r["checked"] for r in res), "nFlagged": sum(1 for r in res if r["flags"]),
                "flagged": [r["file"] for r in res if r["flags"]]}
        json.dump({"summary": summ, "results": res}, open(out, "w"), indent=1)
        print(json.dumps(summ, indent=1))
        return 0
    bad = 0
    for p in a:
        r = check_path(p)
        print(json.dumps(r))
        bad += bool(r["flags"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
