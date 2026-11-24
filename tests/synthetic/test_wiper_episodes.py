"""M772 known-answer tests (analyses/M772_spec.md Rev 2): tools/wiper_episodes.py classifies planted Vehicle_Information streams exactly under the adjacent-row episode rule (an isolated on-row is not an episode; two on-rows 30 s apart are;
a 36 s step, a zero code, a missing code or a stop splits a run; the strict timestamp span and the code-6 sensitivities), applies the 10-valid-row floor and the dry / isolated / wet classes, computes the long-soak flag over the full master
on the boundaries (2 h 59 min versus 3 h, the first drive unknown), fails the nested control on a planted difference, stops on a foreign master and keeps dates and file names out of a result."""
import os, shutil, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import wiper_episodes as E
import odometer_jump_audit as J


def rows(spec, step=30.0):
    """spec: list of (code, moving) at a regular step."""
    return [(1000.0 + i * step, c, m) for i, (c, m) in enumerate(spec)]


M = True
# an isolated on-row is not an episode; two adjacent on-rows (30 s apart) are; sample-hold duration over 30 s
assert E.episodes(rows([(0.0, M), (6.0, M), (0.0, M), (0.0, M)])) == (0, 0, 1, 4)
assert E.episodes(rows([(0.0, M), (6.0, M), (6.0, M), (0.0, M)])) == (1, 2, 2, 4)
assert E.episodes(rows([(6.0, M), (7.0, M), (6.0, M)])) == (1, 3, 3, 3)                                              # codes 6 and 7 pooled: one run of three rows
# a step over 35 s splits a run: 36 s step between two on-rows; 35 s still adjacent
assert E.episodes([(0.0, 6.0, M), (36.0, 6.0, M)]) == (0, 0, 2, 2)
assert E.episodes([(0.0, 6.0, M), (35.0, 6.0, M)]) == (1, 2, 2, 2)
# a missing code or a stop inside a run splits it and neither counts as valid
assert E.episodes(rows([(6.0, M), (None, M), (6.0, M)])) == (0, 0, 2, 2)
assert E.episodes(rows([(6.0, M), (6.0, False), (6.0, M)])) == (0, 0, 2, 2)
# strict span: two rows 30 s apart are NOT a span (needs more than 30 s); 31 s apart is
assert E.episodes([(0.0, 6.0, M), (30.0, 6.0, M)], strict_span=True)[0] == 0
assert E.episodes([(0.0, 6.0, M), (31.0, 6.0, M)], strict_span=True)[0] == 1
# hole sensitivity: a 60 s step is a split at 35 s and adjacent at 90 s
assert E.episodes([(0.0, 6.0, M), (60.0, 6.0, M)])[0] == 0 and E.episodes([(0.0, 6.0, M), (60.0, 6.0, M)], step_max=90.0)[0] == 1
# code 6 only: code 7 rows do not form the run
assert E.episodes(rows([(6.0, M), (7.0, M)]), codes={6.0})[0] == 0 and E.episodes(rows([(6.0, M), (6.0, M), (7.0, M)]), codes={6.0}) == (1, 2, 3, 3)

# classes and the 10-valid-row floor
assert E.episode_class(1, 2, 12) == "wet" and E.episode_class(0, 3, 12) == "isolated" and E.episode_class(0, 0, 12) == "dry" and E.episode_class(2, 4, 9) == "few" and E.episode_class(0, 0, 10) == "dry"

# long-soak flag over the FULL master: boundaries, the first drive unknown, input order irrelevant
t0 = np.array([0.0, 4 * 3600.0, 4 * 3600.0 + 1800 + (3 * 3600.0 - 1), 100000.0])
t1 = np.array([1800.0, 4 * 3600.0 + 1800.0, 4 * 3600.0 + 1800 + (3 * 3600.0 - 1) + 600, 100600.0])
fl, gap = E.soak_flags(t0, t1)
assert np.isnan(fl[3.0][0]) and fl[3.0][1] == 1.0 and fl[3.0][2] == 0.0 and fl[3.0][3] == 1.0                      # gap 2 h 59 min 59 s is not a long soak at 3 h
assert fl[2.0][2] == 1.0 and fl[6.0][1] == 0.0
perm = np.array([2, 0, 3, 1])
fl2, _ = E.soak_flags(t0[perm], t1[perm])
assert np.array_equal(np.nan_to_num(fl2[3.0], nan=-1), np.nan_to_num(fl[3.0][perm], nan=-1))
bins = E.gap_bins(gap)
assert sum(bins.values()) == 3 and all(isinstance(v, int) for v in bins.values())

# nested control: a planted difference stops the tool
frame = pd.DataFrame({"file": ["a"], "day": ["d"]})
m771 = {"G_support_gate": {"thresholds": {"0.05": {"wet_proxy_drives": 1, "wet_proxy_days": 1, "fuel_basis_wet_proxy_drives": 0, "fuel_basis_wet_proxy_days": 0, "dry_reference_drives": 0}}}, "C_integrity": {"drives_eligible": 5}}
try:
    E.nested_control(pd.DataFrame({"file": [], "day": [], "ens_outlier_v2": [], "distance_km": [], "cls": [], "moving_n_veh": [], "ambient": [], "v2": [], "logdist": [], "wiper_nonzero_share": [], "fuel_L_per_100km": []}), m771, 10)
    raise SystemExit("a planted difference must fail the nested control")
except E.W.T.Stop:
    pass

# privacy and language
assert J.scan_privacy({"G_prime_support_gate": {"definitions": {"primary_adjacent_rows": {"wet_proxy_drives": 40}}}, "C": {"gap_bins_hours": {"0_to_1_h": 5}}}) == []
assert J.scan_privacy({"f": "20260511_185709.csv"}) and J.scan_privacy({"d": "2026-07-26"})
assert "never rain" in E.__doc__ and E.STEP_MAX_S == 35.0 and E.SOAK_H == (3.0, 2.0, 6.0)

# a foreign master stops, nothing written
td = tempfile.mkdtemp()
try:
    with open(os.path.join(td, "m.csv"), "w", encoding="utf-8") as f:
        f.write("file\nx.csv\n")
    out = os.path.join(td, "out")
    assert E.main(["--run", "--master", os.path.join(td, "m.csv"), "--out-dir", out]) == 1 and not os.path.exists(out)
finally:
    shutil.rmtree(td, ignore_errors=True)
print("test_wiper_episodes: OK")
