#!/usr/bin/env python3
"""M550 (spec Rev 2 D9 + Rev 3 R4): the scripted, pre-registered audit-sample rule. Run AFTER extraction and BEFORE the auditor sees any value. 18 drives stratified by drive type x cadence regime (2 per cell, seed 42),
the 6 largest |gap| between the peak-power and the peak-current moments, and 3 late-tier drives (seed 42); duplicates are replaced from the stratified pool; tie drives (nTiesAtMinP > 1) are always included. Writes analyses/M550_audit_sample.json (file keys only, no value)."""
import datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import power_peak_temp as P
dm, recs, _ = P.load_records()
ok = {f: r for f, r in recs.items() if r.get("ok")}
rng = np.random.default_rng(42)
dtype = dict(zip(dm.file, dm.drive_type.fillna("unknown")))
cells = {}
for f, r in sorted(ok.items()):
    cells.setdefault((dtype.get(f, "unknown"), r["cadence"]), []).append(f)
strat = []
for k, v in sorted(cells.items()):
    strat += sorted(rng.choice(v, size=min(2, len(v)), replace=False).tolist())
gaps = sorted((f for f, r in ok.items() if r.get("gapS") is not None), key=lambda f: (-abs(ok[f]["gapS"]), f))[:6]
late = sorted(f for f, r in ok.items() if P._cls(r.get("ageKwS")) == "late")
late3 = sorted(rng.choice(late, size=min(3, len(late)), replace=False).tolist())
ties = sorted(f for f, r in ok.items() if r.get("nTiesAtMinP", 1) > 1)
files = sorted(set(gaps) | set(late3) | set(ties))
for f in strat:
    if len(files) >= 27:
        break
    files = sorted(set(files) | {f})
out = {"spec": "analyses/M550_spec.md Rev 3 (R4 / D9)", "seed": 42, "rule": __doc__.split("\n")[1], "files": files, "gaps6": gaps, "late3": late3, "ties": ties, "strataCells": len(cells),
       "drawnAfterExtractionBeforeAuditor": True, "drawnAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "sha256": hashlib.sha256(json.dumps(files).encode()).hexdigest()}
json.dump(out, open("analyses/M550_audit_sample.json", "w", encoding="utf-8"), indent=1)
print(len(files), out["sha256"], len(gaps), len(late3), len(ties))
