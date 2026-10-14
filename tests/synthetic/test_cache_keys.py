"""M434 known-answer tests (audit F11 / F12 / F26): tools/cache_keys.py, drive_raw_cache (verified source identity, archive-only mode), tools/record_spread_fit.py (key before compute)."""
import json, os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import cache_keys as K
import drive_raw_cache as drc

# ---- F11: dependency closure and code hash
cl = {os.path.relpath(p, ROOT).replace("\\", "/") for p in K.module_closure("compute_summary_arrays.py")}
assert {"compute_summary_arrays.py", "drive_raw_cache.py", "soc_spike.py", "tools/soak_tau.py", "m119v2_model.py"} <= cl, sorted(cl)      # direct and transitive local imports
assert not any(x.startswith("numpy") for x in cl)                                                                                         # third-party modules are not part of the closure
with tempfile.TemporaryDirectory() as td:
    a, b = os.path.join(td, "a.py"), os.path.join(td, "b.py")
    open(a, "wb").write(b"x = 1\r\ny = 2\r\n"); open(b, "wb").write(b"z = 3\n")
    h1 = K.code_hash([a, b])
    assert K.code_hash([b, a]) == h1                                         # order-independent
    open(a, "wb").write(b"x = 1\ny = 2\n")
    assert K.code_hash([a, b]) == h1                                         # CRLF-normalised
    open(a, "wb").write(b"x = 1\ny = 3\n")
    assert K.code_hash([a, b]) != h1                                         # an edit changes the key

# ---- F11: frame hash sees a same-file-list metadata / eligibility change
df = pd.DataFrame({"file": ["a", "b"], "ens_outlier_v2": [False, False], "distance_km": [1.0, 2.0]})
f1 = K.frame_hash(df)
d2 = df.copy(); d2.loc[1, "ens_outlier_v2"] = True
assert K.frame_hash(d2) != f1
d3 = df.copy(); d3.loc[0, "distance_km"] = 1.0000001
assert K.frame_hash(d3) != f1
assert K.frame_hash(df.copy()) == f1

# ---- F12: verified source identity
with tempfile.TemporaryDirectory() as td:
    raw, cache = os.path.join(td, "raw"), os.path.join(td, "cache")
    os.makedirs(raw)
    fn = "a.csv"
    open(os.path.join(raw, fn), "w").write("time,x\n00:00:00.0,1\n00:00:01.0,2\n")
    drc.add_missing([fn], raw, cache_dir=cache, verbose=False)
    assert drc.make_frame_loader(cache_dir=cache, raw_dir=raw)(fn) is not None
    k_live = drc.content_key([fn], cache_dir=cache, raw_dir=raw)
    os.remove(os.path.join(raw, fn))                                          # raw source gone, cached frame remains
    strict = drc.make_frame_loader(cache_dir=cache, raw_dir=raw)
    assert strict(fn) is None and strict.stats["missingSource"] == 1          # no verified source identity -> not served
    arch = drc.make_frame_loader(cache_dir=cache, raw_dir=raw, archive_only=True)
    assert arch(fn) is not None and arch.stats["archiveOnlyServed"] == 1     # explicit archive-only mode serves it and counts it
    assert drc.make_frame_loader(cache_dir=cache)(fn) is not None            # no raw_dir: documented unchanged behaviour
    try:
        drc.content_key([fn], cache_dir=cache, raw_dir=raw)
        raise AssertionError("content_key must raise for a missing raw source")
    except FileNotFoundError:
        pass
    k_arch = drc.content_key([fn], cache_dir=cache, raw_dir=raw, archive_only=True)
    assert k_arch != k_live and k_arch == drc.content_key([fn], cache_dir=cache, raw_dir=raw, archive_only=True)
    open(os.path.join(raw, fn), "w").write("time,x\n00:00:00.0,1\n00:00:01.0,9\n")      # a changed raw file under the same name
    assert drc.content_key([fn], cache_dir=cache, raw_dir=raw) != k_live                # the key follows the file on disk, not the manifest

# ---- F26: the history key is built from inexpensive inputs and covers versions and parameters
import record_spread_fit as R
ck = R.build_code_key()
hist = json.load(open(R.HIST, encoding="utf-8"))
assert all(set(R.KEY_FIELDS) <= set(r["codeKey"]) for r in hist["records"]), "history records must carry every key field"
k0 = R.record_key("m", ck)
for fld, val in (("numpy", "0.0"), ("scikit_learn", "0.0"), ("python", "0.0"), ("n_boot", 1), ("seed", 1), ("m19b_sha256", "x"), ("huber_slope_ci_sha256", "x")):
    assert R.record_key("m", dict(ck, **{fld: val})) != k0, fld
assert R.record_key("m2", ck) != k0
print("OK test_cache_keys")
