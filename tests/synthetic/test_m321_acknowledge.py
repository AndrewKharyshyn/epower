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
    # M616: the standing STOP RULE (Director, M608): out-of-basis support at the level gate on either side makes a report-only acknowledgement invalid; a spec file is required
    G_E, G_D = M.L.GATE_EVENTS, M.L.GATE_DAYS
    side = lambda e, d: {"outsideFitRange": {"nEvents": e, "nDays": d, "nAtRiskS": 1}}
    mk = lambda st, sp: {**mon, "sides": {"start": st, "stop": sp}}
    assert M.stop_rule_sides(mk(side(10, 6), side(3, 5))) == [], "the M608 state (10 events / 6 days, 3 events / 5 days) does not trigger"
    assert M.stop_rule_sides(mk(side(G_E - 1, G_D), side(0, 0))) == [] and M.stop_rule_sides(mk(side(G_E, G_D - 1), side(0, 0))) == [], "99 events or 9 days is below the gate"
    assert M.stop_rule_sides(mk(side(G_E, G_D), side(0, 0))) == ["start"] and M.stop_rule_sides(mk(side(0, 0), side(G_E + 50, G_D + 5))) == ["stop"] and M.stop_rule_sides(mk(side(G_E, G_D), side(G_E, G_D))) == ["start", "stop"]
    assert M.stop_rule_sides({**mon}) == [] and M.stop_rule_sides({**mon, "sides": {"start": {}, "stop": None}}) == [], "no support block: rule not triggered"
    trig = mk(side(G_E, G_D), side(0, 0))
    for ref in ("M777 cold level", "M777"):                                          # a CHANGELOG heading is not a spec
        try:
            K.make_record(trig, ref, root=tmp); raise SystemExit("the stop rule must refuse a CHANGELOG-heading ref")
        except ValueError as e:
            assert "STOP RULE" in str(e) and "start" in str(e)
    assert K.make_record(trig, "analyses/M777_spec.md", root=tmp)["ref"] == "analyses/M777_spec.md" and K.make_record(trig, "M777_spec.md", root=tmp)["ref"] == "M777_spec.md"
    assert M.ack_valid({**rec, "ref": "analyses/M777_spec.md"}, trig, tmp) and not M.ack_valid(rec, trig, tmp), "the gate agrees with the tool (a hand-written heading ack no longer clears it)"
    assert M.ack_valid(rec, mon, tmp), "without the trigger the heading ref still works (the M608 acknowledgement stays valid)"
    assert M.ref_is_spec_file("analyses/M777_spec.md", tmp) and not M.ref_is_spec_file("analyses/none_spec.md", tmp) and not M.ref_is_spec_file("", tmp) and not M.ref_is_spec_file("M777 x", tmp)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("M321 acknowledge tests OK")
