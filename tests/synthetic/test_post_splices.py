"""M377a tests for tools/post_splices.restore_m366_shift (analyses/M377_spec.md Rev 2 P1): restore when absent, add basis fields when present
without them, idempotence (byte-identical second run), refusal when the stored block differs from the frozen record, and that nothing else changes."""
import copy, hashlib, json, os, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import post_splices as PS

REC = {"previous": {"a": 1}, "nCiChecked": 5, "basis": "frozen", "milestone": "M366", "basisNDrives": 489}
BASE = {"other": {"x": [1, 2]}, "fuelAnalytics": {"fuel12": {"aggregate": {"est": 1.0}}}}
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()

with tempfile.TemporaryDirectory() as td:
    ap, rp = os.path.join(td, "arrays.json"), os.path.join(td, "rec.json")
    json.dump(REC, open(rp, "w"))

    def put(o):
        json.dump(o, open(ap, "w"))
    # absent -> restored, nothing else changed
    put(BASE)
    assert PS.restore_m366_shift(ap, rp) == "restored"
    A = json.load(open(ap)); assert A["fuelAnalytics"]["fuel12"]["m366Shift"] == REC
    chk = copy.deepcopy(A); del chk["fuelAnalytics"]["fuel12"]["m366Shift"]; assert chk == BASE
    # second run: unchanged and byte-identical
    h = sha(ap); assert PS.restore_m366_shift(ap, rp) == "unchanged" and sha(ap) == h
    # present without the basis fields -> fields added only
    old = copy.deepcopy(BASE); old["fuelAnalytics"]["fuel12"]["m366Shift"] = {"previous": {"a": 1}, "nCiChecked": 5}
    put(old)
    assert PS.restore_m366_shift(ap, rp) == "basis fields added"
    assert json.load(open(ap))["fuelAnalytics"]["fuel12"]["m366Shift"] == REC
    # stored block differs from the frozen record -> STOP, file untouched
    bad = copy.deepcopy(BASE); bad["fuelAnalytics"]["fuel12"]["m366Shift"] = {"previous": {"a": 2}, "nCiChecked": 5}
    put(bad); h = sha(ap)
    try:
        PS.restore_m366_shift(ap, rp)
    except AssertionError:
        assert sha(ap) == h
    else:
        raise AssertionError("a differing block must stop")
    # a record without basis fields is refused
    json.dump({k: v for k, v in REC.items() if k != "basis"}, open(rp, "w")); put(BASE)
    try:
        PS.restore_m366_shift(ap, rp)
    except AssertionError:
        pass
    else:
        raise AssertionError("a record without basis must be refused")
# the committed record carries basis / milestone / basisNDrives
r = json.load(open(os.path.join(ROOT, "analyses", "M366_shift_record.json"), encoding="utf-8"))
assert r["milestone"] == "M366" and r["basisNDrives"] == 489 and r["basis"]
print("test_post_splices: OK")

# ---- M377b P4: blind-audit record ----
import copy as _copy
A0 = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
REC = json.load(open(os.path.join(ROOT, "analyses", "M356_blindaudit_record.json"), encoding="utf-8"))["blocks"]
assert all(r["basisNDrives"] == 489 and r["basisMilestone"] == "M356" and r["basisNote"] for r in REC.values())
def strip(a):
    a = _copy.deepcopy(a)
    pes = [a["crawlStopGo"]["phaseEnergy"]] + [a["seasonalCharts"]["charts"]["CrawlStopGo"]["data"][c]["phaseEnergy"] for c in ("all", "warm", "shoulder")]
    for pe in pes: pe.pop("blindAudit", None)
    return a
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "a.json")
    json.dump(strip(A0), open(p, "w"))
    assert PS.restore_blind_audit(p).startswith("restored top,all,warm,shoulder")      # absent -> restored
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert PS.restore_blind_audit(p) == "unchanged" and hashlib.sha256(open(p, "rb").read()).hexdigest() == h
    X = json.load(open(p)); X["crawlStopGo"]["phaseEnergy"]["blindAudit"]["nCycles"]["author"] += 1; json.dump(X, open(p, "w"))
    try:
        PS.restore_blind_audit(p)
    except AssertionError:
        pass
    else:
        raise AssertionError("a differing blind-audit body must stop")
print("test_post_splices (blind audit): OK")
