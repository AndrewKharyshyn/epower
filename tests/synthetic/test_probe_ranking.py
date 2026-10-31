"""M549 (analyses/M549_spec.md Rev 2): known-answer tests for the temperature-probe ranking tie policy (tools/probe_ranking.py)."""
import itertools, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import probe_ranking as P

def frame(n, vals, step_s=1.0):
    t = pd.Series(pd.date_range("2026-01-01 08:00:00", periods=n, freq=f"{int(step_s * 1000)}ms"))
    return t, {p: pd.Series(np.asarray(vals[i], float)) for i, p in enumerate(P.PROBES)}

# KA1 (the audit acceptance test): four equal probes -> unique 0, tied 100 %, fractional 25 % each, hot and cold
t, T = frame(40, [np.full(40, 20.0)] * 4)
r = P.extract_core(t, T)
for w in ("hot", "cold"):
    m = np.array(r["last"][w]["m"]); n = r["last"]["valid"]
    assert n == 40 and (m[:, 0] == 0).all() and (m[:, 3] == n).all() and r["last"][w]["ties"] == n
    assert all(abs(sum(m[p][k] / (k + 1) for k in range(4)) / n - 0.25) < 1e-12 for p in range(4))
# legacy first-index rule gives T1 every hot tie and T1 every cold tie (the defect)
assert r["legacy"]["hot"] == [r["legacy"]["rows"], 0, 0, 0] and r["legacy"]["cold"] == [r["legacy"]["rows"], 0, 0, 0]

# KA2 (permutation): named-probe unique / tied / fractional do not change; the first-index diagnostic does
rng = np.random.default_rng(1)
base = [rng.integers(18, 24, 200).astype(float) for _ in range(4)]
def named(vals):
    t, T = frame(200, vals)
    return P.extract_core(t, T)
r0 = named(base)
for perm in itertools.permutations(range(4)):
    rp = named([base[i] for i in perm])
    for w in ("hot", "cold"):
        for new_pos, old_pos in enumerate(perm):
            assert rp["last"][w]["m"][new_pos] == r0["last"][w]["m"][old_pos], (perm, w)
rp = named([base[i] for i in (3, 2, 1, 0)])
assert rp["legacy"]["hot"] != r0["legacy"]["hot"]  # order-dependent by construction, labelled as a diagnostic

# KA3 (partition) and D3 (exact identities on the same seconds), random ties
for b in ("last", "mean", "fresh"):
    for w in ("hot", "cold"):
        m = np.array(r0[b][w]["m"]); n = r0[b]["valid"]
        assert abs(sum(m[p][k] / (k + 1) for p in range(4) for k in range(4)) - n) < 1e-9
    assert r0[b]["hot"]["first"][0] == sum(r0[b]["hot"]["m"][0])           # T1 wins every tie it belongs to
    assert r0[b]["cold"]["first"][3] == r0[b]["cold"]["m"][3][0]           # T4 wins only when strictly lowest

# KA6 (cadence): T4 is read at s=0 and s=20 only; the pipeline double fill keeps the grid valid, S2 counts only the seconds within 5 s of a reading
vals = [np.full(30, 21.0), np.full(30, 20.0), np.full(30, 19.0), np.full(30, np.nan)]
vals[3][0] = 18.0; vals[3][20] = 18.0
t, T = frame(30, vals)
r = P.extract_core(t, T)
assert r["last"]["valid"] == 30 and r["fresh"]["valid"] == 10, (r["last"]["valid"], r["fresh"]["valid"])

# KA7: two native readings inside one second whose MEAN equals another probe; a tie under MEAN, not under `last`
t = pd.Series(pd.to_datetime(["2026-01-01 08:00:00.0", "2026-01-01 08:00:00.5", "2026-01-01 08:00:01.0", "2026-01-01 08:00:01.5"]))
T = {"T1": pd.Series([20.0, 22.0, 20.0, 22.0]), "T2": pd.Series([21.0, 21.0, 21.0, 21.0]), "T3": pd.Series([10.0] * 4), "T4": pd.Series([5.0] * 4)}
r = P.extract_core(t, T)
assert r["mean"]["hot"]["ties"] == r["mean"]["valid"] and r["last"]["hot"]["ties"] == 0
assert r["gq"]["T1"]["step"] == 2.0 and r["gq"]["T1"]["off"] == r["gq"]["T1"]["n"] == 2   # G-Q: the MEAN (21) falls off the observed value step (20, 22) in every second

# bootstrap rule: fewer than 5 days -> no interval; ratio of sums
b = P._boot([1, 1, 0], [2, 2, 2], ["d1", "d1", "d2"])
assert b["ci95Pct"] is None and b["pct"] == round(100 * 2 / 6, 3)
# language rule AUD29-F01: the legacy first-index wording fires, the generated unique / tied sentence does not
import language_gate as G
for t in ["Hottest probe — reads highest in 88% of samples", "Coldest probe — reads lowest in 75% of samples", "Sensor 1 is hottest probe in 88% of samples"]:
    assert "M549-F01-first-index-share" in G.scan_text(t), t
for t in ["uniquely hottest 32.6 % of observed time; tied for the extreme 48.5 %", "By the first-index rule Sensor 1 is ranked hottest in 88% of native rows (a tie-biased diagnostic)"]:
    assert "M549-F01-first-index-share" not in G.scan_text(t), t
import json
a = json.load(open("summary_arrays.json", encoding="utf-8"))
assert all("reads highest" not in x["role"] and "reads lowest" not in x["role"] for x in a["sensorSummary"])
assert a["temperatureProbeRanking"]["identities"]["nViolations"] == 0
print("test_probe_ranking OK")
