"""M427 (external audit F30) test: the source inventory works with and without git. With git it is `git ls-files *.py`; without git (a zip export) the directory scan contains every tracked file
and nothing under runs/, node_modules/ or tabtext/."""
import os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import source_inventory as SI
with_git = SI.tracked_py(ROOT)
git_list = sorted(subprocess.run(["git", "ls-files", "*.py"], capture_output=True, text=True, encoding="utf-8").stdout.split())
assert with_git == git_list and len(git_list) > 50
real = SI.subprocess.run
def no_git(*a, **k):
    raise FileNotFoundError("git")
SI.subprocess.run = no_git
try:
    scan = SI.tracked_py(ROOT)
finally:
    SI.subprocess.run = real
assert set(git_list) <= set(scan), sorted(set(git_list) - set(scan))[:5]
assert not [f for f in scan if f.startswith(("runs/", "node_modules/", "tabtext/", ".git/"))]
print("OK test_source_inventory (%d tracked, %d scanned)" % (len(git_list), len(scan)))
