"""M645 (UI-01 remainder): Compare chart domains are computed over every available cohort (not the toggled subset), box charts name their box and whisker meaning,
the sticky Compare header is opaque and its explanatory text is collapsed by default. The axis-stability measurement itself needs a real browser (see CHANGELOG M645)."""
import os, re
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
J = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read().replace("\r\n", "\n")
def fn(name, end):
    i = J.index("function " + name + "("); j = J.index("function " + end + "(", i + 10); return J[i:j]
assert "function domainSeries(){" in J and 'CMP_SERIES.filter(s=>s.key==="all"||cohortAvailable(s.key))' in J
bars, box, lines = fn("CmpBars", "CmpLines"), fn("CmpBox", "CmpKpi"), fn("CmpLines", "ColdConcentrationNote")
assert "domainSeries()" in bars and "perDom.forEach" in bars and "per.forEach(p=>p.cats.forEach(c=>{ const hi" not in bars
assert "domainSeries()" in box and "perDomB.forEach" in box
assert "domainSeries()" in lines and "drawn.forEach(p=>p.y.forEach(v=>{ if(fin(v)){ if(v<mn)" not in lines
for sid, b, w in (("SocBands", "lo to hi as stored", "same lo to hi"), ("DriveDurationDist", "q1 to q3", "min to max"), ("SocBySpeed", "q1 to q3", "min to max"), ("EngineOnDuration", "p10 to p90", "min to max")):
    m = re.search(sid + r':\{kind:"box",boxDef:"([^"]+)",whiskDef:"([^"]+)"', J)
    assert m and b in m.group(1) and w in m.group(2), sid
assert "boxDef||" in box and "whiskDef||" in box
hdr = J[J.index("function CompareControls("):J.index("export default function App")]
assert 'background:"#faf5ff",' in hdr and "backdropFilter" not in hdr and 'data-cmp-help="1"' in hdr and "React.useState(false)" in hdr and "{help&&<div" in hdr
print("PASS test_m645_compare_domains")
