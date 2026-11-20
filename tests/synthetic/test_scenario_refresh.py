"""M720 tests for tools/scenario_refresh.py and the per-drive cache of tools/scenario_frame.py: the step order follows the data dependencies, the freshness verdict, the flag-only comparison with the previous block, and a cached
frame row / slices equal to the uncached ones (reuse only on equal raw bytes and extractor hash)."""
import os, sys, tempfile
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import scenario_refresh as SR
import scenario_frame as SF

names = [n for n, _ in SR.STEPS]
assert names == ["frame", "odometer", "state", "engine_production", "engine_projectrule", "validation", "sensitivity", "gates", "splice", "check"], names
assert names.index("frame") < names.index("odometer") < names.index("state") < names.index("engine_production") < names.index("validation") < names.index("gates") < names.index("splice") < names.index("check")
cur = {"driveMasterMd5": "a", "odometerKm": 100, "odometerAsOf": "2026-11-01", "toolSha256": {"x.py": "1", "y.py": "2"}, "rangesSha256": "r"}
assert SR.verdict(None, cur)[0] == "stale"
assert SR.verdict({"inputs": cur}, cur) == ("fresh", [])
for k, val in (("driveMasterMd5", "b"), ("odometerKm", 101), ("odometerAsOf", "2026-11-02"), ("rangesSha256", "q")):
    v, why = SR.verdict({"inputs": dict(cur, **{k: val})}, cur)
    assert v == "stale" and why == [k], (k, why)
v, why = SR.verdict({"inputs": dict(cur, toolSha256={"x.py": "1", "y.py": "3"})}, cur)
assert v == "stale" and why == ["tool y.py"]
c = SR.compare({"masterMd5": "p", "supportStatus": {"a": "supported", "b": "notSupported"}}, {"masterMd5": "n", "supportStatus": {"a": "supported", "b": "bracket", "c": "index"}})
assert c["statusChanged"] == ["b", "c"] and c["previousMasterMd5"] == "p" and c["newMasterMd5"] == "n"
assert SR.compare({}, {})["statusChanged"] == []

# cache: miss computes and stores, hit returns the same content, a changed raw file or extractor hash is a miss
C = SF.C
HDR = ["time", C["I"], C["V"], C["soc"], C["T1"], C["T2"], C["T3"], C["T4"], C["spd_vcm"], C["rpm"]]
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "20260901_100000.csv")

    def write(scale):
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(HDR) + "\n")
            for s in range(120):
                f.write(",".join(str(x) for x in ("10:%02d:%02d.000" % (s // 60, s % 60), 10.0 * scale if s < 60 else -20.0, 360.0, 60.0, 20, 20, 20, 20, 36.0, 0)) + "\n")
    write(1.0)
    SF.CACHE_DIR = os.path.join(td, "cache")
    os.environ["XT_SCENARIO_CACHE"] = "1"
    r0, s0, e0 = SF._all(p)
    assert e0 is None and os.path.exists(SF._cache_path(p))
    os.environ["XT_SCENARIO_CACHE"] = "0"
    ru, su, _ = SF._all(p)                                          # uncached reference
    os.environ["XT_SCENARIO_CACHE"] = "1"
    r1, s1, _ = SF._all(p)                                          # hit
    assert r1 == r0 == ru and all(np.array_equal(s1[k], su[k], equal_nan=True) for k in su)
    write(2.0)                                                      # raw bytes change -> miss, new content
    r2, _, _ = SF._all(p)
    assert abs(r2["ah_chg"] - 2 * r0["ah_chg"]) < 1e-9
    h = SF._EXTRACTOR_SRC
    SF._EXTRACTOR_SRC = "other"                                    # extractor hash change -> miss
    import pickle
    assert pickle.load(open(SF._cache_path(p), "rb"))["extractor"] != "other"
    SF._all(p)
    assert pickle.load(open(SF._cache_path(p), "rb"))["extractor"] == "other"
    SF._EXTRACTOR_SRC = h
print("test_scenario_refresh: ok")
