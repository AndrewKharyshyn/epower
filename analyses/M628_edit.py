"""M628 (P-05): release_check.py asserts that the master MD5 typed in .github/workflows/ci.yml equals the live drive_master.csv."""
p = 'release_check.py'
s = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s[:5000] else '\n'
anchor = '        run([sys.executable, "tools/release_identity.py", "--check"]'
i = s.index(anchor)
add = '''        _ci_txt = (Path(__file__).resolve().parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")       # M628 (P-05): the typed CI anchor must follow the master
        _m = re.search(r"--expect-master-md5 ([0-9a-f]{32})", _ci_txt)
        _live = md5(Path(__file__).resolve().parent / "drive_master.csv")
        _ok = bool(_m) and _m.group(1) == _live
        print(("PASS " if _ok else "FAIL ") + "ci.yml master MD5 anchor equals the live drive_master.csv (M628, P-05)" + ("" if _ok else " (ci.yml %s, live %s: update the anchor in the ingestion PR)" % (_m.group(1) if _m else None, _live)))
        if not _ok: fails.append("ci.yml master MD5 anchor != live master")
'''.replace('\n', nl)
s = s[:i] + add + s[i:]
open(p, 'w', encoding='utf-8', newline='').write(s)
print('ok')
