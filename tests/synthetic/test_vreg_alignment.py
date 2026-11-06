"""M505 known-answer tests of tools/vreg_alignment.py: each pairing rule on an asynchronous synthetic series, restoration of the production _asof, no-consumer guard."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import compute_drive_summary_v6 as D
import vreg_alignment as VA

t0 = pd.Timestamp("2026-08-01 12:00:00")
ms = lambda x: t0 + pd.Timedelta(milliseconds=x)
# voltage samples at 0, 1000, 2000, 4500 ms (value = 100 + t/1000); current samples at 500, 1000, 1700, 3000, 6000 ms
V = pd.DataFrame({"t": [ms(0), ms(1000), ms(2000), ms(4500)], "v": [100.0, 101.0, 102.0, 104.5]})
base = lambda: pd.DataFrame({"t": [ms(500), ms(1000), ms(1700), ms(3000), ms(6000)], "v": [1.0] * 5})
orig = D._asof


def run(variant):
    with VA.patched_asof(variant):
        return D._asof(base(), V.copy(), "V", "1500ms")["V"].values.astype(float)


assert D._asof is orig                                   # restored after the context
# A0 nearest within 1500 ms (ties resolved by merge_asof): 500 -> 0 or 1000 (distance 500 each), 1000 exact, 1700 -> 2000 (300), 3000 -> 2000 or 4500 (1000 vs 1500) -> 2000, 6000 -> 4500 (1500, inside)
a0 = run("A0")
assert a0[1] == 101.0 and a0[2] == 102.0 and a0[3] == 102.0 and a0[4] == 104.5 and a0[0] in (100.0, 101.0)
# A1 synchronous: 500 -> 100.5, 1000 exact 101.0, 1700 -> 101.7, 3000 -> neighbours 2000 and 4500 are 2500 ms apart (<= 3000) -> 102 + (1000/2500)*2.5 = 103.0, 6000 -> no right neighbour -> NaN
a1 = run("A1")
assert abs(a1[0] - 100.5) < 1e-9 and a1[1] == 101.0 and abs(a1[2] - 101.7) < 1e-9 and abs(a1[3] - 103.0) < 1e-9 and np.isnan(a1[4])
# A1 refuses a wide bracket: samples 4000 ms apart -> NaN
Vw = pd.DataFrame({"t": [ms(0), ms(4000)], "v": [100.0, 104.0]})
with VA.patched_asof("A1"):
    assert np.isnan(D._asof(pd.DataFrame({"t": [ms(2000)], "v": [1.0]}), Vw, "V", "1500ms")["V"].iloc[0])
# A2 nearest within 300 ms: only 1000 (exact) and 1700 (300 ms to 2000) pair
a2 = run("A2")
assert np.isnan(a2[0]) and a2[1] == 101.0 and a2[2] == 102.0 and np.isnan(a2[3]) and np.isnan(a2[4])
# A3 backward (last sample not after, within 1500 ms) and A4 forward (first sample not before)
a3, a4 = run("A3"), run("A4")
assert a3[0] == 100.0 and a3[1] == 101.0 and a3[2] == 101.0 and a3[3] == 102.0 and a3[4] == 104.5      # 6000 ms is exactly 1500 ms after the last sample: inside the inclusive tolerance
assert a4[0] == 101.0 and a4[1] == 101.0 and a4[2] == 102.0 and a4[3] == 104.5 and np.isnan(a4[4])      # 3000 -> 4500 is exactly 1500 ms; nothing after 6000
# the replacement is restored even if the wrapped call raises
try:
    with VA.patched_asof("A1"):
        raise RuntimeError("x")
except RuntimeError:
    pass
assert D._asof is orig
# A0 equals the production function exactly on a random asynchronous series
rng = np.random.default_rng(2)
tv = np.sort(rng.uniform(0, 600000, 500)); ti = np.sort(rng.uniform(0, 600000, 700))
Vr = pd.DataFrame({"t": [ms(x) for x in tv], "v": rng.normal(360, 2, 500)}); Br = pd.DataFrame({"t": [ms(x) for x in ti], "v": rng.normal(0, 30, 700)})
with VA.patched_asof("A0"):
    x = D._asof(Br.copy(), Vr.copy(), "V", "1500ms")
y = orig(Br.copy(), Vr.copy(), "V", "1500ms")
assert x["V"].fillna(-1).equals(y["V"].fillna(-1))
# no-consumer guard: no estimator or eligibility code reads the sensitivity block or the tool
for f in ("eligibility.py", "degradation_trends.py", "compute_drive_summary_v6.py", "compute_summary_arrays.py", "tools/powerfade_equivalence.py", "tools/m499_temp_spec.py"):
    t = open(f, encoding="utf-8").read()
    assert "vregAlignmentSensitivity" not in t and "vreg_alignment" not in t, f
print("test_vreg_alignment: OK")

# ---- M505 Rev 3: scale-aware S1 fidelity, exact S0 (analyses/M505_spec_rev3.md)
import degradation_trends as _DT
_k = VA.MONTH_DAYS / _DT.MONTH_DAYS
assert abs(_k - 30.44 / 30.4375) < 1e-12
_f = {"S1": {"slope": round(0.6564 * _k, 4), "publishedSlope": 0.6564, "n": 274, "publishedN": 274, "nDays": 98, "publishedNDays": 98},
      "S0": {"slope": 0.886, "publishedSlope": 0.886, "n": 274, "publishedN": 274}}
assert VA.fidelity_matches(_f)
assert not VA.fidelity_matches({**_f, "S1": {**_f["S1"], "slope": _f["S1"]["slope"] + 3e-4}})            # off by 3e-4 fails
assert not VA.fidelity_matches({**_f, "S1": {**_f["S1"], "n": 275}}) and not VA.fidelity_matches({**_f, "S1": {**_f["S1"], "nDays": 97}})
assert not VA.fidelity_matches({**_f, "S0": {**_f["S0"], "slope": 0.8861}})                               # S0 gets no tolerance beyond the 4-decimal equality
assert not VA.fidelity_matches({**_f, "S0": {**_f["S0"], "n": 273}})
# Rev 2 vs Rev 3 table: a label change is flagged, an identical verdict is not
_v = {"S0": {"A1": {"label": "reading depends on the alignment rule", "pairedReading": "a", "ownReading": "b", "lowPrecision": False, "pairedN": 271, "pairedSignFlip": False}}}
import json as _json, tempfile as _tf
with _tf.TemporaryDirectory() as _d:
    _p = os.path.join(_d, "r2.json"); _json.dump({"verdicts": _v}, open(_p, "w", encoding="utf-8"))
    _v["S0"]["overall"] = "reading depends on the alignment rule"
    _json.dump({"verdicts": _v}, open(_p, "w", encoding="utf-8"))
    assert VA.rev2_vs_rev3(_v, _p)["nChanged"] == 0
    _v3 = {"S0": {"A1": {**_v["S0"]["A1"], "label": "reading unchanged"}, "overall": "reading depends on the alignment rule"}}
    _t = VA.rev2_vs_rev3(_v3, _p)
    assert _t["nChanged"] == 1 and _t["rows"]["S0/A1"]["labelOrReadingChanged"] is True
print("test_vreg_alignment (M505 Rev 3): OK")
