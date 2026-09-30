#!/usr/bin/env python3
"""M312 propagation after tools/m312_huber_alignment.py changed ONE master column. Additive splice into summary_arrays.json:
  1. recompute only `cellHealthTrend` (the sole consumer of cell_spread_loaded_p95_adj_hub_mv) and splice it leaf-level; assert that every
     key other than huberSlopeMvPerMo / nHuber is unchanged (deep diff);
  2. regenerate the determinism block (determinism_check.build on the new master) into summary_config.json auditMetadata.determinism and
     summary_arrays.json determinism, keeping the audit labels of the previous block (harness / scopeLabel / releaseTest);
  3. re-issue every stamp whose corpusHash is the old master MD5 (32-hex and 12-hex forms) with reissuedFrom + a one-line note that only
     cell_spread_loaded_p95_adj_hub_mv changed (proven by m312_huber_alignment's per-column hash check). Block contents are NOT touched
     (masterRefitAudit / masterRefitProvenance keep the hash of the master they audited).
Usage: python tools/m312_propagate.py --old-md5 5197ab6d... ; run after the splice, before build_html.js. Prints a JSON summary."""
import argparse, datetime, hashlib, json, os, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import compute_summary_arrays as csa
import ingest_core as ic

ap = argparse.ArgumentParser()
ap.add_argument("--old-md5", required=True)
a = ap.parse_args()
new = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
assert new != a.old_md5, "master unchanged"
A = json.load(open("summary_arrays.json", encoding="utf-8"))
dm = pd.read_csv("drive_master.csv", low_memory=False)
# 1. cellHealthTrend
old, fresh = A["cellHealthTrend"], csa._cell_health_trend(dm)
diff = sorted(k for k in set(old) | set(fresh) if old.get(k) != fresh.get(k))
allowed = {"huberSlopeMvPerMo", "nHuber"}
assert set(diff) <= allowed, f"unexpected cellHealthTrend keys changed: {diff}"
A["cellHealthTrend"] = {**old, **{k: fresh[k] for k in diff}}
# 2. determinism
block, _ = ic.step3_determinism(os.path.join(ROOT, "drive_master.csv"))
prev = A.get("determinism") or {}
for lab in ("harness", "scopeLabel", "releaseTest"):
    if lab in prev and lab not in block:
        block[lab] = prev[lab]
cfg = json.load(open("summary_config.json", encoding="utf-8"))
pc = cfg.setdefault("auditMetadata", {}).get("determinism") or {}
for lab in ("harness", "scopeLabel", "releaseTest"):
    if lab in pc and lab not in block:
        block[lab] = pc[lab]
cfg["auditMetadata"]["determinism"] = block
A["determinism"] = block
# 3. stamps
n32 = n12 = 0
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
for k, s in A["_artifactStamps"].items():
    if not isinstance(s, dict):
        continue
    h = s.get("corpusHash")
    if h == a.old_md5:
        s["corpusHash"] = new
        s["reissuedFrom"] = a.old_md5
        s["reissueNote"] = "M312: master hash re-issued; only cell_spread_loaded_p95_adj_hub_mv changed (per-column hash check); block content unchanged unless listed (cellHealthTrend)."
        n32 += 1
    elif h == a.old_md5[:12]:
        s["corpusHash"] = new[:12]
        n12 += 1
A["_artifactStamps"]["cellHealthTrend"]["computationStatusNote"] = (
    (A["_artifactStamps"]["cellHealthTrend"].get("computationStatusNote") or "") + " | M312: recomputed after Huber exclusion alignment (huberSlopeMvPerMo, nHuber).").lstrip(" |")
with open("summary_arrays.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(A, ensure_ascii=False, indent=1))
with open("summary_config.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(cfg, ensure_ascii=False, indent=1))
print(json.dumps({"new_md5": new, "cellHealthTrend_changed_keys": diff, "old": {k: old.get(k) for k in diff}, "new": {k: fresh.get(k) for k in diff},
                  "stamps_reissued_32hex": n32, "stamps_12hex": n12}, indent=1))
