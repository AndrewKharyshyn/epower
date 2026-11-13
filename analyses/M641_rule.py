p='language_gate.py'
s=open(p,encoding='utf-8',newline='').read()
nl='\r\n' if '\r\n' in s else '\n'
a='    Rule("M639-fgen-mix-wording"'
assert s.count(a)==1
rx='(?<![a-z])((true|corrected) (gross )?throughput( total)?|the true total|support policy (error bar|uncertainty interval|confidence interval)|ladder (is|gives) (an? )?(error bar|uncertainty interval|confidence interval)|monte carlo (range|interval) is (an? )?(coverage|confidence) interval)(?![a-z])'
new=('    Rule("M641-energy-ladder-wording", "regex", "M641 Director ruling (2026-11-13): the energy ladder is a deterministic support-policy sensitivity of an estimated, offset-uncorrected throughput, never an error bar or an uncertainty or confidence interval; the Monte Carlo range is a numerical sensitivity of the capped-rule total, not a coverage or confidence interval; no true or corrected throughput total is claimed.",'+nl+
     '         rx=r"'+rx+'"),'+nl)
open(p,'w',encoding='utf-8',newline='').write(s.replace(a,new+a))
