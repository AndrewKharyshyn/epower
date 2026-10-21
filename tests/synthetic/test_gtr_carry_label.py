"""M463: tools/gtr_carry_label.py labels carried GTR-family blocks from the payload only; known-answer and negative cases."""
import copy, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("XT_INGEST_LABEL", "T1")
import gtr_carry_label as GL

G = {"nProduction": 376, "nDrives": 376, "kmProduction": 3723.6, "corpus": {"fGen": 0.518, "generator": 15.9, "tractionGross": 18.29, "etaBus": 0.33},
     "refreshedBlocks": [{"block": "sensitivity", "basisMilestone": "M373", "nDrives": 348, "nDays": 63}, {"block": "simultaneity", "basisMilestone": "M373", "nDrives": 348, "nDays": 63},
                         {"block": "speedSplit", "basisMilestone": "M373", "nDrives": 348, "nDays": 63}],
     "sensitivity": [{"axis": "BASE", "fgen": 0.466}], "gtrClosure": {"scope": {"nDrives": 346, "nDays": 63}, "fGen": {"est": 0.4662, "ci95": [0.3823, 0.5342], "ciContains0p5": True}}}
b = GL.build(copy.deepcopy(G), "T1")
assert b["carried"]["sensitivity"] == {"nDrives": 348, "nDays": 63, "baseFgen": 0.466} and b["liveHeadline"]["fGen"] == 0.518 and b["liveHeadline"]["nProduction"] == 376
s = b["statement"]
for x in ("348 drives, 63 days", "346 drives", "376 drives: f_gen 0.518", "BASE row shows f_gen 0.466", "0.3823 to 0.5342", "crossed 0.5 within an interval that already contained 0.5"):
    assert x in s, x
G2 = copy.deepcopy(G); G2["corpus"]["fGen"] = 0.49
assert "crossed 0.5" not in GL.build(G2, "T1")["statement"]                      # no crossing sentence when the live estimate is below 0.5
G3 = copy.deepcopy(G); G3["gtrClosure"]["fGen"]["ciContains0p5"] = False
assert "crossed 0.5" not in GL.build(G3, "T1")["statement"]                      # nor when the carried interval excludes 0.5
print("test_gtr_carry_label OK")
