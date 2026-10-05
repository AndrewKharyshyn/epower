#!/usr/bin/env python3
"""Old/new parity for recon_engine.load_drive (M383, audit F21). The OLD module is the frozen pre-M383 reference copy (or a git revision via --rev),
the NEW one from the working tree; every output column of load_drive must be bit-identical (the absolute date of 't' is excluded: only
differences of 't' are used downstream), and precompute() outputs must match too. Read-only.
Usage: XT_RAW_DIR=$PWD/raw python tools/parity_load_drive.py [--rev HEAD] [--limit N] [--time]"""
import argparse, importlib.util, os, subprocess, sys, tempfile, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import numpy as np, pandas as pd


def load_old(rev=None):
    """OLD module: the frozen reference copy (tests/synthetic/reference/recon_engine_pre_m383.py, no git needed: CI checks out depth 1), or
    `git show <rev>:recon_engine.py` when --rev is given."""
    if rev:
        src = subprocess.run(["git", "show", f"{rev}:recon_engine.py"], capture_output=True, check=True).stdout.decode("utf-8")
        p = os.path.join(tempfile.mkdtemp(prefix="re_old_"), "recon_engine_old.py")
        open(p, "w", encoding="utf-8", newline="\n").write(src)
    else:
        p = os.path.join(ROOT, "tests", "synthetic", "reference", "recon_engine_pre_m383.py")
    spec = importlib.util.spec_from_file_location("recon_engine_old", p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def eq(x, y):
    x, y = np.asarray(x), np.asarray(y)
    if x.shape != y.shape:
        return False
    return np.array_equal(x, y, equal_nan=True) if np.issubdtype(x.dtype, np.floating) else bool(np.array_equal(x, y))


def same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return False
    for c in a.columns:
        x, y = a[c].values, b[c].values
        if c == "t":
            x, y = (a[c] - a[c].iloc[0]).values, (b[c] - b[c].iloc[0]).values
        if np.issubdtype(x.dtype, np.floating):
            if not np.array_equal(x, y, equal_nan=True):
                return False
        elif not np.array_equal(x, y):
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default=None); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--time", action="store_true")
    ap.add_argument("--fuel", type=int, default=0, help="only the first N fuel-instrumented drives of analyses/M377c_closure_perdrive.csv (CI smoke)")
    a = ap.parse_args()
    import recon_engine as NEW
    OLD = load_old(a.rev)
    from gtr_closure_diag import _raw_names, _norm
    names = _raw_names()
    dm = pd.read_csv("drive_master.csv").set_index("file")
    files = [f for f in dm.index if _norm(f) in names]
    if a.fuel:
        fl = pd.read_csv("analyses/M377c_closure_perdrive.csv")["file"].tolist()[:a.fuel]
        files = [f for f in files if f in set(fl)]
    if a.limit: files = files[:a.limit]
    bad, n, none, to, tn = [], 0, 0, 0.0, 0.0
    for f in files:
        off = float(dm.loc[f].get("I_offset_A_applied", 0.0) or 0.0)
        t0 = time.perf_counter(); go = OLD.load_drive(names[_norm(f)], off); t1 = time.perf_counter(); gn = NEW.load_drive(names[_norm(f)], off); t2 = time.perf_counter()
        to += t1 - t0; tn += t2 - t1
        if go is None:
            none += 1
        n += 1
        if not same(go, gn):
            bad.append(f); continue
        if go is not None:
            po, pn = OLD.precompute(go), NEW.precompute(gn)
            for k in po:
                x, y = po[k], pn[k]
                if isinstance(x, dict):
                    ok = x.keys() == y.keys() and all(eq(x[q], y[q]) for q in x)
                else:
                    ok = eq(x, y)
                if not ok:
                    bad.append(f + ":precompute:" + k); break
    print({"files": n, "noFuelOrShort": none, "mismatches": bad[:10], "nMismatches": len(bad), "oldSeconds": round(to, 2), "newSeconds": round(tn, 2),
           "speedup": round(to / tn, 2) if tn else None})
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
