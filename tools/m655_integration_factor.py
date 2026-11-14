#!/usr/bin/env python3
"""M655: set integrationScenarios.capacityReferences[G1].factor to exposureBasis.factor.aggregateRatedOverLegacy (the leaf says 'read from exposureBasis'; it had been read before the exposureBasis refresh ran, 1.1583 against 1.1582).
Exact-leaf edit, deep-diff guarded, idempotent; the stage order is fixed separately (exposure_basis_refresh now runs before integration_scenarios). Usage: python tools/m655_integration_factor.py [--dry-run]"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
P = os.path.join(ROOT, "summary_arrays.json")
raw = open(P, "rb").read().decode("utf-8")
A = json.loads(raw); old = copy.deepcopy(A)
g1 = [c for c in A["integrationScenarios"]["capacityReferences"] if c["id"] == "G1"]
assert len(g1) == 1 and g1[0]["status"] == "read from exposureBasis"
g1[0]["factor"] = A["exposureBasis"]["factor"]["aggregateRatedOverLegacy"]
chk = copy.deepcopy(A); [c for c in chk["integrationScenarios"]["capacityReferences"] if c["id"] == "G1"][0]["factor"] = [c for c in old["integrationScenarios"]["capacityReferences"] if c["id"] == "G1"][0]["factor"]
assert chk == old, "unexpected change"
if "--dry-run" in sys.argv or A == old:
    print(json.dumps({"changed": A != old, "factor": g1[0]["factor"]})); sys.exit(0)
open(P, "wb").write(json.dumps(A, ensure_ascii=False, indent=1).encode("utf-8") + (b"\n" if raw.endswith("\n") else b""))
print(json.dumps({"changed": True, "factor": g1[0]["factor"]}))
