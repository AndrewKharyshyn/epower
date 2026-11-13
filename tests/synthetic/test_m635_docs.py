"""M635 (W1-18) documentation-drift tests: figures typed in the docs follow the payload and the files; STATE.md is clean UTF-8; state.py names its encoding."""
import json, os, re
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
rd = lambda p: open(os.path.join(REPO, p), encoding="utf-8").read()
A = json.loads(rd("summary_arrays.json"))
ov = rd("docs/overview.md")
assert "cell-spread %s mV/month" % A["degradationTrends"]["cellSpread"]["releasedEquivalence"]["delta"] in ov, "docs/overview.md cell-spread bound != payload delta"
assert "resistance %s mOhm/month" % A["degradationTrends"]["resistanceVreg"]["releasedEquivalence"]["delta"] in ov
cl = rd("CLAUDE.md")
for fn, key in (("xtrail_summary.jsx", "xtrail_summary.jsx` (~"), ("compute_summary_arrays.py", "compute_summary_arrays.py` (~")):
    m = re.search(re.escape(key) + r"([\d.]+)k lines", cl)
    n = sum(1 for _ in open(os.path.join(REPO, fn), encoding="utf-8", errors="replace"))
    assert m and abs(float(m.group(1)) * 1000 - n) / n < 0.06, (fn, m and m.group(1), n)      # within 6 % of the file
st = rd("STATE.md")
assert "\ufffd" not in st and "\u00e2\u20ac" not in st and "\u0432\u0402" not in st, "mojibake in STATE.md"
src = rd("tools/state.py")
assert 'open(P("state.json"), "w", encoding="utf-8"' in src and 'open(P("STATE.md"), "w", encoding="utf-8"' in src
stages = json.loads(rd("tools/ingest_stages.json"))["stages"]
assert all(s.get("verified") is True for s in stages if s["id"] in ("m321_ladder_monitor", "start_ratio_refresh", "m432_refresh"))
assert "not_implemented (first use)" not in rd(".claude/skills/ingest-drive/SKILL.md")
print("PASS test_m635_docs")
