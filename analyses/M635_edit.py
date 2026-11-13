"""M635 (W1-18): documentation drift. Every figure below was re-read from disk (line counts: wc; stage timings: runs/20261110T232013Z/status.json and runs/20261105T173024Z/status.json; cell-spread bound: summary_arrays.json degradationTrends.cellSpread.releasedEquivalence.delta)."""
import json


def edit(p, pairs, enc='utf-8'):
    s = open(p, encoding=enc, newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn)
                ok = True
                break
        assert ok, (p, o[:90], s.count(o))
    open(p, 'w', encoding=enc, newline='').write(s)


edit('CLAUDE.md', [
    ('`xtrail_summary.jsx` (~11.5k lines), `compute_summary_arrays.py` (~17.8k lines)', '`xtrail_summary.jsx` (~14.4k lines), `compute_summary_arrays.py` (~18.9k lines)'),
    ('reprocesses every raw file (~440 s) and refits ML columns', 'reprocesses every raw file (~440 s measured at the 410-drive basis, not re-measured since; it grows with the corpus) and refits ML columns'),
    ('about 260 s extra', 'about 320-350 s (runs/20261110T232013Z: 316 s; runs/20261105T173024Z: 353 s)'),
    ('F03 (raw content provenance) stays\n  open until Andrii decides on re-anchoring. Audit v3 follow-up plan',
     'F03 (raw content provenance) was\n  resolved at the raw-file level by M366 (see the F03 bullet above); what remains open is the clean-room rebuild and a new cross-validation. Audit v3 follow-up plan'),
])
edit('docs/overview.md', [('cell-spread 0.2315 mV/month', 'cell-spread 0.2318 mV/month')])
edit('.claude/skills/ingest-drive/SKILL.md', [
    ('3. If a stage is `not_implemented` (first use): implement `tools/ingest_core.py` from `docs/workflow-and-tools.md`\n   protocol steps 1-5 by reading the real function signatures with grep (Sonnet task). Then rerun.\n',
     '3. All stages are implemented (`tools/ingest_core.py` and the stages of `tools/ingest_stages.json`). A stage reporting `not_implemented` is a defect: do not\n   re-implement it here; stop and report it. Typical full-run cost (runs/20261110T232013Z): about 3,360 s over 87 stages (regen_v2 316 s, release_check 417 s).\n'),
])

# ingest_stages.json: the note states what 'verified' means now; stages that ran ok in the last full ingestion are verified
d = open('tools/ingest_stages.json', encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in d[:300] else '\n'
note_old = "'verified' = command is evidenced in release_check.py / project code; false = reconcile against the real scripts in the first Code session."
note_new = "'verified' = the stage ran green in a full ingestion run (the latest: runs/20261110T232013Z, 87 stages) or is evidenced in release_check.py; false = new since that run (not yet run in a full ingestion: winter_temperature_controls M634, release_identity M621), reconcile on its first full run."
assert d.count(note_old) == 1
d = d.replace(note_old, note_new)
J = json.loads(d)
want = {'m321_ladder_monitor', 'start_ratio_refresh', 'm432_refresh'}
out = d
for sid in want:
    i = out.index('"id": "%s"' % sid)
    j = out.index('"verified": false', i)
    assert j - i < 3000, sid
    out = out[:j] + '"verified": true' + out[j + len('"verified": false'):]
json.loads(out)
open('tools/ingest_stages.json', 'w', encoding='utf-8', newline='').write(out)

# state.py: explicit UTF-8 for both files (the default Windows code page wrote mojibake into STATE.md)
edit('tools/state.py', [
    ('json.dump(s, open(P("state.json"), "w"), indent=1)', 'json.dump(s, open(P("state.json"), "w", encoding="utf-8", newline="\\n"), indent=1)'),
    ('open(P("STATE.md"), "w").write("\\n".join(md))', 'open(P("STATE.md"), "w", encoding="utf-8", newline="\\n").write("\\n".join(md))'),
])
print('ok')
