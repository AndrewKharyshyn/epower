"""M536 phase 1: known-answer tests of the run helpers of tools/engine_on_evidence.py, and faithfulness of the 1 Hz grid to rpm_opt_band.grid_rpm on a synthetic drive."""
import io, os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import engine_on_evidence as E
nan = float("nan")
assert E._runs(np.array([0, 1, 1, 0, 0, 1], bool)) == [(0, 1, False), (1, 2, True), (3, 2, False), (5, 1, True)]
# hysteresis: on at >= 400, stays on down to 300, off below 300, NaN turns it off
r = np.array([100, 350, 400, 350, 301, 299, 350, 420, 380, nan, 450], float)
assert E.hysteresis(r).tolist() == [False, False, True, True, True, False, False, True, True, False, True]
# min hold: short ON run removed, short OFF gap filled
s = np.array([0, 1, 0, 0, 1, 1, 1, 0, 1, 1, 1, 0], bool)
assert E.min_hold(s, 1).tolist() == s.tolist()
assert E.min_hold(s, 2).tolist() == [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 0]
assert E.drop_short_on(s, 3).tolist() == [0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 1, 0]
assert E.drop_short_on(s, 4).sum() == 0
# the grid of evidence_row equals rpm_opt_band.grid_rpm (valid values) on a synthetic 1 Hz-ish drive with gaps
import compute_summary_arrays as cs, compute_drive_summary_v6 as D, rpm_opt_band as OB
t = pd.date_range("2026-05-01 10:00:00", periods=60, freq="1s")
rp = np.array([0] * 5 + [350] * 3 + [1500] * 30 + [380] * 2 + [0] * 20, float)
df = pd.DataFrame({"time": [x.strftime("%H:%M:%S.%f")[:-3] for x in t], "Оберти двигуна (rpm)": rp, "[VCM] Vehicle Speed (km/h)": 40.0})
b = df.to_csv(index=False).encode("utf-8")
row = E.evidence_row(b, cs, D)
g, _ = OB.grid_rpm(pd.read_csv(io.BytesIO(b)), cs)
assert row["grid_valid_s"] == len(g) and row["g_ge300"] == int((g >= 300).sum()) and row["g_gt400"] == int((g > 400).sum()) and row["g_ge500"] == int((g >= 500).sum())
assert row["band_300_400_s"] == int(((g >= 300) & (g < 400)).sum()) == 5 and row["band_adjacent_off_s"] == 2
assert row["b6_runs"] >= 1 and row["b6_on_s"] == int((g > 300).sum())
print("OK test_engine_on_evidence: run helpers and grid faithfulness")
