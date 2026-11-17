"""M707 (B3) tests for tools/raw_resolver.py and its three callers (tools/new_raw_files.py, tools/ingest_core.py, tools/stage_raw.py)."""
import io, json, os, subprocess, sys, tempfile, contextlib
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import raw_resolver as RR
import new_raw_files as NRF

def w(d, name, data=b"t,v\n1,2\n"):
    open(os.path.join(d, name), "wb").write(data)
def raises(fn):
    try: fn()
    except RR.RawConflict as ex: return ex
    return None

assert RR.key_of("2026-09-13_10-11-12.csv") == RR.key_of("20260913_101112.csv") == "20260913101112" and RR.key_of("e4ORCE_20260807_073756.csv") == "420260807073756"
with tempfile.TemporaryDirectory() as d:
    man = os.path.join(d, "m.json"); json.dump({"files": [{"canonical": "2026-09-13 10-11-12.csv"}]}, open(man, "w", encoding="utf-8"))
    w(d, "20260913_101112.csv"); w(d, "2026-09-13 10-11-12.csv"); w(d, "20260913_235959.csv"); w(d, "20260914_000000.csv"); w(d, "notes.txt")
    r = RR.resolve(d, man)
    assert len(r.index) == 3 and os.path.basename(r.index["20260913101112"]) == "2026-09-13 10-11-12.csv", "byte-identical alias accepted, the manifest name is chosen"
    s = r.summary(); assert s["nAliasedKeys"] == 1 and s["aliased"]["20260913101112"]["aliases"] == ["20260913_101112.csv"] and len(s["aliased"]["20260913101112"]["sha256"]) == 64
    assert "20260913235959" in r.index and "20260914000000" in r.index, "day rollover keys stay distinct"
    r2 = RR.resolve(d)                                   # no manifest: smallest name, deterministic
    assert os.path.basename(r2.index["20260913101112"]) == "2026-09-13 10-11-12.csv"
    # same timestamp key, different bytes: stop (also the DST fall-back case and a zero-byte or truncated duplicate)
    w(d, "20260914_000000 copy.csv", b"t,v\n9,9\n")
    ex = raises(lambda: RR.resolve(d, man)); assert ex is not None and "20260914000000" in ex.conflicts and len(ex.conflicts["20260914000000"]) == 2
    os.remove(os.path.join(d, "20260914_000000 copy.csv")); w(d, "2026-09-14_00-00-00.csv", b"")
    assert raises(lambda: RR.resolve(d, man)) is not None, "an empty duplicate is a conflict, not an alias"
    # callers
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        NRF.main(["--raw-dir", d, "--manifest", man])
    assert "RAW FILE CONFLICT" in buf.getvalue() and "20260914000000" in buf.getvalue(), "the hook reports a conflict instead of 'nothing new'"
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "raw_resolver.py"), "--raw-dir", d], capture_output=True, text=True)
    assert p.returncode == 3 and "STOP raw_resolver" in p.stdout
    os.remove(os.path.join(d, "2026-09-14_00-00-00.csv"))   # clean retry
    assert RR.resolve(d, man).summary()["nKeys"] == 3
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        NRF.main(["--raw-dir", d, "--manifest", man])
    assert "RAW FILE CONFLICT" not in buf.getvalue()
    assert NRF.new_files(d, man) == ["20260913_235959.csv", "20260914_000000.csv"], "the manifest names one key; the two other keys are new"
    # ingest_core.raw_index and detect_new both go through the resolver
    import ingest_core as IC
    assert os.path.basename(IC.raw_index(d)["20260913101112"]) == "2026-09-13 10-11-12.csv"
    w(d, "20260913_101112 b.csv", b"other")
    try:
        IC.raw_index(d); assert False
    except RR.RawConflict: pass
    try:
        IC.detect_new(None, d); assert False
    except IC.Gate as g: assert "different bytes" in str(g)
src = open(os.path.join(ROOT, "tools", "stage_raw.py"), encoding="utf-8").read()
assert "RR.resolve(" in src and "RawConflict" in src
print("test_raw_resolver: ok")
