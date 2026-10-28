"""M533 (analyses/M533_spec.md Rev 2): the reference-draw statement and the additive leaf group emulation.seedSensitivity. The numbers are recomputed here from the M532 JSON itself
(no producer helper is imported for them): A1 payload leaves = independent recomputation + source SHA-256; the statement binds them; A2 the leaf stays out of verify_declared and the
CI-checkable estimate set; negative controls: missing file, hash mismatch, control mismatch (not_available), stale basis (stale clause); the language rule; splice idempotent."""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))

F = "analyses/M532_emulation_seed_sensitivity.json"
raw = open(F, "rb").read()
J = json.loads(raw.decode("utf-8"))
A = json.load(open("summary_arrays.json", encoding="utf-8"))
reps = J["replicates"]
lo = lambda e: min(abs(r["paired"][e].get("meanUnrounded", r["paired"][e]["mean"])) for r in reps)
hi = lambda e: max(abs(r["paired"][e].get("meanUnrounded", r["paired"][e]["mean"])) for r in reps)
zero = {e: sum(1 for r in reps if r["paired"][e]["ci95"][0] <= 0 <= r["paired"][e]["ci95"][1]) for e in ("fast1", "fast2")}
neg = sum(1 for r in reps for e in ("fast1", "fast2") if r["paired"][e]["mean"] < 0)

for loc in (A["powerFade"]["cadenceSensitivity"], A["fadeModes"]["power"]["trend"]["cadenceSensitivity"]):
    ss = loc["emulation"]["seedSensitivity"]
    assert ss["status"] == "ok" and ss["source"] == "M532" and ss["sourceSha256"] == hashlib.sha256(raw).hexdigest()          # A1 incl. source hash
    assert ss["nReplicates"] == len(reps) == 11 and ss["nEraReplicates"] == 22 and ss["referenceIsControl"] is True and ss["controlMatchesSnapshot"] is True
    for e in ("fast1", "fast2"):
        assert abs(ss["eraMeanRangeMohm"][e][0] - lo(e)) < 6e-4 and abs(ss["eraMeanRangeMohm"][e][1] - hi(e)) < 6e-4, e
        assert ss["intervalIncludesZeroByEra"][e] == zero[e]
    assert ss["nIntervalIncludesZero"] == sum(zero.values()) == 2 and ss["nEraMeansNegative"] == neg == 22
    assert ss["loseRange"] == [min(r["nLose"] for r in reps), max(r["nLose"] for r in reps)] == [27, 31]
    assert ss["poolSeeds"] == J["poolSeeds"] and ss["stale"] is False and ss["basisNClean"] == 274
    st = loc["statement"]
    want = ("In the reference draw, emulated slow-cadence thinning", "across %d slow-pool draws and seeds (reference draw included) the era-mean lowering spans %.1f-%.1f mΩ (fast1) and %.1f-%.1f mΩ (fast2)"
            % (len(reps), lo("fast1"), hi("fast1"), lo("fast2"), hi("fast2")),
            "the paired interval includes zero in %d of 22 era replicates (fast1 %d, fast2 %d)" % (sum(zero.values()), zero["fast1"], zero["fast2"]), "not a causal cadence effect")
    assert all(w in st for w in want), [w for w in want if w not in st]
    assert " ;" not in st and "previous basis" not in st

# the notes carry the same tail
for h in (A["powerFade"], A["fadeModes"]["power"]["trend"]):
    assert h["note"].endswith(h["cadenceSensitivity"]["statement"])

# A2: the leaf is not an estimate: absent from verify_declared dependencies and the CI-checkable set
for f in ("tools/stamp_dependencies.json", "release_check.py", "tools/stamp_dependencies_apply.py"):
    assert "seedSensitivity" not in open(f, encoding="utf-8").read(), f
import compute_summary_arrays as C
emu = C._powerfade_emulation_snapshot(274)
assert emu["seedSensitivity"]["status"] == "ok"
# negative controls
ok = emu["seedSensitivity"]
assert C._powerfade_seed_sensitivity(emu, ok["sourceSha256"])["status"] == "ok"
bad = C._powerfade_seed_sensitivity(emu, "0" * 64)
assert bad["status"] == "not_available" and "SHA-256" in bad["reason"]
mism = json.loads(json.dumps(emu)); mism["nFastLoseProxy"] += 1
assert C._powerfade_seed_sensitivity(mism)["status"] == "not_available"
st_emu = C._powerfade_emulation_snapshot(275)
assert st_emu["stale"] is True and st_emu["seedSensitivity"]["stale"] is True
cs = {k: v for k, v in A["powerFade"]["cadenceSensitivity"].items() if k not in ("emulation", "statement")}
s_stale = C._powerfade_cadence_block(cs, st_emu)["statement"]
assert "computed on the previous basis (274 clean drives)" in s_stale and "stale: the clean-drive count is now" in s_stale          # A5
s_na = C._powerfade_cadence_block(cs, dict(emu, seedSensitivity={"status": "not_available"}))["statement"]
assert "sensitivity to the slow-pool draw and the seeds is not available on this build" in s_na and "across 11" not in s_na
# rule
import language_gate as G
R = {r.rid: r for r in G.RULES}["M533-cadence-reference-draw"]
assert R.hits("no fade rate is claimed. Emulated slow-cadence thinning (each column") and R.hits("the span interval is wide") and R.hits("the interval of the span")
assert not R.hits("no fade rate is claimed. In the reference draw, emulated slow-cadence thinning (each") and not R.hits("spans 1.1-2.2 mΩ (fast1) and the paired interval includes zero in 2 of 22")
def strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)
    elif isinstance(o, str): yield o
assert not [s for s in strings(A) if R.hits(s)] and "no fade rate is claimed. Emulated slow" not in open("xtrail_dashboard.html", encoding="utf-8").read()
import m533_cadence_splice as S
assert S.main(["--check"]) == 0
print("OK test_m533_seed_sensitivity: leaf = independent recomputation, statement, A2, negatives, rule, splice")
