"""M377b: master-hash pin of the point runner. Historical tags keep the frozen hash (even when the file differs); later tags pin the live file;
a change of the file between start and end is detectable."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import m377_pin as P

with tempfile.TemporaryDirectory() as td:
    f = os.path.join(td, "dm.csv"); open(f, "w").write("a,b\n1,2\n")
    live = P.md5_of(f)
    assert P.master_pin("M377", f) == live
    assert P.master_pin("M373", f) == P.FROZEN["M373"] != live and P.master_pin("M375", f) == P.FROZEN["M375"]
    pin = P.master_pin("M376", f)
    open(f, "a").write("3,4\n")
    assert P.md5_of(f) != pin, "a modified master must differ from the pin"
src = open(os.path.join(ROOT, "tools", "m373_point.py"), encoding="utf-8").read()
assert "m377_pin.master_pin(TAG" in src and "STAGE_FORMER_ONLY_FOR_R" not in src and 'if P == "R" else None' in src
print("test_m377_pin: OK")
