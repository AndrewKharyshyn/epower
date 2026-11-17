"""M711 known-answer tests for tools/restart_stage.py and the condition tables of tools/restart_census.py (spec analyses/M708_spec.md Rev 2, sections 7 and 9): the winter masks, the support floor (10 pairs on 5 days,
else not evaluable), the splice isolation, the stage registration and stamp policy, and the committed block (frozen-basis reproduction gates, no flags, language gate)."""
import copy, json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import restart_census as RC
import restart_stage as S
import restamp_ingest as R
import language_gate as LG

# winter masks: reconstructed restart ambient below 10 C, or the recorded reading below 10 C after a gap of 4 h or more
D = pd.DataFrame({"n_Abar_s": [5.0, 12.0, 12.0, 12.0, np.nan], "n_A0": [20.0, 8.0, 8.0, 20.0, np.nan], "gap_h": [1.0, 5.0, 2.0, 5.0, 9.0], "gc": ["10-60 min", "4-12 h", "1-4 h", "4-12 h", "4-12 h"]})
c = S.conditions(D)
assert c["winterOnly"][0].tolist() == [True, True, False, False, False], "reconstructed < 10, or reading < 10 after >= 4 h; NaN is not winter"
assert c["gap4to12h"][0].tolist() == [False, True, False, True, True]

# support floor: >= 10 pairs on >= 5 days, else notEvaluable (numbers withheld)
assert RC.supported(10, 5) and not RC.supported(9, 5) and not RC.supported(10, 4)
rows = []
def add(cls, n, ndays, val):
    for i in range(n):
        rows.append({"gc": cls, "d_same": val, "d_T1": val, "elig": True, "flagged": False, "day": "d%s%d" % (cls[:2], i % ndays), "p_day": "p%s%d" % (cls[:2], i % ndays)})
add("<10 min", 12, 6, 0.1)       # evaluable
add("1-4 h", 5, 5, -2.0)         # too few pairs
add("4-12 h", 12, 3, -6.0)       # too few days
P = pd.DataFrame(rows)
P["gc"] = P["gc"].astype(str)
t = RC.condition_table(P, pd.Series(True, index=P.index), "all")
assert not t["flaggedKept"]["<10 min"].get("notEvaluable") and abs(t["flaggedKept"]["<10 min"]["meanChange"]["est"] - 0.1) < 1e-9
assert t["flaggedKept"]["1-4 h"]["notEvaluable"] and t["flaggedKept"]["1-4 h"]["n"] == 5
assert t["flaggedKept"]["4-12 h"]["notEvaluable"] and t["flaggedKept"]["4-12 h"]["nDays"] == 3
assert t["flaggedKept"][">=12 h"]["notEvaluable"] and t["flaggedKept"][">=12 h"]["n"] == 0
# flagged pairs: kept in the primary table, dropped in the secondary
P2 = P.copy()
P2.loc[P2["gc"] == "<10 min", "flagged"] = [True] * 4 + [False] * 8
t2 = RC.condition_table(P2, pd.Series(True, index=P2.index), "all")
assert t2["flaggedKept"]["<10 min"]["meanChange"]["n"] == 12 and t2["flaggedDropped"]["<10 min"]["notEvaluable"] and t2["flaggedDropped"]["<10 min"]["n"] == 8, "without the flagged pairs the cell falls below the floor"

# splice isolation (only the key and its stamp change)
stamp = {"corpusHash": "x", "generatedAt": "t", "computationStatus": "computed", "upstreamHashes": {}, "includedInReleaseAt": "t", "computedAt": "t"}
Ap = {"a": 1, "_artifactStamps": {"fuelContract": copy.deepcopy(stamp), "a": {"corpusHash": "x"}}}
new, bad = S.splice(Ap, {"k": 1}, "m")
assert bad == [] and new[S.KEY] == {"k": 1} and new["_artifactStamps"]["a"] == {"corpusHash": "x"} and S.KEY not in Ap

# registration: the stage exists after build_ambient_table, declares its block, is regenerated in the stamp policy
st = json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]
ids = [s["id"] for s in st]
s = st[ids.index("restart_census")]
assert ids.index("restart_census") > ids.index("build_ambient_table") and s["needs"] == ["build_ambient_table"] and s["writes"] == ["arrays:restartTemperature"] and s["outputs"] == ["summary_arrays.json"]
assert R.STAMP_POLICY["restartTemperature"][0] == "regen"

# the committed block: frozen-basis reproduction gates pass, no flags, the targets are matched, the language gate is clean
A = json.load(open("summary_arrays.json", encoding="utf-8"))
b = A[S.KEY]
assert b["nDrives"] == 665 and b["exclusions"]["eligible"] == 639 and b["deltaFlags"] == []
assert b["reproductionGates"]["evaluated"] and all(v["pass"] for v in b["reproductionGates"]["gates"].values())
T = json.load(open("analyses/M708_targets.json", encoding="utf-8"))["E1"]
for cls, tv in T.items():
    assert abs(b["E1_primary_flaggedKept"][cls]["meanChange"]["est"] - tv["meanChange"]) <= 0.02, cls
assert set(b["conditionTables"]) == {"winterOnly", "gap4to12h"} and b["parkGates"]["P-R2"]["pass"] is False and b["parkGates"]["P-R2"]["milestone"] == "M718" and b["parkGates"]["P-R2"]["evaluatedOnDrives"] == 665
assert b["parkGates"]["P-R3b"]["pass"] is True and b["parkGates"]["P-R4"]["contaminationDirection"]["pass"] is True
assert abs(b["parkModel"]["M2_fullSample_nonFlagged"]["tau_h"] - 9.105) < 0.01
def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
assert [x for x in strings(b) if LG.scan_text(x)] == []
print("test_restart_stage: ok")
