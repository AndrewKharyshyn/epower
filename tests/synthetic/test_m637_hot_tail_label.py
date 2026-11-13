"""M637 (W1-08): the hot-tail share is labelled by its estimand; the meaning leaf exists; the old bare wording is a gate rule."""
import json, os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
import language_gate as LG
assert "M637-hot-tail-estimand" in LG.scan_text("38% of drive-time \u226535\u00b0C, highway thermal rise +17\u00b0C")
assert "M637-hot-tail-estimand" not in LG.scan_text("38% of drive time spent in drives with a drive-average pack temperature \u226535\u00b0C (a drive-average estimand), highway thermal rise")
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
m = A["seasonalLife"]["hotTail"]["packThermalMeasured"]
assert "drive-average" in m["driveTimeShareGeCMeaning"] and "not the share of logged samples" in m["driveTimeShareGeCMeaning"]
J = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read()
assert "drive-average pack temperature \u226535\u00b0C" in J and "% of drive-time \u226535\u00b0C" not in J
print("PASS test_m637_hot_tail_label")
