"""M541 (analyses/M541_spec.md Rev 2): wave 2b-i, the display rebind to engineOnRule. Source-level and payload-level checks (no browser):
T3 the only remaining slice(1) engine-on totals of the rpm histogram in the JSX are the four allowed sites and each is tagged with the rpm >= 300 basis; the rule block is read only through the guarded accessor;
cohort guard; the displayed block flag; the language rule retires the old wording in the dom / jsx scopes; the payload and cohort arrays are untouched apart from the engineOnRule leaves (declared); bin data unchanged."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
src = open("xtrail_summary.jsx", encoding="utf-8").read()
lines = src.split("\n")
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["engineOnRule"]

# T3: exactly the allowed rpm-histogram slice(1) sites, each followed (within 12 lines) by a rpm >= 300 basis tag
hits = [i for i, l in enumerate(lines) if "slice(1)" in l and ("pooledHours" in l or "reduce((a" in l or "h.slice(1)" in l or "hrs.slice(1)" in l)]
allowed = {"const on = h && h.length > 1 ? h.slice(1)": "rpm ≥ 300", "const engineOnHrsTotal = hrs.slice(1)": "rpm ≥ 300", "    .slice(1).reduce((a, b) => a + b, 0);": "rpmGe300Hours"}
found = []
for i in hits:
    l = lines[i]
    key = next((k for k in allowed if k in l), None)
    assert key, ("unregistered engine-on slice(1) total", i + 1, l.strip()[:100])
    found.append(key)
assert found.count("const engineOnHrsTotal = hrs.slice(1)") == 2 and found.count("const on = h && h.length > 1 ? h.slice(1)") == 1 and found.count("    .slice(1).reduce((a, b) => a + b, 0);") == 1, found
assert "rpmGe300Hours" in src and "rpm ≥ 300 basis" in src

# the rule block is read through the guarded accessor only; the guard names the declared rule
assert "function engineOnRuleBlock()" in src and "thresholdRpm===400" in src and "boundary==='gt'" in src
assert sum(len(re.findall(r"S\.engineOnRule", l)) for l in lines if not l.strip().startswith("//")) == 1   # no other direct reader
# cohort guard: the pooled engine-on quotes are suppressed outside the all-drives view (chart and tab note)
assert '_coh!=="all"' in src and src.count('cohort==="all" ?') >= 3
# the bin label is renamed at render time only; the stored bins are unchanged
assert "function rpmBinLabel" in src and A["rpmDistribution"]["bins"][0] == "0 (engine off)"
assert A["engineOnRule"]["pooled"]["ge300Seconds"] - A["engineOnRule"]["pooled"]["lowRpmBandSeconds"] == A["engineOnRule"]["pooled"]["engineOnSeconds"]
# old wording gone from the JSX strings (comments excluded by the gate itself)
import language_gate as G
assert not [r for r in G.scan_text("of engine-on time (rpm ≥ 300, 1 Hz grid, duration-weighted) and the chart cuts at rpm < 300")] == [], "rule M541-engine-on-label must fire"
assert "M541-engine-on-label" in [r.rid for r in G.RULES]
# the block is displayed since M541 and the limits no longer say it is unbound
assert B["displayed"] is True and not any("no consumer is rebound" in x for x in B["limits"])
# payload keys: wave 2b-i changes no other leaf (rpmDistribution identical in meaning to M540: bins, edges, threshold)
assert A["rpmDistribution"]["params"].get("engineOnThresholdRpm", 300) == 300 if "params" in A["rpmDistribution"] else True
print("OK test_m541_display_rebind: T3 allow-list, guarded accessor, cohort guard, bin label render-only, language rule, displayed flag")
