"""M523 (analyses/M523_spec.md Rev 2): the motored share near the RPM chart is bound to the payload (hours basis), the M205/M218/M89 historical literals carry the 'not recomputed on the current corpus' qualifier,
and 'raw field telemetry' is gone. Runs motoredShareText extracted from xtrail_summary.jsx in node (real and patched payloads), checks the language rule with positive/negative controls and the rendered dumps (when present)."""
import json, os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
m = re.search(r"function motoredShareText\(rd, floor\)\{.*?\n\}\n", jsx, re.S)
assert m, "helper not found"
A = json.load(open("summary_arrays.json", encoding="utf-8"))
RD = A["rpmDistribution"]; FLOOR = RD["params"]["fuelStateRpmMin"]
SC = A["seasonalCharts"]["charts"]["RpmDistribution"]["data"]

def run(rd, floor):
    js = m.group(0) + "\nconsole.log(motoredShareText(%s, %s));" % (json.dumps(rd), json.dumps(floor))
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()

def recompute(rd, floor):
    mt = tt = 0.0
    for i, b in enumerate(rd["bins"]):
        lo = int(re.match(r"\d+", b).group(0))
        if i >= 1 and lo >= floor:
            mt += rd["motored"]["hours"][i]; tt += rd["motored"]["hours"][i] + rd["fuelled"]["hours"][i]
    return mt, tt

mt, tt = recompute(RD, FLOOR)
base = run(RD, FLOOR)
assert ("%.1f %% of boost-classified engine-on hours" % (mt / tt * 100)) in base and ("motored %.2f h of %.1f h" % (mt, tt)) in base, base
assert "population" not in base and "~" not in base
# cohort modes follow their own payload (b)
texts = {}
for mode in ("all", "warm", "shoulder", "cold"):
    if SC.get(mode):
        a_, b_ = recompute(SC[mode], FLOOR)
        if b_ > 0:
            assert ("%.1f %%" % (a_ / b_ * 100)) in run(SC[mode], FLOOR), mode
            texts[mode] = run(SC[mode], FLOOR)
assert len(set(texts.values())) > 1, "cohort modes should differ"
# (a) patched threshold moves the share and uses no literal
assert run(RD, 2000.0) != base
# (c) missing / malformed keys -> n/a
for bad in ({}, None, {"bins": RD["bins"]}, dict(RD, fuelled={"hours": [1]}), dict(RD, motored={"hours": [None] * len(RD["bins"])})):
    t = run(bad, FLOOR)
    assert "(n/a)" in t and "%" not in t, (bad if bad is None else list(bad.keys()), t)
assert "(n/a)" in run(RD, None)
# language rule: (e) fires on the old wording and the unqualified class C numbers, passes the new wording
R = {r.rid: r for r in G.RULES}["M523-historical-rpm-literals"]
assert R.hits("at this RPM floor it is only ~2.5% of the boost-classified population, so a calc-load-only rule")
assert R.hits("derived from raw field telemetry rather than a bench calibration")
# M527 superseded the 2000.30 alternative (the value is recomputed and bound to rpmModeCentres; the historical value is dated history): the M527 rule owns it
assert not R.hits("the weighted center of mass 2000.30 rpm, and nothing else is said")
assert R.hits("the mode 45/55 across a bin edge")
assert not R.hits("weighted center of mass 2000.30 rpm; historical M205 re-derivation at 5 rpm resolution on the corpus of that date, not recomputed on the current corpus)")
assert not R.hits("derived from logged field telemetry rather than a bench calibration")
assert not R.hits(base)
# sources: old literals gone
assert "raw field telemetry" not in jsx and "~2.5%" not in jsx
# rendered dumps (local only): every 2000.30 / 1589 / 45-55 passage in the dumps is qualified
if os.path.isdir("tabtext"):
    for mode in ("all", "warm", "shoulder", "cold", "compare"):
        p = os.path.join("tabtext", "highway_vs_city__%s.txt" % mode)
        if os.path.exists(p):
            t = open(p, encoding="utf-8").read()
            assert not R.hits(t), mode
            if "independently resolves its floor" in t:
                assert "logged field telemetry" in t, mode
print("OK test_m523_literals: bound motored share, controls, historical qualifier, gate rule")
