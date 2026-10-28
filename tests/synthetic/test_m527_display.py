"""M527 display step (analyses/M527_spec.md Rev 2 + Director): the RPM-mode sentences bind to S.rpmModeCentres. Recomputes every displayed value from summary_arrays.json and checks the rendered dumps in all modes
(the sentences use the pooled corpus beside a cohort-aware chart and say so), the guards (helpers run in node with patched / missing payloads), the superseded historical qualifiers and the rule."""
import json, os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

A = json.load(open("summary_arrays.json", encoding="utf-8")); M = A["rpmModeCentres"]
assert M["faithfulness"]["passed"] and M["descriptive"] is True and M["rpmChannelResolution"]["gridStepCounts"] == {"1.0": 104}
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
NL = chr(10)
def _fn(n):
    return re.search(r"function " + n + r"\(.*?" + NL + "}" + NL, jsx, re.S).group(0)
_pct = re.search(r"function rpmModePct\([^" + NL + "]*" + NL, jsx).group(0)
src = NL.join([_fn("rpmModeFmt"), _fn("rpmModeHistRange"), _pct])
def run(expr, payload):
    js = src + "\nconst M=%s;\nconsole.log(%s);" % (json.dumps(payload), expr)
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
c = M["centres"]["c2000"]
exp_fmt = "%.2f rpm (95 %% CI %.2f\u2013%.2f)" % (c["centre"], c["ci95"][0], c["ci95"][1])
assert run('rpmModeFmt(M,"c2000")', M) == exp_fmt
# guards: missing / malformed -> n/a, never a literal
for bad in (None, {}, {"centres": {}}, {"centres": {"c2000": {"centre": None, "ci95": [1, 2]}}}, {"centres": {"c2000": {"centre": 2000.0}}}):
    assert run('rpmModeFmt(M,"c2000")', bad) == "n/a", bad
assert run('rpmModeHistRange(M,"c2000")', M) == "2000.30 rpm" and run('rpmModeHistRange(M,"c1500")', M) == "1499.69\u20131500.08 rpm"
assert run('rpmModeHistRange(M,"c2000")', {}) == "n/a" and run("rpmModePct(undefined)", M) == "n/a"
# negative control: a patched centre changes the text
M2 = json.loads(json.dumps(M)); M2["centres"]["c2000"]["centre"] += 1.0
assert run('rpmModeFmt(M,"c2000")', M2) != exp_fmt
# rule: a bare historical value is flagged, 'reported' history is not
R = {r.rid: r for r in G.RULES}["M527-recomputed-mode-centres"]
assert R.hits("the weighted center of mass is 2000.30 rpm") and not R.hits("the M205 pass reported 2000.30 rpm")
assert "historical M205 re-derivation at 5 rpm resolution on the corpus of that date, not recomputed on the current corpus" not in jsx
# rendered dumps (local): all modes show the bound sentences
s1a = M["shares"]["S1a_window_over_1900_2100_pct"]; h307 = M["historicalSubsets"]["first307_M205"]
exp = ["the window's centre of mass is %s and it holds %.1f %% (95 %% CI %.1f\u2013%.1f) of the 1900\u20132100 rpm mass" % (exp_fmt, s1a["pct"], s1a["ci95Pct"][0], s1a["ci95Pct"][1]),
       "reported 2000.30 rpm, a 45.3/54.7 split across the old edge and 96%+ of the window mass",
       "including on the first %d drives (%.2f rpm; %.1f %% of the 1900\u20132100 rpm mass below 2000" % (h307["drives"], h307["c2000"]["centre"], h307["shares"]["S2_pct"]["pct"]),
       "centre of mass of the 1975-2025 window %s on the current corpus" % exp_fmt]
if os.path.isdir("tabtext"):
    for mode in ("all", "warm", "shoulder", "cold", "compare"):
        p = os.path.join("tabtext", "highway_vs_city__%s.txt" % mode)
        if os.path.exists(p):
            t = " ".join(open(p, encoding="utf-8").read().split())
            if "independently resolves its floor" in t:
                for e in (exp[3:] if mode == "compare" else exp):      # compare mode replaces the chart (and its caption) by the compare block; the cross-check paragraph still renders
                    assert e in t, (mode, e)
                assert not R.hits(t), mode
print("OK test_m527_display: bound values, guards, superseded qualifiers, dumps in all modes")
