"""M642 (W1-17, owner decisions D-01 and D-08): the official-disclosure block states only what the Nissan sheet states.
Edits the builder (compute_summary_arrays._official_disclosure_correlation), summary_config.json (officialDisclosure._provenance), xtrail_summary.jsx (the panel intro, the threshold card, the Rated capacity side note)
and splices the same text leaves into summary_arrays.json. All new text is ASCII. The sheet (X-Trail_e-POWER.pdf, sha256 edd2e4719e54c73feff940a2afc87733ddddce71e47579b42336bb423582b3c8) gives: rated capacity 5 Ah
(capacity = energy / nominal battery voltage), capacity fade 34 % and power fade 25.8 % and resistance increase 75 % as maxima after 14 years or 190,000 km of normal European use, power 66.0 kW at SOC 80 % of new battery
condition at room temperature, internal resistance 0.210 ohm under SOC 80 % of new battery condition, round-trip efficiency 99.6 % under new battery condition; no test protocol, pulse length or current is stated."""
import json, re

BS = chr(92)


def cut(s, start, end_marker):
    i = s.index(start)
    j = s.index(end_marker, i) + len(end_marker)
    return i, j


# ---------------- new texts (ASCII) ----------------
RES_NOTE_OLD_ARR = 'The official figure is a standardized long-pulse DCIR at 80% SoC, ~25°C. our '
RES_NOTE_NEW = ('The official figure is the sheet\'s "internal resistance under SOC 80% of new battery condition"; the sheet states no test protocol, pulse length or temperature for it. our ')
RT_OLD_ARR = 'Lab figure at gentle current, new battery. Real buffering at 20-35C peaks incurs I²R losses this figure does not capture, which is why the study reports gross throughput rather than a round-trip efficiency.'
RT_NEW = ('The sheet gives 99.6% for a new battery and states no current, load or protocol. Whether it applies to the current levels of in-drive buffering is not stated; '
          'this study reports gross throughput per 100 km rather than a round-trip efficiency.')
RT_OFF_OLD = '% (new, benign protocol)'
RT_OFF_NEW = '% (new battery condition)'
HEAD_NEW = ('No official figure contradicts a study finding, and the disclosure does not test one either. Its structure -- a large tolerated capacity fade alongside separately tracked power fade and a large '
            'internal-resistance increase, on a high power/energy-ratio pack -- is consistent with this study\'s framing of the HV battery as a power buffer whose functionally relevant degradation is '
            'internal-resistance-driven power fade; it neither corroborates nor establishes that framing (the figures are the manufacturer\'s own maxima after 14 years or 190,000 km). '
            'The one figure that must never be read as a direct level match is internal resistance (see resistance.note) -- track its TREND against ours, never its absolute value.')
HEAD_OLD_START = 'No official figure contradicts a study finding. The disclosure\'s own structure'
CAP_NOTE_TAIL_NEW = ('. This is an arithmetic scenario with no evidentiary weight: this study\'s own estimated gtcPerKm (from logged current; assumed capacity basis) multiplied by the sheet\'s 190,000 km. '
                     'The band lies near the assumed threshold only because both rest on this study\'s own intensities and assumed capacity; it neither calibrates nor verifies the threshold (still verified:false), '
                     'and the sheet gives the 34% as a maximum decrease after 14 years or 190,000 km of normal European use, not as a defined GTC endpoint.')
ROW0_OURS_NEW = '{round(float(clean[\'cap_ah_est\'].median()),2)}'  # placeholder (see builder block)
PROV_OLD = 'Figures are the manufacturer\'s own test-protocol outputs; the source table states'
PROV_NEW = ('The values are those printed in the manufacturer\'s table, which states no test protocol for any of them; a copy of the sheet (X-Trail_e-POWER.pdf, 310,365 bytes, sha256 '
            'edd2e4719e54c73feff940a2afc87733ddddce71e47579b42336bb423582b3c8) is stored outside the repository (reference_downloads/nissan_article10). The source table states')
PROV_OLD2 = 'image source reviewed 2026-07-31; no public URL captured this session'
PROV_NEW2 = 'image source reviewed 2026-07-31; no public URL captured; the stored copy is described below'

