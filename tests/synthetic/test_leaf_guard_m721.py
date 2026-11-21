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

# M725 (independent audit): pinned field_changed and entry_state_pinned are not vacuous
Rf = [dict(id="f", rationale="r", milestone="T", pathTemplate="b/{key}/note", condition="field_changed", entryDepth=2, field="ev", prevValue=True, curValue=False)]
uf = lambda prev, cur, R_=Rf: LG.guard(prev, cur, R_)["unexpected"]
Pf = {"b": {"X": {"ev": True, "note": "n"}}}
assert uf(Pf, {"b": {"X": {"ev": False}}}) == []                                  # evaluated true -> false: the note may vanish
assert uf(Pf, {"b": {"X": {"ev": None}}})                                         # a different change is not the stated transition
assert uf({"b": {"X": {"ev": False, "note": "n"}}}, {"b": {"X": {"ev": True}}})   # the reverse direction fails
Rn = [dict(id="n", rationale="r", milestone="T", pathTemplate="b/{key}/rmst/note", condition="field_changed", entryDepth=2, field=["rmst", "tauS"], prevIsNull=True, curNotNull=True)]
assert uf({"b": {"X": {"rmst": {"tauS": None, "note": "n"}}}}, {"b": {"X": {"rmst": {"tauS": 900}}}}, Rn) == []
assert uf({"b": {"X": {"rmst": {"tauS": 5, "note": "n"}}}}, {"b": {"X": {"rmst": {"tauS": 900}}}}, Rn)            # a non-null previous value is not the stated transition
assert uf({"b": {"X": {"rmst": {"tauS": None, "note": "n"}}}}, {"b": {"X": {"rmst": {"tauS": None}}}}, Rn)        # the field did not change: the loss is not explained
Re = [dict(id="e", rationale="r", milestone="T", pathTemplate="b/{key}/ivals/{i}", condition="field_changed", entryDepth=2, field="ivals", prevNonEmpty=True, curValue=[])]
assert uf({"b": {"X": {"ivals": ["p95"]}}}, {"b": {"X": {"ivals": []}}}, Re) == []
assert uf({"b": {"X": {"ivals": ["p95", "p50"]}}}, {"b": {"X": {"ivals": ["p50"]}}}, Re)                         # one element removed from a surviving list is not covered
Rs = [dict(id="s", rationale="r", milestone="T", pathTemplate="t/c/term/{key}", condition="entry_state_pinned", entryDepth=3, prevPath=["status"], prevValue="not reached", curPath=["frozen"], curValue=True)]
assert uf({"t": {"c": {"term": {"status": "not reached", "need": 20}}}}, {"t": {"c": {"term": {"frozen": True}}}}, Rs) == []
assert uf({"t": {"c": {"term": {"status": "not reached", "need": 20}}}}, {"t": {"c": {"term": {"status": "not reached"}}}}, Rs)   # a single leaf removed from the same state is not covered
assert uf({"t": {"c": {"term": {"status": "x", "need": 20}}}}, {"t": {"c": {"term": {"frozen": True}}}}, Rs)
print("test_leaf_guard_m721 OK")
