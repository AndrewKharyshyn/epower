#!/usr/bin/env python3
"""M332 (wording sweep W1a) exact-string leaf edits of summary_arrays.json (addendum analyses/M332_W1a_addendum.md, P1-P5). The generatorTractionRecon
glossary / regimeTable / limitations blocks are carried payload with no reproducing builder (stamp carriedFromMaster), so they are changed here only;
metricConvention.note is also changed at its builder (compute_summary_arrays.py). Idempotent; asserts each old text (or the new text already present); touches no
other string.  Usage: python tools/m332_w1a_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
A = json.load(open(ARR, encoding="utf-8"))
G = A["generatorTractionRecon"]
# (container, key, old, new)
EDITS = [
    (G["glossary"][5], "meaning",
     "Two independent generator-output estimates: Path A from vehicle speed/road-load, Path B (primary, used for headline figures) from measured fuel flow through the BSFC surface.",
     "Two generator-output estimates with shared priors: Path A from vehicle speed/road-load, Path B (primary, used for headline figures) from the logged (app-calculated) fuel rate through the assumed BSFC surface."),
    (G["glossary"][3], "meaning",
     "Engine brake-thermal efficiency: mechanical output ÷ fuel chemical energy.",
     "Model-derived engine-brake/fuel ratio (implied by the assumed BSFC surface): mechanical output ÷ fuel chemical energy."),
    (G["glossary"][4], "term", "η tank→bus", "Net traction-bus/fuel index"),
    (G["glossary"][4], "meaning",
     "Whole-chain efficiency from fuel chemical energy to electricity actually reaching the HV bus (includes generator + power-electronics losses).",
     "Model-derived index of electricity reaching the HV bus per fuel chemical energy (implied by the assumed BSFC surface; includes generator + power-electronics losses; affected by SoC drift, regen and unmetered auxiliary loads)."),
    (G["regimeTable"][4], "note", "enrichment", "assumed high-load (boost proxy)"),
    (G["limitations"], 4, "Pearson r 0.997, ratio median 1.177 all identical, M280", "ratio median 1.177 and the correlation all identical, M280"),
    (G["limitations"], 4,
     "into near-agreement with the independent Path A road-load traction 17.45 — an independent corroboration of M265.)",
     "closer to the Path A road-load traction 17.45; Path A and Path B share priors, so this is not an independent check of M265.)"),
    (A["metricConvention"], "note",
     "charge/discharge asymmetry (round-trip loss), not a definitional difference",
     "charge-discharge imbalance (SoC drift, unlogged use, sensor-offset residual, auxiliaries), not a definitional difference"),
]
changed = []
for c, k, old, new in EDITS:
    v = c[k]
    if old == v or (old in v and old != "enrichment"):
        c[k] = v.replace(old, new) if old != v else new
        changed.append(old[:40])
    else:
        assert new in v, ("neither old nor new text found", old[:60])
if "--dry-run" not in sys.argv and changed:
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
print(json.dumps({"changed": changed, "n": len(changed)}))
