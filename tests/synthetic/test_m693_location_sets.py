"""Known-answer tests for tools/location_sets.py (M693 spec Rev 1.1, section 6)."""
import math, os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import changepoints as C
import location_sets as L


def days(nd, per):
    return np.repeat(np.arange(nd), per)


def test_critical_value():
    assert abs(L.CRIT - 7.35) < 0.01
    assert abs((1 - math.exp(-L.CRIT / 2)) ** 2 - 0.95) < 1e-9       # CDF of 2 max(E1, E2)


def test_profile_set_equals_brute_force_formula():
    n, t = 120, 50
    dayidx = days(40, 3)
    feas = C._feasible(dayidx)
    eps = 0.05 * np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    y = np.where(np.arange(n) >= t, 1.0, 0.0) + eps
    K, locs = L.fit(y, feas)
    assert K == 1 and abs(locs[0] - t) <= 1
    got = L.lr_set(y, dayidx, feas, locs, 0)
    # independent brute force of the same statistic
    th = locs[0]
    def rss(tau):
        return float(((y[:tau] - y[:tau].mean()) ** 2).sum() + ((y[tau:] - y[tau:].mean()) ** 2).sum())
    seg = np.concatenate([y[:th] - y[:th].mean(), y[th:] - y[th:].mean()])
    e2 = float((seg ** 2).sum())
    u, inv = np.unique(dayidx, return_inverse=True)
    S = np.bincount(inv, weights=seg)
    lam = max(1.0, (np.sum(S ** 2) + np.sum(S[:-1] * S[1:])) / e2)
    acc = [tau for tau in range(1, n) if feas[0, tau] and feas[tau, n] and (rss(tau) - rss(th)) / (e2 / n * lam) <= L.CRIT]
    assert got["lo"] == min(acc) and got["hi"] == max(acc) and abs(got["lambda"] - lam) < 1e-9
    assert got["lo"] <= t <= got["hi"]


def test_lambda_floor_and_day_effect():
    n = 300
    dayidx = days(30, 10)
    feas = C._feasible(dayidx)
    rng = np.random.default_rng(5)
    y = np.where(np.arange(n) >= 150, 4.0, 0.0) + rng.normal(0, 1, n)
    K, locs = L.fit(y, feas)
    assert K >= 1
    j = int(np.argmin([abs(x - 150) for x in locs]))
    assert L.lr_set(y, dayidx, feas, locs, j)["lambda"] >= 1.0            # floor
    y2 = y + rng.normal(0, 2.0, 30)[dayidx]                                # a strong day random effect
    K2, locs2 = L.fit(y2, feas)
    j2 = int(np.argmin([abs(x - 150) for x in locs2]))
    assert L.lr_set(y2, dayidx, feas, locs2, j2)["lambda"] > 1.5


def test_c0_reproduces_m676_and_c1_refits_k():
    n = 300
    dayidx = days(100, 3)
    feas = C._feasible(dayidx)
    hit = None
    for step in (0.6, 0.5, 0.45, 0.4):
        for seed in range(40):
            y = np.random.default_rng(seed).normal(0, 1, n) + np.where(np.arange(n) >= 150, step, 0.0)
            K, locs = L.fit(y, feas)
            if K != 1:
                continue
            c0, c1 = L.boot_both(y, dayidx, feas, 1, locs, 40, 11)
            if (c1[:, 0] == -1).any() and (c1[:, 0] >= 0).any():
                hit = (y, locs, c0, c1)
                break
        if hit:
            break
    assert hit, "no weak-step case where K changes across draws"
    y, locs, c0, c1 = hit
    ref, same = C.wild_bootstrap(y, dayidx, feas, 1, locs, nboot=40, seed=11)
    assert np.array_equal(c0, ref)                                    # C0 is exactly the M676 construction
    c0b, c1b = L.boot_both(y, dayidx, feas, 1, locs, 40, 11)
    assert np.array_equal(c0, c0b) and np.array_equal(c1, c1b)         # determinism


def test_no_break_series_returns_no_set():
    n = 200
    dayidx = days(50, 4)
    feas = C._feasible(dayidx)
    for seed in range(40):
        y = np.random.default_rng(seed).normal(0, 1, n)
        K, locs = L.fit(y, feas)
        if K == 0:
            assert L.intervals(y, dayidx, feas, 0, [], 10, 1) == {"C0": [], "C1": [], "C2": []}
            return
    raise AssertionError("no null seed with K = 0")


