"""M676 language rule (id M675-changepoint-wording). Backslashes via chr(92). ASCII only."""
BS = chr(92)
p = 'language_gate.py'
t = open(p, encoding='utf-8', newline='').read()
crlf = '\r\n' in t[:5000]
S = t.replace('\r\n', '\n')
rx = (BS + 'b(?:dates|detects|identifies|confirms) the (?:battery |hv )?software update' + BS + 'b|' + BS + 'bsoftware[- ]update effect' + BS + 'b|' + BS + 'bchange[- ]point (?:caused|proves|confirms)' + BS + 'b|'
      + BS + 'b(?:detected|selected) (?:capacity|resistance) (?:fade|loss|increase|growth)' + BS + 'b|' + BS + 'bdate of the software update was (?:found|detected)' + BS + 'b')
rule = ('    Rule("M675-changepoint-wording", "regex", "M676 (spec analyses/M675_spec.md Rev 1.1, Director review): a detected change point is a statistical break (a level shift in a logged per-drive series) with a date interval conditional on K; '
        'never that it dates, detects or confirms the software update, a software-update effect, or a capacity or resistance fade, loss or increase",\n'
        '         rx=r"' + rx + '"),\n')
i = S.rindex('\n]\n')
S = S[:i + 1] + rule + S[i + 1:]
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', '\r\n') if crlf else S)
print('ok')
