p='language_gate.py'
s=open(p,encoding='utf-8',newline='').read()
nl='\r\n' if '\r\n' in s else '\n'
a='    Rule("M641-energy-ladder-wording"'
assert s.count(a)==1
rx='(?<![a-z])(independently corroborat[a-z]*|(standardi[sz]ed )?long pulse dcir|(lab figure at )?gentle current|benign protocol|first external anchor|gains its first external anchor|order of magnitude corroboration|bracket(s|ing)? the [0-9 ]*gtc (capacity fade|scenario) threshold)(?![a-z])'
new=('    Rule("M642-official-sheet-claims", "regex", "M642/self-audit W1-17 (owner decisions D-01, D-08): the Nissan Article 10 sheet states no test protocol, pulse length or current for internal resistance or round-trip efficiency, so DCIR-pulse and gentle-current protocols are not attributed to it; the 190,000 km / 34 % mapping onto GTC is an arithmetic scenario with no evidentiary weight (never an anchor or a corroboration), and the disclosure is consistent with, not independent corroboration of, the study framing.",'+nl+
     '         rx=r"'+rx+'"),'+nl)
open(p,'w',encoding='utf-8',newline='').write(s.replace(a,new+a))
