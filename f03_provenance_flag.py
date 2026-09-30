#!/usr/bin/env python3
"""f03_provenance_flag.py (M307): idempotent post-pass. Injects f03_provenance.json (built by tools/f03_provenance_build.py from script outputs)
into summary_arrays.json as `provenanceSensitivity` so the degradation tab can render the F03 notice from a computed S.* key (no literals).
Must run after the other post-pass scripts (see apply_m284_post.sh). Run from the directory holding summary_arrays.json."""
import copy, json, os
ARR, SRC = "summary_arrays.json", "f03_provenance.json"
arr = json.load(open(ARR, encoding="utf-8"))
src = json.load(open(SRC, encoding="utf-8"))
arr["provenanceSensitivity"] = src
stamps = arr.get("_artifactStamps")
if isinstance(stamps, dict) and "provenanceSensitivity" not in stamps and "records" in stamps:   # stamp once (same corpus identity)
    st = copy.deepcopy(stamps["records"])
    if isinstance(st, dict):
        st["computationStatusNote"] = ("M307: F03 provenance-sensitivity notice injected by f03_provenance_flag.py from f03_provenance.json "
                                       "(tools/f03_provenance_build.py); no recomputation of any published value.")
        stamps["provenanceSensitivity"] = st
json.dump(arr, open(ARR, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("provenanceSensitivity injected:", src, "->", ARR)
