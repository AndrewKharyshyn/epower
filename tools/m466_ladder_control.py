#!/usr/bin/env python3
"""M466 stage C: run tools/m320_ladder.py UNCHANGED on a control population. The only difference from the production call is the known-answer reference: the production run compares the refit
with the stored surfaces of summary_arrays.json (606-drive, re-levelled); a control on the first N rows takes the reference from the matching control block (tools/m466_m119v2_control.py output,
same rows, same raw). The replacement is applied in memory (tools/m320_ladder.py stays byte-identical, so the M321 selection-code hash is untouched).
Usage: python tools/m466_ladder_control.py --kat-ref analyses/M466_c_control/ctrl489_originals.json run --tables TABLES489.pkl --out DIR --sides start"""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
i = sys.argv.index("--kat-ref")
ref = os.path.abspath(sys.argv[i + 1])
del sys.argv[i:i + 2]
src = open(os.path.join(ROOT, "tools", "m320_ladder.py"), encoding="utf-8").read()
old = 'A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["socHysteresisV2"]\n    legacy ='
new = 'A = json.load(open(%r, encoding="utf-8"))\n    legacy =' % ref
src = src.replace("\r\n", "\n")
assert src.count(old) == 1, "known-answer line not found: m320_ladder.py changed"
code = compile(src.replace(old, new), os.path.join(ROOT, "tools", "m320_ladder.py"), "exec")
g = {"__name__": "__main__", "__file__": os.path.join(ROOT, "tools", "m320_ladder.py")}
exec(code, g)
