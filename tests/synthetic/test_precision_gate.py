"""M368 negative/positive tests for precision_gate.py (A3)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from precision_gate import check, leaf_violations

assert leaf_violations("rate 0.00182 / 0.00166") == []                    # 3 significant figures: passes
assert leaf_violations("x 0.00182") == [] and leaf_violations("n 1,497.36") == []
assert leaf_violations("value 1.23456") == ["1.23456"]                     # injected 5-dp value fails
assert leaf_violations("kappa 0.3026") == []                              # 4 dp passes
assert leaf_violations("ρ=0.22, p=0.00000562")                             # raw p string fails
assert leaf_violations("p<0.001") == []
bad = [{"tab": "fuel", "mode": "all", "text": "value 1.23456"}]
v, o = check(bad, [])
assert len(v) == 1 and not o                                               # injected value fails
v, o = check(bad, [{"tab": "fuel", "text": "value 1.23456", "class": "test", "reason": "t", "milestone": "M368"}])
assert not v and not o                                                     # allow-listed passes
v, o = check([], [{"tab": "fuel", "text": "gone 9.87654", "class": "test", "reason": "t", "milestone": "M368"}])
assert not v and len(o) == 1                                               # orphan entry fails
print("test_precision_gate: ok")
