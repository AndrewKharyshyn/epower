#!/usr/bin/env python3
"""M328 (wording sweep W3a) exact-string leaf edits of summary_arrays.json (addendum analyses/M328_W3a_addendum.md, A1). Idempotent; asserts the declared count
of leaves per edit (or the new text already present); touches no other string.  Usage: python tools/m328_w3a_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
EDITS = [  # (old, new, expected leaves)
    ("MEASURED - null result with stated detection limit", "PROXY - no resolved trend; precision stated as a CI half-width", 1),
    ("own detection floor (", "own CI half-width (", 2),
    ("-- i.e. the M25 null result is consistent with, not in tension with, the official trajectory at this mileage.",
     "-- i.e. the M25 interval does not exclude the official trajectory at this mileage (a consistency check, not a validation).", 2),
]


def walk(o):
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if isinstance(v, str):
                yield o, k
            else:
                yield from walk(v)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if isinstance(v, str):
                yield o, i
            else:
                yield from walk(v)


A = json.load(open(ARR, encoding="utf-8"))
changed = []
for old, new, cnt in EDITS:
    leaves = [(c, k) for c, k in walk(A) if old in c[k]]
    if not leaves:
        assert any(new in c[k] for c, k in walk(A)), ("neither old nor new text found", old[:60])
        continue
    assert len(leaves) == cnt, (old[:60], len(leaves), cnt)
    for c, k in leaves:
        c[k] = c[k].replace(old, new)
        changed.append(old[:40])
if "--dry-run" not in sys.argv and changed:
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
print(json.dumps({"changed": changed, "n": len(changed)}))
