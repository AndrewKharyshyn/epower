"""M433 (audit F21): no silent numeric default for a required metric or declared parameter in xtrail_summary.jsx (ratchet, tools/literal_defaults_scan.py), plus known-answer detection."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import literal_defaults_scan as L

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "t.jsx")
    open(p, "w", encoding="utf-8").write("a = S.x?.cold ?? 20;\nb = ht.median || 8;\nc = z || { coldBelowC:20 };\nd = n ?? 0;\ne = w || 1;\n// f = q ?? 44\nstrokeWidth={sw||0.8}\n")
    got = [h["line"] for h in L.scan(p)]
    assert got == [1, 2, 3], got                                   # three dangerous forms found; zero/unit guards, comments and the listed geometry pass
r = L.scan()
assert not r, "new numeric literal default(s) in xtrail_summary.jsx: %r (use the payload, 'unavailable', or add a reasoned ALLOW entry)" % r[:5]
print("OK test_literal_defaults")
