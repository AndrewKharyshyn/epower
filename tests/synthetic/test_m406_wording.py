"""M406 (Director ruling): the minimum-effect quantity is design-conditional; the reserved power phrases are forbidden everywhere (W3-power80) while W3-mde stays unchanged; the block carries
neither."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

R = {r.rid: r for r in G.RULES}
assert not any(ord(c) < 32 for c in R["W3-power80"].rx.pattern)
assert not R["W3-power80"].hits("no degraded pack has been observed. Power fade is hypothesised")         # a sentence boundary must not match
for bad in ("the observed power of the test", "a post hoc power calculation", "the trend is powered to detect any rise", "this rules out slopes above 1 mV"):
    assert R["W3-power80"].hits(bad), bad
for good in ("slope size that a two-sided 5 % test flags with probability 0.8 at the observed standard error; design-conditional", "week-block interval"):
    assert not R["W3-power80"].hits(good), good
assert R["W3-mde"].hits("the minimum detectable effect")                      # W3-mde stays in force
a = json.load(open("summary_arrays.json", encoding="utf-8"))
ds = a["dependenceSensitivity"]
strings = []
def walk(o):
    if isinstance(o, dict):
        [walk(v) for v in o.values()]
    elif isinstance(o, list):
        [walk(v) for v in o]
    elif isinstance(o, str):
        strings.append(o)
walk(ds)
hit = [(rid, s[:60]) for s in strings for rid in ("W3-power80", "W3-mde") if R[rid].hits(s)]
assert not hit, hit
for t in ds["trendSlopes"].values():
    assert t["minEffect80"]["definition"].startswith("slope size that a two-sided 5 % test flags") and "design-conditional" in t["minEffect80"]["definition"]
print("OK test_m406_wording")
