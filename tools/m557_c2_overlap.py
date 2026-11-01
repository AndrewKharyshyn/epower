#!/usr/bin/env python3
"""M557 (Director follow-up): overlap between the 40 pool drives and the 100 slow-to-slower control drives of the cadence study, recomputed with the study's own selection code (tools/cadence_sensitivity.py lines for pool_keys and ctrl, seed 42)
on the CURRENT corpus. The stored M379b study ran on the corpus of its day; this is a recomputation of the selection, not a read of the stored keys (they are not stored). Writes analyses/M557_c2_overlap.json.
Usage: python tools/m557_c2_overlap.py"""
import json, os, sys, warnings
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
warnings.filterwarnings("ignore")
import numpy as np
import cadence_sensitivity as CS

dm, m, raw, ok = CS.setup()
slow_all = m[(m["regime"] == "slow") & m.index.isin(list(raw))]
slow_ok = m[ok & (m["regime"] == "slow")]
rng = np.random.default_rng(42)
pool = list(rng.choice(slow_all.index.values, 40, replace=False))
ctrl = list(rng.choice(slow_ok.index.values, 100, replace=False)) if len(slow_ok) >= 100 else list(slow_ok.index)
out = {"basis": "selection code of tools/cadence_sensitivity.py (seed 42) recomputed on the current corpus; the stored study keys are not available",
       "nSlowWithRaw": int(len(slow_all)), "nSlowOk": int(len(slow_ok)), "nPool": len(pool), "nControl": len(ctrl), "overlap": int(len(set(pool) & set(ctrl))), "overlapKeys": sorted(str(k) for k in set(pool) & set(ctrl))}
json.dump(out, open(os.path.join(ROOT, "analyses", "M557_c2_overlap.json"), "w", encoding="utf-8"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "overlapKeys"}))
