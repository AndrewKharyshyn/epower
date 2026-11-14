"""M655: integrationScenarios.capacityReferences[G1].factor equals exposureBasis.factor.aggregateRatedOverLegacy (it says 'read from exposureBasis'), exposure_basis_refresh runs before integration_scenarios, and the
declared read is enforced by the stage lint (the swapped order is rejected). Run: python tests/synthetic/test_m655_integration_factor.py"""
import copy, json, os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import stage_order as SO
A = json.load(open("summary_arrays.json", encoding="utf-8"))
g1 = [c for c in A["integrationScenarios"]["capacityReferences"] if c["id"] == "G1"][0]
assert g1["factor"] == A["exposureBasis"]["factor"]["aggregateRatedOverLegacy"], (g1["factor"], A["exposureBasis"]["factor"])
r = subprocess.run([sys.executable, "tools/m655_integration_factor.py", "--dry-run"], capture_output=True, text=True)
assert r.returncode == 0 and '"changed": false' in r.stdout, r.stdout
stages = SO.load_stages("tools/ingest_stages.json"); ids = [s["id"] for s in stages]
assert ids.index("capacity_basis") < ids.index("exposure_basis_refresh") < ids.index("integration_scenarios") < ids.index("stamp_basis")
sw = copy.deepcopy(stages); i, j = ids.index("exposure_basis_refresh"), ids.index("integration_scenarios"); sw[i], sw[j] = sw[j], sw[i]
res = SO.lint(sw, ROOT, file_level=False)
assert not res["ok"] and any(v["kind"] == "declared_read_before_write" and v["stage"] == "integration_scenarios" for v in res["violations"]), res
print("PASS test_m655_integration_factor")
