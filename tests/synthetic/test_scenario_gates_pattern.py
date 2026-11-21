"""M721: known-answer tests for scenario_gates.accepted_pattern (Director M713 option A failure pattern; recorded tooling deviation, no gate is relaxed)."""
import copy, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import scenario_gates as SG

D = os.path.join(ROOT, "analyses", "M713")
def gate(st, hs, cyc=0.005, clean=None):
    g = {"pass": False, "startsBelow15C": {"relError": st}, "ahShare_ge35": {"relError": hs}, "arrCycleAF_Ea50": {"relError": cyc}, "gate": {}}
    if clean is not None:
        g["gate"]["cleanHoldout"] = clean
    return g
G = {"G-S0": {"pass": True}, "G-S1": {"pass": True}, "G-S3": {"pass": True}, "G-S4": {"pass": None, "reportedNotGated": True},
     "G-S2": gate(0.2812, -0.128), "G-S2b": gate(0.3226, -0.2512, clean=False), "supportStatus": {"failedGates": ["G-S2", "G-S2b"]}}
assert SG.accepted_pattern(G, D) == (True, [])
G2 = copy.deepcopy(G); G2["G-S2b"]["startsBelow15C"]["relError"] = 0.1515; G2["G-S2b"]["ahShare_ge35"]["relError"] = -0.1980   # M721 values: toward zero, accepted
assert SG.accepted_pattern(G2, D) == (True, [])
G3 = copy.deepcopy(G); G3["G-S2"]["startsBelow15C"]["relError"] = 0.2812 + 0.04   # away by 0.04 <= 0.05: accepted
assert SG.accepted_pattern(G3, D)[0]
def bad(mut):
    g = copy.deepcopy(G); mut(g); ok, why = SG.accepted_pattern(g, D); assert not ok, why; return why
bad(lambda g: g.__setitem__("G-S0", {"pass": False}))
bad(lambda g: g.__setitem__("G-S3", {"pass": False}))
bad(lambda g: g.__setitem__("G-S5", {"pass": False}))
bad(lambda g: g["G-S2b"].__setitem__("pass", True))
bad(lambda g: g["G-S2"]["startsBelow15C"].__setitem__("relError", -0.05))          # sign flip
bad(lambda g: g["G-S2"]["ahShare_ge35"].__setitem__("relError", 0.1))              # sign flip
bad(lambda g: g["G-S2"]["startsBelow15C"].__setitem__("relError", 0.40))           # away from zero by > 0.05
bad(lambda g: g["G-S2b"]["startsBelow15C"].__setitem__("relError", 0.0))           # not an overestimate any more
bad(lambda g: g["G-S2b"].__setitem__("pass", True))
bad(lambda g: g["G-S2b"]["gate"].__setitem__("cleanHoldout", True))
bad(lambda g: g["G-S2"]["arrCycleAF_Ea50"].__setitem__("relError", 0.2))
bad(lambda g: g["supportStatus"].__setitem__("failedGates", ["G-S2"]))
bad(lambda g: g["G-S2"]["ahShare_ge35"].__setitem__("relError", None))
bad(lambda g: g["G-S2"]["startsBelow15C"].__setitem__("relError", None))
bad(lambda g: g["G-S2"]["arrCycleAF_Ea50"].__setitem__("relError", None))
bad(lambda g: g["G-S2"].pop("startsBelow15C"))
bad(lambda g: g["G-S4"].__setitem__("pass", False))
bad(lambda g: g.pop("supportStatus"))
bad(lambda g: g["G-S2"].__setitem__("pass", True))                                  # only G-S2b false
G4 = copy.deepcopy(G); G4["G-S2"]["startsBelow15C"]["relError"] = 0.2812 + 0.05     # exactly 0.05 away: accepted
assert SG.accepted_pattern(G4, D)[0]
G5 = copy.deepcopy(G); G5["G-S2"]["ahShare_ge35"]["relError"] = -0.10               # toward zero for G-S2: accepted
assert SG.accepted_pattern(G5, D)[0]
assert SG.accepted_pattern(G, "/nonexistent") == (False, [])
assert SG.accepted_pattern({"G-S0": {"pass": True}}, D) == (False, [])           # nothing failed: ordinary path
print("test_scenario_gates_pattern OK")
