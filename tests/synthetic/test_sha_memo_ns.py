"""M467 (external audit F07) known-answer test: the raw SHA-256 memo of tools/regen_v2_cache.py must not return a stale digest after a same-length edit whose mtime differs by less than one second."""
import os, sys, tempfile, hashlib, shutil
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import regen_v2_cache as RC
d = tempfile.mkdtemp()
try:
    os.environ["XT_RAW_DIR_STAGED"] = d
    p = os.path.join(d, "x.csv"); memo = {}
    open(p, "wb").write(b"AAAA"); t0 = 1_700_000_000_000_000_000
    os.utime(p, ns=(t0, t0))
    h1 = RC.raw_sha256("x.csv", memo)
    assert h1 == hashlib.sha256(b"AAAA").hexdigest()
    open(p, "wb").write(b"BBBB"); os.utime(p, ns=(t0 + 250_000_000, t0 + 250_000_000))      # same size, +0.25 s, same whole second
    h2 = RC.raw_sha256("x.csv", memo)
    assert h2 == hashlib.sha256(b"BBBB").hexdigest() and h2 != h1, "stale digest returned"
    assert RC.raw_sha256("x.csv", memo) == h2                                                   # unchanged file: memo hit
finally:
    shutil.rmtree(d, ignore_errors=True)
print("OK test_sha_memo_ns")
