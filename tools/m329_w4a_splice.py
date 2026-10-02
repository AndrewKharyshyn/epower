#!/usr/bin/env python3
"""M329 (wording sweep W4a) exact-string leaf edit of summary_arrays.json (addendum analyses/M329_W4a_addendum.md, Q6): comparisonCube.metrics.starts_100km.label.
Idempotent; asserts the old text (or the new text already present); touches no other string.  Usage: python tools/m329_w4a_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
OLD, NEW = "Engine-start proxy (current sign crossings)", "Current-direction reversals (pack-current sign crossings)"
A = json.load(open(ARR, encoding="utf-8"))
m = A["comparisonCube"]["metrics"]["starts_100km"]
changed = []
if m["label"] == OLD:
    m["label"] = NEW
    changed.append("comparisonCube.metrics.starts_100km.label")
else:
    assert m["label"] == NEW, m["label"]
if "--dry-run" not in sys.argv and changed:
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
print(json.dumps({"changed": changed, "n": len(changed)}))
