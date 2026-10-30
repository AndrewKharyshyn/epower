"""M522 (analyses/M522_spec.md Rev 2): the 300-1400 rpm band occupancy text is bound to the payload. Extracts rpmBandOccupancyText from xtrail_summary.jsx and runs it in node with the real and patched payloads
(negative controls), checks the old literal is gone, the gate rule flags the old sentence and not the producer bin label, and (when tabtext/ exists) the rendered dumps in the five cohort modes."""
import json, os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
m = re.search(r"function rpmBandOccupancyText\(rd, floor, scope\)\{.*?\n\}\n", jsx, re.S)
assert m, "helper not found"
A = json.load(open("summary_arrays.json", encoding="utf-8"))
RD = A["rpmDistribution"]
FLOOR = RD["params"]["fuelStateRpmMin"]

def run(rd, floor, scope="pooled, all cohorts"):
    js = m.group(0) + "\nconsole.log(rpmBandOccupancyText(%s, %s, %s));" % (json.dumps(rd), json.dumps(floor), json.dumps(scope))
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()

h = RD["pooledHours"]; on = sum(h[1:])
exp = "(%.1f %% of rpm ≥ 300 time, pooled, all cohorts, %.1f h of %.1f h;" % (h[1] / on * 100, h[1], on)
base = run(RD, FLOOR)
assert exp in base and ("300-%s rpm band" % int(FLOOR)) in base, base
# (a) patched pooledHours[1] changes the text
rd2 = json.loads(json.dumps(RD)); rd2["pooledHours"][1] = h[1] * 2
assert run(rd2, FLOOR) != base and "%.1f %%" % (h[1] * 2 / (on + h[1]) * 100) in run(rd2, FLOOR)
# (b) patched floor changes the floor text
assert "300-1500 rpm band" in run(RD, 1500.0)
# guards: missing / zero / NaN -> n/a, never a literal
for bad in ({"pooledHours": []}, {"pooledHours": [1.0, None, 2.0]}, {"pooledHours": [1.0, 0.0, 0.0]}, {}, None):
    t = run(bad, FLOOR)
    assert "share n/a" in t and "%" not in t, (bad, t)
assert "300-n/a rpm band" in run(RD, None)
# C1 guard: a relabelled bins[1] (or a floor that disagrees with the label) renders n/a
for bl in ("1400-1475", "200-1400", "300-1500", "x"):
    rd3 = json.loads(json.dumps(RD)); rd3["bins"][1] = bl
    assert "share n/a" in run(rd3, FLOOR), bl
assert "in the shown cohort, exploratory" in run(RD, FLOOR, "in the shown cohort, exploratory")
# C1 guard: a relabelled bins[1] (or a floor that disagrees with the label) renders n/a
for bl in ("1400-1475", "200-1400", "300-1500", "x"):
    rd3 = json.loads(json.dumps(RD)); rd3["bins"][1] = bl
    assert "share n/a" in run(rd3, FLOOR), bl
assert "in the shown cohort, exploratory" in run(RD, FLOOR, "in the shown cohort, exploratory")
# (c) the gate flags the old sentences, not the producer bin label
R = {r.rid: r for r in G.RULES}["M522-band-occupancy"]
assert R.hits("with the 300-1400 rpm band near-empty (~4% of engine-on time, a transient rev-through, not a sustained band)")
assert R.hits("independently resolves as near-empty (~4% of engine-on time, a rev-through transient, M83)")
assert not R.hits("300-1400 (transient)") and not R.hits(base)
assert not R.hits("the best point band occupancy 63.4% of engine-on time falls in steady cruise")
# (d) the old literal is gone from the sources
assert "~4%" not in jsx and "~4%" not in open("summary_config.json", encoding="utf-8").read()
# rendered dumps (local only; tabtext/ is git-ignored). Cross-check site (pooled S.rpmDistribution): identical in all five modes. Chart site (cohort-aware, by design): follows its own cohort payload
# (seasonalCharts.charts.RpmDistribution.data[mode]); in all it equals the pooled text.
if os.path.isdir("tabtext"):
    SC = A["seasonalCharts"]["charts"]["RpmDistribution"]["data"]
    for mode in ("all", "warm", "shoulder", "cold", "compare"):
        p = os.path.join("tabtext", "highway_vs_city__%s.txt" % mode)
        if os.path.exists(p):
            t = open(p, encoding="utf-8").read()
            if "independently resolves its floor" in t:
                assert base in t, mode                       # cross-check site: pooled, identical in all five modes
                if mode in ("warm", "shoulder", "cold") and SC.get(mode):
                    exp_c = run(SC[mode], FLOOR, "in the shown cohort" + (", exploratory" if mode == "cold" else ""))
                    assert exp_c in t, (mode, exp_c)         # chart site follows its cohort data
                if mode == "all":
                    assert run(RD, FLOOR, "in the shown cohort") in t
print("OK test_m522_band_binding: bound to the payload, guards, negative controls, gate rule")
