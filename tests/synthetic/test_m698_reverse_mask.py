"""Known-answer tests for tools/reverse_mask.py (M695 spec Rev 1.1 + section 12)."""
import copy, os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import reverse_mask as R

TAU = 45.0


def arr(v, T, dt=1.0, rpm=0.0, I=None, t0=0.0):
    n = len(v)
    ts = t0 + dt * np.arange(n)
    I = np.full(n, 0.0) if I is None else np.asarray(I, float)
    return {"ts": ts, "T": np.asarray(T, float), "v": np.asarray(v, float), "rpm": np.full(n, rpm), "I": I, "lastPos": np.full(n, np.nan)}


def test_reverse_episode_found_and_labelled():
    a = arr([0, 0, 0, 0, 2, 4, 6, 5, 3, 1, 0, 0], [0, 0, 0, 0, -60, -70, -70, 30, 30, 20, 0, 0])
    r = R.analyse(a, TAU, detail=True)
    assert len(r["episodes"]) == 1
    ep = r["episodes"][0]
    assert ep["j1"] == 4 and ep["e"] == 10 and ep["vmax"] == 6 and ep["nMoving"] == 6
    assert list(r["labels"][4:10]) == [3] * 6 and r["labelCounts"]["REV_CAND"] == 6
    assert r["negCounts"]["REV_CAND"] == 3
    assert r["tMin"] == -70 and r["tMinExclRev"] == 0            # the minimum is inside the episode


def test_forward_launch_has_no_episode():
    r = R.analyse(arr([0, 0, 3, 6, 9, 12, 10, 8], [0, 0, 80, 90, 90, 60, -20, -10]), TAU, detail=True)
    assert r["episodes"] == [] and r["labelCounts"]["REV_CAND"] == 0


def test_regen_to_stop_is_never_reverse():
    a = arr([0, 5, 10, 10, 8, 5, 2, 0, 0], [0, 40, 40, 0, -30, -50, -40, 0, 0])
    r = R.analyse(a, TAU, detail=True)
    assert r["episodes"] == []
    assert list(r["labels"][4:7]) == [5, 5, 5] and r["negCounts"]["REGEN_TO_STOP"] == 3


def test_negative_at_standstill_is_its_own_class():
    r = R.analyse(arr([0, 0, 0, 0, 0], [0, -80, -90, -10, 0]), TAU, detail=True)
    assert r["labelCounts"]["NEG_AT_STANDSTILL"] == 2 and r["episodes"] == []


def test_caps_send_candidates_to_ambiguous_low():
    v = [0, 0, 5, 10, 20, 18, 10, 4, 0, 0]
    T = [0, 0, -60, -70, -70, 20, 20, 20, 0, 0]
    r = R.analyse(arr(v, T), TAU, detail=True)
    assert r["episodes"] == [] and r["labelCounts"]["AMBIGUOUS_LOW"] > 0 and r["labelCounts"]["REV_CAND"] == 0          # vmax 20 > cap 15
    r20 = R.analyse(arr(v, T), TAU, {"cap": 20.0}, detail=True)
    assert len(r20["episodes"]) == 1                                                                                   # the cap sensitivity admits it
    slow = R.analyse(arr(v, T, dt=60.0), TAU, detail=True)
    assert slow["episodes"] == []                                                                                      # duration above 120 s


def test_k_and_dynamics_rule():
    v = [0, 0, 3, 5, 7, 4, 1, 0, 0]
    T = [0, 0, -60, 40, 40, 20, 10, 0, 0]       # only the first moving sample is below -tau0
    assert R.analyse(arr(v, T), TAU)["episodes"] == []                    # k = 2 fails
    assert len(R.analyse(arr(v, T), TAU, {"k": 1})["episodes"]) == 1      # k = 1: first sample negative and the next speed higher
    v2 = [0, 0, 5, 4, 3, 1, 0, 0]
    T2 = [0, 0, -60, -70, -70, 20, 20, 0]       # torque negative on both samples but the speed does not rise
    assert R.analyse(arr(v2, T2), TAU)["episodes"] == []


def test_standstill_onset_requirement():
    v = [0, 0, 6, 8, 0, 3, 6, 5, 3, 0]
    T = [0, 0, 80, 80, 0, -60, -70, 30, 30, 0]
    a = arr(v, T, dt=0.2)                      # standstill of 0.4 s before the second start
    assert R.analyse(a, TAU)["episodes"] == []
    assert len(R.analyse(a, TAU, {"stand": 0.25})["episodes"]) == 1
    assert len(R.analyse(arr(v, T, dt=1.0), TAU)["episodes"]) == 1


