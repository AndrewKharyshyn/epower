"""M427 (owner request 2026-10-13): the regen-by-pack-temperature bins are 10 C wide on the multiples of 10 for every observable temperature, including the winter bins below zero;
contiguous, open-ended at both ends, every temperature in exactly one [lo, hi) bin, unique display labels."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import compute_summary_arrays as C

B = C.REGEN_TEMP_BINS
assert all(B[i][1] == B[i + 1][0] for i in range(len(B) - 1)), "bins must be contiguous"
assert B[0][0] <= -90 and B[-1][1] >= 90, "open-ended below and above"
assert all(hi - lo == 10 for lo, hi, _ in B[1:-1]) and all(lo % 10 == 0 for lo, _, _ in B[1:]), "10 C interior bins on the multiples of 10"
assert any(hi <= 0 for _, hi, _ in B) and any(lo < 0 <= hi for lo, hi, _ in B), "winter bins below zero are present"
assert len({lbl for _, _, lbl in B}) == len(B)
for t in (-40.0, -10.0, -0.1, 0.0, 9.99, 10.0, 19.99, 25.0, 49.99, 50.0, 80.0):
    assert sum(1 for lo, hi, _ in B if lo <= t < hi) == 1, t
assert [lbl for _, _, lbl in B][0].startswith("<") and [lbl for _, _, lbl in B][-1].endswith("+")
print("test_regen_temp_bins: OK (%d bins)" % len(B))
