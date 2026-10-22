#!/usr/bin/env python3
"""M483 exact-string leaf edit of summary_arrays.json (wording debt, language gate rule M483-measured-intensity-wording): five payload strings that call the logged-data-derived, app-calculated GTC/km intensities
or the M25 resistance proxy 'measured' (Director: GTC/km is estimated from the logged current with an assumed capacity constant; final wording 'estimated').
  (1) fadeModes.capacity.rows[5].basis                'the same measured intensities'              -> 'the same observed (logged / app-calculated) intensities'
  (2) officialDisclosureCorrelation.rows[5].note       'this study's measured gtcPerKm'             -> 'this study's observed (estimated) gtcPerKm'
  (3) officialDisclosureCorrelation.capacityFadeAnchor.note   same as (2)
  (4b) the same two notes (2) and (3): 'OWN measured cycling intensity' -> 'OWN observed (estimated) cycling intensity'
  (4) officialDisclosureCorrelation.official.note      'whether the measured M25 null result'       -> 'whether the estimated M25 proxy null result'
  (5) _provenance.new_no_archived_counterpart['seasonalLife.observedConstant']   'whose workload is measured'   -> 'whose workload is observed (logged)'   (carried leaf)
The producer text in compute_summary_arrays.py and summary_config.json is edited in the same change. Idempotent; asserts old/new text; touches no other string or number.
Usage: python tools/m483_wording_splice.py [--dry-run]"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
EDITS = [   # (path, key, [accepted old texts], new text); the second old text is the intermediate wording of the first M483 pass
    (("fadeModes", "capacity", "rows", 5), "basis", ["the same measured intensities", "the same observed (logged / app-calculated) intensities"], "the same estimated per-class intensities (integrated from logged current)"),
    (("officialDisclosureCorrelation", "rows", 5), "note", ["this study's measured gtcPerKm", "this study's observed (estimated) gtcPerKm"], "this study's estimated gtcPerKm (from logged current; assumed capacity)"),
    (("officialDisclosureCorrelation", "capacityFadeAnchor"), "note", ["this study's measured gtcPerKm", "this study's observed (estimated) gtcPerKm"], "this study's estimated gtcPerKm (from logged current; assumed capacity)"),
    (("officialDisclosureCorrelation", "rows", 5), "note", ["OWN measured cycling intensity", "OWN observed (estimated) cycling intensity"], "OWN estimated cycling intensity"),
    (("officialDisclosureCorrelation", "capacityFadeAnchor"), "note", ["OWN measured cycling intensity", "OWN observed (estimated) cycling intensity"], "OWN estimated cycling intensity"),
    (("officialDisclosureCorrelation", "official"), "note", ["whether the measured M25 null result"], "whether the estimated M25 proxy null result"),
    (("_provenance", "new_no_archived_counterpart"), "seasonalLife.observedConstant", ["whose workload is measured"], "whose workload is observed (logged)"),     # carried provenance leaf, no builder text in the repository
]

raw = open(ARR, "rb").read().decode("utf-8")
A = json.loads(raw)
changed = []
for path, key, olds, new in EDITS:
    o = A
    for p in path:
        o = o[p]
    v = o[key]
    hit = [x for x in olds if x in v]
    if hit:
        assert v.count(hit[0]) == 1, (path, key)
        o[key] = v.replace(hit[0], new)
        changed.append("/".join(str(p) for p in path) + "/" + key)
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
