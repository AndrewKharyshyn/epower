#!/usr/bin/env python3
"""M484 exact-string leaf edit of summary_arrays.json (wording debt, language gate rule M484-thermal-sensor-wording): payload strings that call the BMS temperature-sensor readings and the hot-tail inputs derived from them 'measured'.
  (1) seasonalLife.assumptions.hotTail._provenance   'this one is MEASURED:'                      -> 'this one comes from logged BMS sensor readings:'
  (2) seasonalLife.assumptions.hotTail._provenance   '(ambient + measured per-class rise)'        -> '(ambient + logged per-class rise)'
  (4) seasonalLife.hotTail.note                        'MEASURED high-T cycle-damage sensitivity'   -> 'Logged-sensor high-T cycle-damage sensitivity'
  (3) _retractedLifeEol                               'measured thermics'                           -> 'logged thermics'
The same sentences in summary_config.json and compute_summary_arrays.py are edited in the same change. Payload keys (packThermalMeasured, measured:false, ...) are never renamed.
Idempotent; asserts old/new text; touches no other string or number.  Usage: python tools/m484_wording_splice.py [--dry-run]"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
EDITS = [
    (("seasonalLife", "assumptions", "hotTail"), "_provenance", "this one is MEASURED:", "this one comes from logged BMS sensor readings:"),
    (("seasonalLife", "assumptions", "hotTail"), "_provenance", "(ambient + measured per-class rise)", "(ambient + logged per-class rise)"),
    ((), "_retractedLifeEol", "measured thermics", "logged thermics"),
    (("seasonalLife", "hotTail"), "note", "MEASURED high-T cycle-damage sensitivity", "Logged-sensor high-T cycle-damage sensitivity"),
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
        assert v.count(old) == 1, (path, key, old)
        o[key] = v.replace(old, new)
        changed.append("/".join(str(p) for p in path) + "/" + key + " [" + old[:24] + "]")
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
