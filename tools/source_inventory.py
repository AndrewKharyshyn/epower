#!/usr/bin/env python3
"""M427 (external audit F30): the Python source inventory without a hard dependency on git. `tracked_py(root)` is `git ls-files *.py` inside a git checkout and a directory scan
(skipping .git, node_modules, runs, tabtext, __pycache__) in a zip/export without git, so the source-inventory tests run on both. Paths are root-relative with forward slashes."""
import os, subprocess

SKIP_DIRS = {".git", "node_modules", "runs", "tabtext", "__pycache__"}


def tracked_py(root):
    try:
        r = subprocess.run(["git", "ls-files", "*.py"], cwd=root, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0 and r.stdout.split():
            return sorted(r.stdout.split())
    except (OSError, ValueError):
        pass
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
    return sorted(out)
