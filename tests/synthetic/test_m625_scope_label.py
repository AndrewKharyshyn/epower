"""M625 known-answer tests (spec analyses/M625_spec.md Rev 1 section 3 and R3/R4): scope helper, producers carry no typed month list or ambient range, language-gate rules."""
import os, re, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools")); sys.path.insert(0, REPO)
import scope_label as S

# month_span
assert S.month_span(['2026-05-11', '2026-10-31']) == 'May-October 2026'
assert S.month_span(['2026-05-11', '2026-11-09']) == 'May-November 2026'
assert S.month_span(['2026-05-11', '2027-05-10']) == 'May 2026-May 2027'
assert S.month_span(['2026-05-01', '2026-05-30']) == 'May 2026'
assert S.month_span([]) is None and S.month_span([None, 'x']) is None
# ambient_span (R4: decimal half-up, -0.0, one decimal for both endpoints)
assert S.ambient_span([3, 38]) == 'ambient 3 to 38 C'
assert S.ambient_span([-1.0, 38.0]) == 'ambient -1 to 38 C'
assert S.ambient_span([-0.5, 12.25]) == 'ambient -0.5 to 12.3 C'          # 12.25 -> 12.3 (half up on the decimal string, not binary %.1f)
assert S.ambient_span([-0.0, 5]) == 'ambient 0 to 5 C'
assert S.ambient_span([2.5, 38]) == 'ambient 2.5 to 38.0 C'
assert S.ambient_span([float('nan'), None, 'a']) is None and S.ambient_span([]) is None
# winter clause (R2)
assert S.winter_clause(['2026-05-11', '2026-11-09']) == 'winter (December to February) stays unobserved'
assert S.winter_clause(['2026-12-05', '2026-12-06', '2026-11-01']) == 'December to February observed on 2 drives on 2 days, below the support floor'
try:
    S.winter_clause(['2026-12-%02d' % d for d in range(1, 11)])        # 10 drives on 10 days: at the floor
    raise AssertionError('no stop at the floor')
except S.WinterAtSupport:
    pass
assert 'below the support floor' in S.winter_clause(['2026-12-01'] * 12)      # 12 drives on 1 day: days below the floor

# static: producers hold no typed month list or ambient range (historic analyses/*.json excluded)
BAD = [r"May-October", r"ambient 3-38", r"ambient 3-5 C", r"3-38 C"]
for p in ("tools/m435_tte.py", "tools/m438_strata.py", "tools/m437_fill.py", "tools/thermal_support_ledger.py", "tools/capacity_basis.py", "tools/dependence_sensitivity.py", "tools/integration_scenarios.py", "tools/serial_dependence.py"):
    t = open(os.path.join(REPO, p), encoding="utf-8").read()
    for b in BAD:
        assert not re.search(b, t), (p, b)

# static: the dashboard source holds no typed scope sentence either (en dash and JSX-expression dash forms included; found by the semantic gate at M625)
jsx = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read()
assert not re.search(r'May(?:[–—-]|\{"[–—-]"\})October', jsx), "typed May-October in xtrail_summary.jsx"
assert not re.search(r'ambient 3(?:[–—-]|\{"[–—-]"\})38', jsx), "typed ambient 3-38 in xtrail_summary.jsx"

# language gate (R3): old phrases hit, the helper's own wording does not
import language_gate as L
for old in ("single vehicle, one driver, May-October", "one vehicle, May-October data", "this vehicle, one driver, May-October, ambient 3-38 C", "the cold cohort (55 drives on 11 days, ambient 3-5 C)"):
    assert any(r.startswith("M625") for r in L.scan_text(old)), old
for new in ("single vehicle, one driver, May-October 2026", "this vehicle, one driver, May-November 2026, ambient -1 to 38 C", "driver-recorded start ambient -1 to 5 C"):
    assert not any(r.startswith("M625") for r in L.scan_text(new)), new

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
print("PASS test_m625_scope_label")
