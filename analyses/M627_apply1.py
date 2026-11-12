"""One-off editor for M626/M627: replace the headroom region of compute_summary_arrays.py by the new code (analyses/M627_new_headroom_code.py.txt)."""
p = 'compute_summary_arrays.py'
s = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s[:5000] else '\n'
a = s.index("_HDRM_PP_IN_COL = '[BMS] Input possible power (hp)'")
b = s.index("# ======================================================================" + nl + "# M141 (2026-08-19): heat-soak carryover")
new = open('analyses/M627_new_headroom_code.py.txt', encoding='utf-8', newline='').read().replace('\r\n', '\n').replace('\n', nl)
s = s[:a] + new + nl + nl + s[b:]
open(p, 'w', encoding='utf-8', newline='').write(s)
print('ok', len(new))