# ---------------- 1. builder ----------------
p = 'compute_summary_arrays.py'
s = open(p, encoding='utf-8', newline='').read()
crlf = '\r\n' in s[:20000]
S = s.replace('\r\n', '\n')

# resistance.note (source is split over lines)
o = ("        'note': ('NOT a like-for-like comparison. The official figure is a '\n"
     "                 'standardized long-pulse DCIR at 80% SoC, ~25" + BS + "u00b0C. our '\n")
n = ("        'note': ('NOT a like-for-like comparison. The official figure is the sheet" + BS + "'s '\n"
     "                 '\"internal resistance under SOC 80% of new battery condition\"; the sheet states no test protocol, '\n"
     "                 'pulse length or temperature for it. our '\n")
assert S.count(o) == 1, 'resistance note'
S = S.replace(o, n)

# Rated capacity row
i, j = cut(S, "        _row('Rated capacity',", "(see fadeModes.capacity).'),\n")
S = S[:i] + (
    "        _row('Rated capacity', f\"{od['ratedCapacityAh']} Ah\",\n"
    "             f\"{od['ratedCapacityAh']} Ah adopted as the throughput reference (exposureBasis.referenceAh, verified:false); no capacity is measured here\",\n"
    "             'not_comparable',\n"
    "             'The sheet defines rated capacity as energy divided by the nominal battery voltage. This study adopted 5.0 Ah as its exposure reference (owner decision D-01) and estimates no capacity, '\n"
    "             'so nothing is compared. The legacy 2.1 kWh reference divided by the median pack voltage ' +\n"
    "             (f\"is {round(float(clean['cap_ah_est'].median()),2)} Ah\" if 'cap_ah_est' in clean.columns else 'gives a different Ah value') +\n"
    "             ', an algebraic restatement of that assumption and not an independent capacity estimate (see fadeModes.capacity).'),\n"
) + S[j:]

# Round-trip efficiency row
i, j = cut(S, "        _row('Round-trip efficiency',", "'rather than a round-trip efficiency.'),\n")
S = S[:i] + (
    "        _row('Round-trip efficiency',\n"
    "             f\"{od['roundTripEfficiencyPct']}% (new battery condition)\",\n"
    "             'not measured (gross-throughput-per-100km convention used instead)',\n"
    "             'not_comparable',\n"
    "             '" + RT_NEW + "'),\n"
) + S[j:]

# capacity-fade anchor note tail (from the 'First external anchor' literal to the end of the note)
i, j = cut(S, "                     '. First external anchor for a constant previously '", "'decrease, not a defined GTC endpoint.')}\n")
S = S[:i] + "                     '" + CAP_NOTE_TAIL_NEW + "')}\n" + S[j:]
# the bracketing clause of the same note
o = "                     (f\" -- a band that BRACKETS the study's assumed \"\n                      f\"{thr:,} GTC capacity-fade threshold\" if brackets else\n"
n = "                     (f\" -- a band that includes the study's assumed \"\n                      f\"{thr:,} GTC capacity-fade threshold\" if brackets else\n"
assert S.count(o) == 1, 'brackets clause'
S = S.replace(o, n)

# verdict headline
i, j = cut(S, "        'verdictHeadline': (\n", "against ours, never its absolute value.'),\n")
S = S[:i] + "        'verdictHeadline': (\n            '" + HEAD_NEW.replace("\\'", "'").replace("'", BS + "'") + "'),\n" + S[j:]
S = S.replace('\n', '\r\n') if crlf else S
open(p, 'w', encoding='utf-8', newline='').write(S)

# ---------------- 2. config provenance ----------------
p = 'summary_config.json'
c = open(p, encoding='utf-8', newline='').read()
assert c.count(PROV_OLD) == 1 and c.count(PROV_OLD2) == 1
c = c.replace(PROV_OLD, PROV_NEW).replace(PROV_OLD2, PROV_NEW2)
json.loads(c)
open(p, 'w', encoding='utf-8', newline='').write(c)

