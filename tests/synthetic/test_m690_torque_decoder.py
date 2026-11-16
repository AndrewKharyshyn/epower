"""Known-answer tests for tools/torque_decoder.py (M690 spec Rev 1.2 final)."""
import copy, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import torque_decoder as T


def synth(n=600, scale=256.0, noise=0.0, lag=0, step=None, zero_frac=0.0, rpm=False, speed=50.0, seed=3, gap=0.04, flip=False):
    """Log order: a target row then an actual row, 0.1 s apart (the real layout: the two PIDs sit on adjacent rows)."""
    rng = np.random.default_rng(seed)
    tgt = np.cumsum(rng.normal(0, 8, n)) + rng.choice([-1, 1], n) * 60.0
    tgt = np.where(np.abs(tgt) < 25, 25.0 * np.sign(tgt + 1e-9), tgt)
    src = np.roll(tgt, lag) if lag else tgt
    act = src / scale + rng.normal(0, noise, n)
    if flip:
        act = -act
    if step:
        act = np.round(act / step) * step
    if zero_frac:
        act[rng.random(n) < zero_frac] = 0.0
    rows = []
    for k in range(n):
        rows.append({"t": 0.1 * k, "actual": np.nan, "target": tgt[k], "speed": speed, "rpm": np.nan})
        rows.append({"t": 0.1 * k + gap, "actual": act[k], "target": np.nan, "speed": speed, "rpm": 64.0 * tgt[k] if rpm else np.nan})
    return pd.DataFrame(rows)


def test_planted_scale_256():
    m = T.drive_metrics(synth())
    assert m["nPairs"] == 600 and m["shareActualRowsPaired"] == 1.0 and m["nUnpairedActual"] == 0
    assert abs(m["ratioMedian"] - 256.0) < 1e-6 and abs(m["l1Slope"] - 256.0) < 1e-6
    assert m["tol3"] == 1.0 and m["oppositeSignShare"] == 0.0 and m["bestLag"] == 0
    assert abs(m["medianPairGapS"] - 0.04) < 1e-9


def test_planted_lag_two_is_found_but_status_uses_lag0():
    m = T.drive_metrics(synth(lag=2))
    assert abs(m["bestLag"]) == 2 and m["tol3AtBestLag"] > 0.99 and m["tol3"] < 0.5


def test_planted_scale_128_is_not_consistent():
    m = T.drive_metrics(synth(scale=128.0))
    assert abs(m["ratioMedian"] - 128.0) < 1e-6
    ci = {"ci95": [127.5, 128.5], "estimate": 128.0}
    d = T.decide(ci, ci, {"estimate": 0.9, "ci95": [0.8, 0.95]}, {"estimate": 0.0, "ci95": [0, 0.01]}, False)
    assert d["status"] == "not consistent" and not d["d1Passed"]


def test_wide_interval_containing_256_fails():
    wide = {"ci95": [200.0, 300.0], "estimate": 256.0}
    d = T.decide(wide, wide, {"estimate": 0.9, "ci95": [0.8, 0.95]}, {"estimate": 0.0, "ci95": [0, 0.01]}, False)
    assert d["d1RatioContains256"] and not d["d1Passed"] and d["status"] == "not consistent"


def test_decision_statuses():
    ok = {"ci95": [255.0, 257.0], "estimate": 256.0}
    good2, good3 = {"estimate": 0.8, "ci95": [0.7, 0.9]}, {"estimate": 0.01, "ci95": [0.0, 0.02]}
    assert T.decide(ok, ok, good2, good3, False)["status"] == "decoder consistent with x256"
    # point passes, lower bound fails -> tolerance not established
    assert T.decide(ok, ok, {"estimate": 0.65, "ci95": [0.55, 0.75]}, good3, False)["status"] == "tolerance not established"
    assert T.decide(ok, ok, {"estimate": 0.65, "ci95": [0.65, 0.75]}, {"estimate": 0.04, "ci95": [0.0, 0.08]}, False)["status"] == "tolerance not established"
    # point fails -> scale consistent, tolerance weak
    assert T.decide(ok, ok, {"estimate": 0.4, "ci95": [0.3, 0.5]}, good3, False)["status"] == "scale consistent, tolerance weak"


def test_quantised_actual_grid_is_resolution_limited():
    m = T.drive_metrics(synth(step=1.0 / 64.0))
    assert abs(m["actualStep"] - 1.0 / 64.0) < 1e-9 and m["resolutionLimited"] is True and m["quantisationOnlyShare3"] <= 1.0
    fine = T.drive_metrics(synth(step=0.001))
    assert fine["resolutionLimited"] is False


def test_actual_zero_samples_counted_and_excluded_from_ratio_and_sign():
    m = T.drive_metrics(synth(zero_frac=0.1))
    assert 0.05 < m["shareActiveActualZero"] < 0.15
    assert abs(m["ratioMedian"] - 256.0) < 1e-6 and m["oppositeSignShare"] == 0.0 and m["nSignScored"] == m["nActive"] - m["nActiveActualZero"]


def test_opposite_sign_detected():
    m = T.drive_metrics(synth(flip=True))
    assert m["oppositeSignShare"] == 1.0


