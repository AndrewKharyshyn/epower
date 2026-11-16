"""Known-answer tests for tools/capacity_anchors.py (M699 spec Rev 1): planted Ah-per-SoC, anchor geometry, verdict logic, step rule."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import capacity_anchors as C

BETA = 5.0          # planted Ah per 100 SoC points


def _frame(n, gap_h=3.0, unlogged=None):
    t0 = pd.Timestamp("2026-06-01 08:00")
    rows = []
    for i in range(n):
        rows.append({"file": "f%d" % i, "date": (t0 + pd.Timedelta(days=i // 2)).date(), "t0u": t0 + pd.Timedelta(hours=i * (0.5 + gap_h)), "durH": 0.5, "clean": True,
                     "unlogged": (unlogged or {}).get(i, 0.0), "tclass": "warm"})
    return pd.DataFrame(rows)


def _rec(n, dsoc_step=-12.0, gap_reest=0.0, q_scale=1.0):
    rec, soc = {}, 80.0
    for i in range(n):
        within = dsoc_step
        rec["f%d" % i] = {"soc_first": soc, "soc_last": soc + within, "q_ah": q_scale * BETA * within / 100.0, "cover": 1.0, "fast": False}
        soc = soc + within + gap_reest
        if soc < 30 or soc > 90:
            soc = 80.0
    return rec


def test_anchor_pair_recovers_planted_beta_without_gap_reestimate():
    d, rec = _frame(30), {}
    soc = 80.0
    for i in range(30):                      # alternate discharge / charge so SoC stays in range, no gap re-estimate
        within = -12.0 if i % 2 == 0 else 12.0
        rec["f%d" % i] = {"soc_first": soc, "soc_last": soc + within, "q_ah": BETA * within / 100.0, "cover": 1.0, "fast": False}
        soc += within
    p, why = C.build_pairs(d, rec, 2.0, 10.0)
    assert len(p) >= 20
    b = (p["q_ah"] * p["dsoc_anchor"]).sum() / (p["dsoc_anchor"] ** 2).sum() * 100.0
    assert abs(b - BETA) < 1e-9
    assert abs(p["gap_reest"]).max() < 1e-9


def test_gap_reestimate_biases_anchor_estimate_not_within_drive():
    d = _frame(30)
    rec = {}
    soc = 80.0
    for i in range(30):
        within = -12.0 if i % 2 == 0 else 12.0
        rec["f%d" % i] = {"soc_first": soc, "soc_last": soc + within, "q_ah": BETA * within / 100.0, "cover": 1.0, "fast": False}
        soc += within + (-3.0 if i % 2 == 0 else 3.0)      # BMS re-estimate across each parked gap enlarges the anchor difference
    p, _ = C.build_pairs(d, rec, 2.0, 10.0)
    anchor = (p["q_ah"] * p["dsoc_anchor"]).sum() / (p["dsoc_anchor"] ** 2).sum() * 100.0
    within = (p["q_ah"] * p["dsoc_drive"]).sum() / (p["dsoc_drive"] ** 2).sum() * 100.0
    assert abs(within - BETA) < 1e-9 and anchor < BETA - 0.5


def test_gap_and_guard_exclusions():
    d = _frame(30, gap_h=1.0)
    p, why = C.build_pairs(d, _rec(30), 2.0, 10.0)
    assert len(p) == 0 and why["gapShort"] > 0
    d2 = _frame(30, unlogged={5: 4.0})
    p2, why2 = C.build_pairs(d2, _rec(30), 2.0, 10.0)
    assert why2["unloggedGuard"] >= 1
    rc = _rec(30)
    rc["f7"]["cover"] = 0.5
    _, why3 = C.build_pairs(_frame(30), rc, 2.0, 10.0)
    assert why3["coverage"] >= 1


def test_verdict_logic():
    assert C.verdict([-0.1, 0.1], 0.25) == "consistent"
    assert C.verdict([0.3, 0.9], 0.25) == "disagrees"
    assert C.verdict([-1.0, 0.9], 0.25) == "not established"


def test_bootstrap_ratio_known_answer():
    rng = np.random.default_rng(1)
    n_days, per = 20, 5
    day = np.repeat(np.arange(n_days), per)
    x = rng.uniform(10, 30, len(day))
    y = BETA / 100.0 * x
    W = C.CB.boot_weights(n_days, 200, 42)
    est, dr = C.draws(C.day_stats(day, x, y, n_days), W, lambda b: 100.0 * b[0])
    assert abs(est - BETA) < 1e-9 and np.nanmax(np.abs(dr - BETA)) < 1e-9


def test_quarter_labels():
    assert C.quarter_of("2026-05-11") == "2026Q2" and C.quarter_of("2026-11-09") == "2026Q4"


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("PASS test_m699_capacity_anchors")
