"""M658 language rule (id M658-bms-map-wording). Backslashes via chr(92). ASCII only."""
BS = chr(92)
p = 'language_gate.py'
t = open(p, encoding='utf-8', newline='').read()
crlf = '\r\n' in t[:5000]
S = t.replace('\r\n', '\n')
rx = (BS + 'bbms (?:limits|limited|restricts?|restricted) (?:the )?(?:regen' + BS + 'w*|charg' + BS + 'w*)' + BS + 'b|'
      + BS + 'btrue (?:power |charge )?limit' + BS + 'b|'
      + BS + 'bregenerative acceptance' + BS + 'b|'
      + BS + 'bthe battery limit(?:s|ed)' + BS + 'b|'
      + BS + 'bcaused by (?:the )?cold' + BS + 'b')
rule = ('    Rule("M658-bms-map-wording", "regex", "M658 (spec analyses/M657_spec.md Rev 1.1, Director review R11): the possible-power map describes the BMS-reported (logged / app-calculated) possible power; '
        'it never says the BMS limited regeneration or charging, a true limit, regenerative acceptance, that the battery limits, or that the cold caused a value",\n'
        '         rx=r"' + rx + '"),\n')
i = S.rindex('\n]\n')
S = S[:i + 1] + rule + S[i + 1:]
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', '\r\n') if crlf else S)
print('ok')
