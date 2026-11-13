"""M629 (W1-05): the Compare urban-contrast prose no longer says Cold has no urban trips of 3 km or longer; the Cold rows are listed from the payload bands."""
import re


def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        assert s.count(o) == 1, (p, o[:80], s.count(o))
        s = s.replace(o, n)
    open(p, 'w', encoding='utf-8', newline='').write(s)


edit('xtrail_summary.jsx', [(
    '; Cold has no urban trips of 3 km or longer, so only the first and second rows show it. Cold is a display band',
    '; Cold rows shown: {U.bands.filter(b => b.cold).map(b => `${b.band} (${b.cold.nDrives} drives, ${b.cold.nDays} days${b.cold.status === "observed" ? "" : ", thin: no interval"})`).join("; ")}. Cold is a display band')])

edit('language_gate.py', [(
    '    Rule("M500-emulation-attribution"',
    '''    Rule("M629-urban-cold-rows", "regex", "M629/self-audit W1-05: Cold HAS urban trips of 3 km or longer (payload comparisonCube.urbanContrast.bands: 3-10 km 9 drives on 4 days, 10 km and longer 5 drives on 4 days, thin, no interval); the former sentence said it had none; the rows shown are generated from the payload bands",
         rx=r"cold has no urban trips of 3 km or longer"),
    Rule("M500-emulation-attribution"''')])

edit('semantic_gate.py', [(
    'ok("A2 REQUIRED selector label reads \'Thermal cohort\'", any("Thermal cohort" in t for t in T.values()))',
    'ok("A2 REQUIRED selector label reads \'Thermal cohort\'", any("Thermal cohort" in t for t in T.values()))\n'
    '_uc = A["comparisonCube"]["urbanContrast"]["bands"]                                                   # M629 (W1-05): the Cold rows named in the Compare urban-contrast prose are the payload bands that carry a Cold value\n'
    'ok("A2 REQUIRED M629 urban Cold note: every payload band with a Cold value is named with its drives and days, and the false \'no urban trips of 3 km or longer\' sentence is absent",\n'
    '   all(("%s (%d drives, %d days" % (b["band"], b["cold"]["nDrives"], b["cold"]["nDays"])) in T.get("highway_vs_city__all", "") for b in _uc if b.get("cold")) and any(b.get("cold") for b in _uc)\n'
    '   and "Cold has no urban trips of 3 km" not in T.get("highway_vs_city__all", ""))')])
print('ok')
