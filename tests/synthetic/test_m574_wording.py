"""M574: the M573 cell-spread-step wording rule must FIRE on its target phrases and stay silent on the dashboard wording of the step panel (the gate normalises to lower case)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as L

fire = {"M573-cell-spread-step": ["a change point was detected in October", "confirmed change point", "the October 1 step is real", "cell imbalance is growing",
                                    "cadence is ruled out", "balancing has been ruled out", "seasonal effects ruled out", "measured degradation", "degradation was confirmed"]}
clean = ["a level shift around late September / early October (date chosen post hoc) fits better than a steady linear trend (model-derived)",
         "degradation and real imbalance growth are neither established nor excluded; the cause is unidentified",
         "the polling regime is reported with the step, not excluded", "an interval that includes zero is not detected, not excluded",
         "the step size is conditional on a post hoc date and is not adjusted for selection", "awaiting data"]
for rid, phrases in fire.items():
    for ph in phrases:
        assert rid in L.scan_text(ph), (rid, ph)
for ph in clean:
    hit = [r for r in L.scan_text(ph) if r.startswith("M573")]
    assert not hit, (ph, hit)
print("test_m574_wording OK")
