#!/usr/bin/env python3
"""M325 step A (read-only): grid check of the 9 files flagged R2 by the M324 corpus scan.
For each: original (originals_recovered/) vs raw/ copy vs published master row. Per cell-voltage channel: n_distinct, grid_step, max_decimals,
share_on_0p1_grid, share of identical Max/Min values; master-builder outputs from compute_drive_summary_v6.analyze_bytes (pre-postprocess):
cell_spread_loaded_p95_mv / max / mean, n_loaded_spread_samples. Spec: analyses/M325_spec.md rev 2. Never writes raw/, the manifest or the master.
Usage: python tools/f03_grid_check.py ORIGINALS_DIR OUT.json"""
import json, os, re, sys
import numpy as np
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(__file__))
import compute_drive_summary_v6 as v6
import signal_representation as sr

ORIG, OUT = sys.argv[1], sys.argv[2]
OUTCOLS = ["cell_spread_loaded_p95_mv", "cell_spread_loaded_max_mv", "cell_spread_loaded_mean_mv", "n_loaded_spread_samples"]
CH = ["[BMS] Max Cell Voltage (V)", "[BMS] Min Cell Voltage (V)"]
dg = lambda s: re.sub(r"\D", "", str(s).rsplit(".", 1)[0])[:14]
rid = lambda s: (lambda d: d[:8] + "_" + d[8:14] + ".csv")(dg(s))

scan = json.load(open(os.path.join(ROOT, "analyses", "M324_gatea2_corpus_scan.json"), encoding="utf-8"))
nine = sorted({v["file"] for v in scan.values() if "R2_quantisation" in v["flags"] and v["grp"] == "raw_reexport"})
assert len(nine) == 9, nine
man = {r["record_id"]: r for r in json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))["files"] if r["role"] == "canonical"}
master = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
mkey = {dg(f): f for f in master["file"]}
rawdir = os.path.join(ROOT, "raw")
rawidx = {dg(f): f for f in os.listdir(rawdir) if f.lower().endswith(".csv")}
import hashlib

def chan_stats(b):
    d = pd.read_csv(__import__("io").BytesIO(b), dtype=str, low_memory=False)
    return {c: sr._channel(d[c]) for c in CH if c in d.columns}, d

def analyze(b, key):
    r = v6.analyze_bytes(b, key)
    return {c: (None if r.get(c) is None or (isinstance(r.get(c), float) and np.isnan(r.get(c))) else float(r[c])) for c in OUTCOLS}

rows = []
for f in nine:
    k = dg(f); r = rid(f); key = mkey[k]
    ob = open(os.path.join(ORIG, r), "rb").read(); rb = open(os.path.join(rawdir, rawidx[k]), "rb").read()
    in_fail = hashlib.sha256(rb).hexdigest() != man[r]["sha256"]
    assert hashlib.sha256(ob).hexdigest() == man[r]["sha256"], r
    oc, od = chan_stats(ob); rc, rd = chan_stats(rb)
    same = {}
    for c in CH:
        a, b_ = pd.to_numeric(od[c], errors="coerce"), pd.to_numeric(rd[c], errors="coerce")
        both = a.notna() & b_.notna()
        same[c] = {"n_both": int(both.sum()), "share_identical": round(float((np.abs(a[both] - b_[both]) < 1e-12).mean()), 6) if both.any() else None}
    pub = master.loc[master["file"] == key, OUTCOLS].iloc[0].astype(float).to_dict()
    ao, ar = analyze(ob, key), analyze(rb, key)
    diff = lambda x: {c: (None if x[c] is None or pd.isna(pub[c]) else round(x[c] - pub[c], 6)) for c in OUTCOLS}
    rows.append({"file": f, "record_id": r, "master_key": key, "raw_hash_failing": bool(in_fail),
                 "original": {"channels": oc, "analyze": ao, "minus_published": diff(ao)},
                 "raw_copy": {"channels": rc, "analyze": ar, "minus_published": diff(ar)},
                 "published": pub, "identical_value_share": same})
p95 = [abs(x["raw_copy"]["minus_published"]["cell_spread_loaded_p95_mv"]) for x in rows if x["raw_copy"]["minus_published"]["cell_spread_loaded_p95_mv"] is not None]
orig_ok = all(all(v is None or abs(v) <= 1e-9 for v in x["original"]["minus_published"].values()) for x in rows)
summ = {"n": len(rows), "all_in_hash_failing_set": all(x["raw_hash_failing"] for x in rows),
        "originals_reproduce_published_all_outputs": orig_ok,
        "originals_max_grid_step": max((c["grid_step"] or 0) for x in rows for c in x["original"]["channels"].values()),
        "originals_any_grid_step_ge_0p05": any((c["grid_step"] or 0) >= 0.05 for x in rows for c in x["original"]["channels"].values()),
        "raw_copy_abs_p95_diff_mv_min_max": [round(min(p95), 1), round(max(p95), 1)] if p95 else None,
        "raw_copy_reproduces_published_p95": [bool(abs(x["raw_copy"]["minus_published"]["cell_spread_loaded_p95_mv"] or 0) <= 1e-9) for x in rows]}
json.dump({"summary": summ, "files": rows}, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps(summ, indent=1))
