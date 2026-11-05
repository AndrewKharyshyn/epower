"""M578 known-answer tests for tools/engine_on_blocks_stage.evidence_rows_identical (Director condition: anchored to the pinned evidence file list, fail closed)."""
import hashlib, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import engine_on_blocks_stage as S

ev = ["d%03d.csv" % i for i in range(10)]
pin = {"masterMd5": "abc", "nDrives": 10, "files": ev, "filesSha256": hashlib.sha256("\n".join(ev).encode("utf-8")).hexdigest()}
live = ev + ["n1.csv", "n2.csv", "n3.csv"]
head = ev + ["n1.csv"]
assert S.evidence_rows_identical(live, pin, 10, head, "abc")                      # exact prefix, committed list is a prefix of the live list
assert S.evidence_rows_identical(live, pin, 10, None, "abc")
assert not S.evidence_rows_identical([ev[1], ev[0]] + ev[2:] + ["n1.csv"], pin, 10, None, "abc")      # reordered
assert not S.evidence_rows_identical(ev[:5] + ev[6:] + ["n1.csv", "n2.csv"], pin, 10, None, "abc")     # dropped
assert not S.evidence_rows_identical(ev[:9] + ["x.csv", "n1.csv"], pin, 10, None, "abc")                # replaced
assert not S.evidence_rows_identical(live, pin, 10, ev[:8], "abc")                # committed list shorter than n_ev
assert not S.evidence_rows_identical(live, pin, 10, ev + ["other.csv"], "abc")    # committed list is not a prefix of the live list
assert not S.evidence_rows_identical(live, {**pin, "filesSha256": "0" * 64}, 10, head, "abc")    # wrong pin hash
assert not S.evidence_rows_identical(live, pin, 10, head, "different")            # pin bound to another evidence master
assert not S.evidence_rows_identical(live, None, 10, head, "abc") and not S.evidence_rows_identical(live, pin, 10, head, None)      # fail closed
assert not S.evidence_rows_identical(live, {**pin, "nDrives": 9}, 10, head, "abc")
print("test_m578_evidence_rows: OK")
