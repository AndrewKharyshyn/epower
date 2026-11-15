"""M667 language rule (id M666-seasonal-fits-wording). Backslashes via chr(92). ASCII only."""
BS = chr(92)
p = 'language_gate.py'
t = open(p, encoding='utf-8', newline='').read()
crlf = '\r\n' in t[:5000]
S = t.replace('\r\n', '\n')
rx = (BS + 'bequivalent years?' + BS + 'b|' + BS + 'b(?:ageing|aging) rate' + BS + 'b|' + BS + 'byears of (?:battery )?life' + BS + 'b|' + BS + 'bcaused by (?:the )?cold' + BS + 'b')
rule = ('    Rule("M666-seasonal-fits-wording", "regex", "M667 (spec analyses/M666_spec.md Rev 1.1, Director review): the fitted seasonal quantities are associations by thermal class and an exposure index; '
        'never equivalent years, an ageing rate or years of life, and nothing is caused by the cold",\n'
        '         rx=r"' + rx + '"),\n')
i = S.rindex('\n]\n')
S = S[:i + 1] + rule + S[i + 1:]
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', '\r\n') if crlf else S)
print('ok')
