"""M368 known-answer test for tools/m368_fmt.py (analyses/M368_spec.md Rev 2 item 8)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
from m368_fmt import fmt_energy, fmt_cycles

CASES = [
    (fmt_energy(1.9852), "1.99"), (fmt_energy(0.3968), "0.40"), (fmt_energy(-0.0288, signed=True), "-0.029"),
    (fmt_energy(-0.0023, signed=True), "-0.0023"),          # not "-0.00"
    (fmt_energy(0.0, signed=True), "0.00"), (fmt_energy(-1e-9, signed=True), "0.00"),   # no signed zero
    (fmt_energy(0.4, signed=True), "+0.40"), (fmt_energy(0.0999), "0.10"),
    (fmt_cycles(0.9453), "0.95"), (fmt_cycles(0.0456), "0.046"), (fmt_cycles(15.4169), "15.42"),
]
bad = [(got, want) for got, want in CASES if got != want]
assert not bad, bad
print("test_m368_fmt: ok", len(CASES))
