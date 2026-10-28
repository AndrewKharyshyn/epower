"""M530 (analyses/M530_spec.md Rev 2): session-ledger notes name their date. Old wording absent from config / dashboard HTML; new present; the rule fires on 'corpus now N drives' and not on the batch phrase; 0 hits on the whole
post-edit config and payload; the ledger generator template does not emit 'corpus now' (a later template edit is caught); sessionLedgerAudit and the declared stamps do not read note text; splice idempotent, planted change caught."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import language_gate as G
import m530_text_splice as S

C = json.load(open("summary_config.json", encoding="utf-8")); A = json.load(open("summary_arrays.json", encoding="utf-8"))
R = {r.rid: r for r in G.RULES}["M530-ledger-corpus-now"]
def strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)
    elif isinstance(o, str): yield o
for i, d, n in ((17, "Jul 21", 167), (18, "Jul 22", 173), (19, "Jul 23", 180)):
    t = C["sessionGroups"][i]["note"]
    assert "corpus as of %s: %d drives" % (d, n) in t and ("corpus now %d drives" % n) not in t, i
assert "corpus now 167 drives" not in open("xtrail_dashboard.html", encoding="utf-8").read()
# numeric ledger fields untouched by the text edit: the rows keep their drives / km fields
assert all(isinstance(C["sessionGroups"][i].get("drives"), (int, float)) for i in (17, 18, 19))
# rule
assert R.hits("Extends the observation window to Jul 21; corpus now 167 drives / 4,644.7km") and R.hits("corpus now 180 drives")
assert not R.hits("corpus as of Jul 21: 167 drives / 4,644.7km") and not R.hits("Corpus-level, this batch lifts the study to 247 drives / 6,848.2km")
assert not [s for s in strings(C) if R.hits(s)] and not [s for s in strings(A) if R.hits(s)]
# generator template and splice tools never emit the old wording
for f in ("tools/extend_session_ledgers.py", "tools/m368_ledger_round.py", "tools/m496_ledger_splice.py"):
    assert not re.search(r"corpus now", open(f, encoding="utf-8").read(), re.I), f
# sessionLedgerAudit / the declared stamps do not parse the note text
rc = open("release_check.py", encoding="utf-8").read()
seg = rc[rc.index("sessionLedgerAudit"): rc.index("sessionLedgerAudit") + 900]
assert '["note"]' not in seg and ".get(\"note\")" not in seg
# splice: idempotent, planted change caught
assert S.main(["--check"]) == 0
plant = json.loads(json.dumps(C)); plant["sessionGroups"][17]["drives"] += 1
assert [p for p in S.diff_paths(C, plant)] == [("sessionGroups", 17, "drives")]
print("OK test_m530_ledger_notes: dated ledger notes, rule, template, splice")
