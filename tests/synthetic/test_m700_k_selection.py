"""Known-answer tests for tools/k_selection.py (M700 spec Rev 1, section 6)."""
import os, sys, time
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import changepoints as C
import k_selection as K


def _layout(nd=40, per=5):
    return np.repeat(np.arange(nd), per)


def test_k0_is_bic_and_finds_a_strong_step():
    dayidx = _layout()
    n = len(dayidx)
    rng = np.random.default_rng(1)
    y = rng.normal(0, 1, n)
    y[n // 2:] += 4.0
    feas = C._feasible(dayidx)
    (k, locs), rss, lc = K.rule_k0(y, dayidx, feas)
    assert k == 1 and abs(locs[0] - n // 2) <= 5
    assert k == C.choose_k(C.bic_table(rss, n))


def test_k1_equals_k0_when_lambda_is_one():
    dayidx = _layout()
    rng = np.random.default_rng(2)
    y = rng.normal(0, 1, len(dayidx))
    y[100:] += 3.0
    feas = C._feasible(dayidx)
    base = K.rule_k0(y, dayidx, feas)
    f, _ = C.fitted(y, base[0][1])
    # iid residuals within days: lambda_hat floors at 1 when the day sums are not inflated
    assert K.lambda_hat(np.tile([1.0, -1.0], len(dayidx) // 2 + 1)[: len(dayidx)] * 0.0 + (np.arange(len(dayidx)) % 2 * 2 - 1.0), dayidx) == 1.0
    (k1, _), lam = K.rule_k1(y, dayidx, feas, base)
    if lam == 1.0:
        assert k1 == base[0][0]


def test_lambda_exceeds_one_for_a_day_effect():
    dayidx = _layout(60, 5)
    rng = np.random.default_rng(3)
    e = rng.normal(0, 1, 60)[dayidx] + rng.normal(0, 0.3, len(dayidx))
    assert K.lambda_hat(e - e.mean(), dayidx) > 2.0


def test_k2_does_not_over_segment_a_pure_day_effect_where_k0_does():
    dayidx = _layout(80, 4)
    n = len(dayidx)
    feas = C._feasible(dayidx)
    k0_over = k2_over = 0
    for s in range(20):
        rng = np.random.default_rng(100 + s)
        y = rng.normal(0, 1.5, 80)[dayidx] + rng.normal(0, 0.5, n)
        base = K.rule_k0(y, dayidx, feas)
        k0_over += int(base[0][0] >= 1)
        k2, _ = K.rule_k2(y, dayidx, feas, base)
        k2_over += int(k2[0] >= 1)
    assert k0_over >= 5 and k2_over < k0_over


def test_k3_finds_planted_step_and_stays_at_zero_on_iid():
    dayidx = _layout(40, 5)
    n = len(dayidx)
    feas = C._feasible(dayidx)
    rng = np.random.default_rng(4)
    y = rng.normal(0, 1, n)
    y[n // 2:] += 3.0
    (k, locs), steps, capped = K.rule_k3(y, dayidx, feas, np.random.default_rng(5), time.time())
    assert not capped and k == 1 and abs(locs[0] - n // 2) <= 5
    zero = 0
    for s in range(10):
        r = np.random.default_rng(200 + s)
        (kk, _), _, cap = K.rule_k3(r.normal(0, 1, n), dayidx, feas, np.random.default_rng(300 + s), time.time())
        zero += int(kk == 0)
    assert zero >= 8


def test_k4_deterministic_and_prefers_zero_on_noise():
    dayidx = _layout(40, 5)
    months = np.repeat(np.arange(40) // 10 + 5, 5)
    feas = C._feasible(dayidx)
    y = np.random.default_rng(6).normal(0, 1, len(dayidx))
    a = K.rule_k4(y, dayidx, feas, months)
    b = K.rule_k4(y, dayidx, feas, months)
    assert a == b and a[0][0] == 0


def test_gate_logic_and_study_toy():
    summ = {}
    for sc in K.CORE + K.NULLS:
        summ[sc] = {"n": 200, "kTrue": 0, "rules": {r: {"recovery": 0.9, "recoveryWilson95": [0.85, 0.94], "overSegmentation": 0.02, "falseBreakRate": 0.02, "falseBreakWilson95": [0.0, 0.05]} for r in K.RULES}}
    adm, sel = K.admissibility(summ)
    assert sel == "K1" and all(adm[r]["admissible"] for r in K.RULES)
    summ["N5"]["rules"]["K1"]["falseBreakWilson95"] = [0.0, 0.2]
    adm, sel = K.admissibility(summ)
    assert not adm["K1"]["admissible"] and sel == "K2"


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("PASS test_m700_k_selection")
