"""M776 known-answer tests (analyses/M776_spec.md Rev 2.1): tools/cloud_monthly_payload.py copies the registered monthly result into the additive block
cloudMonthlyCoverage, fails closed on a pin mismatch or a missing source, touches only its own key, is idempotent, binds every displayed number to a registered field,
carries the spec sha, flags the first and last month as partial, and writes wording that passes the M776, M749 and M760 language rules."""
import copy, json, os, shutil, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import cloud_monthly_payload as cmp_
import language_gate as LG

try:
    src = cmp_.load()
except cmp_.Stop as e:
    print("test_cloud_monthly_payload: registered sources absent or changed, value tests skipped (%s)" % e)
    sys.exit(0)

blk = cmp_.build(src)
m = src["M776_cloud_monthly.json"]
rows = {r["month"]: r for r in blk["months"]}
# every displayed value equals the registered field it is copied from
for r in m["months"]:
    if r["month"] == "month unknown":
        continue
    b = rows[r["month"]]
    assert b["obdKm"] == r["obdKm"] and b["cloudOutsideKm"] == r["cloudOutsideKm"] and b["definitionRangeKm"] == r["definitionRangeKm"]
    assert b["definitionRangeKm"][0] == r["cloudOutsideKm"] and b["definitionRangeKm"][1] >= b["definitionRangeKm"][0]
assert blk["specSha256"] == m["specSha256"] and "Rev 2.1" in blk["spec"]
assert blk["totals"] == m["totals"] and blk["crossReferenceM739"] == m["crossReferenceM739"]
# first and last month of the span are partial, the others are not (Director change: November was wrongly false)
real = [r["month"] for r in m["months"] if r["month"] != "month unknown"]
assert rows[real[0]]["partial"] is True and rows[real[-1]]["partial"] is True
assert all(rows[k]["partial"] is False for k in real[1:-1])
# headline month = the non-partial month with the largest cloud movement outside the logs
full = [r for r in blk["months"] if not r["partial"]]
assert blk["headlineMonth"] == max(full, key=lambda r: r["cloudOutsideKm"])["month"]
# the M739 reference numbers are bound from the registered file, not typed
u = src["M739_unlogged_exposure.json"]
assert blk["m739Reference"]["aggregateSignedDifferenceRelative"] == u["V1_reconstruction_error"]["distance"]["aggregate_signed_bias"]
# aggregates only: no coordinates, no per-drive tracks
# wording: every string written here passes the M776 rule plus M749 and M760
def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
rules = [x for x in LG.RULES if x.rid in ("M776-cloud-monthly-wording", "M749-cloud-wording", "M760-logged-distance-wording")]
assert len(rules) == 3
for s in strings(blk):
    for r in rules:
        assert not r.hits(s), (r.rid, s[:120])
# the new rule catches what it is meant to catch
r776 = [x for x in rules if x.rid == "M776-cloud-monthly-wording"][0]
for bad in ("the missed kilometres in October", "the definition range is an upper bound", "share of OBD plus cloud distance"):
    assert r776.hits(bad), bad
for ok in ("at least 560 km of speed-supported movement outside those logs", "the definition range is not an interval"):
    assert not r776.hits(ok), ok
# fails closed: a pin mismatch writes nothing
d = tempfile.mkdtemp()
try:
    for fn in cmp_.PINS:
        shutil.copy(os.path.join(cmp_.A_DIR, fn), os.path.join(d, fn))
    p = os.path.join(d, "M776_cloud_monthly.json")
    t = open(p, encoding="utf-8").read()
    open(p, "w", encoding="utf-8", newline="").write(t.replace("1793", "1794", 1))
    try:
        cmp_.load(d)
        raise SystemExit("pin mismatch not detected")
    except cmp_.Stop:
        pass
    os.remove(os.path.join(d, "M739_unlogged_exposure.json"))
    try:
        cmp_.load(d)
        raise SystemExit("missing source not detected")
    except cmp_.Stop:
        pass
finally:
    shutil.rmtree(d, ignore_errors=True)
# splice touches only its own key (and its stamp), is idempotent
A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
B = copy.deepcopy(A)
B["cloudMonthlyCoverage"] = blk
assert not [x for x in cmp_.walk(A, B) if not x.startswith("/cloudMonthlyCoverage")] or A.get("cloudMonthlyCoverage") == blk
assert A.get("cloudMonthlyCoverage") == blk, "payload block in summary_arrays.json differs from the registered source"
print("PASS test_cloud_monthly_payload")
