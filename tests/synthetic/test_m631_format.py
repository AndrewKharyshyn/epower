"""M631 (W1-11) static tests: every toLocaleString call of xtrail_summary.jsx names its locale; 'constant constant' is gone; the unrounded kWh interval and the unverified '93.2C peak' note are gone."""
import json, os, re
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
rd = lambda p: open(os.path.join(REPO, p), encoding="utf-8").read()
jsx = rd("xtrail_summary.jsx")
bare = re.findall(r"toLocaleString(?:\?\.)?\((?!\"en-US\")", jsx)
assert not bare, "toLocaleString without a fixed locale: %d call(s)" % len(bare)
assert jsx.count('toLocaleString') >= 100
for p in ("energy_uncertainty_mc.py", "energy_uncertainty_mc.json", "summary_arrays.json", "xtrail_summary.jsx", "compute_summary_arrays.py"):
    assert "constant constant" not in rd(p), p
assert "93.2C peak" not in rd("summary_config.json")
assert "throughputKwh?.p2_5}, ${" not in jsx and "p2_5?.toFixed(1)" in jsx
# the sidecar and the shipped payload carry the same note
a = json.loads(rd("summary_arrays.json"))
side = json.loads(rd("energy_uncertainty_mc.json"))
def find(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "note" and isinstance(v, str) and v.startswith("A constant current offset"):
                return v
            r = find(v)
            if r: return r
    if isinstance(o, list):
        for v in o:
            r = find(v)
            if r: return r
assert find(a) and find(a) == find(side)
print("PASS test_m631_format")
