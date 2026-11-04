#!/usr/bin/env python3
"""M575: exact-string leaf edit of the carried provenance leaf _provenance.new_no_archived_counterpart['seasonalLife.observedConstant'] ('whose workload is measured' ->
'whose workload is observed (logged)'; language gate rule M483-measured-intensity-wording). This is item (5) of tools/m483_wording_splice.py; that tool's other edits were superseded by later wording
and its post-condition no longer holds on the live payload, so only this still-needed edit is applied by the ingestion (the leaf is rebuilt from an untracked baseline file on every ingestion).
Idempotent; asserts old/new text; touches no other string or number. Usage: python tools/provenance_wording_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
OLD, NEW = "whose workload is measured", "whose workload is observed (logged)"
raw = open(ARR, "rb").read().decode("utf-8")
A = json.loads(raw)
d = A["_provenance"]["new_no_archived_counterpart"]
v = d["seasonalLife.observedConstant"]
if OLD in v:
    assert v.count(OLD) == 1
    d["seasonalLife.observedConstant"] = v.replace(OLD, NEW)
    assert NEW in d["seasonalLife.observedConstant"] and OLD not in d["seasonalLife.observedConstant"]
    print("edited seasonalLife.observedConstant")
    if "--dry-run" not in sys.argv:
        with open(ARR, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(A, ensure_ascii=False, indent=1))
else:
    assert NEW in v, v[:120]
    print("already edited")
