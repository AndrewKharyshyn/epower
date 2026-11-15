"""M674 language rule (id M673-exposure-wording). Backslashes via chr(92). ASCII only."""
BS = chr(92)
p = 'language_gate.py'
t = open(p, encoding='utf-8', newline='').read()
crlf = '\r\n' in t[:5000]
S = t.replace('\r\n', '\n')
rx = (BS + 'bcold[- ]charging (?:damage|harm|injury)' + BS + 'b|' + BS + 'b(?:harmful|damaging) charg' + BS + 'w+|' + BS + 'bsafe charging' + BS + 'b|' + BS + 'blithium plating (?:occurred|is occurring|has occurred)' + BS + 'b|' + BS + 'bmeasured exposure' + BS + 'b')
rule = ('    Rule("M673-exposure-wording", "regex", "M674 (spec analyses/M673_spec.md Rev 1.1, Director review): the exposure vector and the cold-charging screens count exposure of the logged driving window estimated from the logged current; '
        'never cold-charging damage, harmful or safe charging, plating that occurred, or a measured exposure",\n'
        '         rx=r"' + rx + '"),\n')
i = S.rindex('\n]\n')
S = S[:i + 1] + rule + S[i + 1:]
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', '\r\n') if crlf else S)
print('ok')
