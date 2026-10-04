"""M369 known-answer tests for the raw frame-cache defects (HANDOFF item C): a changed raw file must never be served from a stale cache
entry by name; result caches keyed by content; run_ingest forces XT_RAW_DIR=raw/."""
import os, subprocess, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
import drive_raw_cache as drc

with tempfile.TemporaryDirectory() as td:
    raw, cache = os.path.join(td, "raw"), os.path.join(td, "cache")
    os.makedirs(raw)
    fn = "a.csv"
    open(os.path.join(raw, fn), "w").write("time,x\n00:00:00.0,1\n00:00:01.0,2\n")
    n_add, _ = drc.add_missing([fn], raw, cache_dir=cache, verbose=False)
    assert n_add == 1
    load = drc.make_frame_loader(cache_dir=cache, raw_dir=raw)
    assert load(fn) is not None
    k1 = drc.content_key([fn], cache_dir=cache)

    open(os.path.join(raw, fn), "w").write("time,x\n00:00:00.0,1\n00:00:01.0,2\n00:00:02.0,3\n")   # raw file changed under the same name
    assert drc.make_frame_loader(cache_dir=cache, raw_dir=raw)(fn) is None, "stale frame served for a changed raw file"
    assert drc.make_frame_loader(cache_dir=cache)(fn) is not None                                     # documented: no raw_dir -> no check
    n_add, _ = drc.add_missing([fn], raw, cache_dir=cache, verbose=False)                              # default verify_md5=True re-adds
    assert n_add == 1
    assert len(drc.make_frame_loader(cache_dir=cache, raw_dir=raw)(fn)) == 3
    k2 = drc.content_key([fn], cache_dir=cache)
    assert k1 != k2, "content key must change when the raw file changes"
    assert drc.content_key([fn], cache_dir=cache) == k2                                                # deterministic
    n_add, _ = drc.add_missing([fn], raw, cache_dir=cache, verbose=False)
    assert n_add == 0                                                                                  # unchanged file is skipped

    code = os.path.join(td, "code.py")
    open(code, "w").write("x=1\n")
    c1 = drc.content_key([fn], cache_dir=cache, code_paths=[code])
    open(code, "w").write("x=2\n")
    assert drc.content_key([fn], cache_dir=cache, code_paths=[code]) != c1, "content key must change when builder code changes"

src = open(os.path.join(ROOT, "tools", "run_ingest.py"), encoding="utf-8").read()
assert 'env["XT_RAW_DIR"] = want' in src and 'env.setdefault("XT_RAW_DIR"' not in src, "run_ingest must force XT_RAW_DIR=raw/"
print("test_m369_raw_cache: ok")
