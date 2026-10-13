"""M426: tools/restamp_blocks.write_retry retries a transient OSError 13/22 on open (bounded), raises other errors and the last failure unchanged, and writes the exact text."""
import builtins, errno, os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import restamp_blocks as RB

d = tempfile.mkdtemp(); p = os.path.join(d, "x.json")
real = builtins.open
calls = {"n": 0}
def flaky(fail_times, err):
    calls["n"] = 0
    def _o(file, mode="r", *a, **k):
        if str(file) == p and "w" in mode:
            calls["n"] += 1
            if calls["n"] <= fail_times:
                raise OSError(err, "simulated")
        return real(file, mode, *a, **k)
    return _o
try:
    builtins.open = flaky(2, errno.EINVAL); RB.write_retry(p, "abc", pause=0)
    assert calls["n"] == 3 and real(p, encoding="utf-8").read() == "abc"                 # two refusals, third write succeeds
    builtins.open = flaky(99, errno.EINVAL)
    try: RB.write_retry(p, "zzz", tries=3, pause=0)
    except OSError as e: assert e.errno == errno.EINVAL and calls["n"] == 3               # bounded: the last failure is raised
    else: raise AssertionError("endless retry")
    builtins.open = flaky(1, errno.ENOENT)
    try: RB.write_retry(p, "zzz", pause=0)
    except OSError as e: assert e.errno == errno.ENOENT and calls["n"] == 1               # another error is not retried
    else: raise AssertionError("other error swallowed")
finally:
    builtins.open = real
assert real(p, encoding="utf-8").read() == "abc"                                           # a failed write never truncated the file
print("test_restamp_write_retry: OK")
