"""M594 (audit D4): every CI python-test list line must be ONE command, so the shard runner's `eval "$cmd" || exit 1`
sees each failure. A multi-command line (for-loop, `;`, `&&`) lets a failing early command be masked by a passing last one."""
import os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
txt = open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
m = re.search(r"<<'LIST'\r?\n(.*?)\r?\n\s*LIST\r?\n", txt, re.S)
assert m, "test list not found"
lines = [l.strip() for l in m.group(1).splitlines() if l.strip()]
bad = [l for l in lines if re.search(r"[;&|]|\bfor\b|\bdo\b|\bdone\b", l)]
assert not bad, "multi-command CI list lines: %r" % bad
# behavioural: the runner pattern must turn a failing first command followed by a passing last one red
for first, last, want in (("exit 1", "exit 0", 1), ("exit 0", "exit 0", 0)):
    r = subprocess.run(["bash", "-c", 'printf "%s\n%s\n" "$A" "$B" > l.txt; while IFS= read -r c; do eval "$c" || exit 1; done < l.txt; rm l.txt'],
                       env={**os.environ, "A": first, "B": last}, cwd=os.environ.get("TMPDIR", None) or ".", capture_output=True)
    assert r.returncode == want, (first, last, r.returncode)
print("ok test_ci_list_failfast: %d single-command lines" % len(lines))
