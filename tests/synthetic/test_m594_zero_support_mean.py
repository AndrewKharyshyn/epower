"""M594 (audit D3): raw_temp_pass.channel_stats must not turn a sample mean into a time mean when no elapsed interval qualifies.
Fixtures: zero reads, one read, stale reads (gap > cap), and a resumed channel."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
import raw_temp_pass as R
cap = R.GAP_CAP_S
z = R.channel_stats([])
assert z["time_mean"] is None and z["n_valid"] == 0
one = R.channel_stats([(0.6, 9.0)])
assert one["time_mean"] is None and one["start_only"] is True and one["max"] == 9.0 and one["start"] == 9.0 and one["covered_s"] == 0.0
stale = R.channel_stats([(0.6, 9.0), (0.6 + cap + 5, 18.0)])           # the only interval exceeds the gap cap -> unsupported
assert stale["time_mean"] is None and stale["start_only"] is True and stale["covered_s"] == 0.0 and stale["max"] == 18.0
resume = R.channel_stats([(0.0, 10.0), (5.0, 20.0), (5.0 + cap + 50, 30.0), (5.0 + cap + 55, 40.0)])   # 5 s covered, then a gap, then 5 s covered
assert resume["start_only"] is False and abs(resume["covered_s"] - 10.0) < 1e-6
assert abs(resume["time_mean"] - ((15.0 * 5 + 35.0 * 5) / 10.0)) < 1e-3, resume
print("ok test_m594_zero_support_mean")
