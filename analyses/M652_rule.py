BS = chr(92)
p = 'language_gate.py'
t = open(p, encoding='utf-8', newline='').read(); crlf = '\r\n' in t[:5000]; S = t.replace('\r\n', '\n')
rx = BS + 'bkW battery cap' + BS + 'b|' + BS + 'bown measured / modeled figures' + BS + 'b'
rule = ('    Rule("M652-official-disclosure-wording", "regex", "M652 (spec analyses/M652_spec.md): the sheet\'s 66 kW is a disclosed figure at 80 % SoC, not a battery cap (the logged peak exceeds it); '
        'the comparison side is logged and estimated, not measured / modeled", rx=r"' + rx + '"),\n')
i = S.rindex('\n]\n'); S = S[:i + 1] + rule + S[i + 1:]
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', '\r\n') if crlf else S)