def test_gap_gives_ambiguous_gap():
    ts = np.array([0, 1, 2, 3, 4, 5, 30, 31, 32, 33, 34], float)
    a = {"ts": ts, "T": np.array([0, 0, 0, -60, -70, -70, 30, 30, 20, 0, 0], float), "v": np.array([0, 0, 0, 2, 4, 6, 5, 3, 1, 0, 0], float),
         "rpm": np.zeros(11), "I": np.zeros(11), "lastPos": np.full(11, np.nan)}
    r = R.analyse(a, TAU, detail=True)
    assert r["episodes"] == [] and r["labelCounts"]["AMBIGUOUS_GAP"] > 0


def test_precedence_and_one_label_per_sample():
    a = arr([0, 0, 0, 0, 2, 4, 6, 5, 3, 1, 0, 0], [0, -80, 0, 0, -60, -70, -70, 30, 30, 20, 0, 0])
    r = R.analyse(a, TAU, detail=True)
    assert sum(r["labelCounts"].values()) == r["n"]
    assert r["labels"][1] == 4 and r["labels"][5] == 3


def test_v1_inputs_and_v3():
    I = np.array([0, 0, 0, 0, -30, -40, -40, 10, 10, 5, 0, 0], float)          # discharge positive = -I
    a = arr([0, 0, 0, 0, 2, 4, 6, 5, 3, 1, 0, 0], [0, 0, 0, 0, -60, -70, -70, 30, 30, 20, 0, 0], I=I)
    r = R.analyse(a, TAU, detail=True)
    vi = R.validation_inputs(a, TAU, r)
    e = vi["episodes"][0]
    assert e["supported"] and e["meanDischargeExcess"] > 30
    a2 = arr([0, 0, 0, 0, 2, 4, 6, 5, 3, 1, 0, 0], [0, 0, 0, 0, -60, -70, -70, 30, 30, 20, 0, 0], I=I, rpm=1000.0)
    vi2 = R.validation_inputs(a2, TAU, R.analyse(a2, TAU, detail=True))
    assert vi2["episodes"][0]["supported"] is False                              # engine on: V1 not testable for this episode
    # V3: negative-torque onset above 40 km/h after a speed decrease, speed rising afterwards = a hit; falling = no hit
    hi = arr([60, 58, 56, 57, 59, 61], [10, 10, -60, -70, -70, -70])
    assert R.validation_inputs(hi, TAU, R.analyse(hi, TAU, detail=True))["v3"] == {"onsets": 1, "hits": 1}
    hi2 = arr([60, 58, 56, 54, 52, 50], [10, 10, -60, -70, -70, -70])
    assert R.validation_inputs(hi2, TAU, R.analyse(hi2, TAU, detail=True))["v3"] == {"onsets": 1, "hits": 0}


def make_row(i, a, regime="slow", date=None, source="VCM"):
    r = R.analyse(a, TAU, detail=True)
    prim = {k: r[k] for k in ("labelCounts", "negCounts", "tMin", "tMinExclRev")}
    prim["nEpisodes"] = len(r["episodes"])
    variants = {"primary": prim}
    for name, par in R.GRID[1:]:
        rr = R.analyse(a, TAU, par)
        variants[name] = {"labelCounts": rr["labelCounts"], "nEpisodes": len(rr["episodes"])}
    return {"file": "d%02d" % i, "date": date or "2026-06-%02d" % (1 + i % 15), "regime": regime, "speedSource": source, "nSamples": int(r["n"]), "variants": variants, "episodes": r["episodes"],
            "validation": R.validation_inputs(a, TAU, r), "reason": None}


