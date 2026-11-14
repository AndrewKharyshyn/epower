"""M649 (P-03) stage wiring + leaf_guard report-only flag. ASCII only."""
import json
def rep(t, o, n):
    assert t.count(o) == 1, (o[:80], t.count(o))
    return t.replace(o, n)

p = 'tools/leaf_guard.py'
t = open(p, encoding='utf-8', newline='').read(); nl = '\r\n' if '\r\n' in t[:3000] else '\n'; S = t.replace('\r\n', '\n')
S = rep(S, '    ap.add_argument("--out")\n', '    ap.add_argument("--out")\n    ap.add_argument("--report-only", action="store_true", help="M649 (P-03): early run right after ingest_core; lists the losses but never fails (later splice stages restore known leaves; the final run stays the gate)")\n')
S = rep(S, '    if rep["nUnexpected"]:\n        print("UNEXPECTED LOSSES (first 30):", file=sys.stderr)', '    if rep["nUnexpected"] and a.report_only:\n        print("EARLY REPORT (non-blocking, M649): %d unexpected losses before the splice stages; the final leaf_guard decides" % rep["nUnexpected"])\n        return\n    if rep["nUnexpected"]:\n        print("UNEXPECTED LOSSES (first 30):", file=sys.stderr)')
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', nl))

p = 'tools/ingest_stages.json'
raw = open(p, encoding='utf-8', newline='').read(); nl = '\r\n' if '\r\n' in raw[:3000] else '\n'
d = json.loads(raw)
st = d['stages']
ids = [x['id'] for x in st]
def put_after(anchor, new):
    i = ids.index(anchor)
    st.insert(i + 1, new); ids.insert(i + 1, new['id'])
put_after('ingest_core', {"id": "leaf_guard_early", "title": "M649 (P-03): early, NON-blocking lost-leaf report right after ingest_core (the splice stages restore known leaves later, so the final leaf_guard stays the gate; P-07 turns this into a blocking check)", "cmd": ["python3", "tools/leaf_guard.py", "--previous", "git:HEAD", "--report-only", "--out", "analyses/leaf_guard_early_report.json"], "verified": False, "outputs": ["analyses/leaf_guard_early_report.json"]})
put_after('powerfade_equivalence', {"id": "s1_fidelity", "title": "M649 (P-03): one shared S1 fidelity check (point slope, n, nDays, temperature coefficient of the replicated T0 design vs the published powerFade S1 reference) before the temperature-specification stages; STOP on mismatch", "cmd": ["python3", "tools/s1_fidelity.py"], "verified": False, "outputs": ["analyses/s1_fidelity.json"], "needs": ["powerfade_equivalence"]})
put_after('build_html', {"id": "dump_tabs", "title": "M649 (P-03): render every tab x All/Warm/Shoulder/Compare to text (dump_tabs.js) right after the build, so the language gate runs at ingestion and not only at the release gate", "cmd": ["node", "dump_tabs.js"], "verified": False, "outputs": ["tabtext/_precision_leaves.json"]})
put_after('dump_tabs', {"id": "semantic_gate", "title": "M649 (P-03): semantic/language gate (forbidden wording, prose == payload, mode behaviour) on the rendered tab dumps, at ingestion time; the clean-environment release gate repeats it", "cmd": ["python3", "semantic_gate.py"], "verified": False, "needs": ["dump_tabs"]})
open(p, 'w', encoding='utf-8', newline='').write(json.dumps(d, indent=1, ensure_ascii=False).replace('\n', nl) + nl)
print('ok')
