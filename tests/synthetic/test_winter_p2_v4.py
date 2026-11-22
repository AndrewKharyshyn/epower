"""M736 known-answer tests of registry v4 P2 handling (analyses/M736_spec.md Rev 1): provenance of bound and offsets, the three carry bands, offset pass-through, agreement / disagreement / path-carry verdicts. Stub bands; the engine is not run here."""
import json, os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_p2_v4 as W4

prov = W4.provenance()
r = json.load(open("analyses/M735_p2_window_check.json", encoding="utf-8"))["result"]
assert prov["bound"] == r["maxRelDiffAhLt10"] and prov["offsets"] == [0.0, 1.37, 3.98], prov
cb = W4.carry_bands([0.2, 0.4], 0.01)
assert np.allclose(cb["shrunk"], [0.202, 0.396]) and np.allclose(cb["widened"], [0.198, 0.404])
assert W4.carry_bands([0.2, 0.2], 0.05)["shrunk"][0] == W4.carry_bands([0.2, 0.2], 0.05)["shrunk"][1]
P = {"bound": 0.01, "offsets": [0.0, 1.37, 3.98]}
OBS = (0.30, 0.34)


def ev(band):
    lo, hi = band
    return "within the band" if (OBS[0] >= lo and OBS[1] <= hi) else ("outside the band" if (OBS[1] < lo or OBS[0] > hi) else "inconclusive")


seen = []
def fn_same(frame, o):
    seen.append(o)
    return {"status": "ok", "windowMatched": [0.2, 0.5], "table": [{"month": 1}]}
v = W4.p2_v4(None, fn_same, ev, P)
assert seen == [0.0, 1.37, 3.98] and v["status"] == "within the band" and v["call"] == "within the band"
# planted disagreement: the band moves away with the offset (cooler engine scale lowers the share band)
fn_dis = lambda f, o: {"status": "ok", "windowMatched": [0.2, 0.5] if o == 0 else [0.05, 0.12], "table": []}
v = W4.p2_v4(None, fn_dis, ev, P)
assert v["status"] == "not established (ambient-scale sensitive)" and v["call"] is None and v["offsetCalls"]["3.98"] == "outside the band"
# planted path-carry: the observed interval touches the band edge within the bound
fn_edge = lambda f, o: {"status": "ok", "windowMatched": [0.2, 0.3405], "table": []}
v = W4.p2_v4(None, fn_edge, ev, P)
assert v["status"] == "not evaluable (path-carry)" and v["carryCalls"]["shrunk"] != v["carryCalls"]["widened"]
# band not available at an offset
v = W4.p2_v4(None, lambda f, o: {"status": "not available", "reason": "x"} if o else {"status": "ok", "windowMatched": [0.2, 0.5]}, ev, P)
assert v["status"] == "not evaluable"
v = W4.p2_v4(None, fn_same, ev, P, expected_primary=[0.2, 0.5])
assert v["status"] == "within the band" and v["fillNotOffsetShifted"] is False
v = W4.p2_v4(None, fn_same, ev, P, expected_primary=[0.2, 0.5000001])
assert v["status"] == "not evaluable" and "float identity" in v["reason"]
print("OK test_winter_p2_v4")