def drive_with_reverse(i, charging=False):
    pre = [0] * 3
    mid = [3, 5, 7, 5, 2, 0]
    fwd = [5, 15, 30, 40, 35, 20, 8, 0, 0, 0]
    # reverse at the start (frac low), forward in the middle, reverse at the end
    v = pre + mid + [0, 0] + [10, 20, 30, 40, 30, 20, 10, 0] * 4 + [0, 0] + [3, 5, 7, 5, 2, 0, 0, 0]
    T = [0] * 3 + [-150, -160, -160, 30, 30, 0] + [0, 0] + [80, 80, 60, 20, -20, -40, -50, 0] * 4 + [0, 0] + [-150, -160, -160, 30, 30, 0, 0, 0]
    I = [0] * 3 + ([20, 25, 25, 10, 10, 0] if charging else [-30, -40, -40, 10, 10, 0]) + [0, 0] + [-60, -70, -50, -10, 20, 30, 10, 0] * 4 + [0, 0] + ([20, 25, 25, 10, 10, 0, 0, 0] if charging else [-30, -40, -40, 10, 10, 0, 0, 0])
    return arr(v, T, I=I)


def test_aggregate_supports_owner_pattern_and_verdict():
    import json
    rows = [make_row(i, drive_with_reverse(i), regime=("fast" if i % 2 else "slow")) for i in range(40)]
    R.TAU0_FILE = os.path.join(ROOT, "analyses", "M698_tau0.json")
    blk = R.aggregate(rows, nboot=300)
    a = blk["strata"]["VCM"]["all"]
    assert a["nEpisodes"] == 80 and a["nDrivesWithEpisode"] == 40 and a["V4_startOrEndShare"]["share"] == 1.0 and a["V4_startOrEndShare"]["supportsOwnerStatement"] is True
    assert a["V1_currentSign"]["shareFailing"] == 0.0 and a["V5_stability"]["passed"] is True
    assert "not falsified" in blk["verdict"]["VCM"]["text"] and "validated" not in blk["verdict"]["VCM"]["text"].replace("never worded as validated", "") and "none" in blk["verdict"]["pooledAcrossSources"]
    assert set(blk["strata"]["VCM"]) == {"all", "fast", "slow"} and a["shareOfNegativeSamplesLabelledREV_CAND"] is not None and set(blk["strata"]) == {"VCM"}
    # V1 falsifier: reverse acceleration that CHARGES the battery in every supported episode
    rows2 = [make_row(i, drive_with_reverse(i, charging=True)) for i in range(40)]
    blk2 = R.aggregate(rows2, nboot=300)
    assert blk2["strata"]["VCM"]["all"]["V1_currentSign"]["falsified"] is True and any(x.startswith("V1") for x in blk2["verdict"]["VCM"]["discriminatorFalsifiedBy"])
    # not testable with few episodes
    blk3 = R.aggregate(rows[:3], nboot=300)
    assert "not testable" in blk3["strata"]["VCM"]["all"]["V1_currentSign"]["status"]
    # OBD rows form their own stratum and no pooled verdict is drawn
    mixed = [make_row(i, drive_with_reverse(i), source=("OBD" if i % 2 else "VCM")) for i in range(40)]
    blk4 = R.aggregate(mixed, nboot=200)
    assert set(blk4["strata"]) == {"VCM", "OBD"} and "VCM" in blk4["verdict"] and "OBD" in blk4["verdict"] and blk4["deviation"].startswith("Rev 1.2")
    # V5 post hoc supplement and not-applicable status
    v5 = blk4["strata"]["VCM"]["all"]["V5_stability"]
    assert v5["status"] == "passed" and v5["passed"] is True
    none_ep = [make_row(i, arr([0, 0, 5, 8, 9, 7, 3, 0], [0, 0, 80, 80, 60, 20, 0, 0])) for i in range(12)]
    v5b = R.aggregate(none_ep, nboot=100)["strata"]["VCM"]["all"]["V5_stability"]
    assert v5b["passed"] is None and "not applicable" in v5b["status"]


def test_splice_isolation():
    A = {"_artifactStamps": {}, "other": {"k": 1}}
    B = R.splice(copy.deepcopy(A), {"x": 1}, "abc")
    assert set(B) - set(A) == {"reverseInference"} and B["other"] == A["other"] and set(B["_artifactStamps"]) == {"reverseInference"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    import language_gate as G
    rule = {x.rid: x for x in G.RULES}["M698-reverse-wording"]
    for bad in ("reverse detected in the drive", "reverse was measured", "the reverse share of regeneration", "reversing events", "corrected regeneration", "regeneration corrected for reverse", "reverse torque"):
        assert rule.hits(bad), bad
    for ok in ("inferred reverse-consistent episode", "share labelled REV_CAND under the frozen rule", "sensitivity with inferred reverse excluded", "the logger has no gear or direction channel"):
        assert not rule.hits(ok), ok
    print("PASS test_m698_reverse_mask")
