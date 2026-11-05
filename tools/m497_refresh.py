#!/usr/bin/env python3
"""M575 ingestion stage: refresh socHysteresis.startRatioClustered (M497, spec analyses/M497_spec.md Rev 2) on the live master.
The arrays rebuild recomputes socHysteresis and drops this additively spliced block; this stage re-runs the pre-registered estimator
(tools/m497_start_ratio.py, unchanged: seed 42, 4000 draws, day-clustered) and re-applies tools/m497_splice.py. Method and spec are unchanged; only the corpus grows.
Usage: python tools/m497_refresh.py"""
import os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
for cmd in ([sys.executable, "tools/m497_start_ratio.py"], [sys.executable, "tools/m497_splice.py"]):
    r = subprocess.run(cmd)
    if r.returncode:
        raise SystemExit(r.returncode)
