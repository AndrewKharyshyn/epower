"""M719 checks of the park-model propagation control (tools/park_propagation_control.py, analyses/M719/park_propagation_control.json): the control reproduces the displayed primary of `parkedTimeBudget`,
every M709 value lies inside the displayed assumption-grid envelope (no flag, no escalation), and the other two blocks do not use the park model (static checks that fail if that changes)."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
C = json.load(open("analyses/M719/park_propagation_control.json", encoding="utf-8"))
A = json.load(open("summary_arrays.json", encoding="utf-8"))
assert C["flags"] == [] and all(v["M709InsideGridEnvelope"] for v in C["metrics"].values()) and all(v["M709InsideGridEnvelope"] for v in C["bands"].values())
# the control reproduces the displayed primary band hours of the block
blk = A["parkedTimeBudget"]
disp = {b["band"]: b["parkedModelledHours"] for b in blk["B1"]["bands"]}
for lab, v in C["bands"].items():
    assert abs(v["displayedPrimary"] - disp[lab]) < 0.002, (lab, v["displayedPrimary"], disp[lab])
assert abs(C["variants"]["displayedPrimary (tau 7.873, offset 0)"]["parkedHours"] - sum(disp.values())) < 0.02
assert C["tauAxis"][0]["tauH"] == blk["tauAxis"][0]["tauH"] == A["seasonalFits"]["Q3"]["primary"]["tauH"], "the displayed tau is the seasonalFits.Q3 value (owner decision D-05)"
pk = json.load(open("analyses/M709/park_model.json", encoding="utf-8"))["M2_fullSample_nonFlagged"]
assert any("%.3f" % pk["tau_h"] in k for k in C["variants"]) and C["metrics"]["cold10"]["relDelta"] < 0 < C["metrics"]["hot35"]["relDelta"]
# static: the other blocks do not use the park model
led = open("tools/thermal_support_ledger.py", encoding="utf-8").read().lower()
assert "tau" not in led and "park_model" not in led and "park_t" not in led, "thermal_support_ledger now references the park model: extend the control"
ev = open("tools/exposure_vector.py", encoding="utf-8").read()
assert "park_model" not in ev and "park_T" not in ev, "exposure_vector now references the park model: extend the control"
print("test_park_propagation_control: ok")
