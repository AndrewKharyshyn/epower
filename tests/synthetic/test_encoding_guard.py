"""M401 (audit D7): no tracked .py file may add text-mode file I/O without an explicit encoding (ratchet against tools/encoding_baseline.json)."""
import ast, json, os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import encoding_scan as ES

# known answers on a scratch file
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "x.py")
    open(p, "w", encoding="utf-8").write(
        "open('a')\nopen('b','w')\nopen('c','rb')\nopen('d', encoding='utf-8')\nopen('e', mode='wb')\nfrom pathlib import Path\nPath('f').read_text()\nPath('g').write_text('x', encoding='utf-8')\nPath('h').write_text('x')\n")
    ES.ROOT = td
    assert ES.count_file("x.py") == 4, ES.count_file("x.py")      # a, b, f, h
ES.ROOT = ROOT
base = json.load(open(ES.BASE, encoding="utf-8"))["files"]
cur = ES.scan()
worse = {f: (c, base.get(f, 0)) for f, c in cur.items() if c > base.get(f, 0)}
assert not worse, "un-encoded text-mode I/O added (pass encoding='utf-8'): %s" % worse
print("OK test_encoding_guard (%d un-encoded calls in %d files; baseline %d)" % (sum(cur.values()), len(cur), sum(base.values())))
