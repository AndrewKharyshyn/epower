"""Known-answer tests for tools/step_events.py and the simulation truth of tools/step_resistance.py (M702 spec Rev 1 + errata 12)."""
import os, sys
import numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
os.chdir(ROOT)
import step_events as SE

CI = "[BMS] HV Battery Current (A)"; CV = "[BMS] HV Battery voltage (V)"


def make(Id, R=0.12, n=None, dt=1.0, v_shift_s=0.0, v_nan_at=None, sentinel_at=None):
    n = n or len(Id)
    t = pd.to_datetime("2026-09-01 10:00:00") + pd.to_timedelta(np.arange(n) * dt, unit="s")
    V = 400 - R * (np.asarray(Id) - 5.0)
    I = -np.asarray(Id, float).copy()                 # logged charge-positive; Id is discharge-positive
    if sentinel_at is not None:
        I[sentinel_at] = -1600.0
    df = pd.DataFrame({"time": [x.strftime("%H:%M:%S.%f")[:-3] for x in t], CI: I, CV: V})
    if v_shift_s:
        tv = pd.to_datetime("2026-09-01 10:00:00") + pd.to_timedelta(np.arange(n) * dt + v_shift_s, unit="s")
        df = pd.DataFrame({"time": df["time"], CI: I, CV: np.nan})
        # voltage on its own shifted timestamps: write two rows sets
        rows = [{"time": a, CI: b, CV: np.nan} for a, b in zip(df["time"], I)] + [{"time": x.strftime("%H:%M:%S.%f")[:-3], CI: np.nan, CV: v} for x, v in zip(tv, V)]
        df = pd.DataFrame(rows)
    return df.to_csv(index=False).encode("utf-8")


def step(n=400, at=200, lo=5.0, hi=45.0):
    Id = np.full(n, lo); Id[at:] = hi
    return Id


def test_known_step_recovers_the_resistance_and_the_sign_conversion():
    ev, exc, med = SE.drive_events(make(step()))
    assert len(ev) == 1 and abs(ev["R_sh_ohm"].iloc[0] - 0.12) < 1e-9 and ev["dI"].iloc[0] == 40.0 and med == 1.0
    assert ev["plausible"].iloc[0]


def test_charge_direction_step_is_not_primary_but_is_a_sensitivity():
    Id = step(lo=45.0, hi=5.0)                                  # discharge falls by 40 A: a charge-direction step
    ev, exc, _ = SE.drive_events(make(Id, R=0.12))
    assert len(ev) == 0 and exc["chargeDirection"] >= 1
    ev2, _e, _m = SE.drive_events(make(Id, R=0.12), direction="charge")
    assert len(ev2) == 1 and ev2["dI"].iloc[0] < 0 and abs(ev2["R_sh_ohm"].iloc[0] - 0.12) < 1e-6


def test_unsteady_pre_step_edge_and_overlap_rules():
    Id = step(); Id[198] = 20.0                                 # the two pre-step samples differ by 15 A (> 5 A band)
    ev, exc, _ = SE.drive_events(make(Id))
    assert len(ev) == 0 and exc["preNotSteady"] >= 1
    ev, exc, _ = SE.drive_events(make(step(at=10)))             # within 20 s of the drive start
    assert len(ev) == 0 and exc["nearEdge"] >= 1
    Id = np.full(400, 5.0); Id[200:205] = 45.0; Id[205:] = 85.0     # a second 40 A step 5 s after the first: one event
    ev, exc, _ = SE.drive_events(make(Id))
    assert len(ev) == 1 and exc["overlap"] >= 1


def test_sentinel_values_and_step_threshold():
    ev, exc, _ = SE.drive_events(make(step(), sentinel_at=100))
    assert len(ev) == 1                                         # the -1600 sentinel never enters
    ev, exc, _ = SE.drive_events(make(step(hi=20.0)))            # a 15 A step is below the primary 20 A threshold
    assert len(ev) == 0
    ev, exc, _ = SE.drive_events(make(step(hi=20.0)), step_a=15.0)
    assert len(ev) == 1


def test_simulation_truth_depends_on_the_sampling_gap():
    import step_resistance as SR
    assert abs(SR.rtrue(1e9) - (SR.R0_MOHM + SR.R1_MOHM) / 1000.0) < 1e-12
    assert SR.rtrue(1.27) > SR.rtrue(0.87) > SR.R0_MOHM / 1000.0


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("PASS test_m702_step_resistance")
