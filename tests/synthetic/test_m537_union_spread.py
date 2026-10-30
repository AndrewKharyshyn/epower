"""M537 (analyses/M537_spec.md Rev 2): the union spread over the M532 and M534 configurations. The numbers are recomputed here from the two JSON files themselves (no producer helper for them): 41 unique
(pool seed, seed offset, pool size) configurations / 82 era configurations, duplicates checked equal, era-mean ranges, zero-including counts, per-arm SDs and ratios, both source SHA-256; the statement binds the leaf;
negative controls: hash mismatch, control mismatch, fallback sentence, stale basis; rule; the leaf stays out of verify_declared; splice idempotent."""
import hashlib, json, os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
F32, F34 = "analyses/M532_emulation_seed_sensitivity.json", "analyses/M534_pool_seed_size.json"
r32, r34 = open(F32, "rb").read(), open(F34, "rb").read()
J32, J34 = json.loads(r32.decode("utf-8")), json.loads(r34.decode("utf-8"))
A = json.load(open("summary_arrays.json", encoding="utf-8"))
E_ = ("fast1", "fast2")
OM = "mΩ"
mean = lambda r, e: r["paired"][e]["meanUnrounded"]
conf = {}
for r in J32["replicates"]:
    conf.setdefault((r["poolSeed"], r["seedOffset"], 40), r)
dups = 0
for r in J34["replicates"]:
    k = (r["poolSeed"], r["seedOffset"], r["poolSize"])
    if k in conf:
        dups += 1
        assert all(abs(mean(conf[k], e) - mean(r, e)) < 1e-9 and conf[k]["paired"][e]["ci95"] == r["paired"][e]["ci95"] for e in E_), k          # duplicates are numerically equal
    else:
        conf[k] = r
assert len(conf) == 41 and dups == 5            # 11 M532 + 10 P + 10 S + 5 N20 + 5 N80; the M534 control and the 4 N40 runs duplicate
cs = list(conf.values())
rng = {e: (min(abs(mean(c, e)) for c in cs), max(abs(mean(c, e)) for c in cs)) for e in E_}
zero = {e: sum(1 for c in cs if c["paired"][e]["ci95"][0] <= 0 <= c["paired"][e]["ci95"][1]) for e in E_}
sd = lambda f, e: float(np.std([mean(r, e) for r in J34["replicates"] if f(r["id"])], ddof=1))
ratio = {e: sd(lambda i: i.startswith("P_"), e) / sd(lambda i: i.startswith("S_") or i == "P_R7_k0", e) for e in E_}
assert all(0.5 <= v <= 2 for v in ratio.values())
for loc in (A["powerFade"]["cadenceSensitivity"], A["fadeModes"]["power"]["trend"]["cadenceSensitivity"]):
    u = loc["emulation"]["seedSensitivity"]["unionOverStudies"]
    assert u["status"] == "ok" and u["nConfigurations"] == 41 and u["nEraConfigurations"] == 82 and u["nDuplicatesCheckedEqual"] == 5 and u["stale"] is False
    assert u["sourceSha256"] == {"M532": hashlib.sha256(r32).hexdigest(), "M534": hashlib.sha256(r34).hexdigest()}
    for e in E_:
        assert abs(u["eraMeanRangeMohm"][e][0] - rng[e][0]) < 6e-4 and abs(u["eraMeanRangeMohm"][e][1] - rng[e][1]) < 6e-4 and u["intervalIncludesZeroByEra"][e] == zero[e]
        assert abs(u["attribution"][e]["ratio"] - ratio[e]) < 2e-3 and u["attribution"][e]["withinBand"] is True
    assert u["nIntervalIncludesZero"] == sum(zero.values()) and u["nEraMeansNegative"] == 82 and u["nByArm"] == {"M532": 11, "P": 10, "S": 10, "N20": 5, "N80": 5}
    assert u["poolSizes"] == [20, 40, 80] and u["loseRange"] == [min(c["nLose"] for c in cs), max(c["nLose"] for c in cs)]
    arm_min = min(u["rangeByArm"][a][e][0] for a in u["rangeByArm"] for e in E_)
    arm_max = max(u["rangeByArm"][a][e][1] for a in u["rangeByArm"] for e in E_)
    assert arm_min == min(u["eraMeanRangeMohm"][e][0] for e in E_) and arm_max == max(u["eraMeanRangeMohm"][e][1] for e in E_)               # a union bound is never outside the per-arm extremes
    st = loc["statement"]
    want = ("across 41 slow-pool configurations (11 coupled draws and seeds, M532; 30 single-factor and pool-size runs of 20, 40 or 80 slow drives, M534)",
            "the era-mean lowering spans %.1f-%.1f %s (fast1) and %.1f-%.1f %s (fast2) (min / max across configurations, descriptive, not an interval)" % (rng["fast1"][0], rng["fast1"][1], OM, rng["fast2"][0], rng["fast2"][1], OM),
            "the paired interval includes zero in %d of 82 era configurations (fast1 %d, fast2 %d)" % (sum(zero.values()), zero["fast1"], zero["fast2"]),
            "the spread cannot be apportioned between the pool draw and the seeds (standard-deviation ratio %.1f and %.1f, not resolved at 10 replicates per arm)" % (ratio["fast1"], ratio["fast2"]), "not a causal cadence effect")
    assert all(w in st for w in want), [w for w in want if w not in st]
    assert "across 11 slow-pool draws and seeds (reference draw included)" not in st and "previous basis" not in st and " ;" not in st
