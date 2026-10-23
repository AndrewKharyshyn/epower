#!/usr/bin/env python3
"""M487 exact-string leaf edit of summary_arrays.json (audit Update 7 A03; language gate rule M487-cold-below-support): three payload strings still say the Cold class is
'below minimum support' (13 Cold drives analysed as a cohort against the minimum of 10; the real limitation is concentration, see cohortSupport).
  seasonalLife.hotTail.note, seasonalLife.assumptions.hotTail._provenance, auxLoadAmbient.interpretation
plus the RPM load-proxy calibration figure (98.3% recall / 0.33% contamination) is labelled a historical M89 calibration, not recomputed (5 loadProxyBasis leaves).
Idempotent; asserts old/new text; touches no other string or number.   Usage: python tools/m487_wording_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
EDITS = [
    (("seasonalLife", "hotTail"), "note", "Cold-class drives are below minimum support", "Cold-class drives are thinly observed and concentrated, see cohortSupport"),
    (("seasonalLife", "assumptions", "hotTail"), "_provenance", "Cold-class drives are below minimum support", "Cold-class drives are thinly observed and concentrated, see cohortSupport"),
    (("auxLoadAmbient",), "interpretation", "the Cold class is below minimum support", "the Cold class is thinly observed and concentrated, see cohortSupport"),
    (("rpmDistribution", "params"), "loadProxyBasis", "boost-covered corpus (98.3% recall", "boost-covered corpus (historical M89 calibration, not recomputed on the current corpus: 98.3% recall"),
] + [((("seasonalCharts", "charts", "RpmDistribution", "data", c, "params")), "loadProxyBasis", "boost-covered corpus (98.3% recall", "boost-covered corpus (historical M89 calibration, not recomputed on the current corpus: 98.3% recall") for c in ("all", "warm", "shoulder", "cold")]
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
        assert new in v, (path, key)
if "--dry-run" in sys.argv or not changed:
    print(json.dumps({"changed": changed, "dryRun": "--dry-run" in sys.argv})); sys.exit(0)
rt = json.dumps(json.loads(raw), ensure_ascii=False, indent=1)
if rt != raw and rt + chr(10) != raw:
    raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
with open(ARR, "w", encoding="utf-8", newline=chr(10)) as f:
    f.write(json.dumps(A, ensure_ascii=False, indent=1) + (chr(10) if raw.endswith(chr(10)) else ""))
print(json.dumps({"changed": changed}))
