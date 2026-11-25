#!/usr/bin/env python3
"""M777: install the tracked git hooks of tools/git_hooks/ into this clone's .git/hooks (copy, executable). Idempotent.
Usage: python tools/install_git_hooks.py"""
import os, shutil, stat, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def main():
    src = os.path.join(ROOT, "tools", "git_hooks")
    git_dir = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    dst = git_dir if os.path.isabs(git_dir) else os.path.join(ROOT, git_dir)
    os.makedirs(dst, exist_ok=True)
    for name in sorted(os.listdir(src)):
        target = os.path.join(dst, name)
        with open(os.path.join(src, name), "rb") as f:
            data = f.read().replace(b"\r\n", b"\n")
        with open(target, "wb") as f:
            f.write(data)
        os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print("installed", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
