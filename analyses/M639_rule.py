p='language_gate.py'
s=open(p,encoding='utf-8',newline='').read()
nl='\r\n' if '\r\n' in s else '\n'
a='    Rule("M638-hot-tail-share-wording"'
assert s.count(a)==1
rx = '(?<![a-z])(corpus f gen|(corrected|true|unbiased|representative|measured) f gen|adjusted headline|headline is biased)(?![a-z])'
new=('    Rule("M639-fgen-mix-wording", "regex", "M639 Director ruling (2026-11-13): the mix-standardised f_gen is a labelled sensitivity (drive-type-mix-standardised, corpus km mix, model-derived Path B); it is never the corpus f_gen, a corrected, true, unbiased, representative or measured f_gen, an adjusted headline, and the headline is not called biased.",'+nl+
     '         rx=r"'+rx+'"),'+nl)
open(p,'w',encoding='utf-8',newline='').write(s.replace(a,new+a))
