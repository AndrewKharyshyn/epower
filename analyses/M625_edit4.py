"""One-off editor #4 for M625 (Director pre-merge conditions): the semantic gate M418 slice fails closed, and both dash forms are tested."""
import re


def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        assert s.count(o) == 1, (p, o[:80], s.count(o))
        s = s.replace(o, n)
    open(p, 'w', encoding='utf-8', newline='').write(s)


# fail closed: the slice start must be followed by its end anchor; otherwise the check fails (never an empty or open-ended slice)
edit('semantic_gate.py', [(
    '"".join(_x[_x.find("Support (ledger counts"):_x.find("Single vehicle, one driver", _x.find("Support (ledger counts"))] for _x in (_tl_lag, _tl_cur, _tl_fuel))))',
    '"".join(_x[_x.find("Support (ledger counts"):_x.find("Single vehicle, one driver", _x.find("Support (ledger counts"))] for _x in (_tl_lag, _tl_cur, _tl_fuel)))\n'
    '           and all(("Single vehicle, one driver" in _x[_x.find("Support (ledger counts"):]) for _x in (_tl_lag, _tl_cur, _tl_fuel) if "Support (ledger counts" in _x))        # M625: fail closed: the end anchor of the slice must exist after its start')])

p = 'tests/synthetic/test_m625_scope_label.py'
s = open(p, encoding='utf-8', newline='').read()
add = '''
# deviations (a) and (b): both dash forms of the old sentence are caught (plain en dash and the JSX-expression form found at xtrail_summary.jsx:9404 in M625)
BS = chr(92)
EN, DEG = chr(0x2013), chr(0xb0)
for old in ("Single vehicle, one driver, May" + EN + "October (ambient 3" + EN + "38 " + DEG + "C).",
            'Single vehicle, one driver, May{"' + EN + '"}October (ambient 3{"' + EN + '"}38 {"' + DEG + '"}C).'):
    hits = L.scan_text(old)
    assert "M625-scope-months" in hits and "M625-scope-ambient" in hits, (old, hits)
# the semantic gate slice guard (fail closed) is present in the source
sg = open(os.path.join(REPO, "semantic_gate.py"), encoding="utf-8").read()
assert 'find("Single vehicle, one driver"' in sg and "fail closed: the end anchor of the slice must exist after its start" in sg
'''
marker = 'print("PASS test_m625_scope_label")'
assert marker in s
s = s.replace(marker, add + marker, 1)
open(p, 'w', encoding='utf-8', newline='').write(s)
print("ok")
