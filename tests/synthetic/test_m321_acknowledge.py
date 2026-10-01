"""Tests for tools/m321_acknowledge.py: only a warn-newspec set is acknowledged, the ref must resolve, the record satisfies the gate's ack_valid. Run: python tests/synthetic/test_m321_acknowledge.py"""
import json, os, shutil, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import m321_acknowledge as K
import m321_ladder_monitor as M

mon = {"status": "warn-newspec", "warningSetHash": "a" * 64, "selectionCodeSha256": "b" * 64, "basisNDrives": 489, "warningCodes": ["W2:start:-7.5"]}
tmp = tempfile.mkdtemp(prefix="m321ack_")
try:
    os.makedirs(os.path.join(tmp, "analyses"))
    open(os.path.join(tmp, "CHANGELOG.md"), "w").write("## M777 (2026-10-02): handling of the cold-season W2\n\nbody\n")
    open(os.path.join(tmp, "analyses", "M777_spec.md"), "w").write("spec")
    rec = K.make_record(mon, "M777 cold level", "note", root=tmp, today="2026-10-02")
    assert rec["warningSetHash"] == "a" * 64 and rec["basisNDrives"] == 489 and rec["selectionCodeSha256"] == "b" * 64 and rec["date"] == "2026-10-02"
    assert M.ack_valid(rec, mon, tmp)                                              # exactly what the gate demands
    assert K.make_record(mon, "analyses/M777_spec.md", root=tmp)["ref"] == "analyses/M777_spec.md"
    for bad_ref in ("M999 nonexistent", "", "analyses/none_spec.md"):
        try:
            K.make_record(mon, bad_ref, root=tmp); raise SystemExit(f"must reject ref {bad_ref!r}")
        except ValueError:
            pass
    for st in ("ok", "warn-refit", "cache-invalid"):
        try:
            K.make_record({**mon, "status": st}, "M777 x", root=tmp); raise SystemExit(f"must refuse status {st}")
        except ValueError:
            pass
    path = os.path.join(tmp, "analyses", "M321_acknowledgements.json")
    assert K.append_record(rec, path) is True and K.append_record(rec, path) is False       # idempotent
    assert len(json.load(open(path))) == 1 and b"\r\n" not in open(path, "rb").read()      # LF, one record
    assert K.append_record({**rec, "basisNDrives": 600}, path) is True                       # another basis is a different acknowledgement
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("M321 acknowledge tests OK")
