"""M637 (W1-08, D-03 part 1): label the hot-tail share by its estimand (drive-average pack temperature), additive meaning leaf."""
import json

def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn); ok = True; break
        assert ok, (p, o[:80], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)

MEAN = ('Share of drive time (duration-weighted) spent in drives whose drive-average pack temperature (T_pack_mean_avg) is at or above the threshold; '
        'a drive-average estimand. It is not the share of logged samples above the threshold; the sample-resolved occupancy is a separate quantity (M637/M638, self-audit W1-08, owner decision D-03).')
edit('compute_summary_arrays.py', [
    ("            'driveTimeShareGeC': share_ge,\n",
     "            'driveTimeShareGeC': share_ge,\n            'driveTimeShareGeCMeaning': (" + repr(MEAN) + "),\n")])
edit('xtrail_summary.jsx', [
    ('% of drive-time ≥35°C, highway thermal rise',
     '% of drive time spent in drives with a drive-average pack temperature ≥35°C (a drive-average estimand, not the share of logged samples above 35°C), highway thermal rise')])
# arrays: additive leaf only
raw = open('summary_arrays.json', encoding='utf-8', newline='').read()
A = json.loads(raw)
A['seasonalLife']['hotTail']['packThermalMeasured']['driveTimeShareGeCMeaning'] = MEAN
open('summary_arrays.json', 'w', encoding='utf-8', newline='').write(json.dumps(A, ensure_ascii=False, indent=1) + ('\n' if raw.endswith('\n') else ''))
print('ok')
