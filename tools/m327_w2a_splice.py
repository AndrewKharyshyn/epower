#!/usr/bin/env python3
"""M327 (wording sweep W2a) exact-string edits (addendum analyses/M327_W2a_addendum.md, E9 + A1). Idempotent; asserts every old text appears the declared number
of times (or the new text is already present); touches no other string.
 * summary_arrays.json: leaf strings (registry label + the 'no sub-15 C' / 'whole corpus is warm-season' payload text and its copies of config text).
 * summary_config.json: the two hand-curated provenance strings (raw-text replacement; the rest of the file stays byte-identical).
Usage: python tools/m327_w2a_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR, CFG = os.path.join(ROOT, "summary_arrays.json"), os.path.join(ROOT, "summary_config.json")
COLD_TAIL = "the cold tail below the lowest logged pack-probe reading is modelled, not observed"
EDITS = [  # (old, new, expected count in arrays leaves)
    ("no sub-15 C pack data exists", COLD_TAIL, 1),
    ("(no sub-15C pack data in corpus; assumption-driven, superseded by real winter logs)", "(" + COLD_TAIL + "; assumption-driven, superseded by real winter logs)", 1),
    ("No sub-15 C data exists (warm-season corpus) -- this characterises the warm end of the range only.",
     "Ambient below ~15 C is thinly observed (the Cold class is below minimum support) -- this characterises the warm end of the range only.", 1),
    ("no sub-15C pack data exists in the corpus. ", COLD_TAIL + ". ", 1),
    ("because the corpus contains no sub-15C pack data;", "because " + COLD_TAIL + ";", 1),
    ("the whole corpus is warm-season, so pack thermal exposure is characterised directly",
     "the logged corpus is almost entirely Warm and Shoulder ambient class (Cold-class drives are below minimum support), so pack thermal exposure is characterised directly for that range", 1),   # seasonalLife.assumptions.hotTail._provenance
    ("whole corpus is warm-season, so pack thermal exposure is characterised directly",
     "the logged corpus is almost entirely Warm and Shoulder ambient class (Cold-class drives are below minimum support), so pack thermal exposure is characterised directly for that range", 1),   # seasonalLife.hotTail.note (builder text)
]
CFG_EDITS = [(o, n) for o, n, _ in (EDITS[4], EDITS[5])]


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
# registry label (E9)
hit = [x for x in A["assumptionsRegistry"]["entries"] if x.get("id") == "thermal_regime_bins"]
assert len(hit) == 1
OLDL, NEWL = "Seasonal cohort thresholds (drive-mean ambient)", "Ambient thermal regime thresholds (drive-mean ambient)"
if hit[0]["label"] == OLDL:
    hit[0]["label"] = NEWL; changed.append("assumptionsRegistry.thermal_regime_bins.label")
else:
    assert hit[0]["label"] == NEWL
for old, new, cnt in EDITS:
    leaves = [(c, k) for c, k in walk(A) if old in c[k] and new not in c[k]]
    if not leaves:
        assert any(new in c[k] for c, k in walk(A)), ("neither old nor new text found", old[:60])
        continue
    assert len(leaves) == cnt, (old[:60], len(leaves), cnt)
    for c, k in leaves:
        c[k] = c[k].replace(old, new); changed.append(old[:40])
# config (raw text, exact)
raw = open(CFG, encoding="utf-8", newline="").read()
craw = raw
for old, new in CFG_EDITS:
    if old in craw:
        assert craw.count(old) == 1, (old[:60], craw.count(old))
        craw = craw.replace(old, new); changed.append("config:" + old[:40])
if "--dry-run" not in sys.argv:
    if any(not x.startswith("config:") for x in changed):
        with open(ARR, "w", encoding="utf-8", newline="\n") as f:
            json.dump(A, f, ensure_ascii=False, indent=1)
    if craw != raw:
        open(CFG, "w", encoding="utf-8", newline="").write(craw)
print(json.dumps({"changed": changed, "n": len(changed)}))