# ---------------- 3. payload leaves ----------------
p = 'summary_arrays.json'
raw = open(p, encoding='utf-8', newline='').read()
A = json.loads(raw)
O = A['officialDisclosureCorrelation']
O['official']['_provenance'] = O['official']['_provenance'].replace(PROV_OLD, PROV_NEW).replace(PROV_OLD2, PROV_NEW2)
assert PROV_NEW in O['official']['_provenance']
rn = O['resistance']['note']
assert RES_NOTE_OLD_ARR in rn
O['resistance']['note'] = rn.replace(RES_NOTE_OLD_ARR, RES_NOTE_NEW)
O['rows'][2]['note'] = O['resistance']['note']
ah = re.search(r'([0-9.]+) Ah \(median', O['rows'][0]['ours']).group(1)
O['rows'][0] = {'parameter': 'Rated capacity', 'official': O['rows'][0]['official'],
                'ours': '5.0 Ah adopted as the throughput reference (exposureBasis.referenceAh, verified:false); no capacity is measured here', 'verdict': 'not_comparable',
                'note': ('The sheet defines rated capacity as energy divided by the nominal battery voltage. This study adopted 5.0 Ah as its exposure reference (owner decision D-01) and estimates no capacity, so nothing is compared. '
                         'The legacy 2.1 kWh reference divided by the median pack voltage is ' + ah + ' Ah, an algebraic restatement of that assumption and not an independent capacity estimate (see fadeModes.capacity).')}
O['rows'][4]['official'] = O['rows'][4]['official'].replace(RT_OFF_OLD, RT_OFF_NEW)
assert O['rows'][4]['note'] == RT_OLD_ARR, O['rows'][4]['note']
O['rows'][4]['note'] = RT_NEW
cn = O['capacityFadeAnchor']['note']
k = cn.index('. First external anchor')
head = cn[:k].replace('BRACKETS', 'includes')
O['capacityFadeAnchor']['note'] = head + CAP_NOTE_TAIL_NEW
O['rows'][5]['note'] = O['capacityFadeAnchor']['note']
O['verdictHeadline'] = HEAD_NEW
open(p, 'w', encoding='utf-8', newline='').write(json.dumps(A, ensure_ascii=False, indent=1) + ('\n' if raw.endswith('\n') else ''))

# ---------------- 4. jsx ----------------
p = 'xtrail_summary.jsx'
j = open(p, encoding='utf-8', newline='').read()


def rep(txt, o, n):
    for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
        if txt.count(oo) == 1:
            return txt.replace(oo, nn)
    raise AssertionError(o[:80])


j = rep(j, '<strong style={{color:"#b45309"}}>The capacity-fade threshold gains its first external anchor:</strong>', '<strong style={{color:"#b45309"}}>An arithmetic scenario with no evidentiary weight:</strong>')
j = rep(j, '— bracketing the {S.officialDisclosureCorrelation.capacityFadeAnchor?.scenarioThresholdGtc?.toLocaleString("en-US")}-GTC scenario threshold used throughout Section P, previously carried with no external provenance at all (order-of-magnitude corroboration only, not a calibration — see capacityFadeAnchor.note).',
        '— a band that {S.officialDisclosureCorrelation.capacityFadeAnchor?.bracketsThreshold ? "includes" : "does not include"} the {S.officialDisclosureCorrelation.capacityFadeAnchor?.scenarioThresholdGtc?.toLocaleString("en-US")}-GTC scenario threshold used throughout Section P; it neither calibrates nor verifies that threshold, because both rest on this study\'s own intensities and assumed capacity (see capacityFadeAnchor.note).')
j = rep(j, 'cfa ? `brackets the ${cfa.scenarioThresholdGtc.toLocaleString("en-US")}-GTC scenario threshold: ${cfa.bracketsThreshold?"yes":"no"}` : "",',
        'cfa ? `band includes the ${cfa.scenarioThresholdGtc.toLocaleString("en-US")}-GTC scenario threshold: ${cfa.bracketsThreshold?"yes":"no"} (arithmetic scenario, no evidentiary weight)` : "",')
j = rep(j, '{r.ours}{r.parameter==="Rated capacity" ? <div style={{fontSize:9,color:"#92400e",marginTop:2}}>Assumption restated, not an estimate: the value is the legacy 2.1 kWh reference divided by the median pack voltage; its ratio to 5.0 Ah is the reference factor itself, not agreement or disagreement with the OEM figure, and the verdict is a bookkeeping consistency, not a validation.</div> : null}</td>',
        '{r.ours}</td>')
open(p, 'w', encoding='utf-8', newline='').write(j)
print('ok')
