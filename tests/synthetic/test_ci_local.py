"""M628 (P-05) tests for tools/ci_local.py: the parser follows ci.yml (one source of truth), the anchor MD5 is read, a skip file is applied and never silent, the temp copy leaves tracked files alone."""
import json, os, re, sys, tempfile
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import ci_local as L

SAMPLE = """      - name: Import integrity
        run: python tools/verify_import.py --quick --expect-master-md5 0123456789abcdef0123456789abcdef
      - name: Compile all Python
        run: python -m compileall -q *.py tools
      - name: Unit tests
        run: |
          cat > ci_python_tests.txt <<'LIST'
          python a.py
          python tests/b.py --x 1
          LIST
          awk ...
      - name: Dashboard tests (jsdom)
        run: |
          node t1.js
          node t2.js
  release-check:
"""
c = L.parse_ci(SAMPLE)
assert c["python"] == ["python a.py", "python tests/b.py --x 1"], c
assert c["js"] == ["node t1.js", "node t2.js"], c
assert c["anchorMd5"] == "0123456789abcdef0123456789abcdef" and c["compile"].startswith("python -m compileall") and c["import"].startswith("python tools/verify_import.py")

# the real ci.yml: the parser finds every test line of the heredoc (no second list) and the anchor
real = open(os.path.join(REPO, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
r = L.parse_ci(real)
m = re.search(r"<<'LIST'\n(.*?)\n\s*LIST\n", real, re.S)
assert len(r["python"]) == len([x for x in m.group(1).split("\n") if x.strip()]) > 100
assert r["js"] and r["anchorMd5"] and re.fullmatch(r"[0-9a-f]{32}", r["anchorMd5"])
assert r["anchorMd5"] == L.md5(os.path.join(REPO, "drive_master.csv")), "ci.yml master MD5 anchor != live drive_master.csv"

# skip file: keys per platform with a reason; missing file -> no skips
tmp = tempfile.mkdtemp(prefix="xt_cil_")
sk = os.path.join(tmp, "skip.json")
json.dump({"windows": {"python x.py": "reason w"}, "linux": {"python y.py": "reason l"}}, open(sk, "w", encoding="utf-8"))
L.SKIP_FILE = sk
assert L.load_skips() == ({"python x.py": "reason w"} if os.name == "nt" else ({"python y.py": "reason l"} if sys.platform.startswith("linux") else {}))
L.SKIP_FILE = os.path.join(tmp, "absent.json")
assert L.load_skips() == {}
print("PASS test_ci_local")
