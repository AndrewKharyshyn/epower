"""M642 second pass (Director wording review, 2026-11-13): headline without the unsupported consistency claim, the trend sentence labelled unverified, a scenario_only verdict for the capacity row,
the 14-year arm and variability caveat, the sheet's stated conditions in the provenance. All new text ASCII."""
import json

BS = chr(92)


def rep_once(txt, o, n, tag):
    for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
        if txt.count(oo) == 1:
            return txt.replace(oo, nn)
    raise AssertionError((tag, o[:90], txt.count(o)))


HEAD_OLD = open('analyses/M642_edit.py', encoding='utf-8').read()          # only to read the previous HEAD_NEW text
HEAD_PREV = ('No official figure contradicts a study finding, and the disclosure does not test one either. Its structure -- a large tolerated capacity fade alongside separately tracked power fade and a large '
             'internal-resistance increase, on a high power/energy-ratio pack -- is consistent with this study\'s framing of the HV battery as a power buffer whose functionally relevant degradation is '
             'internal-resistance-driven power fade; it neither corroborates nor establishes that framing (the figures are the manufacturer\'s own maxima after 14 years or 190,000 km). '
             'The one figure that must never be read as a direct level match is internal resistance (see resistance.note) -- track its TREND against ours, never its absolute value.')
HEAD_NEW = ('No official figure contradicts a study finding, and the disclosure does not test one either. Article 10 prescribes the parameter set, so the sheet carries no evidence for or against this study\'s framing '
            'of the HV battery as a power buffer; its figures are the manufacturer\'s own maxima after 14 years or 190,000 km (a maximum capacity fade, a maximum power fade and a maximum internal-resistance increase), '
            'and the pack\'s power/energy ratio is a study estimate that assumes the capacity. '
            'The one figure that must never be read as a direct level match is internal resistance (see resistance.note); only a relative change could be contrasted, assuming the in-drive proxy scales with the sheet figure (unverified).')
TREND_OLD = 'What IS comparable is the estimated TREND (see powerFade / fadeModes.power), which is the null result reported separately below.'
TREND_NEW = 'The closest contrast is a relative change, assuming the in-drive proxy scales with the sheet figure (unverified); see powerFade / fadeModes.power for the estimated trend, a null result reported separately below.'
CAPHEAD_OLD = 'capacity-fade reference point maps'
CAPHEAD_NEW = 'maximum capacity fade (stated for 14 years or that mileage) maps'
CAPTAIL_OLD = 'and the sheet gives the 34% as a maximum decrease after 14 years or 190,000 km of normal European use, not as a defined GTC endpoint.'
CAPTAIL_NEW = ('and the sheet gives the 34% as a maximum decrease after 14 years or 190,000 km of normal customer use in the European market, which may vary with driving style, charging behaviour and environmental factors, '
               'not as a defined GTC endpoint.')
PROV_OLD = ('The values are those printed in the manufacturer\'s table, which states no test protocol for any of them; ')
PROV_NEW = ('The values are those printed in the manufacturer\'s table. Conditions the sheet states: power at SOC 80% of new battery condition at room temperature; internal resistance and round-trip efficiency under SOC 80% / new battery condition; '
            'the fade, increase and life values are maxima or guide values after 14 years or 190,000 km of normal customer use in the European market. It states no test protocol for any of them; ')

# builder
p = 'compute_summary_arrays.py'
s = open(p, encoding='utf-8', newline='').read()
o = ("                 'must NEVER be read as a state-of-health percentage. What '\n"
     "                 'IS comparable is the estimated TREND (see powerFade / '\n"
     "                 'fadeModes.power), which is the null result reported '\n"
     "                 'separately below.')}\n")
n = ("                 'must NEVER be read as a state-of-health percentage. The '\n"
     "                 'closest contrast is a relative change, assuming the in-drive proxy scales with the sheet figure (unverified); see powerFade / '\n"
     "                 'fadeModes.power for the estimated trend, a null result reported '\n"
     "                 'separately below.')}\n")
s = rep_once(s, o, n, 'trend')
s = rep_once(s, 'f"capacity-fade reference point maps, via this study\'s "', 'f"maximum capacity fade (stated for 14 years or that mileage) maps, via this study\'s "', 'caphead')
tail_old = 'and the sheet gives the 34% as a maximum decrease after 14 years or 190,000 km of normal European use, not as a defined GTC endpoint.'
tail_new = CAPTAIL_NEW.replace("'", BS + "'")
s = rep_once(s, tail_old, tail_new, 'captail')
s = rep_once(s, "             'consistent_by_design',\n", "             'scenario_only',\n", 'verdict')
i = s.index("        'verdictHeadline': (\n")
j = s.index("never its absolute value.'),\n", i) + len("never its absolute value.'),\n")
s = s[:i] + "        'verdictHeadline': (\n            '" + HEAD_NEW.replace("'", BS + "'") + "'),\n" + s[j:]
open(p, 'w', encoding='utf-8', newline='').write(s)

# config
p = 'summary_config.json'
c = open(p, encoding='utf-8', newline='').read()
assert c.count(PROV_OLD) == 1
c = c.replace(PROV_OLD, PROV_NEW).replace('filed under Article 10', 'published under Article 10')
json.loads(c)
open(p, 'w', encoding='utf-8', newline='').write(c)

# payload
p = 'summary_arrays.json'
raw = open(p, encoding='utf-8', newline='').read()
A = json.loads(raw)
O = A['officialDisclosureCorrelation']
O['official']['_provenance'] = O['official']['_provenance'].replace(PROV_OLD, PROV_NEW).replace('filed under Article 10', 'published under Article 10')
assert O['official']['_provenance'] == json.loads(c)['officialDisclosure']['_provenance']
assert TREND_OLD in O['resistance']['note']
O['resistance']['note'] = O['resistance']['note'].replace(TREND_OLD, TREND_NEW)
O['rows'][2]['note'] = O['resistance']['note']
cn = O['capacityFadeAnchor']['note']
assert CAPHEAD_OLD in cn and CAPTAIL_OLD in cn
cn = cn.replace(CAPHEAD_OLD, CAPHEAD_NEW).replace(CAPTAIL_OLD, CAPTAIL_NEW)
O['capacityFadeAnchor']['note'] = cn
O['rows'][5]['note'] = cn
O['rows'][5]['verdict'] = 'scenario_only'
assert O['verdictHeadline'] == HEAD_PREV
O['verdictHeadline'] = HEAD_NEW
open(p, 'w', encoding='utf-8', newline='').write(json.dumps(A, ensure_ascii=False, indent=1) + ('\n' if raw.endswith('\n') else ''))

# jsx
p = 'xtrail_summary.jsx'
j = open(p, encoding='utf-8', newline='').read()
j = rep_once(j, 'external validation, not a new measurement.', 'external reference, not a validation and not a new measurement.', 'jsx ext')
j = rep_once(j, '      not_comparable:        {bg:"#fffbeb",bd:"#fde68a",fg:"#b45309",label:"Not comparable"},\n',
             '      not_comparable:        {bg:"#fffbeb",bd:"#fde68a",fg:"#b45309",label:"Not comparable"},\n      scenario_only:         {bg:"#fffbeb",bd:"#fde68a",fg:"#b45309",label:"Scenario only"},\n', 'jsx verdict')
open(p, 'w', encoding='utf-8', newline='').write(j)
print('ok')
