"""M707 (B2) tests for tools/ci_anchor.py: sync rewrites exactly the one anchor, is idempotent, keeps CRLF and every other byte, stops on a missing or duplicated anchor,
--check writes nothing; the stage sits right after ingest_core, which is the only stage that writes drive_master.csv."""
import hashlib, json, os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ci_anchor as CA

STALE = "0" * 32
def mk(td, text, master=b"a,b\n1,2\n"):
    os.makedirs(os.path.join(td, ".github", "workflows"))
    open(os.path.join(td, ".github", "workflows", "ci.yml"), "wb").write(text.encode("utf-8"))
    open(os.path.join(td, "drive_master.csv"), "wb").write(master)
    return hashlib.md5(master).hexdigest()
rd = lambda td: open(os.path.join(td, ".github", "workflows", "ci.yml"), "rb").read().decode("utf-8")

for eol in ("\n", "\r\n"):
    with tempfile.TemporaryDirectory() as td:
        body = "a: 1" + eol + "      - run: python tools/verify_import.py --quick --expect-master-md5 " + STALE + eol + "tail: x" + eol
        md5 = mk(td, body)
        assert CA.sync(td, check=True) == (True, STALE, md5) and rd(td) == body, "--check must not write"
        assert CA.sync(td) == (True, STALE, md5)
        assert rd(td) == body.replace(STALE, md5), "exactly the anchor changes, line endings kept"
        assert CA.sync(td) == (False, md5, md5), "idempotent"
        assert CA.main(["--root", td, "--check"]) == 0
for bad in ("no anchor here\n", "--expect-master-md5 %s\n--expect-master-md5 %s\n" % (STALE, STALE)):
    with tempfile.TemporaryDirectory() as td:
        mk(td, bad)
        assert CA.main(["--root", td]) == 2, "missing or duplicated anchor is a stop"
st = json.load(open(os.path.join(ROOT, "tools", "ingest_stages.json"), encoding="utf-8"))["stages"]
ids = [s["id"] for s in st]
assert ids[ids.index("ingest_core") + 2] == "ci_anchor" and ids[ids.index("ingest_core") + 1] == "leaf_guard_early", "right after ingest_core and its early leaf report (M649 keeps that report directly behind ingest_core)"
assert [s["id"] for s in st if "drive_master.csv" in (s.get("outputs") or [])] == ["ingest_core"], "a later stage writing the master would stale the anchor"
assert st[ids.index("ci_anchor")]["outputs"] == [".github/workflows/ci.yml"]
print("test_ci_anchor: ok")
