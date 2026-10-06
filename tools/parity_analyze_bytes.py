#!/usr/bin/env python3
"""Old/new parity for compute_drive_summary_v6.analyze_bytes (M383, audit F21): one read + one time parse shared by the three metric families and an
explicit-format time fast path. The OLD module is `git show <rev>:compute_drive_summary_v6.py` (default 71bd4af = main after M382). Every key and
value of the per-drive result dict must be identical (NaN == NaN) on every canonical raw file. Read-only.
Usage: XT_RAW_DIR=$PWD/raw python tools/parity_analyze_bytes.py [--rev 71bd4af] [--limit N]"""
import argparse, importlib.util, math, os, subprocess, sys, tempfile, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import numpy as np, pandas as pd


def load_old(rev):
    src = subprocess.run(["git", "show", f"{rev}:compute_drive_summary_v6.py"], capture_output=True, check=True).stdout.decode("utf-8")
    p = os.path.join(tempfile.mkdtemp(prefix="v6_old_"), "compute_drive_summary_v6_old.py")
    open(p, "w", encoding="utf-8", newline="\n").write(src)
    spec = importlib.util.spec_from_file_location("compute_drive_summary_v6_old", p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def deq(a, b):
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(deq(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return isinstance(b, (list, tuple)) and len(a) == len(b) and all(deq(x, y) for x, y in zip(a, b))
    if isinstance(a, np.ndarray):
        return isinstance(b, np.ndarray) and a.shape == b.shape and bool(np.array_equal(a, b, equal_nan=a.dtype.kind == "f"))
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    try:
        return bool(a == b) or (pd.isna(a) and pd.isna(b))
    except (TypeError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="71bd4af"); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    import compute_drive_summary_v6 as NEW
    OLD = load_old(a.rev)
    raw = os.environ["XT_RAW_DIR"]
    dm = pd.read_csv("drive_master.csv")
    from gtr_closure_diag import _raw_names, _norm
    names = _raw_names()
    files = [(f, names[_norm(f)]) for f in dm["file"] if _norm(f) in names]
    if a.limit:
        files = files[:a.limit]
    bad, to, tn = [], 0.0, 0.0
    for f, rn in files:
        b = open(os.path.join(raw, rn), "rb").read()
        t0 = time.perf_counter(); ro = OLD.analyze_bytes(b, f); t1 = time.perf_counter(); rnw = NEW.analyze_bytes(b, f); t2 = time.perf_counter()
        to += t1 - t0; tn += t2 - t1
        if not deq(ro, rnw):
            bad.append((f, [k for k in set(ro) | set(rnw) if not deq(ro.get(k), rnw.get(k))][:6]))
    print({"files": len(files), "nMismatches": len(bad), "mismatches": bad[:5], "oldSeconds": round(to, 1), "newSeconds": round(tn, 1), "speedup": round(to / tn, 2) if tn else None})
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
