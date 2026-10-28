"""M528 (analyses/M528_spec.md Rev 2): dated narrative strings read as of their date. Old strings absent from payload, config and dashboard HTML; new present; rule positives/negatives and 0 hits on the post-edit payload and config; splice idempotent;
payload/config deep diffs are the allowed leaf only; no stamp touched; rpmOptBand exists before it is cited; the W2 warm-season allow-list for config still holds."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import language_gate as G
import m528_text_splice as S

A = json.load(open("summary_arrays.json", encoding="utf-8")); C = json.load(open("summary_config.json", encoding="utf-8"))
R = {r.rid: r for r in G.RULES}["M528-dated-narrative"]
note = C["drivingMixNote"]; prov = A["generatorTractionRecon"]["_provenance"]

def strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)
    elif isinstance(o, str): yield o

# old absent, new present
for old in ("Current dataset distance mix (audit 2026-07-14)", "corrects the DISTANCE mix", "recomputed on the current 194-drive corpus", "freshly recomputed from the current 374-drive rpmDistribution"):
    assert old not in note and old not in prov, old
    assert old not in open("xtrail_dashboard.html", encoding="utf-8").read(), old
assert note.startswith("Dataset distance mix at the 2026-07-14 audit:") and "reweights the DISTANCE mix" in note and "the corpus was 194 drives at that date (M62, 2026-07-28) and is larger now" in note
assert "at that date every cycle-intensity figure feeding it was from May\u2013Jul (warm-season) data only (the logged corpus began 2026-05-11)" in note
assert "then-current 374-drive rpmDistribution" in prov and prov.endswith("(rpmFinding: superseded by rpmOptBand, M525).")
# rpmOptBand exists before it is cited; the corpus start date is in the master summary
assert "rpmOptBand" in A and "May 11" in A["meta"]["dateRange"]
# rule: fires on the old wording, 0 hits on the whole post-edit payload and config (history and generated strings included)
assert R.hits("Current dataset distance mix (audit 2026-07-14): ~19% pure-highway") and R.hits("the scenario corrects the DISTANCE mix toward typical daily use")
assert R.hits("NOT been recomputed on the current 194-drive corpus") and R.hits("rpmFinding freshly recomputed from the current 374-drive rpmDistribution.")
assert not [s for s in strings(A) if R.hits(s)] and not [s for s in strings(C) if R.hits(s)]
assert not R.hits("verified on the current master (determinism check) with the recomputed rows") and not R.hits("the corpus was 194 drives at that date (M62, 2026-07-28) and is larger now")
# the W2 warm-season rule is not enforced on config (the dated note stays allow-listed)
W2 = {r.rid: r for r in G.RULES}["W2-warmseason-corpus"]
assert "config" not in W2.scope
# splice: idempotent, diff = the allowed leaf only, planted change caught
assert S.main(["--check"]) == 0
new, ch = S.splice_payload(A)
assert not ch and new == A
plant = json.loads(json.dumps(A)); plant["meta"]["totalDrives"] += 1
assert [p for p in S.diff_paths(A, plant) if p != S.PROV_PATH] == [("meta", "totalDrives")]
print("OK test_m528_dated_text: dated narratives, rule, splice")
