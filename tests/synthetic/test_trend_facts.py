"""M427 (external audit F01/F04/F09) known-answer tests: the three new language rules fire on the OLD wording and not on the new wording, and the fact-aware trend check
(language_gate.cell_spread_trend_violations) fails a null sentence beside an interval that excludes zero and a positive-slope sentence beside an interval that includes zero."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as lg

# 1. old wording is detected (rule ids from the audit ledger)
old_ev = "The +/-3 s channel alignment and the 3 s state debounce both bias engine-off upward: every EV distance and time figure is an upper bound."
assert "M427-F04-ev-bound" in lg.scan_text(old_ev), lg.scan_text(old_ev)
assert "M427-F04-ev-bound" in lg.scan_text("Every EV distance figure is an upper bound on the engine-off distance.")
assert "M427-F09-mix-order" in lg.scan_text("the selected 50/40/10 (city/mixed/highway) blend is a hand-chosen scenario")
assert "M427-F09-gtr-root" in lg.scan_text("Carried forward BYTE-IDENTICAL from the prior build (374-drive / M256 corpus basis) rather than recomputed -- it does NOT reflect the current 410-drive corpus.")
assert "M427-F09-gtr-root" in lg.scan_text("The generating script for this key is not present in Project Knowledge this session.")

assert "M427-F18-isolates" in lg.scan_text("combustionPenalty = fuel per engine-on second at matched RPMxload (isolates enrichment+cold-friction; day-clustered bootstrap)")
assert "M427-F18-isolates" in lg.scan_text("dutyCycle = engine-on fraction at matched road speed (isolates series-hybrid strategy; the dominant term)")

# 2. new wording passes
new_ev = ("can move the engine-off boundaries in either direction: every EV distance and time figure is an estimated RPM-defined engine-off share, not a one-sided bound")
assert not {"M427-F04-ev-bound"} & set(lg.scan_text(new_ev)), lg.scan_text(new_ev)
assert not {"M427-F04-ev-bound"} & set(lg.scan_text("At the assumed capacity, the budget is an upper bound on unassisted range."))
assert not {"M427-F09-mix-order"} & set(lg.scan_text("the selected 40/10/50 (city/mixed/highway) blend is a hand-chosen scenario"))

# 3. fact-aware trend check
V = lg.cell_spread_trend_violations
excl, spans = [0.13, 0.61], [-0.2, 0.5]
assert V(excl, {"t": "Cell-spread trend not resolved at 9,338 km"}), "null sentence beside an interval that excludes zero must fail"
assert V(excl, {"t": "no difference from the May baseline is resolved across all 578 drives"})
assert V(excl, {"t": "A positive conditional cell-spread slope is estimated after 9,338 km (95% CI excludes zero)"}) == []
assert V(spans, {"t": "a positive conditional slope is estimated across 578 drives"}), "positive-slope sentence beside an interval that includes zero must fail"
assert V(spans, {"t": "Cell-spread trend not resolved at 9,338 km; no directional cell-spread trend"}) == []
assert V(excl, {"a": "fine", "b": "No directional cell-spread trend was resolved"}) == [("b", "no directional cell-spread trend")]
print("OK test_trend_facts")
