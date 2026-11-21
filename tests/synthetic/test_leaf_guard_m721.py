"""M721 known-answer test for leaf_guard.cond_ancestor_list_shortened_nonempty: a leaf under a list element may vanish only when that list is shorter in the current arrays and still non-empty."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import leaf_guard as LG

R = [dict(id="a", rationale="r", milestone="T", pathTemplate="s/{key}/segs/{i}", condition="ancestor_list_shortened_nonempty", matchPrefix=True, listDepth=3)]
seg = lambda n: {"start": n, "ci95": [n, n + 1]}
P = {"s": {"X": {"segs": [seg(0), seg(1), seg(2), seg(3)]}}}
u = lambda prev, cur: LG.guard(prev, cur, R)["unexpected"]
assert u(P, {"s": {"X": {"segs": [seg(0), seg(1), seg(2)]}}}) == []              # shorter, non-empty: the lost segment 3 (and its nested ci95) is covered
assert u(P, {"s": {"X": {"segs": []}}})                                          # emptied list fails
assert u(P, {"s": {"X": {}}})                                                    # deleted list fails
assert u(P, {"s": {"X": {"segs": [seg(0), seg(1), seg(2), {"start": 3}]}}})      # same length, element lost a field: fails
print("test_leaf_guard_m721 OK")