def test_matching_rule():
    assert L.match([100, 200, 300], [98, 205, 305], 400) == {0: 0, 1: 1, 2: 2}
    m = L.match([100, 200], [150], 400)
    assert len(m) == 1                                                 # one estimated break never covers two planted breaks
    assert L.match([100, 200], [190, 400], 500) == {0: 0}              # the second planted break lies outside the window of its estimated break
    assert L.match([], [10], 100) == {} and L.match([10], [], 100) == {}
    assert L.match([100, 200], [100, 150, 200], 400) == {0: 0, 1: 2}   # order preserving, minimal total distance


def test_wilson_and_fingerprint():
    lo, hi = L.wilson(95, 100)
    assert abs(lo - 0.8883) < 2e-3 and abs(hi - 0.9784) < 2e-3
    st = {"n": 10, "dayidx": np.repeat(np.arange(5), 2)}
    assert L.fingerprint(st, 200) != L.fingerprint(st, 400) and L.fingerprint(st, 200)["nDays"] == 5


def _summ(cov, width=100.0, wl=0.88, ncorr=190, ov=0.0):
    d = {"coverageUnconditional": cov, "wilsonUnconditional": [wl, 0.99], "nCorrectK": ncorr, "coverageConditional": cov, "wilsonConditional": [wl, 0.99], "medianWidthDrives": width, "medianWidthDays": width / 5.0, "adjacentOverlapShare": ov}
    return d


def test_admissibility_and_selection():
    n = 633
    def build(cov_c1, cov_c2, w1=60.0, w2=40.0):
        return {nm: {"constructions": {"C0": _summ(0.6), "C1": _summ(cov_c1, w1), "C2": _summ(cov_c2, w2)}} for nm in L.CORE}
    adm, sel = L.admissibility(build(0.94, 0.95), n)
    assert sel == "C2" and not adm["C0"]["admissible"] and adm["C1"]["admissible"]          # min mean width wins; C0 never
    adm, sel = L.admissibility(build(0.94, 0.80), n)
    assert sel == "C1" and not adm["C2"]["admissible"]
    adm, sel = L.admissibility(build(0.80, 0.80), n)
    assert sel is None
    adm, sel = L.admissibility(build(0.995, 0.94), n)                                          # vacuous: coverage above 0.99
    assert sel == "C2" and not adm["C1"]["admissible"]
    s = build(0.94, 0.94)
    s["S3"]["constructions"]["C2"] = _summ(0.94, width=n / 8.0 + 1)                            # vacuity bound
    adm, sel = L.admissibility(s, n)
    assert sel == "C1"
    s = build(0.94, 0.94)
    s["S2"]["constructions"]["C1"] = _summ(0.94, ncorr=30)                                     # conditional coverage not estimable
    assert L.admissibility(s, n)[1] == "C2"
    s = build(0.94, 0.94)
    del s["S5"]
    assert not L.admissibility(s, n)[0]["C1"]["admissible"]                                    # a missing core scenario blocks admission


def test_study_record_in_the_block_and_staleness():
    import json, copy
    m, frames = C.load(ROOT)
    rec = C._location_set_study(ROOT, frames)
    cv = json.load(open(os.path.join(ROOT, "analyses", "M693_coverage.json"), encoding="utf-8"))
    assert rec["selectedConstruction"] == cv["selected"] and rec["studyStale"] is False and set(rec["constructions"]) == {"C0", "C1", "C2"}
    if cv["selected"] is None:
        assert rec["closestConstruction"]["label"] == "not admissible, reference only" and "no location set is attached" in rec["status"]
        assert not any(c["admissible"] for c in rec["constructions"].values())
    # a different structure is detected as stale
    fr2 = copy.deepcopy(frames)
    fr2["X2"] = fr2["X2"].iloc[:-30].copy()
    assert C._location_set_study(ROOT, fr2)["studyStale"] is True


def test_small_study_is_deterministic():
    a = L.run_study(reps=1, dreps=1, B=8, workers=1)
    b = L.run_study(reps=1, dreps=1, B=8, workers=1)
    for k in ("scenarios", "admissibility", "selected", "fingerprint"):
        assert a[k] == b[k]
    assert set(a["scenarios"]) == set(L.CORE) | set(L.DESCRIPTIVE)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    import language_gate as G
    rule = {x.rid: x for x in G.RULES}["M693-location-set-wording"]
    for bad in ("a calibrated confidence interval for the break date", "the 95% confidence interval of the update date", "this dates the software update"):
        assert rule.hits(bad), bad
    for ok in ("location set with simulated coverage (stated scenarios, X2, K)", "no coverage study", "the date of a statistical break in the logged series (exploratory)"):
        assert not rule.hits(ok), ok
    print("PASS test_m693_location_sets")
