#!/usr/bin/env python3
"""rebaseline_restamp.py (M285c): re-issue corpus-hash stamps after the 187th-column re-baseline.

Usage: rebaseline_restamp.py ARRAYS.json OLD_MD5 NEW_MD5 REFIT_BLOCK.json
Only valid when the master change is a pure column addition proven numerically invariant (Category-A diff old vs new master:
identical except corpusHash/generatedAt and evidenceLedger identity). Replaces the corpus MD5 (32-hex and 12-hex short forms)
wherever it is stamped, swaps in the regenerated masterRefitAudit block, and annotates every re-issued stamp.
"""
import json, sys
p, old, new, refit = sys.argv[1:5]
A = json.load(open(p)); R = json.load(open(refit))
assert R["publishedMasterMD5"] == new
n32 = n12 = 0
def fix(x):
    global n32, n12
    if isinstance(x, dict): return {k: fix(v) for k, v in x.items()}
    if isinstance(x, list): return [fix(v) for v in x]
    if isinstance(x, str):
        if x == old: n32 += 1; return new
        if x == old[:12]: n12 += 1; return new[:12]
    return x
A["masterRefitAudit"] = R
A = fix(A)
A["masterRefitAudit"]["rebaseline"] = {
    "milestone": "M285c", "fromCorpusHash": old, "toCorpusHash": new,
    "change": "published the 187th master column highspeed_discharge_longest_run_s_130p (M271 deferral); all other columns byte-identical (column-drop round trip)",
    "invariance": "Category-A rebuild (53 blocks) on old vs new master identical apart from corpusHash/generatedAt/evidenceLedger identity; seasonal_arrays identical",
    "note": "Stamps carrying rebaselinedFrom were re-issued, not recomputed: their numerics are invariant under the column addition."}
k = 0
for name, st in A["_artifactStamps"].items():
    if isinstance(st, dict) and st.get("corpusHash") == new:
        st["rebaselinedFrom"] = old[:8]; k += 1
json.dump(A, open(p, "w"), ensure_ascii=False, indent=1)
print("replaced 32-hex:", n32, "12-hex:", n12, "stamps annotated:", k)
