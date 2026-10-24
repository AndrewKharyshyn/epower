"""M498 (audit PF-01/02/03) cache invalidation: an entry built by changed code must be a miss. Uses one real raw drive; every write goes to a temp dir."""
import importlib, os, shutil, subprocess, sys, tempfile, textwrap
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd

raw_dir = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
dm = pd.read_csv("drive_master.csv", low_memory=False)
fn = str(dm["file"].iloc[300])
import ah_throughput as _AH0
rb = _AH0.raw_loader()(fn)
assert rb, "raw file not resolved: %s" % fn

# ---- PF-01: raw frame cache. The code key must change when clock_unwrap (reached by add_file) changes, and a stale-code entry must not be served
with tempfile.TemporaryDirectory() as td:
    for f in ("drive_raw_cache.py", "clock_unwrap.py", "soc_spike.py"):
        shutil.copy(os.path.join(ROOT, f), td)
    os.makedirs(os.path.join(td, "tools")); shutil.copy(os.path.join(ROOT, "tools", "dep_hash.py"), os.path.join(td, "tools"))
    code = textwrap.dedent('''
        import sys, os, json; sys.path.insert(0, os.getcwd())
        import drive_raw_cache as d
        cd = os.path.join(os.getcwd(), "c"); os.makedirs(cd, exist_ok=True)
        if sys.argv[1] == "build":
            d.add_file(sys.argv[2], open(sys.argv[3], "rb").read(), cache_dir=cd)
        L = d.make_frame_loader(cache_dir=cd)
        r = L(sys.argv[2])
        print(json.dumps({"key": d.code_key(), "served": r is not None, "staleCode": L.stats["staleCode"]}))
    ''')
    open(os.path.join(td, "run.py"), "w", encoding="utf-8").write(code)
    rawp = os.path.join(td, "raw.csv"); open(rawp, "wb").write(rb)
    run = lambda mode: __import__("json").loads(subprocess.run([sys.executable, "run.py", mode, fn, rawp], cwd=td, capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1])
    a = run("build"); assert a["served"] and a["staleCode"] == 0, a
    p = os.path.join(td, "clock_unwrap.py"); s = open(p, encoding="utf-8").read()
    tail = "return res if isinstance(t, pd.Series) else pd.DatetimeIndex(res)"; assert s.count(tail) == 1
    open(p, "w", encoding="utf-8").write(s.replace(tail, "res = res + pd.Timedelta(seconds=1)" + chr(10) + "    " + tail))   # behaviour change inside unwrap_clock (closure of add_file)
    b = run("load")
    assert b["key"] != a["key"], "code key must change with clock_unwrap"
    assert not b["served"] and b["staleCode"] == 1, ("stale-code entry served", b)

# ---- PF-02: capacity_cache rows and per-drive sidecars are keyed by the extractor closure
import capacity_basis as CB, ah_throughput as AH, timing_support as TS, powerfade_equivalence as PE
loader = lambda f: rb
m1 = dm.iloc[[300]].copy()
import types
calls = types.SimpleNamespace(n=0)   # not a simple constant, so the counter is not part of the closure hash
orig = CB.extract_drive
def counting(b):
    calls.n += 1
    return orig(b)
with tempfile.TemporaryDirectory() as cdir:
    sha = lambda f: __import__("hashlib").sha256(rb).hexdigest()
    CB.extract_drive = counting
    try:
        CB.load_records(m1, loader, sha, cache_dir=cdir); n1 = calls.n
        CB.load_records(m1, loader, sha, cache_dir=cdir); assert calls.n == n1, "unchanged code must reuse the cache"
        def changed(b):                                               # a different extractor body with the same raw bytes
            calls.n += 1
            return orig(b)
        CB.extract_drive = changed
        CB.load_records(m1, loader, sha, cache_dir=cdir); assert calls.n == n1 + 1, "changed extractor must recompute"
    finally:
        CB.extract_drive = orig
for mod, fnname, build in ((AH, "ah_from_bytes", lambda p, **k: AH.build_sidecar(m1, loader, path=p, **k)),
                           (TS, "timing_from_bytes", lambda p, **k: TS.build_sidecar(m1, loader, path=p, **k))):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.csv"); o = getattr(mod, fnname); n = types.SimpleNamespace(c=0)
        sha = lambda f: __import__("hashlib").sha256(rb).hexdigest()
        def w(b, _o=o):
            n.c += 1
            return _o(b)
        setattr(mod, fnname, w)
        try:
            build(p, sha_lookup=sha); c1 = n.c; assert c1 == 1 and os.path.exists(p + ".codekey")
            build(p, sha_lookup=sha); assert n.c == c1, (fnname, "unchanged code must reuse the stored row")
            def w2(b, _o=o):
                n.c += 1
                return _o(b)
            setattr(mod, fnname, w2)
            build(p, sha_lookup=sha); assert n.c == c1 + 1, (fnname, "changed extractor must recompute")
            open(p + ".codekey", "w", encoding="utf-8").write("0\n")
            build(p, sha_lookup=sha); assert n.c == c1 + 2, (fnname, "a foreign code key must recompute")
        finally:
            setattr(mod, fnname, o)
print("test_cache_code_keys: OK")

# ---- a change of a shared helper that the extractor imports locally (compute_drive_summary_v6._series) must also invalidate the sidecar rows and capacity records
import compute_drive_summary_v6 as _D
_o_series = _D._series
def _series_changed(*a, **k):
    return _o_series(*a, **k)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "s.csv"); sha = lambda f: __import__("hashlib").sha256(rb).hexdigest()
    AH.build_sidecar(m1, loader, path=p, sha_lookup=sha)
    k0 = open(p + ".codekey", encoding="utf-8").read()
    _D._series = _series_changed
    try:
        AH.build_sidecar(m1, loader, path=p, sha_lookup=sha)
    finally:
        _D._series = _o_series
    assert open(p + ".codekey", encoding="utf-8").read() != k0, "a helper change must change the sidecar code key"
print("test_cache_code_keys (helper): OK")
