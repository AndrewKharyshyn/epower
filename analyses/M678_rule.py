"""M678 language rule (id M677-early-late-wording). Backslashes via chr(92). ASCII only."""
BS = chr(92)
p = 'language_gate.py'
t = open(p, encoding='utf-8', newline='').read()
crlf = '\r\n' in t[:5000]
S = t.replace('\r\n', '\n')
rx = (BS + 'b(?:early|late)[- ](?:vs|versus)[- ](?:late|early) (?:ageing|aging|degradation)' + BS + 'b|' + BS + 'bageing effect' + BS + 'b|' + BS + 'bthe (?:early|late)[- ](?:vs|versus)[- ](?:late|early) effect' + BS + 'b|'
      + BS + 'bcapacity (?:fade|loss)' + BS + 'b|' + BS + 'bresistance increase' + BS + 'b|' + BS + 'bcap_ah_est is (?:a |the )?(?:capacity|measured)' + BS + 'b')
rule = ('    Rule("M677-early-late-wording", "regex", "M678 (spec analyses/M677_spec.md Rev 1.1, Director review): the early-versus-late contrast is a difference between early and late drives in matched state bins, descriptive and not a look; '
        'never an ageing or degradation estimate, an ageing effect, a capacity fade or loss, a resistance increase, or cap_ah_est as a capacity",\n'
        '         rx=r"' + rx + '"),\n')
i = S.rindex('\n]\n')
S = S[:i + 1] + rule + S[i + 1:]
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', '\r\n') if crlf else S)
print('ok')