for h in (A["powerFade"], A["fadeModes"]["power"]["trend"]):
    assert h["note"].endswith(h["cadenceSensitivity"]["statement"])
# A2: the leaf is not an estimate
for f in ("tools/stamp_dependencies.json", "release_check.py", "tools/stamp_dependencies_apply.py"):
    assert "unionOverStudies" not in open(f, encoding="utf-8").read(), f
import compute_summary_arrays as C
emu = C._powerfade_emulation_snapshot(274)
assert emu["seedSensitivity"]["unionOverStudies"]["status"] == "ok"
sha = emu["seedSensitivity"]["unionOverStudies"]["sourceSha256"]
assert C._powerfade_union_over_studies(emu, sha)["status"] == "ok"
bad = C._powerfade_union_over_studies(emu, {"M532": sha["M532"], "M534": "0" * 64})
assert bad["status"] == "not_available" and "SHA-256" in bad["reason"]
mism = json.loads(json.dumps(emu)); mism["nFastClean"] += 1
assert C._powerfade_union_over_studies(mism)["status"] == "not_available"
# stale and not_available inherit independently
st_emu = C._powerfade_emulation_snapshot(275)
assert st_emu["stale"] is True and st_emu["seedSensitivity"]["unionOverStudies"]["stale"] is True
cs0 = {k: v for k, v in A["powerFade"]["cadenceSensitivity"].items() if k not in ("emulation", "statement")}
s_stale = C._powerfade_cadence_block(cs0, st_emu)["statement"]
assert "computed on the previous basis (274 clean drives)" in s_stale and "stale: the clean-drive count is now" in s_stale and "across 41 slow-pool configurations" in s_stale
fb = json.loads(json.dumps(emu)); fb["seedSensitivity"]["unionOverStudies"] = {"status": "not_available"}
s_fb = C._powerfade_cadence_block(cs0, fb)["statement"]
assert "across 11 slow-pool draws and seeds (reference draw included)" in s_fb and "the wider spread over the M534 configurations is not available on this build" in s_fb and "across 41" not in s_fb
s_na = C._powerfade_cadence_block(cs0, dict(emu, seedSensitivity={"status": "not_available"}))["statement"]
assert "sensitivity to the slow-pool draw and the seeds is not available on this build" in s_na and "across 41" not in s_na
# rule
import language_gate as G
R = {r.rid: r for r in G.RULES}["M537-cadence-union-spread"]
assert R.hits("lowers the proxy; across 11 slow-pool draws and seeds (reference draw included) the era-mean lowering spans 1.1-2.2") and R.hits("the spread is driven by the seeds") and R.hits("not attributable to the pool draw")
assert not R.hits(s_fb) and not R.hits(A["powerFade"]["cadenceSensitivity"]["statement"]) and not R.hits("the spread cannot be apportioned between the pool draw and the seeds")
def strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)
    elif isinstance(o, str): yield o
assert not [s for s in strings(A) if R.hits(s)]
import m537_cadence_splice as S
assert S.main(["--check"]) == 0
print("OK test_m537_union_spread: 41 / 82 configurations, independent recomputation, statement, negatives, rule, splice")
