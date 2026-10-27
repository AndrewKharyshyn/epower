"""M520 Part A known-answer tests (analyses/M520_spec.md Rev 2.1): size-matched null, standardized difference, summary rules, identity-check tolerance, no ladder call, M514 block untouched,
payload block flags (post hoc, not displayed) and the --check round trip."""
import json, os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import resistance_support_restricted as SR
import resistance_joint_matrix as RJ

# standardized mean difference: known answer
assert abs(SR._std_diff([1, 2, 3], [3, 4, 5]) - (-2.0)) < 1e-12 and SR._std_diff([1, 1], [1, 1]) is None

# size-matched null on a synthetic frame with an exact slope of 2 mOhm/month: every subset of the same size recovers it, so the observed slope sits inside the central 95 % and k is exact
rng = np.random.default_rng(1)
dates = pd.date_range("2026-05-11", periods=80).astype(str)
rows = []
for d in dates:
    for _ in range(3):
        rows.append({"date": d, RJ.T_: float(rng.uniform(15, 30)), RJ.I_: float(rng.uniform(20, 40)), "_de": float(rng.uniform(1, 3)), "_dc": float(rng.uniform(.5, 1)), "_chg": False})
F = pd.DataFrame(rows)
t0 = pd.to_datetime(F["date"]).min(); t = SR._months(F, t0)
F[RJ.R_] = 50 + 2.0 * t + 0.3 * F[RJ.T_] + 0.1 * F[RJ.I_] + 0.5 * F["_de"] - 0.2 * F["_dc"]
nul = SR.size_matched_null(F, "A0G0C1T0", 90, t0, RJ.quantile_knots(F[RJ.T_].values), 2.0)
assert nul["k"] == 90 and nul["nDraws"] == SR.NULL_DRAWS and nul["insideCentral95"] and abs(nul["nullQuantiles"]["p50"] - 2.0) < 1e-6
nul2 = SR.size_matched_null(F, "A0G0C1T0", 90, t0, RJ.quantile_knots(F[RJ.T_].values), 5.0)      # an observed slope far outside the null is flagged
assert not nul2["insideCentral95"] and nul2["fractionOfNullAtOrBelowObserved"] == 1.0
assert SR.size_matched_null(F, "A0G0C1T0", 90, t0, RJ.quantile_knots(F[RJ.T_].values), 2.0) == nul         # fixed seed: deterministic

# summary rules: all-positive in every procedure -> consistent reading; one procedure with a mixed reading -> procedure-dependent; counts are script-computed
def rec(slope, readings):
    r = {"slope": slope}
    for p, rd in zip(("day", "week", "M7", "M14"), readings):
        r[p] = {"decisive": rd is not None, "reading": rd}
    return r
S1 = SR.summarize({"a": rec(1.0, ["positive"] * 4), "b": rec(2.0, ["positive"] * 4)})
assert S1["readingAcrossProcedures"].startswith("positive in every") and S1["intervalCounts"]["day"] == {"decisive": 2, "excludeZero": 2, "positive": 2} and not S1["proceduresDiffer"]
S2 = SR.summarize({"a": rec(1.0, ["positive", "positive", "positive", "includesZero"]), "b": rec(2.0, ["positive", "positive", "positive", None])})
assert S2["readingAcrossProcedures"] == "procedure-dependent or mixed" and S2["proceduresDiffer"] and S2["escalationK"] == 2
assert "not six independent results" in S2["note"] and "multiplicity" in S2["note"]

# identity check: equal values pass, a deviation beyond the publication tolerance fails
m = {"id": "A0G0C1T0", "slope": 1.0, "day": {"ci95": [0.5, 1.5]}, "week": {"ci95": [0.4, 1.6]}, "M7": {"ci95": None}, "M14": {"ci95": [0.3, 1.7]}}
r = json.loads(json.dumps(m))
assert SR.identity_check({"A0G0C1T0": r}, [m])["passed"]
r["day"]["ci95"][0] = 0.5 + 1e-4
assert not SR.identity_check({"A0G0C1T0": r}, [m])["passed"]
assert not SR.identity_check({"A0G9C1T0": m}, [m])["passed"]

# no leak: the M514 ladder is never called on the restricted cells
src = open("tools/resistance_support_restricted.py", encoding="utf-8").read()
assert "RJ.ladder(" not in src and "ladder(" not in src.replace("readingAcrossProcedures", "")

# payload (read-only): flags, populations, six cells, M514 block untouched, round trip
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["resistanceSupportRestricted"]
assert B["postHoc"] is True and B["confirmatory"] is False and B["displayed"] is False and B["identityCheck"]["passed"]
assert [c["id"] for c in B["cells"]] == SR.CELLS and all("sizeMatchedNull" in c and "readingAcrossProcedures" in c for c in B["cells"])
assert B["populations"]["A0"]["g2Subset"]["nDrives"] >= RJ.MIN_DRIVES, "G2 subset must stay at or above the 150-drive threshold (else cells are not decisive)"
assert set(B["selectionDiagnostic"]) == {"A0", "A1"} and "flag" in B["selectionDiagnostic"]["A0"]
M = A["resistanceJointSensitivity"]
assert "supportRestricted" not in M and M["ladder"]["level"] and M["cells"] and len(M["cells"]) == 54
assert B["masterMd5"] == A["_artifactStamps"]["resistanceSupportRestricted"]["corpusHash"]
assert not any("resistanceSupportRestricted" in l for l in open("xtrail_summary.jsx", encoding="utf-8")), "payload only: the JSX must not read this block (owner decision 2026-10-27)"
out = subprocess.run([sys.executable, "tools/resistance_support_restricted.py", "--check"], capture_output=True, text=True)
assert out.returncode == 0 and '"matchesPayload": true' in out.stdout, out.stdout[-300:] + out.stderr[-300:]
print("test_resistance_support_restricted: OK")
