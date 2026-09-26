#!/usr/bin/env python3
"""ml16_determinism_check.py (M284) - honestly-named entry point for determinism_check.py.

The underlying harness verifies reproducibility of the ML16 postprocess_master labelling step ONLY
(canonical-set reproducibility over the drive_master rows). It is NOT a whole-pipeline determinism
proof (raw CSV -> drive_master is not covered). This wrapper delegates unchanged and prints the scope.
"""
import os, runpy, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SCOPE = "SCOPE: ML16 postprocess_master labelling step only; not a whole-pipeline determinism proof."
if __name__ == "__main__":
    print(SCOPE)
    target = os.path.join(HERE, "determinism_check.py")
    if not os.path.exists(target):
        target = os.path.join(os.getcwd(), "determinism_check.py")
    if not os.path.exists(target):
        sys.exit("determinism_check.py not found beside this wrapper or in cwd")
    runpy.run_path(target, run_name="__main__")
