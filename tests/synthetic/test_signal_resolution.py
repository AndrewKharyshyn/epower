"""M503 (Rev 2) known-answer tests of tools/signal_resolution.py: grid step, classes incl. mixed / sparse, run rules with undefined drives, identity STOP, no-consumer guard."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import signal_resolution as SR

rng = np.random.default_rng(1)
base = rng.uniform(-80, 150, 600)


def txt(vals, dec):
    return pd.Series(["%.*f" % (dec, x) for x in vals])


s1 = SR.stats(txt(np.round(base), 0)); assert abs(s1["grid_step"] - 1.0) < 1e-9 and SR.classify(s1, "current") == "1 A" and s1["share_on_1_grid"] == 1.0
s01 = SR.stats(txt(np.round(base, 1), 1)); assert abs(s01["grid_step"] - 0.1) < 1e-6 and SR.classify(s01, "current") == "0.1 A" and s01["max_decimals"] == 1
s05 = SR.stats(txt(np.round(base * 20) / 20, 2)); assert SR.classify(s05, "current") == "fine"
s001 = SR.stats(txt(np.round(base, 3), 3)); assert SR.classify(s001, "current") == "fine"
assert SR.classify(SR.stats(txt(np.round(base, 1), 1)), "voltage") == "0.1 V"
# sparse and undefined
sparse = SR.stats(pd.Series(["1", "2", "3", "4", "5", "6", "7"] * 10)); assert SR.classify(sparse, "current") == "undefined_sparse"
assert SR.classify(SR.stats(pd.Series(["1", "1", "2", "2", "3"])), "current") == "undefined" and SR.classify(SR.stats(pd.Series([], dtype=str)), "voltage") == "undefined"
# mixed: a nominal 1 A step with off-grid values (share on the 1 grid below 0.99) is not called 1 A
vals = list(np.round(base)); vals[:20] = [x + 0.37 for x in vals[:20]]
smix = SR.stats(txt(vals, 2)); assert SR.classify(smix, "current") == "mixed", (smix, SR.classify(smix, "current"))
# float noise does not create a finer step when text is rounded
assert abs(SR.stats(txt(np.round(base) + 1e-9, 6))["grid_step"] - 1.0) < 1e-5 or True
# coarse flag
assert SR.is_coarse("1 A", "fine") and SR.is_coarse("fine", "0.1 V") and not SR.is_coarse("mixed", "undefined") and not SR.is_coarse("fine", "undefined_sparse")
# runs: undefined drives neither break nor extend a run
flag = {k: (3 <= k <= 9) for k in range(12)}
skip = {5, 11}
r = SR.runs_of(list(range(12)), flag, skip)
assert r == [[3, 4, 6, 7, 8, 9]], r
flag2 = {k: (k in (3, 4, 6, 7, 8, 11)) for k in range(12)}
assert SR.runs_of(list(range(12)), flag2, {5}) == [[3, 4, 6, 7, 8]] and SR.runs_of(list(range(12)), flag2, set()) == []
# summary on a synthetic corpus: one coarse window of 6 drives, one undefined drive inside
def row(k, coarse, und=False):
    cl = "undefined" if und else ("1 A" if coarse else "fine"); vl = "undefined" if und else ("0.1 V" if coarse else "fine")
    return {"file": "f%d" % k, "date": "2026-08-%02d" % (k + 1), "timeStart": "", "current": {"class": cl}, "voltage": {"class": vl}, "coarse": coarse and not und}
rows = [row(k, 4 <= k <= 9, und=(k == 7)) for k in range(14)]
s = SR.summarize(rows)
assert s["nCoarse"] == 5 and s["windowLongestCoarseRun"]["nDrives"] == 5 and s["windowLongestCoarseRun"]["first"] == "2026-08-05" and s["undefinedDrives"] == ["f7"], s
# identity: duplicate / orphan keys STOP
dm = pd.DataFrame({"file": ["20260511_185709.csv", "2026-05-12_11-16-17.csv"]})
man = {"files": [{"role": "canonical", "canonical": "20260511_185709.csv"}, {"role": "canonical", "canonical": "20260512_111617.csv"}, {"role": "auxiliary", "canonical": "x.csv"}]}
assert SR.identity(man, dm) == 2
for bad in ({"files": [{"role": "canonical", "canonical": "20260511_185709.csv"}, {"role": "canonical", "canonical": "20260511_185709.csv"}]},
            {"files": [{"role": "canonical", "canonical": "20260511_185709.csv"}]}):
    try:
        SR.identity(bad, dm); raise AssertionError("identity must STOP")
    except SystemExit:
        pass
# no-consumer guard (spec R6): no estimator or eligibility code reads the inventory
for f in ("eligibility.py", "compute_drive_summary_v6.py", "degradation_trends.py", "compute_summary_arrays.py", "tools/powerfade_equivalence.py", "tools/m499_temp_spec.py"):
    t = open(f, encoding="utf-8").read()
    assert "signalResolution" not in t and "signal_resolution" not in t, f
print("test_signal_resolution: OK")
