"""M608 (Director ruling 2026-11-10): semantic_gate.py check B compares the operating-state shares in the Conclusions text with energyPath. The dashboard renders a number with JS formatting
(27.0 -> '27', 27.5 -> '27.5'); the check must format the payload value the same way (:g). Known answers read the two format expressions out of the gate source and evaluate them."""
import os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
src = open(os.path.join(ROOT, "semantic_gate.py"), encoding="utf-8").read()
m = re.search(r'f"(engine-off braking \{ep\[\'pure_regen\'\]:g\}%)" in conc and f"(braking overlap \{ep\[\'dual\'\]:g\}%)" in conc', src)
assert m, "check B must format both shares with :g"
a, b = m.group(1), m.group(2)


def want(ep):
    return eval('f"%s"' % a), eval('f"%s"' % b)


assert want({"pure_regen": 27.0, "dual": 22.0}) == ("engine-off braking 27%", "braking overlap 22%")          # exact integers render without '.0'
assert want({"pure_regen": 27.5, "dual": 22.4}) == ("engine-off braking 27.5%", "braking overlap 22.4%")      # non-integers keep their decimals
text = "engine-on 66.8% (non-braking 44.8% + braking overlap 22%) · engine-off braking 27% · engine-off residual 6.2%"
w1, w2 = want({"pure_regen": 27.0, "dual": 22.0})
assert w1 in text and w2 in text                                                                                 # the rendered text of the M608 candidate passes
w1, w2 = want({"pure_regen": 28.0, "dual": 22.0})
assert not (w1 in text and w2 in text), "negative control: payload 28 against text '27%' must fail"
w1, w2 = want({"pure_regen": 27.0, "dual": 23.0})
assert not (w1 in text and w2 in text), "negative control: payload overlap 23 against text '22%' must fail"
print("test_semantic_gate_b_format OK")
