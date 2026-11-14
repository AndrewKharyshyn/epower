"""M650 (P-04): declared payload-key reads/writes in the stage lint, stamping-final rule, stage moves and declarations. ASCII only."""
import json
def rep(t, o, n):
    assert t.count(o) == 1, (o[:80], t.count(o))
    return t.replace(o, n)

p = 'tools/stage_order.py'
t = open(p, encoding='utf-8', newline='').read(); nl = '\r\n' if '\r\n' in t[:3000] else '\n'; S = t.replace('\r\n', '\n')
S = rep(S, 'import argparse, ast, json, os, re, sys\n', 'import argparse, ast, functools, json, os, re, sys\n')
S = rep(S, 'def _string_constants(root, rel):\n', '@functools.lru_cache(maxsize=None)\ndef _string_constants_cached(root, rel):          # M650 (P-04): every stage closure re-parsed the same files; parse each file once per process\n    return _string_constants_uncached(root, rel)\n\n\ndef _string_constants(root, rel):\n    return _string_constants_cached(root, rel)\n\n\ndef _string_constants_uncached(root, rel):\n')
S = rep(S, '''    if not file_level:
        out["ok"] = not out["violations"]
        return out
''', '''    _declared(stages, idx, out)
    if not file_level:
        out["ok"] = not out["violations"]
        return out
''')
S = rep(S, '''def lint(stages, root=ROOT_DEFAULT,''', '''def _declared(stages, idx, out):
    """M650 (P-04): reads / writes declared at payload-key granularity. Tokens: `arrays:<top-level key of summary_arrays.json>` or a repository file.
    A stage that declares `reads: [token]` must come after EVERY stage that declares the token in `writes` (or, for a file token, in `outputs`), unless it lists the token in `reads_prior_state`
    (kind declared_read_before_write). Stamping-final rule: once a stage marked `stamps: true` has run, no later stage may write the payload (`summary_arrays.json` in `outputs` or an `arrays:` token in `writes`)
    unless it is itself marked `stamps: true` (kind payload_write_after_stamp), so the stamps describe the final payload."""
    writers = {}
    for s in stages:
        for tok in list(s.get("writes") or []) + [o.replace("\\\\", "/") for o in (s.get("outputs") or [])]:
            writers.setdefault(tok, []).append(s["id"])
    for s in stages:
        waived = set((x or "").replace("\\\\", "/") for x in (s.get("reads_prior_state") or []))
        for tok in s.get("reads") or []:
            if tok in waived or "*" in waived:
                continue
            ws = [w for w in writers.get(tok, []) if w != s["id"]]
            late = [w for w in ws if idx[w] > idx[s["id"]]]
            if late:
                out["violations"].append({"kind": "declared_read_before_write", "stage": s["id"], "token": tok, "writers": ws, "stageIndex": idx[s["id"]], "firstLaterWriterIndex": min(idx[w] for w in late)})
    stamp_idx = [idx[s["id"]] for s in stages if s.get("stamps")]
    if stamp_idx:
        first = min(stamp_idx)
        for s in stages:
            if idx[s["id"]] > first and not s.get("stamps"):
                wr = [o for o in (s.get("outputs") or []) if o.replace("\\\\", "/") == "summary_arrays.json"] + [w for w in (s.get("writes") or []) if w.startswith("arrays:")]
                if wr:
                    out["violations"].append({"kind": "payload_write_after_stamp", "stage": s["id"], "writes": wr, "stageIndex": idx[s["id"]], "firstStampIndex": first})


def lint(stages, root=ROOT_DEFAULT,''')
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', nl))

p = 'tools/ingest_stages.json'
raw = open(p, encoding='utf-8', newline='').read(); nl = '\r\n' if '\r\n' in raw[:3000] else '\n'
d = json.loads(raw); st = d['stages']
byid = {x['id']: x for x in st}
for k in ('stamp_basis', 'restamp_ingest', 'stamp_dependencies'):
    byid[k]['stamps'] = True
byid['comparison_cube']['writes'] = ['arrays:comparisonCube']
byid['urban_week_block']['reads'] = ['arrays:comparisonCube']; byid['urban_week_block']['writes'] = ['arrays:urbanContrastBlocks']
byid['urban_contrast_balance']['reads'] = ['arrays:comparisonCube']; byid['urban_contrast_balance']['writes'] = ['arrays:urbanContrastBalance']
byid['m483_wording_splice']['writes'] = ['arrays:_provenance']
byid['m432_refresh']['writes'] = ['arrays:evTraction']
byid['dump_tabs']['reads'] = ['xtrail_dashboard.html']
byid['semantic_gate']['reads'] = ['tabtext/_precision_leaves.json']
byid['jsdom']['reads'] = ['xtrail_dashboard.html']
# move the two content stages that wrote the payload after stamping to before stamp_basis
ids = [x['id'] for x in st]
mv = [st.pop([x['id'] for x in st].index(k)) for k in ('m483_wording_splice', 'm432_refresh')]
i = [x['id'] for x in st].index('stamp_basis')
st[i:i] = mv
open(p, 'w', encoding='utf-8', newline='').write(json.dumps(d, indent=1, ensure_ascii=False).replace('\n', nl) + nl)
print('ok')
