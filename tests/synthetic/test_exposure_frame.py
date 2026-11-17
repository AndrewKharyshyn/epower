"""M713a known-answer tests for tools/exposure_frame.py (spec analyses/M712_spec.md Rev 1.1): a synthetic raw drive with a constant charge and a constant discharge current has a known Ah, kWh, km, temperature-bin and
SoC-bin allocation; the slices conserve the per-drive Ah and the charge-by-C-rate-bin Ah exactly; sentinels are masked; engine starts are counted on the rpm > 400 rule."""
import os, sys, tempfile
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import exposure_frame as EF

C = EF.C
HDR = ["time", C["I"], C["V"], C["soc"], C["T1"], C["T2"], C["T3"], C["T4"], C["spd_vcm"], C["rpm"]]


def write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(HDR) + "\n")
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")


with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "20260901_100000.csv")
    rows = []
    for s in range(120):                                   # 120 s at 1 Hz
        I = 10.0 if s < 60 else -20.0                     # raw BMS current: charge positive
        T = 20.0 if s < 60 else 36.0
        T1 = 107 if s == 5 else T                          # logger sentinel on T1 at one second: masked, the other probes carry the mean
        rpm = 0 if s < 30 else (1500 if s < 90 else 0)     # one engine start at s = 30 (rpm > 400 from 30 to 89)
        rows.append(("10:00:%02d.000" % s if s < 60 else "10:01:%02d.000" % (s - 60), I, 360.0, 60.0, T1, T, T, T, 36.0, rpm))
    write(p, rows)
    g = EF.extract_drive(p)
    assert len(g) == 120 and g["key"].iloc[0] == "20260901100000"
    assert np.isnan(g["T1"].iloc[5]) and abs(g["Tm"].iloc[5] - 20.0) < 1e-6, "sentinel masked, mean of the other probes"
    r = EF.drive_row("20260901100000", g)
    assert abs(r["ah_chg"] - 10 * 60 / 3600) < 1e-6 and abs(r["ah_dis"] - 20 * 60 / 3600) < 1e-6, r
    assert abs(r["kwh_chg"] - 10 * 360 / 1000 * 60 / 3600) < 1e-6 and abs(r["kwh_dis"] - 20 * 360 / 1000 * 60 / 3600) < 1e-6
    assert abs(r["km"] - 36.0 * 120 / 3600) < 1e-6
    assert r["eng_starts"] == 1 and r["eng_on_s"] == 60
    assert abs(r["ahc_T_20-25"] - 10 * 60 / 3600) < 1e-6 and abs(r["ahd_T_35-40"] - 20 * 60 / 3600) < 1e-6, "Ah by pack-temperature bin"
    assert abs(r["ah_S_55-60"] - 0.0) < 1e-9 and abs(r["ah_S_60-65"] - (10 * 60 + 20 * 60) / 3600) < 1e-6, "SoC 60 sits in the 60-65 bin (left-closed)"
    assert abs(r["afah_50"] - (EF.arrh(20.0, 50) * 10 * 60 + EF.arrh(36.0, 50) * 20 * 60) / 3600) < 1e-4, "Arrhenius-weighted Ah (cycle dose)"
    assert abs(r["ccs_lt15"]) < 1e-12 and r["h_ge35"] > 0 and abs(r["ah_ge35"] - 20 * 60 / 3600) < 1e-6
    A = EF.slices(g)
    assert abs(np.nansum(A["ahc"]) - r["ah_chg"]) < 1e-9 and abs(np.nansum(A["ahd"]) - r["ah_dis"]) < 1e-9, "slices conserve the per-drive Ah"
    assert abs(A["ahc_cb"].sum() - r["ah_chg"]) < 1e-9, "charge Ah by C-rate bin conserved"
    # 10 A on 5 Ah = 2 C: bin index of 2 on edges [2, 5, 10, ...] is 1 (left-closed)
    assert A["ahc_cb"][:, 1].sum() > 0 and A["ahc_cb"][:, 0].sum() == 0
    assert A["i2"].shape == (EF.K,) and abs(np.nanmean(A["i2"][:8]) - 100.0) < 1e-6 and abs(np.nanmean(A["i2"][8:]) - 400.0) < 1e-6
    assert abs(A["icov"] - 1.0) < 1e-12
# the helper keys are the master's file keys
assert EF.key14("2026-09-01_10-00-00.csv") == "20260901100000" and EF.key14("20260901_100000.csv") == "20260901100000"
print("test_exposure_frame: ok")
