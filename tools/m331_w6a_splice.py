#!/usr/bin/env python3
"""M331 (wording sweep W6a) exact-string leaf edit of summary_arrays.json (addendum analyses/M331_W6a_addendum.md, A3): records[22].note.
Idempotent; asserts the old text (or the new text already present); touches no other string.  Usage: python tools/m331_w6a_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
OLD = "and are where the pack reaches thermal equilibrium."
NEW = "and are where the pack reaches its highest sustained temperatures (a finite maximum, not an established equilibrium)."
A = json.load(open(ARR, encoding="utf-8"))
hits = [r for r in A["records"] if OLD in r.get("note", "")]
changed = []
if hits:
    assert len(hits) == 1, len(hits)
    hits[0]["note"] = hits[0]["note"].replace(OLD, NEW)
    changed.append("records[%d].note" % A["records"].index(hits[0]))
else:
    assert any(NEW in r.get("note", "") for r in A["records"]), "neither old nor new text found"
if "--dry-run" not in sys.argv and changed:
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
print(json.dumps({"changed": changed, "n": len(changed)}))
