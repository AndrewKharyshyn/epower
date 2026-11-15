"""M676 language rule 2 (id M676-uncalibrated-interval). Backslashes via chr(92). ASCII only."""
BS = chr(92)
p = 'language_gate.py'
t = open(p, encoding='utf-8', newline='').read()
crlf = '\r\n' in t[:5000]
S = t.replace('\r\n', '\n')
rx = (BS + 'b(?:95 ?%? ?(?:ci|confidence interval)|confidence interval) (?:of|for) the (?:change[- ]point|break|location)' + BS + 'b|' + BS + 'b(?:change[- ]point|break)s? (?:is |are )?localised to' + BS + 'b|' + BS + 'bthe 95 ?%? ?ci of the (?:change[- ]point|break)' + BS + 'b')
rule = ('    Rule("M676-uncalibrated-interval", "regex", "M676 (Director decision): the change-point location intervals are nominal and uncalibrated (planted-step coverage 0.62 against 0.85); '
        'never a 95 percent CI or confidence interval of a change point or break, nor a change point localised to a number of days",\n'
        '         rx=r"' + rx + '"),\n')
i = S.rindex('\n]\n')
S = S[:i + 1] + rule + S[i + 1:]
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', '\r\n') if crlf else S)
print('ok')
