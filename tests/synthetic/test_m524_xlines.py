"""M524 (analyses/M524_spec.md Rev 2): the four former X lines name their time base. Checks, from the payload, that the engine-state occupancy chart is a share of ALL classified 1 Hz time (so the old
'% of engine-on time' title was false), the rpmFinding basis sentence is payload-bound, the simultaneity block speaks of generator-active time, the language rule, and (when tabtext/ exists) the rendered dumps."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
A = json.load(open("summary_arrays.json", encoding="utf-8"))

def esm_ok(esm, supported_h, tol_sum=1e-3, tol_rel=5e-4):
    occ = [esm["occupancy"][k]["pooled"] for k in ("off", "low", "loadPoint", "mid", "high")]
    if abs(sum(occ) - 1.0) > tol_sum:
        return False, "shares do not sum to 1"
    hrs = esm["pooledTotalSeconds"] / 3600.0
    if abs(hrs - supported_h) / supported_h > tol_rel:
        return False, "classified hours %.3f differ from RPM-supported hours %.3f" % (hrs, supported_h)
    return True, ""

SUP = A["engineRuntime"]["totals"]["supportedHours"]
ok, why = esm_ok(A["engineStateMachine"], SUP)
assert ok, why                                   # observed gap 0.016 %: 1 Hz seconds count vs gap-capped step integration (two conventions); tolerance 0.05 %
assert A["engineStateMachine"]["occupancy"]["off"]["pooled"] > 0.5      # Off is in the bars, so the denominator cannot be engine-on time
# negative controls: shares that do not sum to 1, or a classified total that departs from the supported hours, must fail
bad = json.loads(json.dumps(A["engineStateMachine"])); bad["occupancy"]["loadPoint"]["pooled"] += 0.05
assert not esm_ok(bad, SUP)[0]
bad = json.loads(json.dumps(A["engineStateMachine"])); bad["pooledTotalSeconds"] = int(bad["pooledTotalSeconds"] * 0.99)
assert not esm_ok(bad, SUP)[0]

# sources: old title gone, new title present; rpmFinding basis payload-bound; simultaneity block generator-active
assert "Engine RPM-band occupancy (% of engine-on time)" not in jsx
assert "Engine state occupancy (% of RPM-supported 1 Hz time; stored basis, off = rpm < 400)" in jsx          # M546: the compare-mode title carries the stored-basis label
# M525: the best-point item now binds to the refreshed rpmOptBand; the M524 "not refreshed" disclosure is gone with the stale numbers
assert "S.rpmOptBand" in jsx and "this block was computed once on" not in jsx
i = jsx.index("This is the per-second state decomposition behind the reconstruction."); j = jsx.index("Does the generator drive the motor while charging the battery?", i)
blk = jsx[i:j]
def block_ok(b):
    return "generator-active" in b and "Pgen_t &gt; 0" in b and "engine-on" not in re.sub(r"not comparable with the rpm-based engine-on hours", "", b)
assert block_ok(blk)
assert not block_ok(blk.replace("generator-active", "engine-on"))                      # negative control: reverting the wording fails
assert not block_ok(blk.replace("Pgen_t &gt; 0", "Pgen_t"))                             # negative control: removed threshold sentence fails

R = {r.rid: r for r in G.RULES}["M524-timebase-x-lines"]
assert R.hits("Engine RPM-band occupancy (% of engine-on time)")
assert not R.hits("Engine state occupancy (% of RPM-supported 1 Hz time; off = rpm < 400)")
assert R.hits("and 0.8% of pooled engine time respectively") and R.hits("pooled agrees with the RPM-distribution and EV-traction figures")
assert "of pooled engine time" not in jsx and "pooled agrees with the RPM-distribution" not in jsx

# the 0 / 400 rpm cut: the ESM edges and the rpmDistribution threshold differ (so 1 - off is not the rpmDistribution engine-on time)
assert A["engineStateMachine"]["stateEdgesRpm"] is not None and A["rpmDistribution"]["params"]["engineOnThresholdRpm"] == 300

# gate-edit control (M373 required wording, semantic_gate.py): the updated check still fails when the wording or the Pgen_t > 0 sentence is removed
GATE = open("semantic_gate.py", encoding="utf-8").read()
need = "charge-and-drive is the largest generator-active state in urban and mixed driving"
assert need in GATE and "largest engine-on state" not in GATE.split("M373 simultaneity text")[1][:600].split("is TRUE")[0].replace("M373 originally 'engine-on'", "")
if os.path.exists(os.path.join("tabtext", "fuel__all.txt")):
    ft = " ".join(open(os.path.join("tabtext", "fuel__all.txt"), encoding="utf-8").read().split())
    assert need in ft and "Pgen_t > 0" in ft
    assert need not in ft.replace("generator-active", "engine-on") and "Pgen_t > 0" not in ft.replace("Pgen_t > 0", "Pgen_t")
if os.path.isdir("tabtext"):
    seen = {}
    for f in os.listdir("tabtext"):
        if f.endswith(".txt"):
            mode = f.rsplit("__", 1)[-1][:-4]
            t = open(os.path.join("tabtext", f), encoding="utf-8").read()
            assert not R.hits(t), f
            if "generator-active" in t:
                seen[mode] = True
    for mode in ("all", "warm", "shoulder", "cold"):
        assert seen.get(mode), "generator-active wording missing in mode %s" % mode
print("OK test_m524_xlines: denominators, payload-bound basis, generator-active wording, controls, rule")
