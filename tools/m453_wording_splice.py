#!/usr/bin/env python3
"""M453 exact-string leaf edit of summary_arrays.json (wording debt, language gate rule M453-measured-regen-wording): two payload strings that call logger-derived, assumed-mass quantities 'measured'.
  (1) seasonalCharts.charts.RegenCaptureMeasured.statisticalUnit  'regen capture fraction (measured)' -> 'apparent KE recovery ratio (legacy extraction, assumed mass)'   (carried leaf, no builder text in the repository)
  (2) mountainPattern.descentBudget.note  'pack-measured charge energy' -> 'pack charge energy (integrated from the logged current and voltage)'   (the producer text in compute_summary_arrays.py is edited in the same change)
Idempotent; asserts old/new text; touches no other string or number.  Usage: python tools/m453_wording_splice.py [--dry-run]"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
EDITS = [
    (("seasonalCharts", "charts", "RegenCaptureMeasured"), "statisticalUnit", "regen capture fraction (measured)", "apparent KE recovery ratio (legacy extraction, assumed mass)"),
    (("mountainPattern", "descentBudget"), "note", "capture fraction is pack-measured charge energy over ", "capture fraction is pack charge energy (integrated from the logged current and voltage) over "),
]

raw = open(ARR, "rb").read().decode("utf-8")
A = json.loads(raw)
changed = []
for path, key, old, new in EDITS:
    o = A
    for p in path:
        o = o[p]
    v = o[key]
    if old in v:
        assert v.count(old) == 1, (path, key)
        o[key] = v.replace(old, new)
        changed.append("/".join(path) + "/" + key)
    else:
        assert new in v, (path, key, v[:80])
if "--dry-run" in sys.argv or not changed:
    print(json.dumps({"changed": changed, "dryRun": "--dry-run" in sys.argv}))
    sys.exit(0)
rt = json.dumps(json.loads(raw), ensure_ascii=False, indent=1)
if rt != raw and rt + chr(10) != raw:
    raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
with open(ARR, "w", encoding="utf-8", newline=chr(10)) as f:
    f.write(json.dumps(A, ensure_ascii=False, indent=1) + (chr(10) if raw.endswith(chr(10)) else ""))
print(json.dumps({"changed": changed}))
