#!/usr/bin/env python3
"""Ingestion stage driver (M377b, analyses/M377_spec.md Rev 4): run the point runner on the live corpus, then the generic splice. Exit code of the first failing step.
The ingestion label (milestone id of the running ingestion) is read from XT_INGEST_LABEL (default "ingestion").
Usage: XT_RAW_DIR=<root>/raw_only python tools/gtr_family_refresh.py"""
import os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
env = dict(os.environ, PYTHONUTF8="1")
for cmd in ([sys.executable, "tools/m373_point.py", "--point", "O", "--tag", "M377"],
            [sys.executable, "tools/gtr_family_refresh_splice.py", "--label", os.environ.get("XT_INGEST_LABEL", "ingestion")]):
    rc = subprocess.run(cmd, cwd=ROOT, env=env).returncode
    if rc != 0:
        sys.exit(rc)
