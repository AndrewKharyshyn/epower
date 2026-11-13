"""M640 (W1-15): the M119-v2 temperature hazard chart shows its fit domain and the not-in-fit drive count, bound to the payload keys."""
import json, os
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
J = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read()
for frag in ("const fitMin = B.tpackMinC", "MON.sides[tag].observedRangeC", "not in fit", "MON.newDrivesSinceBasis} of {MON.currentNDrives} drives are not in the fit (basis {MON.basisNDrives})"):
    assert frag in J, frag
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
M = A["socHysteresisV2"]["tempLadderMonitor"]
assert M["newDrivesSinceBasis"] == M["currentNDrives"] - M["basisNDrives"]
for side in ("start", "stop"):
    assert M["sides"][side]["observedRangeC"][0] < A["socHysteresisV2"]["tempLadder"][side]["tpackMinC"], side      # a region outside the fit exists, so the shading appears
print("PASS test_m640_hazard_domain")
