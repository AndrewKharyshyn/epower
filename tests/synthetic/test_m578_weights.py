"""M578 known-answer tests: M438 stored weights vs stratum shares (4-decimal payload precision)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import m438_weights_check as W
assert W.weights_match_shares([0.3326, 0.3326, 0.3349], [142, 142, 143], 427)          # coolant/80 at M578: sum 1.0001
assert W.weights_match_shares([0.331, 0.3333, 0.3357], [141, 142, 143], 426)           # oil/70: sum 1.0
assert not W.weights_match_shares([0.3349, 0.3326, 0.3325], [142, 142, 143], 427)      # shifted shares that still sum to 1
assert not W.weights_match_shares([0.3326, 0.3326, 0.3349], [142, 142, 142], 427)      # strata do not partition the cell
assert not W.weights_match_shares([0.34, 0.33, 0.33], [142, 142, 143], 427)
print("test_m578_weights: OK")
