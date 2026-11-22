"""M731 known-answer tests (analyses/M731_spec.md Rev 2.2, section 3): the P6 per-drive row on planted 1 Hz grids and the extract_p6 cell, counts, reading rule, zero-event-safe bound, support rule, region split.
No observation after the freeze is read by this test."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_p6 as W6


def grid(n=100, tmin=-3.0, soc=60.0, imax=50.0, spike_at=40, spike=200.0):
    g = pd.DataFrame({"I": np.full(n, 10.0), "Imax": np.full(n, imax), "Tmin": np.full(n, tmin), "soc": np.full(n, soc)})
    g.loc[spike_at, "Imax"] = spike
    return g


# ---- limit map: 0 C, SoC 60 -> 33.9221 kW -> 18.85 C on the 360 V / 5 Ah basis (the frozen C_at_0C_soc60)
assert abs(float(W6.limit_c(0.0, 60.0)) - 18.8456) < 1e-3
assert abs(float(W6.limit_c(-10.0, 60.0)) - (33.9221 - 15.529) * 1000 / 360 / 5) < 1e-9
assert abs(float(W6.limit_c(0.0, 70.0)) - (33.9221 - 10.097) * 1000 / 360 / 5) < 1e-9

# ---- exact margin on a planted drive: peak 200 A -> 40 C, at Tlo -3 and SoC 60: limit (33.9221 - 4.6587) = 29.2634 kW -> 16.2575 C
r = W6.p6_row(grid())
assert r["p6_n_s"] == 100 and abs(r["p6_peak_c"] - 40.0) < 1e-9 and r["p6_Tlo"] == -3.0 and r["p6_soc"] == 60.0
lim = (33.9221 + 1.5529 * -3.0) * 1000 / 360 / 5
assert abs(r["p6_limit_c"] - lim) < 1e-9 and abs(r["p6_margin_c"] - (40.0 - lim)) < 1e-9 and r["p6_all_peak_c"] == 40.0
# the margin is the MAX over seconds (not the peak-current second): a lower current at a colder, SoC-higher second can have the larger margin
g = grid(imax=10.0, spike=100.0)                                   # peak second: 20 C at Tlo -3
g.loc[10, ["Imax", "Tmin", "soc"]] = [90.0, -12.0, 80.0]                  # 18 C at -12 C, SoC 80: limit much lower
r2 = W6.p6_row(g)
m_peak = 20.0 - float(W6.limit_c(-3.0, 60.0))
m_cold = 18.0 - float(W6.limit_c(-12.0, 80.0))
assert m_cold > m_peak and abs(r2["p6_margin_c"] - m_cold) < 1e-9 and r2["p6_Tlo"] == -12.0 and abs(r2["p6_peak_c"] - 18.0) < 1e-9
# no sub-zero charge second: not in the cell
assert W6.p6_row(grid(tmin=2.0))["p6_n_s"] == 0
assert all(c in W6.p6_row(grid(tmin=2.0)) for c in ("p6_margin_c", "p6_peak_c", "p6_Tlo", "p6_soc", "p6_limit_c"))      # columns present even without a cell second
nc = grid(tmin=-3.0)
nc["Imax"] = -5.0
nc["I"] = -5.0
assert W6.p6_row(nc)["p6_n_s"] == 0                                # discharge only: no charge second
# missing SoC: those seconds are not used (soc forward-filled at most 60 s, so an all-NaN SoC leaves none)
ns = grid()
ns["soc"] = np.nan
assert W6.p6_row(ns)["p6_n_s"] == 0
# the reference-region variant (0..10 C) takes only seconds with 0 <= Tlo < 10
assert W6.p6_row(grid(tmin=5.0), tlo_lt=10.0)["p6_n_s"] == 100 and W6.p6_row(grid(tmin=-1.0), tlo_lt=10.0)["p6_n_s"] == 0 and W6.p6_row(grid(tmin=12.0), tlo_lt=10.0)["p6_n_s"] == 0
# Imax missing: falls back to the mean current, as in the exposure frame
gm = grid(spike_at=5, spike=np.nan)
gm["Imax"] = np.nan
assert abs(W6.p6_row(gm)["p6_all_peak_c"] - 10.0 / 5.0) < 1e-9


# ---- extract_p6
def frame(margins, tlos=None, ndays=8):
    n = len(margins)
    return pd.DataFrame({"day": ["2026-12-%02d" % (1 + i % ndays) for i in range(n)], "p6_n_s": np.full(n, 50), "p6_margin_c": margins, "p6_Tlo": tlos if tlos is not None else np.full(n, -2.0),
                         "p6_peak_c": np.full(n, 10.0), "p6_soc": np.full(n, 60.0), "p6_limit_c": np.full(n, 12.0)})


f0 = frame(np.full(24, -4.0))
e0 = W6.extract_p6(f0, 0.0, nb=200)
assert e0["status"] == "fitted" and e0["exceedCount"] == 0 and e0["reading"] == "within the map" and e0["nDrives"] == 24 and e0["nDays"] == 8
# zero events: the percentile bootstrap alone would say [0, 0]; the safe bound is the Clopper-Pearson value (> 0)
assert e0["shareUpperBootstrap"] == 0.0 and e0["shareUpperClopperPearson"] > 0.1 and e0["shareUpperSafe"] == e0["shareUpperClopperPearson"]
assert abs(e0["shareUpperClopperPearson"] - (1 - 0.025 ** (1.0 / 24))) < 1e-9          # exact for k = 0
# the tolerance: a margin of +0.5 with tol 1.0 is not an exceedance, with tol 0.0 it is
fm = frame(np.full(24, -4.0))
fm.loc[0, "p6_margin_c"] = 0.5
assert W6.extract_p6(fm, 1.0, nb=100)["exceedCount"] == 0 and W6.extract_p6(fm, 0.0, nb=100)["exceedCount"] == 1
# one exceedance on one day: inconclusive; on two days: outside the map
assert W6.extract_p6(fm, 0.0, nb=100)["reading"].startswith("inconclusive")
fm.loc[1, "p6_margin_c"] = 0.7
assert fm.loc[0, "day"] != fm.loc[1, "day"]
eo = W6.extract_p6(fm, 0.0, nb=100)
assert eo["reading"] == "outside the map" and eo["exceedCount"] == 2 and eo["exceedDays"] == 2 and abs(eo["maxMarginC"] - 0.7) < 1e-12
# support rule: 9 drives, or 4 days: not evaluable
assert W6.extract_p6(frame(np.full(9, -4.0)), 0.0, nb=50)["status"] == "not evaluable"
assert W6.extract_p6(frame(np.full(24, -4.0), ndays=4), 0.0, nb=50)["status"] == "not evaluable"
# region split
fr = frame(np.full(12, -4.0), tlos=np.array([-8.0] * 5 + [-2.0] * 7))
assert W6.extract_p6(fr, 0.0, nb=50)["byTloRegion"] == {"below -5 C": 5, "-5..0 C": 7}
# determinism: day order and seed
fs = f0.sample(frac=1.0, random_state=1)
assert W6.extract_p6(fs, 0.0, nb=200)["shareUpperBootstrap"] == e0["shareUpperBootstrap"]
# drives with p6_n_s == 0 are not in the cell
fz = pd.concat([f0, frame(np.full(5, 3.0)).assign(p6_n_s=0)], ignore_index=True)
assert W6.extract_p6(fz, 0.0, nb=50)["nDrives"] == 24
# the vendored frame module is the one imported (never a live tools module)
SF = W6.vendored_frame_module()
assert os.path.abspath(SF.__file__).startswith(os.path.join(ROOT, "analyses", "M731_frozen_engine"))
print("OK test_winter_p6")
