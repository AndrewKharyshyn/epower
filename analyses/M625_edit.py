"""One-off editor for M625 (record of the producer edits; anchors must match once)."""
import re


def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        assert s.count(o) == 1, (p, o[:80], s.count(o))
        s = s.replace(o, n)
    open(p, 'w', encoding='utf-8', newline='').write(s)


# ---- language gate
edit('language_gate.py', [(
    '    Rule("M500-emulation-attribution"',
    '''    Rule("M625-scope-months", "regex", "M625/self-audit W1-04: the analysis-scope month list is derived from the analysed drives (tools/scope_label.py); the typed 'May-October' (data now run to November) is stale",
         rx=r"may october(?! \\d{4})"),
    Rule("M625-scope-ambient", "regex", "M625/self-audit W1-04: the typed ambient ranges 'ambient 3-38 C' and 'ambient 3-5 C' are stale (the driver-recorded start ambient reaches below 0 C); the range is derived from the analysed drives",
         rx=r"ambient 3 38 c|ambient 3 5 c"),
    Rule("M500-emulation-attribution"''')])

# ---- m435_tte: label from the analysed cold-start drives
edit('tools/m435_tte.py', [
    ('LABEL = "this vehicle, one driver, May-October, ambient 3-38 C"',
     'LABEL_BASE = "this vehicle, one driver"          # M625: the month span and the ambient range are derived from the analysed cold-start drives (tools/scope_label.py), never typed\n\n\n'
     'def scope_text(tte, days, files, ambient_by_drive):\n'
     '    """M625: "<month span>, <ambient span>" of the coolant cold-start drives of the headline cohort (status == cold); None parts are omitted, never typed."""\n'
     '    import scope_label as SL\n'
     '    idx = [i for i, r in enumerate(tte) if r.get("status") == "cold"]\n'
     '    amb = []\n'
     '    for i in idx:\n'
     '        a = (ambient_by_drive or {}).get(files[i]) if files is not None else None\n'
     '        if isinstance(a, list) and a and a[0] is not None:\n'
     '            amb.append(a[0])\n'
     '    parts = [SL.month_span([days[i] for i in idx]), SL.ambient_span(amb)]\n'
     '    return ", ".join(p for p in parts if p) or None\n\n\n'
     'def label_for(scope):\n'
     '    return LABEL_BASE + ", " + (scope or "scope not available")'),
    ('def build_block(tte, raw, days, regimes, C, meta=None):', 'def build_block(tte, raw, days, regimes, C, meta=None, scope=None):'),
    ('"spec": "analyses/M435_spec.md", "label": LABEL,', '"spec": "analyses/M435_spec.md", "label": label_for(scope),'),
    ('"R4": LABEL, "R5":', '"R4": label_for(scope), "R5":'),
    ('"single vehicle, one driver, May-October, ambient 3-38 C",', '"single vehicle, one driver, " + (scope or "scope not available"),'),
    ('"label": "raw/ = sha256-verified originals (M366); " + LABEL},', '"label": "raw/ = sha256-verified originals (M366); " + blk["label"]},'),
    ('    blk = build_block(tte, raw, days, regimes, C, meta)\n',
     '    _cfg = json.load(open("summary_config.json", encoding="utf-8"))\n'
     '    blk = build_block(tte, raw, days, regimes, C, meta, scope=scope_text(tte, days, list(dm["file"]), _cfg.get("ambientByDrive")))\n'),
])
# ---- m438: label from the main block; m437: label from the main block
edit('tools/m438_strata.py', [('"checks": checks, "label": M.LABEL,', '"checks": checks, "label": main_block["label"],')])
edit('tools/m437_fill.py', [('"label": "raw/ = sha256-verified originals (M366); " + M.LABEL}', '"label": "raw/ = sha256-verified originals (M366); " + mb["label"]}')])
print("ok")
