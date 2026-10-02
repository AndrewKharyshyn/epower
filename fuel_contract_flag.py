#!/usr/bin/env python3
"""fuel_contract_flag.py (M334): idempotent post-pass. Injects fuel_contract.json (built by tools/fuel_contract.py from raw headers/values, fuel_recon_master.csv and
model_constants) into summary_arrays.json as `fuelContract` so the Fuel tab banner renders from a computed S.* key (no literals), with an artifact stamp that records
the input hashes. Additive: touches only the `fuelContract` key and its `_artifactStamps` entry. Must run BEFORE f03_provenance_flag.py (which stays last in
apply_m284_post.sh). Run from the directory holding summary_arrays.json."""
import copy, datetime, hashlib, json, os, sys
ARR, SRC = "summary_arrays.json", "fuel_contract.json"
arr = json.load(open(ARR, encoding="utf-8"))
src = json.load(open(SRC, encoding="utf-8"))
live = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
assert src["inputs"]["driveMasterMd5"] == live, "fuel_contract.json was built against a different drive_master.csv; rerun tools/fuel_contract.py"
assert src["inputs"]["fuelReconMasterMd5"] == hashlib.md5(open("fuel_recon_master.csv", "rb").read()).hexdigest(), "fuel_contract.json is stale vs fuel_recon_master.csv"
arr["fuelContract"] = src
stamps = arr.get("_artifactStamps")
_old = (stamps or {}).get("fuelContract") if isinstance(stamps, dict) else None
if isinstance(_old, dict) and _old.get("upstreamHashes") == src["inputs"] and _old.get("corpusHash") == live:
    pass                                    # idempotent: same inputs -> keep the existing stamp (and its timestamp) byte-identical
elif isinstance(stamps, dict) and "records" in stamps:
    st = copy.deepcopy(stamps["records"])
    if isinstance(st, dict):
        st.update(corpusHash=live, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
                  computationStatusNote="M334: Fuel-tab disclosure block injected by fuel_contract_flag.py from fuel_contract.json (tools/fuel_contract.py); input hashes in fuelContract.inputs; no recomputation of any published value.",
                  upstreamHashes=dict(src["inputs"]))
        st.pop("carriedForward", None)
        stamps["fuelContract"] = st
with open(ARR, "w", encoding="utf-8", newline="\n") as f:
    json.dump(arr, f, ensure_ascii=False, indent=1)
print("fuelContract injected:", SRC, "->", ARR)
