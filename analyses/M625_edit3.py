"""One-off editor #3 for M625: ambient coverage (n with a recorded start ambient of n cold starts) in the limits text (spec R8), from the blind audit finding 402 of 454."""


def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        assert s.count(o) == 1, (p, o[:80], s.count(o))
        s = s.replace(o, n)
    open(p, 'w', encoding='utf-8', newline='').write(s)


edit('tools/m435_tte.py', [
    ('def label_for(scope):',
     'def coverage_text(tte, files, ambient_by_drive):\n'
     '    """M625 (spec R8): how many of the analysed cold starts have a driver-recorded start ambient (list entries only)."""\n'
     '    idx = [i for i, r in enumerate(tte) if r.get("status") == "cold"]\n'
     '    n = sum(1 for i in idx if isinstance((ambient_by_drive or {}).get(files[i]), list) and (ambient_by_drive or {}).get(files[i]) and (ambient_by_drive or {}).get(files[i])[0] is not None)\n'
     '    return "start ambient recorded for %d of %d cold starts" % (n, len(idx)) if idx else None\n\n\n'
     'def label_for(scope):'),
    ('def build_block(tte, raw, days, regimes, C, meta=None, scope=None):', 'def build_block(tte, raw, days, regimes, C, meta=None, scope=None, coverage=None):'),
    ('"single vehicle, one driver, " + (scope or "scope not available"),', '"single vehicle, one driver, " + (scope or "scope not available") + (" (" + coverage + ")" if coverage else ""),'),
])
edit('tools/thermal_support_ledger.py', [
    ('    scope = M435.scope_text(tte, _days, files, _amb)\n', '    scope = M435.scope_text(tte, _days, files, _amb)\n    coverage = M435.coverage_text(tte, files, _amb)\n'),
    ('"limits": ["single vehicle, one driver, " + (scope or "scope not available"),', '"limits": ["single vehicle, one driver, " + (scope or "scope not available") + (" (" + coverage + ")" if coverage else ""),'),
    ('regime, C, meta, scope=scope)\n', 'regime, C, meta, scope=scope, coverage=coverage)\n'),
])
print("ok")
