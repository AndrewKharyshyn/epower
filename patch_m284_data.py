#!/usr/bin/env python3
"""M284 data patch: (1) derived GTR limitations[0:2]; (2) determinism harness scope labels
(ml16_determinism_check) in config + arrays; (3) assumptionsRegistry (via builder)."""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd
from derived_literals import gtr_limitations_head
import build_assumptions_registry as BAR

ARR, CFG, DM = "summary_arrays.json", "summary_config.json", "drive_master.csv"
arr = json.load(open(ARR)); cfg = json.load(open(CFG))
dm = pd.read_csv(DM, low_memory=False)

# (1) limitations
l1, l2 = gtr_limitations_head(arr, float(dm["distance_km"].sum()), dm["drive_type"].value_counts().to_dict())
lim = arr["generatorTractionRecon"]["limitations"]
assert lim[0].startswith("Fuel-flow PID coverage is") and lim[1].startswith("Highway (n=")
lim[0], lim[1] = l1, l2

# (2) determinism scope labelling (verbatim copy convention: config block == arrays block)
HARNESS = "ml16_determinism_check"
SCOPE = ("ML16 ensemble-outlier labelling stage only (postprocess_master -> ens_* columns). "
         "Not a whole-pipeline determinism proof; see reproducibilityScope for what is not covered.")
for blk in (cfg["auditMetadata"]["determinism"], arr["determinism"]):
    blk["harness"] = HARNESS
    blk["scopeLabel"] = SCOPE
    blk["releaseTest"] = ("release_check.py (M284) covers clean-environment front-end rebuild, validation and derived-artefact "
                          "consistency; a raw-CSV -> drive_master rebuild in a clean environment remains OPEN.")

# (3) registry
E_ = BAR.build(cfg, arr); BAR.validate(E_)
arr["assumptionsRegistry"] = {
    "_provenance": "M284 (2026-09-19; audit Section 8). Built by build_assumptions_registry.py from model_constants.py, "
                   "summary_config.json (vehicle, kExponentLadder) and summary_arrays (constantProvenance, seasonalCharts._meta). "
                   "Values are read from source, not retyped; test_assumptions_registry.py re-derives every entry.",
    "nEntries": len(E_), "nUnverified": sum(1 for e in E_ if not e["verified"]), "entries": E_}

json.dump(cfg, open(CFG, "w"), ensure_ascii=False, indent=1)
import hashlib, datetime, copy
cfg_md5 = hashlib.md5(open(CFG, "rb").read()).hexdigest()
st = arr["_artifactStamps"]
# idempotent: reuse the first M284 stamp time on re-runs
now = st.get("assumptionsRegistry", {}).get("generatedAt") or datetime.datetime.now(datetime.timezone.utc).isoformat()
note = "M284 (2026-09-19): "
# new key: stamp cloned from constantProvenance (same corpus/config provenance), config hash of the M284 config
st["assumptionsRegistry"] = dict(copy.deepcopy(st["constantProvenance"]), generatedAt=now, fullConfigHash=cfg_md5,
    computationStatus="computed", computationStatusNote=note + "typed assumptions registry built by build_assumptions_registry.py; corpusHash unchanged.")
for k, why in (("determinism", "harness/scope/release-test labelling only; no recomputation."),
               ("generatorTractionRecon", "limitations[0:2] now derived from arrays (derived_literals.py); no numeric change.")):
    prev = st[k].get("computationStatusNote", "")
    if note in prev:
        continue  # M285: already stamped; do NOT re-stamp (it reset generatedAt over later refreshes -> post-step was not a no-op)
    st[k] = dict(st[k], generatedAt=now, fullConfigHash=cfg_md5,
                 computationStatusNote=(prev + " | " if prev else "") + note + why + " corpusHash unchanged.")
json.dump(arr, open(ARR, "w"), ensure_ascii=False, indent=1)
print(l1); print(l2); print("registry", len(E_))
