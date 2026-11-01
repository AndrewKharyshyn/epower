#!/usr/bin/env python3
"""M560 audit sample (spec Rev 2 R7): 30 V0 windows keyed by (drive, load-off timestamp): 10 fast, 10 slow and 10 edge cases (a removed second inside the window, a filled second at the onset, a negative magnitude), seed 42, drawn from the window-key emitter output BEFORE any variant result is read. Writes analyses/M560_audit_sample.json."""
import json, os
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
W = json.load(open(os.path.join(ROOT, "analyses", "M560_window_keys.json"), encoding="utf-8"))["windows"]
rng = np.random.default_rng(42)
plain = lambda s: [w for w in W if w["stratum"] == s and not (w["gapInside"] or w["onsetFilled"] or w["negative"])]
pick, used = [], set()
def take(pool, n, cat):
    idx = rng.permutation(len(pool))
    k = 0
    for ix in idx:
        w = pool[ix]
        if (w["file"], w["key"]) in used:
            continue
        used.add((w["file"], w["key"])); pick.append({**{k_: w[k_] for k_ in ("file", "key", "stratum", "day")}, "category": cat}); k += 1
        if k == n:
            break
take(plain("fast"), 10, "fast"); take(plain("slow"), 10, "slow")
for flag, n in (("gapInside", 3), ("onsetFilled", 3), ("negative", 4)):
    take([w for w in W if w[flag]], n, "edge_" + flag)
json.dump({"milestone": "M560", "seed": 42, "windows": pick, "counts": {c: sum(1 for p in pick if p["category"] == c) for c in sorted({p["category"] for p in pick})}}, open(os.path.join(ROOT, "analyses", "M560_audit_sample.json"), "w", encoding="utf-8"), indent=1)
print(len(pick), {c: sum(1 for p in pick if p["category"] == c) for c in sorted({p["category"] for p in pick})})
