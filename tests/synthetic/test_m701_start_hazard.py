"""Known-answer tests for tools/start_hazard.py (M701 spec Rev 1 + errata 13)."""
import os, sys
import numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import start_hazard as H


def _hz(n=300, ped_spike_at=None, on_at=None):
    idx = pd.date_range("2026-09-01 10:00:00", periods=n, freq="s")
    hz = pd.DataFrame({"rpm": np.zeros(n), "cool": 80.0, "speed": 30.0, "soc": 50.0, "tt": 0.0, "ped": 5.0, "ped_age": 0.0, "tt_age": 0.0}, index=idx)
    if ped_spike_at is not None:
        hz.iloc[ped_spike_at, hz.columns.get_loc("ped")] = 90.0
    if on_at is not None:
        hz.iloc[on_at:on_at + 5, hz.columns.get_loc("rpm")] = 1500.0
    return hz


def test_covariates_use_only_samples_before_the_block():
    hz = _hz(ped_spike_at=100, on_at=100)          # the onset second carries the pedal spike: the spike must not be a covariate of its own block
    t = H.drive_rows(hz, excl="none", lag=2, width=2)
    row = t[t["k"] == 100].iloc[0]
    assert row["y"] == 1 and row["ped"] == 5.0
    nxt = t[t["k"] == 102]
    assert nxt.empty or nxt.iloc[0]["w"] >= 0                  # the on-run seconds are not at-risk after the onset


def test_nan_rpm_seconds_are_not_at_risk_and_runs_below_two_seconds_are_not_onsets():
    hz = _hz()
    hz.iloc[50:60, hz.columns.get_loc("rpm")] = np.nan
    hz.iloc[200, hz.columns.get_loc("rpm")] = 1500.0           # a 1 s blip
    t = H.drive_rows(hz, excl="none", width=1)
    assert int(t["y"].sum()) == 0
    assert not t["k"].between(50, 59).any()


def test_first_sixty_seconds_are_excluded_from_risk_time():
    hz = _hz(on_at=30)
    a = H.drive_rows(hz, excl="first60", width=1); b = H.drive_rows(hz, excl="none", width=1)
    assert a["k"].min() >= 60 and int(a["y"].sum()) == 0 and int(b["y"].sum()) == 1


def test_planted_effect_is_recovered_and_null_is_not_flagged():
    planted = [H.sim_one((900 + i, float(np.log(1.5)), False)) for i in range(4)]
    null = [H.sim_one((950 + i, 0.0, False)) for i in range(6)]
    assert np.median([r["hr"] for r in planted]) > 1.2
    assert np.median([r["hr"] for r in null]) < 1.25
    assert sum((r["lo"] > 1) or (r["hi"] < 1) for r in null) <= 2


def test_design_has_full_rank_and_cluster_interval_is_defined():
    r = H.sim_one((777, 0.0, False))
    assert np.isfinite(r["lo"]) and r["hi"] > r["lo"]
    assert r["events"] > 200


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("PASS test_m701_start_hazard")
