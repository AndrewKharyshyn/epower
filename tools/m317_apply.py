#!/usr/bin/env python3
"""M317 additive application on the frozen master: recompute ONLY `cellHealthTrend` (new keys huberSlopeCi95, huberSlopeCiFailedDraws, huberSlopeCiMethod) and splice it
into summary_arrays.json, asserting that every pre-existing key of the block is unchanged and that no other arrays key differs from HEAD except the intended new blocks
(spreadFitProvenance, written by tools/record_spread_fit.py) and stamps. drive_master.csv is not touched (MD5 asserted). Usage: python tools/m317_apply.py"""
import hashlib, json, os, subprocess, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import compute_summary_arrays as csa

md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
A = json.load(open("summary_arrays.json", encoding="utf-8"))
dm = pd.read_csv("drive_master.csv", low_memory=False)
old, fresh = A["cellHealthTrend"], csa._cell_health_trend(dm)
changed = sorted(k for k in set(old) | set(fresh) if old.get(k) != fresh.get(k))
new_keys = {"huberSlopeCi95", "huberSlopeCiFailedDraws", "huberSlopeCiMethod"}
assert set(changed) <= new_keys, f"unexpected cellHealthTrend keys changed: {changed}"
A["cellHealthTrend"] = {**old, **{k: fresh[k] for k in changed}}
st = A["_artifactStamps"]["cellHealthTrend"]
note = st.get("computationStatusNote") or ""
if "M317" not in note:
    st["computationStatusNote"] = (note + " | M317: huberSlopeCi95 added (day-clustered bootstrap, conditional on the first-stage fit).").lstrip(" |")
with open("summary_arrays.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(A, ensure_ascii=False, indent=1))
head = json.loads(subprocess.check_output(["git", "show", "HEAD:summary_arrays.json"]).decode("utf-8"))
diff = sorted(k for k in set(A) | set(head) if A.get(k) != head.get(k))
allowed = {"cellHealthTrend", "spreadFitProvenance", "_artifactStamps"}
assert set(diff) <= allowed, f"arrays keys changed outside the intended set: {diff}"
sd = sorted(k for k in set(A["_artifactStamps"]) | set(head["_artifactStamps"]) if A["_artifactStamps"].get(k) != head["_artifactStamps"].get(k))
assert set(sd) <= {"cellHealthTrend", "spreadFitProvenance"}, f"stamps changed outside the intended set: {sd}"
print(json.dumps({"master_md5": md5, "cellHealthTrend_new_keys": changed, "huberSlopeCi95": fresh.get("huberSlopeCi95"), "arrays_keys_changed_vs_HEAD": diff, "stamps_changed": sd}, indent=1))
