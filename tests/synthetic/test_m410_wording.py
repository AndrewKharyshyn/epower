"""M410: the serialDependence block carries no reserved or over-reading wording (W3-mde, W3-power80 unchanged), states that the rule result 'not supported' is not evidence of absence, discloses the power, the forking path and the
original statistic, and the stage/CI wiring exists."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

R = {r.rid: r for r in G.RULES}
a = json.load(open("summary_arrays.json", encoding="utf-8"))
sd = a["serialDependence"]
strings = []
def walk(o):
    if isinstance(o, dict):
        [walk(v) for v in o.values()]
    elif isinstance(o, list):
        [walk(v) for v in o]
    elif isinstance(o, str):
        strings.append(o)
walk(sd)
for rid in ("W3-mde", "W3-power80", "M408-powerfade-wording"):
    hit = [(rid, s[:60]) for s in strings if R[rid].hits(s)]
    assert not hit, hit
bad = re.compile(r"\b(significant(?:ly)?|confirmed|robust|stable|detected|detectable|corrected|proves?|demonstrates|measured)\b", re.I)
hit = [s for s in strings if bad.search(s)]
# 'corrected' appears only in the negation 'never described as a correction' / 'never corrected' forms
hit = [s for s in hit if not re.search(r"never (?:described as )?(?:a )?correct", s) and "not 'corrected'" not in s and "never 'corrected'" not in s]
assert not hit, [h[:100] for h in hit]
for k, t in sd["trendSlopes"].items():
    ac = t["residualAutocorr"]
    assert ac["ruleStatistic"].startswith("rho_1") and "supportedOriginalPooledStatistic" in ac and "forkingPathNote" in ac and "multiplicityNote" in ac
    if not ac["supported"]:
        assert "not evidence of absence" in ac["statement"] and "not excluded" in (ac["powerDisclosure"] or ""), k
    assert t["rowsRule"]["classification"] in ("procedure-dependent", "every row includes zero", "no row includes zero (a count of rows, not a finding)")
    assert "separate estimator" in t["gls"]["note"] and "never described as a correction" in t["gls"]["note"]
    assert "does not separate" in t["misspecControl"]["reading"] or "remains after removing" in t["misspecControl"]["reading"]
assert sd["harnessCoverage"] and "powerDisclosure" in sd["harnessCoverage"]
assert "season" in " ".join(sd["limits"]) and "none of these procedures removes confounding" in " ".join(sd["limits"])
stages = json.load(open("tools/ingest_stages.json", encoding="utf-8"))
ids = [x["id"] for x in (stages["stages"] if isinstance(stages, dict) else stages)]
assert "serial_dependence" in ids and ids.index("serial_dependence") > ids.index("dependence_sensitivity")
ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
assert "test_serial_dependence.py" in ci and "test_m410_wording.py" in ci
print("OK test_m410_wording")
