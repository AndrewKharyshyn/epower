#!/usr/bin/env python3
"""M575 ingestion stage: refresh the on-demand M432 detector-sensitivity block (evTraction.detectorSensitivity) on the live master. The semantic gate requires the released share of that block to equal
the carried evPctDistance (1 dp), which an ingestion changes. Re-runs the unchanged tool (tools/m432_ev_sens.py run, gate G1, about 25 s) and re-applies tools/m432_splice.py (deep-diff guarded).
Usage: python tools/m432_refresh.py   (XT_RAW_DIR is set by the stage; the sensitivity tool reads raw_only/)"""
import os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
for cmd in ([sys.executable, "tools/m432_ev_sens.py", "run", "--out", "analyses/M432_result.json", "--workers", "8"], [sys.executable, "tools/m432_splice.py"]):
    r = subprocess.run(cmd)
    if r.returncode:
        raise SystemExit(r.returncode)