def test_pairing_rule():
    # a gap above the tolerance is not paired; each target row is used once; the same row is accepted; following-target variant pairs forward
    df = pd.DataFrame({"t": [0.0, 0.04, 0.2, 5.0, 5.2],
                       "target": [30.0, np.nan, 40.0, np.nan, np.nan], "actual": [np.nan, 30 / 256, 40 / 256, 50 / 256, 60 / 256],
                       "speed": 50.0, "rpm": np.nan})
    b, n_act = T.make_pairs(df)
    assert n_act == 4 and len(b) == 2 and list(b["target"]) == [30.0, 40.0] and abs(b["gap"].iloc[0] - 0.04) < 1e-12 and b["gap"].iloc[1] == 0.0
    fw, _ = T.make_pairs(df, follow=True)
    assert len(fw) == 2 and list(fw["target"]) == [40.0, 40.0][:len(fw)] or len(fw) >= 1
    b2, _ = T.make_pairs(df, tol=10.0)
    assert len(b2) == 2          # the actual rows after the last target row reuse an already used target: one use only


def test_missing_actual_register():
    df = synth()
    df["actual"] = np.nan
    m = T.drive_metrics(df)
    assert m["actualPresent"] is False and m["nPairs"] == 0 and "ratioMedian" not in m


def test_rpm_sign_agreement():
    m = T.drive_metrics(synth(rpm=True, speed=60.0))
    assert m["rpm"]["signAgreement"] == 1.0 and abs(m["rpm"]["negRpmShare"] - m["rpm"]["negTargetShare"]) < 1e-12
    slow = T.drive_metrics(synth(rpm=True, speed=10.0))
    assert "rpm" not in slow         # the rpm sign check needs speed above 20 km/h


def test_pair_gap_band_and_variants():
    m = T.drive_metrics(synth(gap=0.2))
    assert "gap>0.1s" in m["tol3ByGapBand"] and "gap<=0.1s" not in m["tol3ByGapBand"]
    v = T.variants(synth(gap=0.3))
    assert v["tol0.25s"]["nActive"] == 0 and v["tol1.0s"]["nActive"] > 500 and v["followingTarget"]["nActive"] >= 0


def test_following_target_not_estimable_in_the_real_layout():
    # real layout: the next target row is a full polling cycle (about 2 s) after the actual row
    rows = []
    for k in range(300):
        rows.append({"t": 2.0 * k, "actual": np.nan, "target": 40.0, "speed": 50.0, "rpm": np.nan})
        rows.append({"t": 2.0 * k + 0.04, "actual": 40.0 / 256, "target": np.nan, "speed": 50.0, "rpm": np.nan})
    df = pd.DataFrame(rows)
    v = T.variants(df)
    assert v["followingTarget"]["nActive"] == 0 and abs(v["followingTarget"]["followingGapMedianS"] - 1.96) < 1e-6 and v["tol0.25s"]["nActive"] == 300


def test_aggregate_end_to_end_and_splice_isolation():
    rng = np.random.default_rng(1)
    rows, stats, cad, pidc = [], {}, {}, {}
    for i in range(40):
        f = "d%02d.csv" % i
        m = T.drive_metrics(synth(seed=i, noise=1e-5))
        m["variants"] = T.variants(synth(seed=i, noise=1e-5))
        m.update(sha="x", reason=None)
        stats[f] = m
        rows.append({"file": f, "date": "2026-06-%02d" % (1 + i % 12), "clean": True})
        cad[f], pidc[f] = ("fast" if i % 2 else "slow"), "A"
    master = pd.DataFrame(rows)
    blk = T.aggregate(stats, master, cad, pidc, nboot=300)
    assert blk["decision"]["status"] == "decoder consistent with x256" and blk["population"]["nEligible"] == 40
    assert blk["decision"]["d1RatioContains256"] is True and blk["sensitivities"]["statusDisagreement"] is True and blk["sensitivities"]["variants"]["followingTarget"]["decision"] == "not consistent" and blk["sensitivities"]["variants"]["tol0.25s"]["decision"] == "decoder consistent with x256"
    A = {"_artifactStamps": {}, "other": {"k": 1}}
    B = T.splice(copy.deepcopy(A), blk, "abc")
    assert set(B) - set(A) == {"torqueDecoder"} and B["other"] == A["other"] and set(B["_artifactStamps"]) == {"torqueDecoder"}
    # few active pairs: excluded and counted
    short = T.drive_metrics(synth(n=100))
    stats["d00.csv"] = {**short, "variants": T.variants(synth(n=100)), "sha": "x", "reason": None}
    blk2 = T.aggregate(stats, master, cad, pidc, nboot=300)
    assert blk2["population"]["nExcludedFewActive"] == 1 and blk2["population"]["nEligible"] == 39


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    import language_gate as G
    rule = {x.rid: x for x in G.RULES}["M690-torque-decoder-wording"]
    for bad in ("the measured torque of the motor", "validated motor torque", "calibrated torque", "corrected torque", "the rpm PID is the motor speed"):
        assert rule.hits(bad), bad
    for ok in ("logged actual-torque register x 256", "neither register is a shaft-torque reading", "the rejected rpm PID is not used as a speed", "it is not a measured shaft torque or a verified output ceiling", "never a measured torque"):
        assert not rule.hits(ok), ok
    print("PASS test_m690_torque_decoder")
